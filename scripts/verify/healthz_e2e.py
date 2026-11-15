# -*- coding: utf-8 -*-
"""健康检查端到端：真实进程 + 真实 MongoDB

pytest 里的 `test_healthz.py` 走的是 test_client，覆盖不了这条链路的三处关键行为，
它们只有起真进程才暴露得出来：

  1. **路由会不会被 SPA 的 404 兜底接管** —— 接管后返回的是一页 HTML 200，
     探针看不出任何异常，这是最危险的一种"绿"；
  2. **数据库挂掉时能否快速返回 503** —— 而不是把探针一起挂住；
  3. **响应里是否带出连接串、库名、端口等部署细节** —— 该端点**没有鉴权**，
     任何能访问到它的人都能看到响应体。

因此分两段跑：

  A. 正常实例（真实 MongoDB）：200 + `status=ok`，响应体干净；
  B. 降级实例（MONGO_URI 指向不可达端口）：进程照常启动，`/healthz` 返回
     503 + `status=degraded`，且**只有**数据库这一项变红。

用法::

    python scripts/verify/healthz_e2e.py

前置条件：MongoDB 可达（默认 ``mongodb://localhost:27017``，可用
``VERIFY_MONGO_BASE`` 覆盖）。用独立临时库，结束时 drop。
"""

import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from _common import MONGO_BASE, PYTHON, RESULTS_DIR, ROOT

TEST_DB = 'ecg_auth_db_healthz'
PORT_OK = 5041
PORT_BAD = 5042
# 指向一个必然拒绝连接的端口：比"指向不存在的域名"更可控 ——
# 立刻 ECONNREFUSED，不会因为 DNS 解析把等待时间变得不确定。
DEAD_MONGO_HOST = '127.0.0.1'
DEAD_MONGO_PORT = 1

LAUNCHED = []
_results = []


def check(name, ok, detail=''):
    _results.append((name, bool(ok)))
    line = '  {}  {}'.format('PASS' if ok else 'FAIL', name)
    if detail:
        line += '   -- {}'.format(detail)
    print(line, flush=True)


def wait_for_port(proc, port, timeout=90):
    """等端口开始监听；进程提前退出说明启动就失败了。"""
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


def port_is_free(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.5):
            return False
    except OSError:
        return True


def launch(port, tag, mongo_uri, selection_timeout_ms):
    env = dict(os.environ)
    env.update({
        'MONGO_URI': mongo_uri,
        'FLASK_HOST': '127.0.0.1',
        'FLASK_PORT': str(port),
        'FLASK_DEBUG': '0',
        # 用 spa 模式：只有装了 SPA 适配层，才能验证 404 兜底没有把 /healthz 吞掉
        'FRONTEND_MODE': 'spa',
        'LOG_LEVEL': 'INFO',
        'CSRF_ENABLED': '1',
        'MONGO_SERVER_SELECTION_TIMEOUT_MS': str(selection_timeout_ms),
        'DEMO_MODE': '0',
        'PYTHONIOENCODING': 'utf-8',
        'ADMIN_USERNAME': 'healthz_admin',
        'ADMIN_PASSWORD': 'healthz-admin-pw',
    })
    env.pop('FLASK_SECRET_KEY', None)

    # 日志写文件而不是 PIPE：管道写满会把子进程卡死，表现为"请求莫名超时"
    log_path = RESULTS_DIR / 'healthz_e2e_{}.log'.format(tag)
    handle = open(str(log_path), 'w', encoding='utf-8')
    proc = subprocess.Popen(
        [PYTHON, os.path.join('web_auth', 'app.py')],
        cwd=str(ROOT), env=env, stdout=handle, stderr=subprocess.STDOUT,
    )
    proc.log_handle = handle
    proc.log_path = str(log_path)
    LAUNCHED.append(proc)
    return proc


