# -*- coding: utf-8 -*-
"""
SPA 适配层

作用：
  1. 为 React 前端补充缺失的「会话 / 管理后台」JSON 接口；
  2. 托管前端构建产物（web_auth/static/dist）；
  3. 前端路由回退（catch-all 返回 index.html）。

设计原则：
  - **不修改任何既有业务路由**。原始 Jinja2 页面与 /api 全部保持原样，
    本模块只做「新增」与「兜底」。
  - 所有写操作沿用原有函数或原有路由，避免逻辑分叉。

接入方式：在 app.py 末尾（启动前）调用 register_spa(app, mongo)。
"""

import os
import logging

from flask import (
    jsonify,
    request,
    send_from_directory,
    session,
)

logger = logging.getLogger('web_auth.spa')

# 前端构建产物目录
DIST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'dist')

# 未构建前端时统一返回的提示页。
# 原来这段 HTML 在 `spa_root` 与 `_serve_index` 里各写了一份（逐字相同），
# 共用这一个常量后不会出现「改了一处、另一处还是旧文案」。
_NOT_BUILT_HTML = (
    "<h1>前端尚未构建</h1>"
    "<p>请在 web_auth/frontend 目录执行 "
    "<code>npm install && npm run build</code></p>"
)


def _serve_index():
    """
    返回前端入口页；产物不存在时给出明确提示。

    刻意定义在所有引用点之前：`spa_fallback_named` 与 `spa_not_found` 都要用
    它，原先定义在最后、靠 Python 的运行时名字解析才能工作，读起来像 bug。
    """
    index = os.path.join(DIST_DIR, 'index.html')
    if not os.path.exists(index):
        return _NOT_BUILT_HTML, 404
    return send_from_directory(DIST_DIR, 'index.html')


