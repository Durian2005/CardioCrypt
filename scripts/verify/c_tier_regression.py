# -*- coding: utf-8 -*-
"""
C 档端到端回归（真实进程 + 真实 HTTP + 真实 MongoDB）

目的：`create_app()` 工厂与蓝图拆分是纯结构重构，必须用**真实启动路径**
（`python web_auth/app.py`）验证行为没有变化 —— pytest 走的是 test_client，
不会经过 socket、WSGI 入口和 `__main__` 分支。

跑法：
    python scripts/verify/c_tier_regression.py

安全：全程使用独立临时库 `ecg_auth_db_cverify`，测完 drop；
      开发库与其他项目的数据库不会被读写。
"""
import atexit
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar

from _common import ROOT, PYTHON, MONGO_BASE  # noqa: E402

TEST_DB = 'ecg_auth_db_cverify'
PORT_SPA = 5013
PORT_CLASSIC = 5014

PASSED = []
FAILED = []
LAUNCHED = []


@atexit.register
def _cleanup_children():
    """
    无论脚本怎么退出（包括断言异常）都要收掉子进程。

    否则残留实例会继续占着端口，下一次运行时请求打到的其实是
    **上一次的旧进程**（它的限流器早已耗尽、连的还是已被 drop 的库），
    表现为「同一脚本两次结果不一样」这种极难排查的抖动。
    """
    for proc in LAUNCHED:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            proc.log_handle.close()
        except Exception:
            pass


