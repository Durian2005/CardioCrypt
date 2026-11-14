# -*- coding: utf-8 -*-
"""验证脚本的共享运行配置。

本目录下的脚本都用 ``python scripts/verify/<name>.py`` 直接运行，
因此这里通过 ``sys.path`` 保证 ``import _common`` 可用，并把所有与环境
相关的取值收口到一处：

============================  ==========================================
环境变量                      含义 / 默认值
============================  ==========================================
``VERIFY_MONGO_BASE``         MongoDB 地址，默认 ``mongodb://localhost:27017``
``VERIFY_RESULTS_DIR``        日志与结构化结果目录，默认系统临时目录下的
                              ``cardiocrypt-verify``
``VERIFY_BASE_URL``           已启动服务的地址（仅 p0_regression 使用）
============================  ==========================================

解释器一律取 ``sys.executable``：既能用当前虚拟环境，也能在 CI 的
``venv/bin/python`` 下工作，不假设 Windows 专有路径。
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable
MONGO_BASE = os.environ.get('VERIFY_MONGO_BASE', 'mongodb://localhost:27017')
RESULTS_DIR = Path(
    os.environ.get('VERIFY_RESULTS_DIR')
    or (Path(tempfile.gettempdir()) / 'cardiocrypt-verify')
)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
