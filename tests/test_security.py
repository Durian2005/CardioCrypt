# -*- coding: utf-8 -*-
"""
`web_auth/security.py` 的单元测试

限流器与 CSRF 令牌都不依赖数据库和硬件，是最纯粹的一层，
所以放在最前面 —— 它们失败时能最快定位到「安全原语」而不是「业务流程」。
"""

import time

import pytest
from flask import request, session

from web_auth.security import CSRFProtector, RateLimiter, clear_session_keep_csrf


# ============================================================================
# RateLimiter
# ============================================================================
class TestRateLimiter:
    def test_allows_exactly_up_to_limit(self):
        limiter = RateLimiter(limit=3, window=60)
        assert [limiter.allow('1.2.3.4') for _ in range(3)] == [True, True, True]
        # 第 limit+1 次必须被拒 —— 边界值最容易写成 `>` 而不是 `>=`
        assert limiter.allow('1.2.3.4') is False

    def test_rejected_attempt_does_not_extend_lockout(self):
        """被拒的尝试不计入窗口，否则持续重试会把自己永久锁死。"""
        limiter = RateLimiter(limit=2, window=0.4)
        assert limiter.allow('k') is True
        assert limiter.allow('k') is True
        for _ in range(5):
            assert limiter.allow('k') is False
        time.sleep(0.45)
        assert limiter.allow('k') is True

    def test_window_slides(self):
        limiter = RateLimiter(limit=2, window=0.3)
        assert limiter.allow('k') is True
        assert limiter.allow('k') is True
        assert limiter.allow('k') is False
        time.sleep(0.35)
        assert limiter.allow('k') is True

    def test_keys_are_independent(self):
        limiter = RateLimiter(limit=1, window=60)
        assert limiter.allow('a') is True
        assert limiter.allow('b') is True, '不同来源不应相互影响'
        assert limiter.allow('a') is False

    def test_reset_and_clear(self):
        limiter = RateLimiter(limit=1, window=60)
        limiter.allow('a')
        assert limiter.allow('a') is False
        limiter.reset('a')
        assert limiter.allow('a') is True

        limiter.clear()
        assert limiter.stats()['keys'] == 0

    def test_retry_after_is_positive_when_blocked(self):
        limiter = RateLimiter(limit=1, window=10)
        limiter.allow('a')
        assert limiter.retry_after('a') > 0
        assert limiter.retry_after('never-seen') == 0

    def test_key_count_is_bounded(self):
        """大量伪造来源不应把内存撑爆。"""
        limiter = RateLimiter(limit=1, window=60, max_keys=8)
        for index in range(50):
            limiter.allow('ip-{}'.format(index))
        assert limiter.stats()['keys'] <= 8

    @pytest.mark.parametrize('limit,window', [(0, 60), (-1, 60), (5, 0), (5, -1)])
    def test_invalid_parameters_rejected(self, limit, window):
        with pytest.raises(ValueError):
            RateLimiter(limit=limit, window=window)


# ============================================================================
# CSRFProtector
# ============================================================================
class TestCSRFProtector:
    @pytest.fixture()
    def protector(self):
        return CSRFProtector()

    def _validate_in_request(self, flask_app, protector, session_token,
                             submitted, method='POST'):
        """在请求上下文中跑一次校验。"""
        headers = {protector.HEADER_NAME: submitted} if submitted is not None else {}
        with flask_app.test_request_context('/', method=method, headers=headers):
            if session_token is not None:
                session[protector.SESSION_KEY] = session_token
            return protector.validate(session, request)

    def test_ensure_is_idempotent(self, flask_app, protector):
        with flask_app.test_request_context('/'):
            first = protector.ensure(session)
            second = protector.ensure(session)
        assert first and first == second
        assert len(first) >= 16

    def test_rotate_changes_token(self, flask_app, protector):
        with flask_app.test_request_context('/'):
            first = protector.ensure(session)
            second = protector.rotate(session)
        assert first != second

    def test_matching_header_passes(self, flask_app, protector):
        token = protector.generate()
        assert self._validate_in_request(flask_app, protector, token, token) is True

    def test_missing_header_rejected(self, flask_app, protector):
        token = protector.generate()
        assert self._validate_in_request(flask_app, protector, token, None) is False

    def test_wrong_token_rejected(self, flask_app, protector):
        assert self._validate_in_request(
            flask_app, protector, protector.generate(), protector.generate()
        ) is False

    def test_token_without_session_rejected(self, flask_app, protector):
        """会话里没有令牌时必须拒绝，否则等于没有防护。"""
        assert self._validate_in_request(
            flask_app, protector, None, protector.generate()
        ) is False

    def test_safe_methods_are_exempt(self, flask_app, protector):
        for method in ('GET', 'HEAD', 'OPTIONS', 'TRACE'):
            assert self._validate_in_request(
                flask_app, protector, protector.generate(), None, method=method
            ) is True, '{} 不应要求令牌'.format(method)

    def test_non_ascii_token_rejected_without_exception(self, flask_app, protector):
        """hmac.compare_digest 只接受 ASCII，非 ASCII 输入必须安全地判为不匹配。"""
        assert self._validate_in_request(
            flask_app, protector, protector.generate(), '令牌不是ASCII'
        ) is False

    def test_form_field_is_accepted(self, flask_app, protector):
        token = protector.generate()
        with flask_app.test_request_context(
            '/', method='POST', data={protector.FIELD_NAME: token}
        ):
            session[protector.SESSION_KEY] = token
            assert protector.validate(session, request) is True

    def test_json_body_field_is_accepted(self, flask_app, protector):
        token = protector.generate()
        with flask_app.test_request_context(
            '/', method='POST', json={protector.FIELD_NAME: token}
        ):
            session[protector.SESSION_KEY] = token
            assert protector.validate(session, request) is True


# ============================================================================
# clear_session_keep_csrf
# ============================================================================
class TestClearSessionKeepCsrf:
    def test_identity_cleared_token_kept(self, flask_app):
        protector = CSRFProtector()
        with flask_app.test_request_context('/'):
            session['username'] = 'alice'
            session['pending_login'] = 'alice'
            session['admin'] = True
            token = protector.ensure(session)

            clear_session_keep_csrf(session)

            assert 'username' not in session
            assert 'pending_login' not in session
            assert 'admin' not in session
            assert session[protector.SESSION_KEY] == token, (
                '令牌不属于身份状态，必须保留 —— 否则清空后的第一次提交必然因缺令牌被拒'
            )

    def test_works_without_existing_token(self, flask_app):
        with flask_app.test_request_context('/'):
            session['username'] = 'bob'
            clear_session_keep_csrf(session)
            assert dict(session) == {}
