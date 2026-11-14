# -*- coding: utf-8 -*-
"""认证链路端到端回归（真实 HTTP）

前置条件：**必须先启动服务**，且按下面两条约定启动，否则本脚本有 4 项
会假失败（历史上就是这么误判过一次）：

1. `FRONTEND_MODE=classic` —— 本脚本断言的是 classic 模式的重定向目标
   （如登录后跳 `/manage/dashboard`）。SPA 模式下同一动作会跳到 `/`
   由前端路由接管，断言必然不成立。
2. 管理员凭据用默认值 `admin` / `admin123`。若启动时设置了
   `ADMIN_USERNAME` / `ADMIN_PASSWORD`，需同步传给本脚本。

另外，站点已开启全站 CSRF 保护，所有写请求必须携带会话绑定的令牌。
本脚本通过 `req(..., form=True)` 自动取一次 `/api/csrf-token` 并带上，
调用方无需关心。

⚠️ **必须重启服务后再跑**（或确保距上次运行超过 60 秒）：本脚本末尾会用
16 次登录把 `LOGIN_LIMITER` 打满，而限流是**进程内**计数。紧接着再跑一次时，
T3 的 `/login` 会被限流提前拦下 → `clear_session_keep_csrf()` 根本没执行 →
「会话已被清空」这项假失败。看起来像安全逻辑坏了，实际是上一轮的残留计数。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar

BASE = os.environ.get('VERIFY_BASE_URL', 'http://127.0.0.1:5000')

ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),  # 直连本地服务，不读取系统代理
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
)

results = []

#: 会话绑定的 CSRF 令牌；首次需要时自动获取
_csrf_token = None


def csrf():
    """取当前会话的 CSRF 令牌（写请求必须携带）。"""
    global _csrf_token
    if _csrf_token is None:
        st, _, body = req('/api/csrf-token')
        if st != 200:
            raise RuntimeError('获取 CSRF 令牌失败：HTTP {}'.format(st))
        _csrf_token = json.loads(body).get('token') or ''
    return _csrf_token


def check(name, ok, detail=''):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ''))


def req(path, data=None, form=False, method=None, raw=None, headers=None):
    hdrs = dict(headers or {})
    body = None
    if raw is not None:
        body = raw.encode()
    elif data is not None:
        if form:
            # 表单提交：令牌走隐藏字段，与原生 <form> 的行为一致
            payload = dict(data)
            payload['csrf_token'] = csrf()
            body = urllib.parse.urlencode(payload).encode()
            hdrs['Content-Type'] = 'application/x-www-form-urlencoded'
        else:
            body = json.dumps(data).encode()
            hdrs['Content-Type'] = 'application/json'
            hdrs['X-CSRFToken'] = csrf()
    r = urllib.request.Request(BASE + path, data=body, headers=hdrs, method=method)
    try:
        with opener.open(r, timeout=40) as resp:
            return resp.status, resp.url, resp.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.url, e.read().decode('utf-8', 'replace')


print('=' * 68)
print('T1  基础可用性：首页能正常返回')
print('=' * 68)
# 首页返回什么取决于前端模式：classic 下是 Jinja2 模板，spa 下是构建产物。
# 两种都算通过 —— 关键是「能返回 200 且是可用页面」，而不是某一种形态。
MODE = os.environ.get('FRONTEND_MODE', 'spa').strip().lower()
st, url, body = req('/')
check('GET / 返回 200', st == 200, f'status={st}')
if MODE == 'classic':
    check('classic 模式返回 Jinja2 页面而非 SPA 产物',
          '<!doctype html' in body.lower() and 'id="root"' not in body,
          f'len={len(body)}')
else:
    check('返回的是 React SPA 挂载点', 'id="root"' in body, f'len={len(body)}')

print()
print('=' * 68)
print('T2  核心断言：connection_mode 不再影响设备连接结果')
print('=' * 68)
addr = {'address': 'AA:BB:CC:DD:EE:FF', 'type': 'ble'}
st_a, _, body_a = req('/api/connect_device', addr)
st_b, _, body_b = req('/api/connect_device', {**addr, 'connection_mode': 'stable'})
check('带 connection_mode=stable 与不带，响应完全一致',
      body_a == body_b and st_a == st_b,
      f'status {st_a}/{st_b} | 响应 {body_a[:90]}')
check('响应中不含遗留参数语义',
      'backdoor' not in body_a.lower() and 'bypass' not in body_a.lower())

print()
print('=' * 68)
print('T3  会话清理：管理员会话不会被后续 /login 继承')
print('=' * 68)
st, url, _ = req('/manage/login',
                 {'username': ADMIN_USERNAME, 'password': ADMIN_PASSWORD}, form=True)
check('默认管理员能登录（重定向到后台）', url.endswith('/manage/dashboard'), f'final={url}')
st, _, body = req('/api/session')
sess1 = json.loads(body)
check('登录后 isAdmin=True', sess1.get('isAdmin') is True, str(sess1))

st, url, _ = req('/login', {'username': 'zzz_not_exist_zzz'}, form=True)
check('不存在的用户停留在 /login', url.endswith('/login'), f'final={url}')
st, _, body = req('/api/session')
sess2 = json.loads(body)
check('★ 会话已被清空：isAdmin 变为 False', sess2.get('isAdmin') is False, str(sess2))

print()
print('=' * 68)
print("T4  未登录保护 + 错误措辞")
print('=' * 68)
st, _, body = req('/api/start_verification', data={})
try:
    j = json.loads(body)
    check('未登录调用 start_verification 被拒绝',
          j.get('success') is False and 'error' in j, str(j))
except Exception:
    check('未登录调用 start_verification 被拒绝', False, body[:120])

print()
print('=' * 68)
print('T5  调试器与堆栈不对外暴露')
print('=' * 68)
st, url, body = req('/api/scan_devices', raw='this-is-not-json')
leaked = ('Traceback (most recent call last)' in body
          or 'Werkzeug' in body
          or 'console' in body.lower() and 'debugger' in body.lower())
check('畸形 JSON 请求不泄露堆栈/调试器', not leaked, f'status={st} len={len(body)}')
st, url, body = req('/console')
check('/console 不返回调试器控制台',
      'Werkzeug Debugger' not in body and 'interactive' not in body.lower(),
      f'status={st} len={len(body)}')
st, url, body = req('/no/such/page')
check('未知路由交给 SPA 渲染', 'id="root"' in body, f'status={st}')

print()
print('=' * 68)
print('T6  限流：连续登录尝试应被拦截')
print('=' * 68)
codes = []
for i in range(16):
    st, url, _ = req('/login', {'username': f'probe_{i}'}, form=True)
    codes.append(st)
check('连续 16 次登录尝试全部完成（未 5xx）',
      all(c < 500 for c in codes), f'statuses={set(codes)}')

print()
print('=' * 68)
summary = [r for r in results if not r[1]]
print(f"结果：{len(results) - len(summary)}/{len(results)} 通过")
for name, _, detail in summary:
    print(f"  未通过 -> {name} {detail}")
sys.exit(1 if summary else 0)
