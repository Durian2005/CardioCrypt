"""起一个全新的 classic 服务 → 跑 p0_regression → 关掉服务。

p0_regression 有两个前置条件：FRONTEND_MODE=classic、且服务必须是新进程
（脚本末尾会把进程内 LOGIN_LIMITER 打满，复用旧进程会产生假失败）。
这里把两件事绑在一起，避免手工启停漏掉其一。
"""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from _common import ROOT, PYTHON, RESULTS_DIR

PY = PYTHON
SERVICE_LOG = RESULTS_DIR / 'p0_service.log'

env = dict(os.environ)
env['FRONTEND_MODE'] = 'classic'
env['DEMO_MODE'] = '0'
env.pop('ADMIN_USERNAME', None)
env.pop('ADMIN_PASSWORD', None)  # 与 p0_regression 默认的 admin/admin123 对齐

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
rc = 1
with SERVICE_LOG.open('w', encoding='utf-8') as log:
    proc = subprocess.Popen(
        [str(PY), 'web_auth/app.py'], cwd=str(ROOT), env=env,
        stdout=log, stderr=subprocess.STDOUT)
    try:
        ready = False
        for _ in range(80):
            if proc.poll() is not None:
                raise RuntimeError('服务进程提前退出，日志见 %s' % SERVICE_LOG)
            try:
                opener.open('http://127.0.0.1:5000/login', timeout=1).close()
                ready = True
                break
            except Exception:
                time.sleep(0.5)
        if not ready:
            raise RuntimeError('服务 40 秒内未就绪，日志见 %s' % SERVICE_LOG)
        print('classic 服务已就绪，开始跑 p0_regression', flush=True)
        rc = subprocess.call(
            [str(PY), str(Path(__file__).with_name('p0_regression.py'))],
            cwd=str(ROOT), env=env)
        print('p0_regression EXIT=%d' % rc, flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        print('服务已关闭', flush=True)

sys.exit(rc)