def port_free(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            return False
    except OSError:
        return True


def check(name, ok, detail=''):
    (PASSED if ok else FAILED).append(name)
    print('  [{}] {}{}'.format('PASS' if ok else 'FAIL', name,
                               ('  -> ' + str(detail)) if detail else ''))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁止自动跟随 302：重定向本身就是我们要断言的行为。"""
    def redirect_request(self, *args, **kwargs):
        return None


class Client:
    def __init__(self, port):
        self.base = 'http://127.0.0.1:{}'.format(port)
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),          # 直连本地服务，不读取系统代理
            _NoRedirect(),
            urllib.request.HTTPCookieProcessor(self.jar),
        )
        self.token = ''

    def request(self, method, path, data=None, json_body=None, headers=None):
        url = self.base + path
        body = None
        hdrs = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body).encode('utf-8')
            hdrs['Content-Type'] = 'application/json'
        elif data is not None:
            body = urllib.parse.urlencode(data).encode('utf-8')
            hdrs['Content-Type'] = 'application/x-www-form-urlencoded'
        if self.token and method != 'GET':
            hdrs['X-CSRFToken'] = self.token
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        try:
            with self.opener.open(req, timeout=20) as resp:
                return resp.status, dict(resp.headers), resp.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read().decode('utf-8', 'replace')

    def fetch_token(self):
        status, _, body = self.request('GET', '/api/csrf-token')
        assert status == 200, '获取 CSRF 令牌失败: {}'.format(status)
        self.token = json.loads(body)['token']
        return self.token

    def post_form(self, path, data):
        payload = dict(data)
        payload['csrf_token'] = self.token
        return self.request('POST', path, data=payload)


def wait_ready(proc, port, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def launch(port, frontend_mode, tag, extra_env=None):
    env = dict(os.environ)
    env.update({
        'MONGO_URI': '{}/{}'.format(MONGO_BASE, TEST_DB),
        'FLASK_HOST': '127.0.0.1',
        'FLASK_PORT': str(port),
        'FLASK_DEBUG': '0',
        'FRONTEND_MODE': frontend_mode,
        'LOG_LEVEL': 'INFO',
        'CSRF_ENABLED': '1',
        'MONGO_SERVER_SELECTION_TIMEOUT_MS': '4000',
        'PYTHONIOENCODING': 'utf-8',
        # 与 pytest 夹具保持一致，避免依赖默认口令
        'ADMIN_USERNAME': 'pytest_admin',
        'ADMIN_PASSWORD': 'pytest-admin-pw',
    })
    env.pop('FLASK_SECRET_KEY', None)      # 走本地持久化密钥路径
    if extra_env:
        env.update(extra_env)

    # 日志必须写文件：用 subprocess.PIPE 而不读取，日志量大时会把子进程
    # 卡在写管道上（经典死锁），表现为「请求莫名超时」。
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, '{}.log'.format(tag))
    handle = open(log_path, 'w', encoding='utf-8')

    proc = subprocess.Popen(
        [PYTHON, os.path.join('web_auth', 'app.py')],
        cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT,
    )
    proc.log_handle = handle
    proc.log_path = log_path
    LAUNCHED.append(proc)
    return proc


def drain(proc):
    try:
        proc.log_handle.flush()
    except Exception:
        pass
    try:
        with open(proc.log_path, encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except Exception:
        return ''


def drop_test_db():
    assert 'verify' in TEST_DB, '安全保护：拒绝操作非测试库'
    from pymongo import MongoClient
    client = MongoClient(MONGO_BASE, serverSelectionTimeoutMS=4000)
    client.drop_database(TEST_DB)
    client.close()


# ===========================================================================
print('== 0. 准备 ==')
for _port in (PORT_SPA, PORT_CLASSIC):
    if not port_free(_port):
        print('  端口 {} 已被占用，请先结束残留进程（否则请求会打到旧实例）'.format(_port))
        sys.exit(1)
print('  端口 {} / {} 空闲'.format(PORT_SPA, PORT_CLASSIC))
drop_test_db()

print('\n== 1. SPA 模式实例（端口 {}）=='.format(PORT_SPA))
proc = launch(PORT_SPA, 'spa', 'spa')
ready = wait_ready(proc, PORT_SPA)
check('进程在 90 秒内开始监听 {}'.format(PORT_SPA), ready)
if not ready:
    print(drain(proc))
    sys.exit(1)

c = Client(PORT_SPA)
c.fetch_token()

status, headers, body = c.request('GET', '/')
check('GET / 返回 200 且是前端产物', status == 200 and '<div id="root"' in body,
      'status={}'.format(status))

status, _, body = c.request('GET', '/api/session')
payload = json.loads(body)
check('GET /api/session 投影匿名会话',
      status == 200 and payload['authenticated'] is False and payload['isAdmin'] is False)

status, _, body = c.request('GET', '/api/csrf-token')
check('GET /api/csrf-token 下发令牌且开关打开',
      status == 200 and json.loads(body)['enabled'] is True)

status, _, body = c.request('GET', '/api/definitely-missing')
check('未知 /api 路径保持 404', status == 404 and '<div id="root"' not in body,
      'status={}'.format(status))

status, headers, body = c.request('GET', '/manage/dashboard')
check('SPA 模式下管理页只返回前端壳（页面级守卫在前端）',
      status == 200 and '<div id="root"' in body,
      'status={}'.format(status))

status, headers, body = c.request('GET', '/api/admin/users')
location = headers.get('Location') or headers.get('location') or ''
check('未登录访问 /api/admin/users 被后端挡下（真正的权限边界在这层）',
      status == 302 and location.endswith('/manage/login'),
      'status={} loc={!r}'.format(status, location))

# --- CSRF ---------------------------------------------------------------
bare = Client(PORT_SPA)
status, _, body = bare.request('POST', '/api/scan_devices', json_body={})
check('无令牌写请求被 CSRF 拒绝', status == 403, 'status={}'.format(status))

status, _, body = c.request('POST', '/api/scan_devices', json_body={})
check('带令牌写请求放行（不再是 403）', status != 403, 'status={}'.format(status))

# --- 认证结果不可被旁路改写 ----------------------------------------------
payload = {'address': '00:11:22:33:44:55', 'type': 'bogus'}
s1, _, b1 = c.request('POST', '/api/connect_device', json_body=dict(payload))
s2, _, b2 = c.request('POST', '/api/connect_device',
                      json_body=dict(payload, connection_mode='stable'))
check('connection_mode 参数已彻底失效（两次响应逐字节一致）',
      s1 == s2 == 200 and b1 == b2, '{} vs {}'.format(b1[:80], b2[:80]))

# --- 登录链路 -----------------------------------------------------------
s, h, _ = c.post_form('/login', {'username': 'totally-unknown-user'})
check('未知用户登录被统一措辞拒绝并跳回 /login',
      s == 302 and '/login' in h.get('Location', ''))

from pymongo import MongoClient  # noqa: E402
mongo = MongoClient(MONGO_BASE, serverSelectionTimeoutMS=4000)
BASELINE_DBS = set(mongo.list_database_names())
mongo[TEST_DB].users.update_one(
    {'username': 'probe_user'},
    {'$set': {'username': 'probe_user', 'created_at': None, 'model_path': None}},
    upsert=True,
)
print('  >> 临时库内用户: {}'.format(
    [d['username'] for d in mongo[TEST_DB].users.find()]))

s, h, _ = c.post_form('/login', {'username': 'probe_user'})
print('  >> POST /login -> {} Location={!r}'.format(s, h.get('Location')))
check('存在用户登录后进入验证页', s == 302 and '/verify' in h.get('Location', ''),
      '/verify' if '/verify' in h.get('Location', '') else h.get('Location'))

status, _, body = c.request('GET', '/api/session')
check('会话记录了 pendingLogin',
      json.loads(body)['pendingLogin'] == 'probe_user')

# --- 管理员登录 ---------------------------------------------------------
s, h, _ = c.post_form('/manage/login',
                      {'username': 'pytest_admin', 'password': 'nope'})
check('管理员错误口令被拒', s == 302 and '/manage/login' in h.get('Location', ''))

s, h, _ = c.post_form('/manage/login',
                      {'username': 'pytest_admin', 'password': 'pytest-admin-pw'})
print('  >> POST /manage/login(正确口令) -> {} Location={!r}'.format(s, h.get('Location')))
check('管理员正确口令进入后台', s == 302 and '/manage/dashboard' in h.get('Location', ''),
      'status={} loc={!r}'.format(s, h.get('Location')))

status, _, body = c.request('GET', '/api/session')
check('会话标记 isAdmin', json.loads(body)['isAdmin'] is True)

status, _, body = c.request('GET', '/api/admin/users')
check('已登录可读取用户列表', status == 200 and json.loads(body)['success'] is True,
      'status={}'.format(status))
check('用户列表不含本机绝对路径',
      'C:/Users' not in body
      and str(ROOT).replace('\\', '/') not in body)
check('管理员登录后，之前的待认证状态已被清空',
      json.loads(c.request('GET', '/api/session')[2])['pendingLogin'] is None)

# --- 限流（行为证据，不依赖日志文本）-------------------------------------
# 未超限：用户存在 -> 302 /verify；超限后 -> flash 提示并 302 回 /login。
# 前面的用例已经消耗了 2 次配额，这里再发 11 次必定越界。
locations = []
for _ in range(11):
    _, h, _ = c.post_form('/login', {'username': 'probe_user'})
    locations.append(h.get('Location') or h.get('location') or '')

entered = [loc for loc in locations if '/verify' in loc]
blocked = [loc for loc in locations if loc.endswith('/login')]
check('登录限流生效：配额用尽后不再进入验证页',
      len(entered) >= 5 and len(blocked) >= 1 and '/verify' in locations[0],
      'verify={} blocked={} 末三次={}'.format(len(entered), len(blocked), locations[-3:]))
log_text = ''

proc.terminate()
try:
    proc.wait(timeout=15)
except subprocess.TimeoutExpired:
    proc.kill()
log_text += drain(proc)

check('启动日志无未捕获异常', 'Traceback' not in log_text,
      re.findall(r'Traceback[\s\S]{0,200}', log_text)[:1])
check('启动日志记录了 SPA 适配层与前端模式',
      'SPA 适配层注册完成' in log_text and '前端模式: spa' in log_text)

mongo_after = MongoClient(MONGO_BASE, serverSelectionTimeoutMS=4000)
indexes = mongo_after[TEST_DB].users.index_information()
check('username 唯一索引已创建（工厂内初始化生效）',
      any(v.get('unique') for k, v in indexes.items() if k.startswith('username')),
      list(indexes))
check('auth_history 复合索引已创建',
      len(mongo_after[TEST_DB].auth_history.index_information()) >= 2)

print('\n== 2. classic 模式实例（端口 {}）=='.format(PORT_CLASSIC))
proc2 = launch(PORT_CLASSIC, 'classic', 'classic')
ready2 = wait_ready(proc2, PORT_CLASSIC)
check('classic 实例开始监听', ready2)

if ready2:
    c2 = Client(PORT_CLASSIC)
    c2.fetch_token()
    status, _, body = c2.request('GET', '/login')
    check('classic 模式返回 Jinja2 模板而非 SPA',
          status == 200 and '<div id="root"' not in body and '<form' in body.lower(),
          'status={}'.format(status))
    status, _, body = c2.request('GET', '/')
    check('classic 首页正常渲染', status == 200 and '<div id="root"' not in body)

    proc2.terminate()
    try:
        proc2.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc2.kill()
    log_text += drain(proc2)

check('两个实例的日志均无未捕获异常', 'Traceback' not in log_text)

print('\n== 3. 清理 ==')
drop_test_db()
remaining = MongoClient(MONGO_BASE, serverSelectionTimeoutMS=4000).list_database_names()
check('临时库已 drop', TEST_DB not in remaining, remaining)
check('仅清理临时库，其余数据库集合未变化',
      set(remaining) == (BASELINE_DBS - {TEST_DB}))
check('测试用户未写入开发库',
      'ecg_auth_db' not in remaining
      or mongo['ecg_auth_db'].users.count_documents({'username': 'probe_user'}) == 0)

print('\n' + '=' * 60)
print('通过 {} 项，失败 {} 项'.format(len(PASSED), len(FAILED)))
if FAILED:
    print('失败项：')
    for name in FAILED:
        print('  - ' + name)
sys.exit(1 if FAILED else 0)
