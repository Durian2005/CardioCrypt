#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
CardioCrypt — 心电/脉搏生物特征身份认证 Web 应用

本模块是**兼容入口**：真正的应用组装在 `web_auth/__init__.py::create_app()`，
路由按业务域拆在 `web_auth/blueprints/`，进程内共享状态集中在 `web_auth/state.py`。

保留本模块是为了不打断既有用法：

    python web_auth/app.py
    gunicorn -w 1 --threads 8 -b 127.0.0.1:5000 web_auth.app:app

两者拿到的都是同一份 `create_app()` 产物。
"""

import os
import sys

# `python web_auth/app.py` 运行时，sys.path[0] 是 web_auth/ 目录本身，
# 项目根不在搜索路径里 —— 必须先补上，否则 `import web_auth` 直接失败。
# （用 `python -m web_auth.app` 或 WSGI 服务器启动时这一步是无害的空操作。）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web_auth import create_app
from web_auth.config import logger

# 模块级单例：WSGI 服务器与本模块的 __main__ 分支都从这里取应用
app = create_app()


if __name__ == '__main__':
    # 索引初始化已在 create_app() 内完成，此处不再重复调用，避免开发模式下建两次。

    # 这里只用于本地开发。生产环境请改用 WSGI 服务器，例如：
    #   gunicorn -w 1 --threads 8 -b 127.0.0.1:5000 web_auth.app:app
    #
    # 调试模式默认关闭：一旦开启，Werkzeug 会暴露可执行任意代码的交互式调试器，
    # 并显示完整堆栈与配置。仅在完全可信的本机环境下临时用 FLASK_DEBUG=1 打开。
    _debug = os.environ.get('FLASK_DEBUG', '0').strip().lower() in ('1', 'true', 'yes', 'on')
    _host = os.environ.get('FLASK_HOST', '127.0.0.1').strip() or '127.0.0.1'
    try:
        _port = int(os.environ.get('FLASK_PORT', '5000'))
    except ValueError:
        logger.warning("FLASK_PORT 不是合法端口号，回退到 5000")
        _port = 5000

    if _debug and _host not in ('127.0.0.1', 'localhost'):
        logger.warning(
            "调试模式已开启且监听地址为 %s —— 调试器可能被局域网内其他主机访问，"
            "请勿在不可信网络中使用", _host
        )

    # 启动 Flask 应用，禁用自动重载器以避免重复日志
    logger.info("开发服务器启动: http://%s:%s (debug=%s)", _host, _port, _debug)
    app.run(debug=_debug, host=_host, port=_port, use_reloader=False)
