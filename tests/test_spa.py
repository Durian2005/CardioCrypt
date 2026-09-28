# -*- coding: utf-8 -*-
"""
SPA 适配层测试

这一层是用「新增接口 + 包装既有视图」的方式接入的，最容易在重构
（尤其是蓝图拆分导致的端点改名）时被静默破坏，所以单独成文件。

注意：这些接口与 `FRONTEND_MODE` 无关 —— 无论 classic 还是 spa 都会注册。
"""

from tests.helpers import json_get, json_post, response_json


# ============================================================================
# 一、会话投影接口
# ============================================================================
class TestSessionApi:
    def test_projection_shape_for_anonymous(self, client):
        payload = response_json(client.get('/api/session'))
        assert set(payload) == {
            'authenticated', 'username', 'isAdmin', 'pendingLogin', 'systemAvailable',
        }
        assert payload['authenticated'] is False
        assert payload['username'] is None
        assert payload['isAdmin'] is False
        assert payload['pendingLogin'] is None
        assert isinstance(payload['systemAvailable'], bool)

    def test_reflects_pending_login(self, client, csrf_token, existing_user):
        client.post('/login', data={'username': existing_user, 'csrf_token': csrf_token})
        payload = response_json(client.get('/api/session'))
        assert payload['pendingLogin'] == existing_user
        assert payload['authenticated'] is False

    def test_csrf_token_endpoint_returns_token(self, client):
        payload = response_json(client.get('/api/csrf-token'))
        assert payload['enabled'] is True
        assert len(payload['token']) >= 16

    def test_logout_json_clears_pending_login(self, client, csrf_token, existing_user):
        client.post('/login', data={'username': existing_user, 'csrf_token': csrf_token})

        resp = json_post(client, '/api/logout_json', None, csrf_token)
        assert response_json(resp)['success'] is True
        assert response_json(json_get(client, '/api/session'))['pendingLogin'] is None

    def test_admin_logout_json(self, client, csrf_token, admin_client_flask_app):
        client.post('/manage/login', data={
            'username': admin_client_flask_app['username'],
            'password': admin_client_flask_app['password'],
            'csrf_token': csrf_token,
        })
        assert response_json(json_get(client, '/api/session'))['isAdmin'] is True

        resp = json_post(client, '/api/admin/logout_json', None, csrf_token)
        assert response_json(resp)['success'] is True
        assert response_json(json_get(client, '/api/session'))['isAdmin'] is False


# ============================================================================
# 二、404 语义
# ============================================================================
class TestNotFoundHandling:
    def test_unknown_api_path_stays_a_real_404(self, client):
        """接口拼错时应拿到真正的 404，而不是被 SPA 兜底成一坨 HTML。"""
        resp = client.get('/api/definitely-not-a-route')
        assert resp.status_code == 404
        assert 'Not Found' in resp.get_data(as_text=True)
        assert '<div id="root">' not in resp.get_data(as_text=True), \
            '/api/ 前缀被 SPA 兜底接走了'

    def test_unknown_manage_path_stays_a_real_404(self, client):
        resp = client.get('/manage/definitely-not-a-route')
        assert resp.status_code == 404

    def test_unknown_static_path_stays_a_real_404(self, client):
        resp = client.get('/static/definitely-not-here.png')
        assert resp.status_code == 404


# ============================================================================
# 三、注册结果
# ============================================================================
class TestSpaRegistration:
    def test_spa_routes_configured(self, flask_app):
        routes = flask_app.config.get('SPA_ROUTES')
        assert routes, 'SPA_ROUTES 未写入配置'
        assert {'/', '/login', '/register', '/verify'} <= set(routes)

    def test_serve_index_returns_built_frontend(self, flask_app):
        """
        `SPA_SERVE_INDEX` 必须是可调用回调（前端切换会用到它），
        并且能真正吐出构建好的 index.html。

        构建产物 `web_auth/static/dist/` 是入库的（Flask 直接托管），
        所以这里出现 404 就意味着发布产物缺失，而不是环境问题。
        """
        serve_index = flask_app.config.get('SPA_SERVE_INDEX')
        assert callable(serve_index)

        with flask_app.test_request_context('/'):
            resp = serve_index()

        assert resp.status_code == 200, (
            '前端产物 web_auth/static/dist 缺失 —— 请在 web_auth/frontend '
            '执行 npm install && npm run build，并把产物一并入库'
        )
        assert 'text/html' in resp.headers.get('Content-Type', '')
