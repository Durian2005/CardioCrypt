# -*- coding: utf-8 -*-
"""
仪表盘数据来源与请求层端到端验证（真实进程 + 真实 HTTP）

`tests/test_dashboard.py` 已经覆盖已登录场景（24 例，跑在真实 MongoDB 的
独立临时库上）。这里补的是**服务真正跑起来才会暴露**的那部分：路由注册、
未登录语义、JSON 序列化，以及真实 HTTP 下接口的实际输出。

已登录会话用与服务端相同的 `FLASK_SECRET_KEY` 直接签发一个 session cookie ——
省掉跑完整认证流程（需要先训练模型），又确实走的是真实 HTTP 而非测试客户端。

用法::

    python scripts/verify/batch2_e2e.py

跑在独立临时库上，结束时 drop，不触碰开发库或其他项目的数据库。
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from _common import ROOT, PYTHON, MONGO_BASE  # noqa: E402

TEST_DB = 'ecg_auth_db_b2verify'
SECRET = 'batch2-verify-secret'
PORT = 5033
BASE = 'http://127.0.0.1:{}'.format(PORT)
USER = 'verify_user'

_results = []


def check(name, ok, detail=''):
    _results.append((name, ok))
    line = '  {}  {}'.format('PASS' if ok else 'FAIL', name)
    if detail:
        line += '   -- {}'.format(detail)
    print(line)


def wait_for_server(timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', PORT), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def session_cookie(data):
    """用与服务端一致的密钥签发一个合法 session cookie。"""
    from flask import Flask
    from flask.sessions import SecureCookieSessionInterface

    app = Flask(__name__)
    app.secret_key = SECRET
    serializer = SecureCookieSessionInterface().get_signing_serializer(app)
    return serializer.dumps(data)


def http_get(path, cookie=None):
    headers = {'User-Agent': 'batch2e2e'}
    if cookie:
        headers['Cookie'] = 'session=' + cookie
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(BASE + path, headers=headers)
    try:
        resp = opener.open(req, timeout=30)
        status, raw = resp.status, resp.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read().decode('utf-8', 'replace')
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw


def build_env():
    env = dict(os.environ)
    env.update({
        'MONGO_URI': '{}/{}'.format(MONGO_BASE, TEST_DB),
        'FLASK_SECRET_KEY': SECRET,
        'FLASK_HOST': '127.0.0.1',
        'FLASK_PORT': str(PORT),
        'FLASK_DEBUG': '0',
        'FRONTEND_MODE': 'spa',
        'DEMO_MODE': '0',
        'LOG_LEVEL': 'WARNING',
        'MPLBACKEND': 'Agg',
    })
    # 本机默认代理指向一个已失效的端口，会阻断 urllib 与服务启动期的出站连接
    for key in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
        env.pop(key, None)
    return env


def main():
    from pymongo import MongoClient

    client = MongoClient(MONGO_BASE, serverSelectionTimeoutMS=3000)
    db = client[TEST_DB]
    db.users.delete_many({})
    db.auth_history.delete_many({})
    db.users.insert_one({'username': USER, 'created_at': None, 'model_path': None})

    proc = subprocess.Popen(
        [PYTHON, str(ROOT / 'web_auth' / 'app.py')],
        cwd=ROOT, env=build_env(),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    try:
        if not wait_for_server():
            check('服务启动', False, '等待超时')
            return 1
        check('服务启动', True, '{}:{}'.format('127.0.0.1', PORT))

        # ---- 一、未登录语义 ---------------------------------------------
        print('\n[一] 未登录：三个接口都必须拒绝')
        for path in ('/api/dashboard_data', '/api/realtime_health_data', '/api/health_trends'):
            status, _ = http_get(path)
            check('{} -> 401'.format(path), status == 401, '实际 {}'.format(status))

        # ---- 二、真实数据来源 -------------------------------------------
        print('\n[二] 已登录：真实字段跟着数据源走')
        cookie = session_cookie({'username': USER})

        status, payload = http_get('/api/dashboard_data', cookie)
        check('/api/dashboard_data -> 200', status == 200, '实际 {}'.format(status))
        sysstats = payload['system_stats']
        check('active_users 等于库中用户数',
              sysstats['active_users'] == 1, '得到 {}'.format(sysstats['active_users']))
        check('uptime 取自进程启动时刻',
              sysstats['uptime'].endswith('分钟') and sysstats['uptime'] != '7天 14小时 32分钟',
              sysstats['uptime'])
        check('total_devices 反映真实连接（当前无设备）',
              sysstats['total_devices'] == 0, '得到 {}'.format(sysstats['total_devices']))

        check('无历史记录时如实为 0',
              payload['user_stats']['total_logins'] == 0
              and payload['user_stats']['has_history'] is False)

        db.auth_history.insert_many([
            {'username': USER, 'result': 'success', 'duration_ms': 120},
            {'username': USER, 'result': 'success', 'duration_ms': 180},
            {'username': USER, 'result': 'failure', 'duration_ms': 200},
        ])
        status, payload = http_get('/api/dashboard_data', cookie)
        stats = payload['user_stats']
        check('认证次数随 auth_history 变化',
              (stats['total_logins'], stats['successful_auths'], stats['failed_auths']) == (3, 2, 1),
              '得到 {}'.format((stats['total_logins'], stats['successful_auths'], stats['failed_auths'])))
        check('平均耗时按真实记录计算',
              stats['avg_response_time'] == 167, '得到 {}'.format(stats['avg_response_time']))

        # ---- 三、示意数据标注 -------------------------------------------
        print('\n[三] 没有真实来源的字段必须被标出')
        fields = set(payload['synthetic_fields'])
        check('performance_data 已标注', 'performance_data' in fields)
        check('security_events 已标注', 'security_events' in fields)
        check('system_stats.data_integrity 已标注', 'system_stats.data_integrity' in fields)
        check('真实字段未被误标',
              not ({'user_stats', 'system_stats.uptime', 'system_stats.active_users'}
                   & fields),
              '标注清单：{}'.format(sorted(fields)))
        check('附有文字说明', bool(payload.get('synthetic_note')))

        status, rt = http_get('/api/realtime_health_data', cookie)
        check('实时数据带 synthetic 标记', rt.get('synthetic') is True)
        check('实时数据里 device_connected 为真实值', rt.get('device_connected') is False)
        check('实时数据字段名与消费者一致',
              {'heart_rate', 'emotion_status', 'alert_level'} <= set(rt))

        status, trends = http_get('/api/health_trends', cookie)
        check('趋势数据带 synthetic 标记', trends.get('synthetic') is True)

        # ---- 四、前端产物 -----------------------------------------------
        print('\n[四] 前端产物可达')
        status, body = http_get('/')
        check('/ 返回 SPA 页面', status == 200 and '<div id="root"' in body)

        index = os.path.join(ROOT, 'web_auth', 'static', 'dist', 'assets')
        has_js = any(n.startswith('index-') and n.endswith('.js') for n in os.listdir(index))
        check('dist 中存在构建产物', has_js)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        client.drop_database(TEST_DB)
        client.close()

    passed = sum(1 for _, ok in _results if ok)
    total = len(_results)
    print('\n===== {}/{} 通过 ====='.format(passed, total))
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
