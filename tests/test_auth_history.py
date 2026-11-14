# -*- coding: utf-8 -*-
"""
认证历史的写入口径

仪表盘的认证次数取自 `auth_history`。本组用例固定「结论产生 → 落一条记录 →
统计读得到」这条闭环，以及四条容易被忽略的行为契约：

1. 状态机的原始终态要归一成统计侧的两个取值，设备断开也算一次未通过；
2. 一次验证只落一条记录 —— 验证页会持续轮询，不能把轮询次数当成认证次数；
3. 演示模式下数据来源是合成信号，记录带 `demo` 便于事后区分；
4. 写历史是旁路，数据库暂时不可用时不能改变本次认证结论。

read 侧的聚合口径由 `test_dashboard.py` 覆盖，这里只管 write 侧与两端衔接。
"""

import time
from types import SimpleNamespace

import pytest

from tests.helpers import json_post, response_json
from web_auth import demo as demo_module
from web_auth.blueprints import auth as auth_module
from web_auth.services import stats as stats_module


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


def _run_synthetic_verification(client, csrf_token, monkeypatch, passed):
    """用合成信号把验证链路走完；判定结果由参数给定。"""
    monkeypatch.setattr(demo_module, 'DEMO_MODE', True)
    monkeypatch.setattr(auth_module, 'get_user_model', lambda name: object())
    monkeypatch.setattr(
        auth_module, 'authenticate_windowed_signal',
        lambda model, data, **kwargs: {
            'authenticated': passed,
            'score': 0.93 if passed else 0.21,
        },
    )
    assert response_json(json_post(
        client, '/api/start_verification', None, csrf_token
    ))['success'] is True
    return _wait_for_verdict(client)


# ============================================================================
# 一、链路闭环
# ============================================================================
class TestHistoryWritten:
    def test_success_feeds_dashboard_stats(
        self, client, csrf_token, pending_login, db, monkeypatch
    ):
        """验证通过 → 一条 success 记录 → 仪表盘统计立刻读得到。"""
        verdict = _run_synthetic_verification(client, csrf_token, monkeypatch, True)
        assert verdict['status'] == 'completed'

        docs = list(db.auth_history.find({'username': pending_login}))
        assert len(docs) == 1, '一次验证应当只落一条历史'
        doc = docs[0]
        assert doc['result'] == stats_module.HISTORY_RESULT_SUCCESS
        assert doc['demo'] is True, '演示模式的记录要能事后区分'
        assert doc['timestamp'] is not None
        assert doc[stats_module.HISTORY_DURATION_FIELD] >= 0

        stats = stats_module.build_user_stats(pending_login)
        assert stats['total_logins'] == 1
        assert stats['successful_auths'] == 1
        assert stats['failed_auths'] == 0
        assert stats['has_history'] is True

    def test_failed_verdict_writes_failure(
        self, client, csrf_token, pending_login, db, monkeypatch
    ):
        """合成信号一样可能不通过；未通过也必须留痕。"""
        verdict = _run_synthetic_verification(client, csrf_token, monkeypatch, False)
        assert verdict['status'] == 'failed'

        docs = list(db.auth_history.find({'username': pending_login}))
        assert len(docs) == 1
        assert docs[0]['result'] == stats_module.HISTORY_RESULT_FAILURE

    def test_polling_does_not_duplicate(
        self, client, csrf_token, pending_login, db, monkeypatch
    ):
        """验证页会持续轮询，轮询次数不能被算成认证次数。"""
        _run_synthetic_verification(client, csrf_token, monkeypatch, True)
        # 结论已被消费；再轮询两次（一次命中「已登录」，一次是普通重复请求）
        response_json(client.get('/api/verification_status'))
        response_json(client.get('/api/verification_status'))

        assert db.auth_history.count_documents({'username': pending_login}) == 1

    def test_db_failure_does_not_change_verdict(
        self, client, csrf_token, pending_login, db, monkeypatch
    ):
        """历史写不进去时，认证结论照常给出。"""

        class BrokenCollection:
            def insert_one(self, doc):
                raise RuntimeError('mongo unavailable')

        monkeypatch.setattr(
            stats_module, 'mongo',
            SimpleNamespace(db=SimpleNamespace(auth_history=BrokenCollection())),
        )

        verdict = _run_synthetic_verification(client, csrf_token, monkeypatch, True)
        assert verdict['status'] == 'completed'
        assert db.auth_history.count_documents({}) == 0


# ============================================================================
# 二、写入函数自身的字段契约
# ============================================================================
class TestRecordContract:
    @pytest.mark.parametrize('status,expected', [
        ('success', 'success'),
        ('failed', 'failure'),
        ('error', 'failure'),
        ('device_error', 'failure'),
    ])
    def test_terminal_status_maps_to_result(self, status, expected, db):
        """状态机四种终态归并为统计侧的两个取值。"""
        assert stats_module.record_auth_result('probe', status) is True
        doc = db.auth_history.find_one({'username': 'probe'})
        assert doc['result'] == expected

    def test_missing_start_time_omits_duration(self, db):
        """缺开始时刻时不编耗时，聚合侧允许记录不带这个字段。"""
        assert stats_module.record_auth_result('probe', 'success') is True
        doc = db.auth_history.find_one({'username': 'probe'})
        assert stats_module.HISTORY_DURATION_FIELD not in doc
        assert 'demo' not in doc

    def test_write_failure_is_swallowed(self, monkeypatch):
        """旁路写入失败只记日志、返回 False，不向上抛。"""

        class BrokenCollection:
            def insert_one(self, doc):
                raise RuntimeError('mongo unavailable')

        monkeypatch.setattr(
            stats_module, 'mongo',
            SimpleNamespace(db=SimpleNamespace(auth_history=BrokenCollection())),
        )
        assert stats_module.record_auth_result('probe', 'error') is False
