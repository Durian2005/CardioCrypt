# -*- coding: utf-8 -*-
"""
演示模式端到端验证

对照运行两次，唯一差别是 DEMO_MODE：

  关闭（默认）：无设备时注册入口被拒；直接调用采集接口同样判定失败
  开启        ：无设备也能走通「注册 → 训练 → 登录 → 验证」，
                且注册与验证的结果都带 demo 标记，训练出的是真模型而非占位文件

用法::

    python scripts/verify/demo_mode_e2e.py

两条链路都跑在独立临时库上，结束时 drop，不触碰开发库或其他项目的数据库。
"""

import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from _common import ROOT, PYTHON, MONGO_BASE, RESULTS_DIR  # noqa: E402

TEST_DB = 'ecg_auth_db_demoe2e'

_probe_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Session:
    """
    带 cookie jar 的极简会话。

    必须用 jar 而不是手动读 Set-Cookie：登录是 302 到 /verify，urllib 跟随
    重定向时会重新发请求 —— 手动管理的话第二个请求还带着旧 cookie，
    表现为「登录明明 302 成功了，/verify 却又 302 回 /login」。
    """

    def __init__(self, base):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.jar),
        )
        self.csrf = ''

    def _open(self, req):
        try:
            return self.opener.open(req, timeout=60)
        except urllib.error.HTTPError as e:
            return e

    def get(self, path):
        resp = self._open(urllib.request.Request(
            self.base + path, headers={'User-Agent': 'demoe2e'}))
        raw = resp.read().decode('utf-8', 'replace')
        try:
            return resp.status, json.loads(raw)
        except ValueError:
            return resp.status, raw

    def post_json(self, path, body):
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode('utf-8'),
            headers={
                'User-Agent': 'demoe2e',
                'Content-Type': 'application/json',
                'X-CSRFToken': self.csrf,
            },
            method='POST',
        )
        resp = self._open(req)
        raw = resp.read().decode('utf-8', 'replace')
        try:
            return resp.status, json.loads(raw)
        except ValueError:
            return resp.status, raw

    def post_form(self, path, fields):
        fields = dict(fields)
        fields['csrf_token'] = self.csrf
        req = urllib.request.Request(
            self.base + path,
            data=urllib.parse.urlencode(fields).encode('utf-8'),
            headers={
                'User-Agent': 'demoe2e',
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            method='POST',
        )
        resp = self._open(req)
        return resp.status, resp.read().decode('utf-8', 'replace')

    def fetch_csrf(self):
        _, payload = self.get('/api/csrf-token')
        self.csrf = payload.get('token', '')
        return self.csrf


def _free_port(preferred):
    for port in range(preferred, preferred + 40):
        with socket.socket() as s:
            if s.connect_ex(('127.0.0.1', port)) != 0:
                return port
    raise RuntimeError('找不到空闲端口')


def launch(port, demo):
    env = dict(os.environ)
    env.update({
        'MONGO_URI': '{}/{}'.format(MONGO_BASE, TEST_DB),
        'FLASK_SECRET_KEY': 'demoe2e-secret',
        'ADMIN_USERNAME': 'demoe2e_admin',
        'ADMIN_PASSWORD': 'demoe2e-pw',
        'LOG_LEVEL': 'INFO',
        'CSRF_ENABLED': '1',
        'FRONTEND_MODE': 'classic',
        'MPLBACKEND': 'Agg',
        'STATE_CLEANUP_INTERVAL': '3600',
        'FLASK_HOST': '127.0.0.1',
        'FLASK_PORT': str(port),
        'FLASK_DEBUG': '0',
        'DEMO_MODE': '1' if demo else '0',
    })
    for key in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
        env.pop(key, None)

    log_path = RESULTS_DIR / 'demo_e2e_{}.log'.format(port)
    log = open(log_path, 'w', encoding='utf-8')
    proc = subprocess.Popen(
        [PYTHON, str(ROOT / 'web_auth' / 'app.py')],
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    base = 'http://127.0.0.1:{}'.format(port)
    for _ in range(120):
        if proc.poll() is not None:
            raise RuntimeError('进程已退出，见 {}'.format(log_path))
        try:
            _probe_opener.open(base + '/api/session', timeout=2)
            return proc, base, log_path
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError('实例未在 60 秒内就绪')


def poll_registration(s, username, timeout=240):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        _, payload = s.get('/api/registration_status/{}'.format(username))
        if isinstance(payload, dict) and payload.get('success'):
            last = payload['status']
            if last.get('status') in ('completed', 'failed', 'error'):
                return last
        time.sleep(1.0)
    return last or {}


def poll_verification(s, timeout=180):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        _, payload = s.get('/api/verification_status')
        if isinstance(payload, dict):
            last = payload
            if payload.get('status') in ('completed', 'failed'):
                return payload
        time.sleep(0.5)
    return last or {}


def drop_test_db():
    from pymongo import MongoClient
    MongoClient(MONGO_BASE, serverSelectionTimeoutMS=3000).drop_database(TEST_DB)


def run_case(demo, port):
    label = 'DEMO_MODE=1' if demo else 'DEMO_MODE=0（默认）'
    print('\n' + '=' * 62)
    print('== {} =='.format(label))
    print('=' * 62)

    drop_test_db()
    proc, base, log_path = launch(port, demo)
    results = []
    try:
        s = Session(base)
        s.fetch_csrf()

        _, session_info = s.get('/api/session')
        print('  /api/session demoMode = {}'.format(session_info.get('demoMode')))
        results.append(('会话投影的 demoMode 与开关一致',
                        session_info.get('demoMode') is bool(demo)))

        username = 'demoe2e_user'
        s.post_form('/register', {'username': username})
        s.fetch_csrf()

        status, payload = s.post_json('/api/start_data_collection', {'username': username})
        print('  start_data_collection -> {} {}'.format(status, payload))
        accepted = isinstance(payload, dict) and payload.get('success')

        if not accepted:
            results.append(('无设备时注册入口被拒绝', not demo))
            results.append(('拒绝理由指向设备连接',
                            '设备' in str(payload.get('error', ''))))
        else:
            reg = poll_registration(s, username)
            shown = {k: v for k, v in reg.items() if k not in ('data', 'heart_rates')}
            print('  最终注册状态:', shown)
            results.append(('注册走通并训练出模型', reg.get('status') == 'completed'))
            if demo:
                results.append(('注册结果带 demo 标记', reg.get('demo') is True))
                results.append(('注册降级原因留痕', bool(reg.get('demo_reasons'))))

            # 直连数据库确认用户与模型文件确实产生
            from pymongo import MongoClient
            cli = MongoClient(MONGO_BASE, serverSelectionTimeoutMS=3000)
            user = cli[TEST_DB].users.find_one({'username': username})
            cli.close()
            results.append(('用户已写入数据库', user is not None))

            model_path = (user or {}).get('model_path') or ''
            exists = bool(model_path) and os.path.exists(model_path)
            if exists:
                size = os.path.getsize(model_path)
                # 曾经的降级路径会写一个内容为「模拟模型文件」的占位 .pth，
                # 只有十几字节；真模型是 torch 序列化产物，至少几十 KB。
                results.append(('模型文件不是伪造占位（{} 字节）'.format(size), size > 1024))
            else:
                print('  模型文件不存在:', model_path)
                results.append(('模型文件不是伪造占位', False))

            # 验证链路
            s.post_form('/login', {'username': username})
            s.fetch_csrf()
            _, vstart = s.post_json('/api/start_verification', {})
            print('  start_verification ->', vstart)
            verdict = poll_verification(s)
            print('  最终验证响应:', verdict)
            results.append(('验证给出明确结论',
                            verdict.get('status') in ('completed', 'failed')))
            if demo:
                results.append(('验证结果带 demo 标记', verdict.get('demo') is True))

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        drop_test_db()

    ok = 0
    for name, passed in results:
        print('  [{}] {}'.format('PASS' if passed else 'FAIL', name))
        ok += 1 if passed else 0
    print('  ---- {}/{} ----'.format(ok, len(results)))
    print('  日志: {}'.format(log_path))
    return ok, len(results)


def main():
    total_ok = total = 0
    for demo, port in ((False, 5021), (True, 5022)):
        ok, n = run_case(demo, _free_port(port))
        total_ok += ok
        total += n

    print('\n' + '=' * 62)
    print('总计 {}/{} 通过'.format(total_ok, total))
    return 0 if total_ok == total else 1


if __name__ == '__main__':
    sys.exit(main())
