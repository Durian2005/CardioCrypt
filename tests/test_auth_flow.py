# -*- coding: utf-8 -*-
"""
认证主流程测试：登录 → 验证 → 会话

断言三组行为契约：判定结论的完整性（附加请求参数不得影响结果）、
会话清理与反用户枚举、CSRF 令牌校验 —— 这些断言是防止契约被破坏的护栏。
"""

from pathlib import Path

from tests.helpers import form_post, json_get, json_post, response_json

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ============================================================================
# 一、登录
# ============================================================================
class TestLogin:
    def test_login_page_renders(self, client):
        resp = client.get('/login')
        assert resp.status_code == 200

    def test_unknown_user_gets_generic_message(self, client, csrf_token, db):
        """反枚举：失败提示不得暴露「用户是否存在」。"""
        resp = form_post(client, '/login', {'username': 'nobody-here'}, csrf_token)
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

        page = client.get('/login').get_data(as_text=True)
        assert '用户名或验证信息无效' in page
        assert '用户不存在' not in page

    def test_known_user_moves_to_verify(self, client, csrf_token, existing_user):
        resp = form_post(client, '/login', {'username': existing_user}, csrf_token)
        assert resp.status_code == 302
        assert '/verify' in resp.headers['Location']

        payload = response_json(json_get(client, '/api/session'))
        assert payload['pendingLogin'] == existing_user
        assert payload['authenticated'] is False

    def test_malformed_username_is_rejected_cleanly(self, client, csrf_token):
        """超长 / 含控制字符的用户名走白名单校验，不落到数据库查询。"""
        resp = form_post(
            client, '/login', {'username': 'x' * 500}, csrf_token
        )
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_login_clears_previous_identity(self, client, csrf_token,
                                            admin_client_flask_app):
        """会话固定防护：认证前必须重置会话。"""
        resp = form_post(
            client, '/manage/login',
            {'username': admin_client_flask_app['username'],
             'password': admin_client_flask_app['password']},
            csrf_token,
        )
        assert resp.status_code == 302
        assert response_json(json_get(client, '/api/session'))['isAdmin'] is True

        resp = form_post(client, '/login', {'username': 'whoever'}, csrf_token)
        assert resp.status_code == 302

        payload = response_json(json_get(client, '/api/session'))
        assert payload['isAdmin'] is False, '登录前未清空会话（会话固定风险）'

    def test_login_is_rate_limited(self, client, csrf_token):
        """10 次/分钟额度用完后再来一次应被拦下。"""
        for _ in range(10):
            form_post(client, '/login', {'username': 'somebody'}, csrf_token)

        resp = form_post(
            client, '/login', {'username': 'somebody'}, csrf_token,
            follow_redirects=True,
        )
        page = resp.get_data(as_text=True)
        assert '尝试过于频繁' in page, '第 11 次登录未被限流'


# ============================================================================
# 二、验证流程
# ============================================================================
class TestVerifyFlow:
    def test_verify_without_pending_redirects_to_login(self, client):
        resp = client.get('/verify')
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_start_verification_without_session(self, client, csrf_token):
        resp = json_post(client, '/api/start_verification', {}, csrf_token)
        assert resp.status_code == 200
        payload = response_json(resp)
        assert payload['success'] is False
        assert '登录会话' in payload['error']


# ============================================================================
# 三、注册流程（内存态迁移）
# ============================================================================
class TestRegistration:
    def test_register_seeds_in_memory_state(self, client, csrf_token, db):
        resp = form_post(client, '/register', {'username': 'newbie'}, csrf_token)
        assert resp.status_code == 302
        assert '/collect_data/newbie' in resp.headers['Location']

        # 采集向导页依赖这份内存态，存在才算注册流程真正开始
        assert client.get('/collect_data/newbie').status_code == 200

    def test_duplicate_username_is_refused(self, client, csrf_token, existing_user):
        resp = form_post(client, '/register', {'username': existing_user}, csrf_token,
                         follow_redirects=True)
        assert '用户名已存在' in resp.get_data(as_text=True)

    def test_collect_page_without_session_goes_back_to_register(self, client):
        resp = client.get('/collect_data/ghost-user')
        assert resp.status_code == 302
        assert '/register' in resp.headers['Location']