def register_spa(app, mongo, admin_required):
    """
    注册 SPA 相关路由

    参数:
        app: Flask 应用实例
        mongo: PyMongo 实例（沿用主模块的全局实例）
        admin_required: 主模块的管理员校验装饰器
    """

    # ---------------------------------------------------------------
    # 一、会话信息
    # ---------------------------------------------------------------
    @app.route('/api/session', methods=['GET'])
    def spa_session_info():
        """
        返回当前会话状态，供前端路由守卫判断。

        Flask 的 session 是签名的客户端 cookie，这里做只读投影，
        不下发任何敏感字段。
        """
        username = session.get('username')
        is_admin = 'admin' in session
        pending = session.get('pending_login')

        return jsonify({
            'authenticated': bool(username),
            'username': username,
            'isAdmin': bool(is_admin),
            'pendingLogin': pending,
            'systemAvailable': bool(app.config.get('SYSTEM_AVAILABLE', False)),
            # 演示模式：开启时前端各处需显著提示「合成数据」，避免被误当成
            # 真实生物特征采集。默认关闭，见 config.py::DEMO_MODE
            'demoMode': bool(app.config.get('DEMO_MODE', False)),
        })

    # ---------------------------------------------------------------
    # 二、CSRF 令牌
    # ---------------------------------------------------------------
    @app.route('/api/csrf-token', methods=['GET'])
    def spa_csrf_token():
        """
        下发当前会话的 CSRF 令牌。

        为什么必须是接口：SPA 的 index.html 是构建好的静态文件，无法在渲染时
        注入令牌；而令牌存在 session cookie 里（httponly），JS 也读不到。
        故先用 GET 取一次，之后放进 X-CSRFToken 请求头。

        令牌本身不是秘密 —— 它只在「跨站」语境下起鉴别作用：攻击者能从自己
        的会话拿到一个合法令牌，但读不到受害者会话里的那一个（同源策略）。
        """
        protector = app.config.get('CSRF_PROTECTOR')
        if protector is None or not app.config.get('CSRF_ENABLED', True):
            # 未启用时下发空令牌，前端据此跳过请求头，便于兼容旧调用方
            return jsonify({'success': True, 'enabled': False, 'token': ''})

        return jsonify({
            'success': True,
            'enabled': True,
            'token': protector.ensure(session),
        })

    # ---------------------------------------------------------------
    # 三、退出（JSON 语义，供 SPA 调用）
    # ---------------------------------------------------------------
    @app.route('/api/logout_json', methods=['GET', 'POST'])
    def spa_logout_json():
        """退出用户会话，返回 JSON 而非重定向。"""
        session.pop('username', None)
        session.pop('pending_login', None)
        logger.info("用户会话已退出")
        return jsonify({'success': True})

    @app.route('/api/admin/logout_json', methods=['GET', 'POST'])
    def spa_admin_logout_json():
        """退出管理员会话，返回 JSON。"""
        session.pop('admin', None)
        logger.info("管理员会话已退出")
        return jsonify({'success': True})

    # ---------------------------------------------------------------
    # 四、管理后台数据接口
    # ---------------------------------------------------------------
    @app.route('/api/admin/users', methods=['GET'])
    @admin_required
    def spa_admin_users():
        """返回用户列表（供后台表格消费）。"""
        try:
            users = []
            cursor = mongo.db.users.find(
                {},
                {'username': 1, 'created_at': 1, 'model_path': 1, '_id': 0},
            )
            for doc in cursor:
                created = doc.get('created_at')
                # 只回传模型「文件名」而非数据库里存的绝对路径：
                # 后台表格仅需展示"该用户是否已有模型"，而绝对路径会暴露
                # 部署机器的目录结构与用户名。字段名保持不变以兼容现有前端。
                raw_model_path = doc.get('model_path')
                users.append({
                    'username': doc.get('username', ''),
                    'created_at': created.isoformat() if hasattr(created, 'isoformat') else (str(created) if created else None),
                    'model_path': os.path.basename(raw_model_path) if raw_model_path else None,
                })
            users.sort(key=lambda u: u['username'])
            return jsonify({'success': True, 'users': users})
        except Exception as e:
            logger.error(f"读取用户列表失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/admin/config', methods=['GET'])
    @admin_required
    def spa_admin_config():
        """返回动态配置全文（供后台表单初始化）。"""
        try:
            from ecgppg_system.config import config as dynamic_config
            return jsonify({'success': True, 'config': dynamic_config.get_config()})
        except Exception as e:
            logger.error(f"读取动态配置失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    # ---------------------------------------------------------------
    # 五、前端静态资源与路由回退
    # ---------------------------------------------------------------
    @app.route('/static/dist/<path:filename>')
    def spa_dist_assets(filename):
        """托管前端构建产物（带长缓存，Vite 产物已带内容指纹）。"""
        return send_from_directory(DIST_DIR, filename)

    @app.route('/app', defaults={'path': ''})
    @app.route('/app/<path:path>')
    def spa_root(path):
        """便于对比调试：/app 前缀访问新前端。"""
        return _serve_index()

    # 前端路由清单：这些路径交给 SPA 渲染
    SPA_ROUTES = {
        '/', '/login', '/register', '/verify',
        '/dashboard', '/manage/login', '/manage/dashboard',
    }

    @app.route('/spa/<path:path>')
    def spa_fallback_named(path):
        """命名的兜底入口，便于反向代理指向。"""
        return _serve_index()

    # 未知路径：交给 SPA 渲染（由其内部 * 路由展示 404 页面），
    # 但 /api、/static、/manage 这类有后端语义的前缀必须保留真正的 404，
    # 否则接口拼错时会拿到一坨 HTML，调试会非常痛苦。
    _BACKEND_PREFIXES = ('/api/', '/static/', '/manage/')

    @app.errorhandler(404)
    def spa_not_found(error):
        path = request.path or ''
        if (
            request.method in ('GET', 'HEAD')
            and not path.startswith(_BACKEND_PREFIXES)
            and '.' not in os.path.basename(path)
        ):
            if os.path.exists(os.path.join(DIST_DIR, 'index.html')):
                return _serve_index()
        return error, 404

    # 暴露给外部使用（由 switch_frontend 调用）
    app.config['SPA_ROUTES'] = SPA_ROUTES
    app.config['SPA_SERVE_INDEX'] = _serve_index

    logger.info("SPA 适配层注册完成（新增 JSON 接口 6 个 + 静态托管）")
    return True


def make_frontend_switch(app, mode):
    """
    切换前端模式：
      - 'classic'：仅使用原有 Jinja2 页面
      - 'spa'：主要入口页改由 React 前端接管

    实现方式（关键，保证后端逻辑零改动）：
      对既有 HTML 视图函数做**包装**——GET 请求返回前端 index.html，
      POST 请求仍走原函数（表单提交语义保留，重定向逻辑照旧）。
      这样前后端契约完全不变，切换只是「谁来渲染这个页面」。
    """
    if mode not in ('classic', 'spa'):
        raise ValueError("mode 必须是 'classic' 或 'spa'")

    app.config['FRONTEND_MODE'] = mode
    if mode == 'classic':
        logger.info("前端模式: classic（沿用原 Jinja2 页面）")
        return mode

    serve_index = app.config.get('SPA_SERVE_INDEX')
    if not serve_index:
        logger.error("SPA 服务函数缺失，保持 classic 模式")
        app.config['FRONTEND_MODE'] = 'classic'
        return 'classic'

    # 需要被前端接管的端点名 -> 路径
    # 只接管「页面渲染」，不接管 API。
    # 注意：路由已按业务域拆进蓝图（web_auth/blueprints/），端点名带上了
    # 蓝图前缀，这里必须跟着改 —— 否则会静默降级成「未找到端点，跳过接管」，
    # 页面照常返回 Jinja2 模板，表现为「前端切换没生效」。
    SPA_ENDPOINTS = {
        'auth.index': '/',
        'auth.login': '/login',
        'auth.register': '/register',
        'auth.verify': '/verify',
        'dashboard.dashboard': '/dashboard',
        'auth.collect_data': '/collect_data/<username>',
        'admin.admin_login': '/manage/login',
        'admin.admin_dashboard': '/manage/dashboard',
    }

    for endpoint in list(SPA_ENDPOINTS.keys()):
        view = app.view_functions.get(endpoint)
        if view is None:
            logger.warning(f"未找到端点 {endpoint}，跳过接管")
            continue
        app.view_functions[endpoint] = _wrap_html_view(view, serve_index)

    logger.info(f"前端模式: spa（已接管 {len(SPA_ENDPOINTS)} 个页面入口）")
    return mode


def _wrap_html_view(original_view, serve_index):
    """
    包装 HTML 视图：
      - GET  -> 返回前端 index.html（由 React Router 接管渲染）
      - 其他 -> 原样交回原视图（保留 POST 表单提交与重定向）
    """
    from functools import wraps

    @wraps(original_view)
    def wrapper(*args, **kwargs):
        if request.method == 'GET':
            return serve_index()
        return original_view(*args, **kwargs)

    return wrapper
