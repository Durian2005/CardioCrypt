# -*- coding: utf-8 -*-
"""
演示模式（DEMO_MODE）测试

采集链路里原本散落着若干「拿不到真实数据就生成一段合成信号继续走」的分支，
并且几处失败路径直接写死 `status = 'success'`。合起来的效果是：不接设备、
不采数据，流程照样能走到一次「验证成功」—— 但这在返回值上与「真的通过」
完全无法区分。

本次把这些分支收口到一个显式开关，并用这组用例固定三件事：

1. 默认（DEMO_MODE 未设置）时，采集不到数据 → 判定失败，没有任何默认放行；
2. 用户模型缺失 → 明确报错，而不是把结果留在「进行中」（原实现里那个
   `success = np.random.random() < 0.85` 赋值后从未被消费，会让前端一直转圈）；
3. 显式开启演示模式 → 允许用合成信号走完流程，但结果必须带 demo 标记，
   让前端能把「演示数据」和「真实采集」区分开。
"""

import time

import pytest

from tests.helpers import json_post, response_json
from web_auth import demo as demo_module
from web_auth.blueprints import auth as auth_module


def _wait_for_verdict(client, timeout=15.0):
    """轮询验证状态接口，直到出现最终结论。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = response_json(client.get('/api/verification_status'))
        if last.get('status') in ('completed', 'failed'):
            return last
        time.sleep(0.05)
    raise AssertionError('验证未在 {} 秒内给出结论，最后一次响应：{}'.format(timeout, last))


@pytest.fixture()
def pending_login(client, csrf_token, existing_user):
    """把会话推进到「待验证」状态（登录只登记用户名，真正认证在验证阶段）。"""
    resp = client.post(
        '/login',
        data={'username': existing_user, 'csrf_token': csrf_token},
    )
    assert resp.status_code in (200, 302)
    return existing_user


# ============================================================================
# 一、降级决策本身
# ============================================================================
class TestDemoDegrade:
    def test_closed_refuses_and_records_nothing(self, monkeypatch):
        """默认关闭：明确拒绝降级，且不产生任何「降级原因」。"""
        monkeypatch.setattr(demo_module, 'DEMO_MODE', False)
        reasons = []

        assert demo_module.demo_degrade('设备没连上', reasons) is False
        assert reasons == []

    def test_enabled_allows_and_collects_reason(self, monkeypatch):
        """开启后允许降级，并把原因收集起来（用于透出给前端）。"""
        monkeypatch.setattr(demo_module, 'DEMO_MODE', True)
        reasons = []

        assert demo_module.demo_degrade('设备没连上', reasons) is True
        assert reasons == ['设备没连上']

    def test_multiple_degrades_all_recorded(self, monkeypatch):
        """一次验证里可能降级多次，原因要按顺序全部保留。"""
        monkeypatch.setattr(demo_module, 'DEMO_MODE', True)
        reasons = []

        demo_module.demo_degrade('第一条', reasons)
        demo_module.demo_degrade('第二条', reasons)
        assert reasons == ['第一条', '第二条']

    def test_synthetic_series_shape(self):
        series = demo_module.synthetic_signal_series(60)
        assert len(series) == 60
        assert all(hasattr(item, 'shape') for item in series)

    def test_demo_mode_is_off_in_test_env(self):
        """测试环境固定关闭该开关（见 conftest），用例才有可重复的默认语义。"""
        from web_auth import config
        assert config.DEMO_MODE is False


# ============================================================================
# 二、默认语义下的端到端行为
# ============================================================================
class TestFailClosedByDefault:
    def test_no_device_data_fails_instead_of_passing(
        self, client, csrf_token, pending_login, monkeypatch
    ):
        """
        没有设备、没有任何数据 —— 必须判定失败。

        这里给一个「非 None 的模型」让流程能越过模型检查，随后设备采集
        必然拿不到数据（测试环境没有连接任何设备），从而走到总闸门。
        """
        monkeypatch.setattr(demo_module, 'DEMO_MODE', False)
        monkeypatch.setattr(auth_module, 'get_user_model', lambda name: object())

        assert response_json(json_post(
            client, '/api/start_verification', None, csrf_token
        ))['success'] is True

        verdict = _wait_for_verdict(client)
        assert verdict['status'] == 'failed'
        # 结果是失败，而不是「默认成功」
        assert 'demo' not in verdict
        # 且原因必须来自「采集不到数据」这条分支，而不是碰巧因别的错误失败
        assert '未采集到足够的设备数据' in (verdict.get('reason') or ''), verdict

    def test_missing_model_reports_instead_of_hanging(
        self, client, csrf_token, pending_login, monkeypatch
    ):
        """
        模型缺失时给明确结论。

        原实现里 `model is None` 分支只赋值了一个从未被消费的 `success`，
        结果永远停在 `verifying` —— 前端会一直轮询下去。现在它会直接给出
        一个带原因的失败结论。
        """
        monkeypatch.setattr(demo_module, 'DEMO_MODE', False)
        monkeypatch.setattr(auth_module, 'get_user_model', lambda name: None)

        json_post(client, '/api/start_verification', None, csrf_token)

        verdict = _wait_for_verdict(client)
        assert verdict['status'] == 'failed'
        assert '模型不可用' in (verdict.get('reason') or '')


# ============================================================================
# 三、演示模式下的行为
# ============================================================================
class TestDemoModeEnabled:
    def test_synthetic_run_is_flagged(
        self, client, csrf_token, pending_login, monkeypatch
    ):
        """
        演示模式：允许用合成信号完成流程，但结果必须带 demo 标记。

        判定函数被替换成固定返回值 —— 这里要验证的是「降级被如实标记」，
        而不是算法本身的正确性（那由 test_model_authentication.py 覆盖）。
        """
        monkeypatch.setattr(demo_module, 'DEMO_MODE', True)
        monkeypatch.setattr(auth_module, 'get_user_model', lambda name: object())
        monkeypatch.setattr(
            auth_module, 'authenticate_single_signal',
            lambda model, data, threshold=None: {'authenticated': True, 'score': 0.93},
        )

        json_post(client, '/api/start_verification', None, csrf_token)

        verdict = _wait_for_verdict(client)
        assert verdict['status'] == 'completed'
        assert verdict.get('demo') is True, '演示模式的结果必须带标记'

    def test_synthetic_run_can_still_fail(
        self, client, csrf_token, pending_login, monkeypatch
    ):
        """
        演示模式改变的是数据来源，不是判定规则 —— 合成信号一样可能不通过。
        这条用来防止「演示模式」被当成「放行开关」。
        """
        monkeypatch.setattr(demo_module, 'DEMO_MODE', True)
        monkeypatch.setattr(auth_module, 'get_user_model', lambda name: object())
        monkeypatch.setattr(
            auth_module, 'authenticate_single_signal',
            lambda model, data, threshold=None: {'authenticated': False, 'score': 0.21},
        )

        json_post(client, '/api/start_verification', None, csrf_token)

        verdict = _wait_for_verdict(client)
        assert verdict['status'] == 'failed'


# ============================================================================
# 四、提示是否真的透出到界面
# ============================================================================
class TestDemoModeSurfaced:
    def test_session_api_exposes_the_flag(self, client, flask_app):
        """SPA 靠这个字段在流程开始前就能显示提示。"""
        assert response_json(client.get('/api/session'))['demoMode'] is False

        flask_app.config['DEMO_MODE'] = True
        try:
            assert response_json(client.get('/api/session'))['demoMode'] is True
        finally:
            flask_app.config['DEMO_MODE'] = False

    def test_classic_pages_show_banner_when_enabled(self, client, monkeypatch):
        """classic 模式：提示条由 base.html 统一渲染，所有页面都能看到。"""
        import web_auth as web_auth_pkg

        monkeypatch.setattr(web_auth_pkg, 'DEMO_MODE', True)
        body = client.get('/login').get_data(as_text=True)
        assert '演示模式已开启' in body

    def test_classic_pages_have_no_banner_by_default(self, client, monkeypatch):
        """默认关闭时不能出现这个提示，否则等于谎报演示态。"""
        import web_auth as web_auth_pkg

        monkeypatch.setattr(web_auth_pkg, 'DEMO_MODE', False)
        body = client.get('/login').get_data(as_text=True)
        assert '演示模式已开启' not in body