# ============================================================================
# 四、CSRF 契约
# ============================================================================
class TestCsrfContract:
    def test_write_without_token_is_rejected(self, client):
        resp = client.post('/api/scan_devices', json={})
        assert resp.status_code == 403, '缺失 CSRF 令牌的写请求必须被拒'
        assert response_json(resp)['success'] is False

    def test_write_with_random_token_is_rejected(self, client):
        resp = json_post(client, '/api/scan_devices', {}, token='not-a-real-token')
        assert resp.status_code == 403

    def test_token_from_another_session_is_rejected(self, client, flask_app):
        """令牌与会话绑定：换个会话的合法令牌同样无效。"""
        other = flask_app.test_client()
        other_token = other.get('/api/csrf-token').get_json()['token']

        resp = json_post(client, '/api/scan_devices', {}, token=other_token)
        assert resp.status_code == 403

    def test_html_form_without_token_is_rejected(self, client):
        """页面表单缺令牌时被拦在视图之外，跳回首页并给出 flash 提示。"""
        resp = client.post('/login', data={'username': 'nobody'})
        assert resp.status_code == 302
        assert resp.headers['Location'].endswith('/')

        page = client.get('/').get_data(as_text=True)
        assert '页面已过期' in page

    def test_safe_methods_need_no_token(self, client):
        assert client.get('/api/session').status_code == 200

    def test_token_survives_login_reset(self, client, csrf_token, existing_user):
        """登录内部执行了 session.clear()，但令牌必须活下来。"""
        form_post(client, '/login', {'username': existing_user}, csrf_token)

        again = client.get('/api/csrf-token').get_json()['token']
        assert again == csrf_token, 'session.clear() 把 CSRF 令牌一起清掉了'

        resp = json_post(client, '/api/start_verification', {}, again)
        assert resp.status_code != 403, '登录后原令牌失效'


# ============================================================================
# 五、判定结论的完整性：附加请求参数不得影响结果
# ============================================================================
class TestVerdictIntegrity:
    def test_connect_device_ignores_extra_mode_parameter(self, client, csrf_token):
        """
        连接 / 判定结果只能由请求的语义参数决定，附加参数不得改变它。

        用「不支持的设备类型」构造一条确定性的快速失败路径，
        这样两次响应的差异只可能来自参数本身。
        """
        payload = {'address': '00:11:22:33:44:55', 'type': 'bogus'}

        plain = json_post(client, '/api/connect_device', dict(payload), csrf_token)
        with_extra = json_post(
            client, '/api/connect_device',
            dict(payload, connection_mode='stable'), csrf_token,
        )

        assert plain.status_code == with_extra.status_code == 200
        assert plain.get_json() == with_extra.get_json(), (
            '附加参数改变了响应 —— 判定结果被请求参数覆盖了'
        )
        assert plain.get_json()['success'] is False

    def test_no_verdict_override_markers_in_source(self):
        """源码级护栏：结果改写类标记不得出现在 Web 层。"""
        targets = []
        web_auth = PROJECT_ROOT / 'web_auth'
        for pattern in ('*.py', 'templates/**/*.html', 'frontend/src/**/*.ts',
                        'frontend/src/**/*.tsx'):
            targets.extend(web_auth.glob(pattern))

        assert targets, '未找到任何待扫描文件，路径配置有误'

        offenders = []
        for path in targets:
            if '__pycache__' in path.parts:
                continue
            text = path.read_text(encoding='utf-8', errors='ignore').lower()
            for marker in ('backdoor', 'connection_mode'):
                if marker in text:
                    offenders.append('{}: {}'.format(path.relative_to(PROJECT_ROOT), marker))

        assert not offenders, '发现结果改写标记：\n' + '\n'.join(offenders)


# ============================================================================
# 六、登出
# ============================================================================
class TestLogout:
    def test_logout_clears_session(self, client, existing_user, csrf_token):
        form_post(client, '/login', {'username': existing_user}, csrf_token)
        assert response_json(json_get(client, '/api/session'))['pendingLogin']

        resp = client.get('/logout')
        assert resp.status_code == 302

        payload = response_json(json_get(client, '/api/session'))
        assert payload['authenticated'] is False
        assert payload['pendingLogin'] is None


# ============================================================================
# 七、验证「终态」契约
# ============================================================================
class TestVerificationTerminalStates:
    """
    采集与推理链路可能写入多种失败状态，接口必须对**每一种**都立即给出结论。

    这组断言针对的是一类很隐蔽的破坏方式：判定表逐个罗列状态名，于是新增一个
    状态就会悄悄落到「仍在进行中」那一支 —— 调用方既不失败也不超时，
    表现为界面永远停在「正在验证」。这里把「终态只有一处定义」钉住。
    """

    def test_terminal_set_covers_every_failure_state(self):
        from web_auth.blueprints.auth import TERMINAL_VERIFICATION_STATUSES as terminal

        assert 'success' in terminal
        # 采集与推理链路会写入的失败终态，一个都不能少
        assert {'failed', 'error', 'device_error'} <= terminal

    def test_device_error_yields_failed_verdict(self, client, existing_user):
        """设备中途断开必须立即出结论，而不是一直回答「进行中」。"""
        from datetime import datetime

        from web_auth import state

        with client.session_transaction() as sess:
            sess['pending_login'] = existing_user

        with state.verification_lock:
            state.verification_results[existing_user] = {
                'status': 'device_error',
                'timestamp': datetime.now(),
                'error_message': '设备连接意外断开',
            }
        state.touch_state('verification', existing_user)

        payload = response_json(json_get(client, '/api/verification_status'))

        assert payload['status'] == 'failed', '终态被当成「进行中」了'
        assert payload['reason'] == '设备连接意外断开'
        # 结论一旦下达，本次验证的内存态就该释放
        assert existing_user not in state.verification_results
