# -*- coding: utf-8 -*-
"""
管理员后台测试

重点有两条：
  1. **权限**：未登录访问 `/api/admin/*` 或 `/manage/*` 必须被挡下，
     而不是返回数据；
  2. **信息暴露**：用户列表不得回传本机绝对路径。
"""

from tests.helpers import form_post, json_get, json_post, response_json


def _admin_login(client, csrf_token, credentials, follow=False):
    return form_post(
        client, '/manage/login',
        {'username': credentials['username'], 'password': credentials['password']},
        csrf_token, follow_redirects=follow,
    )


# ============================================================================
# 一、权限
# ============================================================================
class TestAdminAccessControl:
    def test_dashboard_requires_login(self, client):
        resp = client.get('/manage/dashboard')
        assert resp.status_code == 302
        assert '/manage/login' in resp.headers['Location']

    def test_users_api_requires_login(self, client):
        resp = client.get('/api/admin/users')
        assert resp.status_code == 302
        assert '/manage/login' in resp.headers['Location']

    def test_config_api_requires_login(self, client):
        resp = client.get('/api/admin/config')
        assert resp.status_code == 302

    def test_batch_delete_requires_login(self, client, csrf_token):
        resp = json_post(client, '/manage/batch_delete_users',
                         {'usernames': ['probe_user']}, csrf_token)
        assert resp.status_code == 302
        assert '/manage/login' in resp.headers['Location']

    def test_delete_user_requires_csrf_after_login(self, client, csrf_token,
                                                   admin_client_flask_app, existing_user):
        _admin_login(client, csrf_token, admin_client_flask_app)
        # 已登录，但没有令牌 -> 仍应被 CSRF 拦下
        resp = client.post('/manage/delete_user/{}'.format(existing_user))
        assert resp.status_code in (302, 403)
        assert client.get('/manage/dashboard').status_code == 200


# ============================================================================
# 二、登录
# ============================================================================
class TestAdminLogin:
    def test_wrong_password_is_refused(self, client, csrf_token, admin_client_flask_app):
        resp = _admin_login(client, csrf_token, {
            'username': admin_client_flask_app['username'],
            'password': 'definitely-wrong',
        })
        assert resp.status_code == 302
        assert '/manage/login' in resp.headers['Location']
        assert response_json(json_get(client, '/api/session'))['isAdmin'] is False

    def test_correct_password_grants_access(self, client, csrf_token,
                                            admin_client_flask_app, db):
        resp = _admin_login(client, csrf_token, admin_client_flask_app)
        assert resp.status_code == 302
        assert '/manage/dashboard' in resp.headers['Location']
        assert response_json(json_get(client, '/api/session'))['isAdmin'] is True
        assert client.get('/manage/dashboard').status_code == 200

    def test_overlong_credentials_are_refused(self, client, csrf_token):
        """超长口令必须在哈希校验之前被挡掉，避免 CPU 被拖满。"""
        resp = _admin_login(client, csrf_token, {
            'username': 'a' * 200, 'password': 'b' * 1000,
        })
        assert resp.status_code == 302
        assert response_json(json_get(client, '/api/session'))['isAdmin'] is False

    def test_login_is_rate_limited(self, client, csrf_token):
        credentials = {'username': 'admin', 'password': 'wrong'}
        for _ in range(5):
            _admin_login(client, csrf_token, credentials)

        resp = _admin_login(client, csrf_token, credentials, follow=True)
        assert '尝试过于频繁' in resp.get_data(as_text=True)


# ============================================================================
# 三、用户列表与信息暴露
# ============================================================================
class TestAdminUsersApi:
    def test_returns_user_list(self, client, csrf_token, admin_client_flask_app,
                               existing_user):
        _admin_login(client, csrf_token, admin_client_flask_app)

        payload = response_json(client.get('/api/admin/users'))
        assert payload['success'] is True
        assert [u['username'] for u in payload['users']] == [existing_user]

    def test_model_path_is_stripped_to_basename(self, client, csrf_token,
                                                admin_client_flask_app, db):
        """
        `model_path` 在库里存的是绝对路径；接口必须只回传文件名。

        字段名保留（前端表格在渲染它），但值不得含部署机器的目录结构。
        """
        db.users.insert_one({
            'username': 'path_probe',
            'created_at': None,
            'model_path': 'C:/Users/durian/Desktop/2.0/web_auth/models/path_probe.pth',
        })
        _admin_login(client, csrf_token, admin_client_flask_app)

        raw = client.get('/api/admin/users').get_data(as_text=True)
        assert 'C:/Users' not in raw
        assert 'durian' not in raw

        payload = client.get('/api/admin/users').get_json()
        entry = next(u for u in payload['users'] if u['username'] == 'path_probe')
        assert entry['model_path'] == 'path_probe.pth'
