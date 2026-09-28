# -*- coding: utf-8 -*-
"""
跨模块共享的扩展单例

放在独立模块是为了避免循环导入：蓝图要 mongo，core 也要 mongo，
而两者又都被 `create_app()` 用到。这里只做**实例化**，
真正的绑定（`mongo.init_app`）留给工厂 —— 这样测试可以用不同配置重复建应用。
"""

from flask_pymongo import PyMongo

from web_auth.config import CSRF_ENABLED
from web_auth.security import CSRFProtector, RateLimiter, clear_session_keep_csrf

# 先构造、后 init_app（见 create_app）
mongo = PyMongo()



LOGIN_LIMITER = RateLimiter(limit=10, window=60)         # /login 用户名尝试

ADMIN_LOGIN_LIMITER = RateLimiter(limit=5, window=60)    # /manage/login 口令尝试

VERIFY_START_LIMITER = RateLimiter(limit=10, window=60)  # /api/start_verification

CSRF = CSRFProtector()

__all__ = [
    'mongo',
    'CSRF',
    'CSRF_ENABLED',
    'LOGIN_LIMITER',
    'ADMIN_LOGIN_LIMITER',
    'VERIFY_START_LIMITER',
    'clear_session_keep_csrf',
]
