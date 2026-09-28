# -*- coding: utf-8 -*-
"""
CardioCrypt Web 应用

对外只暴露一个 `create_app()`：应用工厂。它负责把配置、扩展、蓝图、
SPA 适配层组装成一个可运行的 Flask 应用。

为什么用工厂而不是模块级 `app = Flask(__name__)`
------------------------------------------------
1. **测试可控**：`create_app({'TESTING': True})` 可以在同一进程里建出
   配置不同的实例，不必依赖导入顺序或环境变量；
2. **职责清晰**：扩展的实例化（`extensions.py`）与绑定（这里）分离，
   避免「导入模块即绑定某个具体 app」的隐式耦合；
3. **循环导入的天然解法**：蓝图只在工厂调用时导入，此时配置层与
   视图层都已就绪。

既有用法保持不变（见 `web_auth/app.py`）::

    python web_auth/app.py
    gunicorn -w 1 --threads 8 -b 127.0.0.1:5000 web_auth.app:app

⚠️ **单进程多线程部署**：设备连接句柄、注册进度、验证结果、模型缓存都在
`web_auth/state.py` 里，是进程内内存态。多 worker 会让这些状态在进程间分裂
（表现为「刚采集的进度查不到」「连着的设备在另一个请求里显示未连接」）。
"""

from datetime import datetime

from flask import Flask, flash, jsonify, redirect, request, session, url_for

from web_auth import core, state
from web_auth.config import (
    CSRF_ENABLED,
    FRONTEND_MODE,
    MAX_CONTENT_LENGTH,
    MONGO_SERVER_SELECTION_TIMEOUT_MS,
    MONGO_URI,
    PERMANENT_SESSION_LIFETIME,
    SECRET_KEY,
    SECRET_KEY_FROM_FILE,
    logger,
)
from web_auth.extensions import CSRF, mongo

__all__ = ['create_app']


# ---------------------------------------------------------------------------
# 模板与请求钩子
# ---------------------------------------------------------------------------
def now_filter():
    """返回当前日期时间，供模板使用。"""
    return datetime.now()


def _verify_csrf():
    """对所有写操作做 CSRF 校验（放行时返回 None）。"""
    if not CSRF_ENABLED or CSRF.validate(session, request):
        return None

    logger.warning(
        "CSRF 校验失败: method=%s path=%s ip=%s",
        request.method, request.path, core.client_ip(),
    )
    # 接口调用方期望 JSON；页面表单则给一句能看懂的中文提示
    if request.path.startswith('/api/') or request.is_json:
        return jsonify({'success': False, 'error': '请求校验失败，请刷新页面后重试'}), 403
    flash('页面已过期，请刷新后重试')
    return redirect(url_for('auth.index'))


def _inject_csrf_token():
    """
    向模板注入 csrf_token

    旧版 Jinja2 页面靠它渲染隐藏字段，以及给 ajax 设全局请求头。
    这里一并确保当前会话已有令牌。
    """
    return {'csrf_token': CSRF.ensure(session) if CSRF_ENABLED else ''}


# ---------------------------------------------------------------------------
# 应用工厂
# ---------------------------------------------------------------------------
def create_app(config_overrides=None):
    """
    组装并返回 Flask 应用。

    参数:
        config_overrides: 可选的配置覆盖字典，主要用于测试
                          （例如 `{'TESTING': True}`）。
    """
    app = Flask(__name__)

    app.secret_key = SECRET_KEY
    if SECRET_KEY_FROM_FILE:
        logger.warning(
            "未设置 FLASK_SECRET_KEY，已使用本地持久化密钥（web_auth/.flask_secret_key）。"
            "该文件保证同一部署内多进程密钥一致；生产环境建议显式配置该环境变量。"
        )

    app.config.update(
        MONGO_URI=MONGO_URI,
        PERMANENT_SESSION_LIFETIME=PERMANENT_SESSION_LIFETIME,
        MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
        # 供 SPA 适配层感知开关状态（/api/csrf-token 与前端行为都依赖它）
        CSRF_ENABLED=CSRF_ENABLED,
        CSRF_PROTECTOR=CSRF,
    )
    if config_overrides:
        app.config.update(config_overrides)

    # 扩展绑定放在配置之后：PyMongo 会在这里读取 MONGO_URI 与超时设置。
    mongo.init_app(app, serverSelectionTimeoutMS=MONGO_SERVER_SELECTION_TIMEOUT_MS)

    # 管理员运行时配置（可被后台「参数修改」重新加载）
    state.admin_config = core.load_app_config()

    app.template_filter('now')(now_filter)
    app.jinja_env.globals['now'] = now_filter
    app.before_request(_verify_csrf)
    app.context_processor(_inject_csrf_token)

    _register_blueprints(app)
    _register_spa(app)

    # 索引创建属于「进程启动」阶段的事：生产用 WSGI 服务器导入本模块取 app 时，
    # __main__ 分支不会执行 —— 而 username 的唯一索引正是防止重名的唯一保障。
    core.init_system_on_startup()

    return app


def _register_blueprints(app):
    """按业务域注册蓝图。"""
    from web_auth.blueprints.admin import bp as admin_bp
    from web_auth.blueprints.auth import bp as auth_bp
    from web_auth.blueprints.dashboard import bp as dashboard_bp
    from web_auth.blueprints.device import bp as device_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(device_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)


def _register_spa(app):
    """
    接入 SPA 适配层。

    适配层失败不应让整个应用起不来：classic 模式下它也只负责托管静态产物，
    少了它顶多是没有 React 前端，Jinja2 页面照常可用。
    """
    try:
        from web_auth.spa_adapter import make_frontend_switch, register_spa

        app.config['SYSTEM_AVAILABLE'] = core.SYSTEM_AVAILABLE
        register_spa(app, mongo, core.admin_required)
        mode = FRONTEND_MODE if FRONTEND_MODE in ('spa', 'classic') else 'spa'
        make_frontend_switch(app, mode)
        logger.info("前端模式: %s", app.config.get('FRONTEND_MODE'))
    except Exception as exc:  # pragma: no cover - 兜底，正常路径不该走到
        logger.error("SPA 适配层注册失败: %s", exc)
