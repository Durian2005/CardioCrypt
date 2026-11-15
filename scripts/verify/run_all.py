# -*- coding: utf-8 -*-
"""验证脚本统一入口：串行跑完全部检查并汇总结果。

用法::

    python scripts/verify/run_all.py                # 全部
    python scripts/verify/run_all.py --quick        # 只跑不需要起服务的检查
    python scripts/verify/run_all.py --only demo_mode_e2e.py

前置条件：MongoDB 可达（默认 ``mongodb://localhost:27017``，可用
``VERIFY_MONGO_BASE`` 覆盖）。全部脚本都使用独立临时库，结束时 drop。
日志与结构化结果写到 ``VERIFY_RESULTS_DIR``（默认系统临时目录下的
``cardiocrypt-verify``），不会污染仓库。
"""
import os
import subprocess
import sys
import time
from pathlib import Path

from _common import PYTHON, RESULTS_DIR, ROOT

HERE = Path(__file__).resolve().parent

STEPS = [
    ('健康检查端点端到端', 'healthz_e2e.py', False),
    ('算法层等价性对照', 'p2_perf_equivalence.py', True),
    ('演示模式端到端', 'demo_mode_e2e.py', False),
    ('仪表盘与请求层端到端', 'batch2_e2e.py', False),
    ('启动路径回归（SPA / classic 双模式）', 'c_tier_regression.py', False),
    ('认证链路端到端（含服务启停）', 'run_p0_with_service.py', False),
]

SEPARATOR = '=' * 72


def run_step(title, name):
    log_path = RESULTS_DIR / (Path(name).stem + '.log')
    started = time.monotonic()
    print('\n%s\n%s  ->  %s\n%s' % (SEPARATOR, title, name, SEPARATOR), flush=True)
    with open(str(log_path), 'w', encoding='utf-8') as log:
        rc = subprocess.call(
            [PYTHON, str(HERE / name)], cwd=str(ROOT), env=dict(os.environ),
            stdout=log, stderr=subprocess.STDOUT,
        )
    elapsed = time.monotonic() - started
    try:
        tail = log_path.read_text(encoding='utf-8', errors='replace').strip().splitlines()[-8:]
    except OSError:
        tail = []
    print('\n'.join(tail) if tail else '(无输出)')
    print('[%s] %s  退出码=%d  耗时=%.1fs  日志=%s'
          % ('PASS' if rc == 0 else 'FAIL', title, rc, elapsed, log_path), flush=True)
    return rc == 0


def main():
    args = sys.argv[1:]
    quick = '--quick' in args
    only = None
    if '--only' in args:
        idx = args.index('--only')
        if idx + 1 >= len(args):
            sys.exit('--only 需要跟一个脚本文件名')
        only = args[idx + 1]

    if only:
        steps = [(only, only, True)]
    elif quick:
        steps = [s for s in STEPS if s[2]]
    else:
        steps = STEPS

    env = dict(os.environ)
    env.setdefault('MPLBACKEND', 'Agg')
    os.environ.update(env)

    print('项目根：%s' % ROOT)
    print('解释器：%s' % PYTHON)
    print('结果目录：%s' % RESULTS_DIR)
    print('待运行：%d 项' % len(steps), flush=True)

    failed = []
    for title, name, _ in steps:
        if not run_step(title, name):
            failed.append(title)

    print('\n%s' % SEPARATOR)
    for title, name, _ in steps:
        print('  %-4s %s' % ('FAIL' if title in failed else 'PASS', title))
    print('合计 %d 项，失败 %d 项' % (len(steps), len(failed)))
    print(SEPARATOR)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