def stop(proc):
    try:
        proc.terminate()
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
    except Exception:
        pass
    finally:
        try:
            proc.log_handle.close()
        except Exception:
            pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """不跟随重定向：健康检查本就不该重定向，跟随后会把 3xx 伪装成 200。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get(path, port, timeout=30):
    """发一个 GET，返回 (状态码, 响应头, 正文, 耗时秒)。不跟随重定向。"""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar), NoRedirect(),
    )
    url = 'http://127.0.0.1:{}{}'.format(port, path)
    started = time.monotonic()
    try:
        with opener.open(url, timeout=timeout) as resp:
            body = resp.read().decode('utf-8', 'replace')
            return resp.status, dict(resp.headers), body, time.monotonic() - started
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', 'replace')
        return exc.code, dict(exc.headers), body, time.monotonic() - started


def auth_history_count():
    """直连数据库数认证历史条数，用来证明探针没有写库。"""
    from pymongo import MongoClient

    client = MongoClient(MONGO_BASE, serverSelectionTimeoutMS=3000)
    try:
        return client[TEST_DB].auth_history.count_documents({})
    finally:
        client.close()


def drop_test_db():
    from pymongo import MongoClient

    client = MongoClient(MONGO_BASE, serverSelectionTimeoutMS=3000)
    try:
        client.drop_database(TEST_DB)
    finally:
        client.close()


def section_ok_instance():
    print('\n[一] 正常实例（真实 MongoDB）', flush=True)
    proc = launch(PORT_OK, 'ok', '{}/{}'.format(MONGO_BASE, TEST_DB), 4000)
    if not wait_for_port(proc, PORT_OK):
        check('服务在 90 秒内开始监听 {}'.format(PORT_OK), False,
              '见日志 {}'.format(proc.log_path))
        return
    check('服务在 90 秒内开始监听 {}'.format(PORT_OK), True)

    before = auth_history_count()
    status, headers, body, elapsed = get('/healthz', PORT_OK)
    check('GET /healthz 返回 200', status == 200, '实际 {}'.format(status))

    # SPA 的 404 兜底会返回一页 HTML，状态码同样是 200 —— 必须靠内容类型分辨
    ctype = headers.get('Content-Type', '')
    check('响应是 JSON 而不是 HTML 页面', 'application/json' in ctype, ctype)
    check('未登录也能访问（无 Cookie、无令牌）', status == 200 and 'Set-Cookie' not in headers)

    payload = {}
    try:
        payload = json.loads(body)
    except ValueError:
        pass
    check('正文可解析为 JSON', bool(payload), body[:120])
    check('整体状态为 ok', payload.get('status') == 'ok', str(payload.get('status')))

    checks = payload.get('checks') or {}
    check('数据库检查通过', checks.get('database', {}).get('ok') is True)
    check('算法层检查通过', checks.get('algorithm_layer', {}).get('ok') is True)

    uptime = payload.get('uptime_seconds')
    check('运行时长是非负整数', isinstance(uptime, int) and uptime >= 0, str(uptime))
    check('演示模式标记与启动参数一致（关闭）', payload.get('demo_mode') is False)
    check('缓存被禁用', headers.get('Cache-Control') == 'no-store',
          str(headers.get('Cache-Control')))

    # 该端点没有鉴权，响应体必须干净
    forbidden = ['mongodb://', TEST_DB, str(PORT_OK), '.flask_secret_key',
                 'healthz-admin-pw']
    leaked = [item for item in forbidden if item in body]
    check('响应体不含连接串 / 库名 / 端口 / 密钥', not leaked, '泄漏：{}'.format(leaked))

    after = auth_history_count()
    check('探针是只读的（认证历史条数未变）', before == after,
          '{} -> {}'.format(before, after))

    check('响应耗时在合理范围（<5 秒）', elapsed < 5.0, '{:.2f}s'.format(elapsed))

    # 对照项：只有真路由才返回 JSON，未知路径会被 SPA 兜底成 HTML ——
    # 这条同时说明上面"未接管的 JSON"不是巧合
    unknown_status, unknown_headers, _, _ = get('/healthz-not-a-route', PORT_OK)
    check('对照：未知路径由 SPA 兜底为 HTML',
          'text/html' in unknown_headers.get('Content-Type', ''),
          '{} {}'.format(unknown_status, unknown_headers.get('Content-Type')))

    stop(proc)


def section_degraded_instance():
    print('\n[二] 降级实例（MONGO_URI 指向不可达端口）', flush=True)
    dead_uri = 'mongodb://{}:{}/{}'.format(DEAD_MONGO_HOST, DEAD_MONGO_PORT,
                                           'ecg_auth_db_healthz_dead')
    proc = launch(PORT_BAD, 'degraded', dead_uri, 1200)
    if not wait_for_port(proc, PORT_BAD):
        check('数据库不可达时进程仍能启动并监听 {}'.format(PORT_BAD), False,
              '见日志 {}'.format(proc.log_path))
        return
    check('数据库不可达时进程仍能启动并监听 {}'.format(PORT_BAD), True)

    status, headers, body, elapsed = get('/healthz', PORT_BAD)
    check('GET /healthz 返回 503', status == 503, '实际 {}'.format(status))

    payload = {}
    try:
        payload = json.loads(body)
    except ValueError:
        pass
    check('整体状态为 degraded', payload.get('status') == 'degraded',
          str(payload.get('status')))

    checks = payload.get('checks') or {}
    db_check = checks.get('database') or {}
    check('数据库检查标记为失败', db_check.get('ok') is False)
    error_name = str(db_check.get('error', ''))
    check('失败原因只给异常类型名（不含 host:port）',
          bool(error_name) and ':' not in error_name and '/' not in error_name,
          error_name)
    check('算法层不跟着一起变红', checks.get('algorithm_layer', {}).get('ok') is True)
    # 用完整的 host:port 组合判定：端口号是 "1"，单看子串会命中响应里的任意数字
    dead_target = '{}:{}'.format(DEAD_MONGO_HOST, DEAD_MONGO_PORT)
    check('响应未带出数据库目标地址',
          dead_target not in body and DEAD_MONGO_HOST not in body,
          dead_target)
    # 快速失败：等待时间受 MONGO_SERVER_SELECTION_TIMEOUT_MS(1200ms) 约束，
    # 留足余量；若这里慢到几十秒，说明探针会被一起拖死
    check('数据库故障时快速失败（<6 秒）', elapsed < 6.0, '{:.2f}s'.format(elapsed))

    stop(proc)


def main():
    print('=' * 72)
    print('健康检查端到端：/healthz')
    print('=' * 72)
    print('解释器：{}'.format(PYTHON))
    print('MongoDB：{}'.format(MONGO_BASE))
    print('结果目录：{}'.format(RESULTS_DIR), flush=True)

    for port in (PORT_OK, PORT_BAD):
        if not port_is_free(port):
            print('端口 {} 已被占用，先停掉占用它的进程再跑。'.format(port))
            return 1

    drop_test_db()
    try:
        section_ok_instance()
        section_degraded_instance()
    finally:
        for proc in LAUNCHED:
            if proc.poll() is None:
                stop(proc)
        drop_test_db()

    passed = sum(1 for _, ok in _results if ok)
    total = len(_results)
    print('\n{}'.format('=' * 72))
    for name, ok in _results:
        if not ok:
            print('  FAIL  {}'.format(name))
    print('===== {}/{} 通过 ====='.format(passed, total))
    print('=' * 72)
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
