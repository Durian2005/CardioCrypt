# -*- coding: utf-8 -*-
"""
`/healthz` 的契约

这个端点会被探针反复调用，它自己也是"部署是否真的可用"的唯一入口，
因此需要把下面几件事固定下来：

1. **谁能访问**：不登录、不带 CSRF 令牌也能拿到结果 —— 探针拿不到会话；
2. **怎么判定**：依赖正常 200 + `status=ok`，任一依赖异常 503 + `status=degraded`，
   调用方靠状态码就能分流，不必解析业务字段；
3. **不能泄漏什么**：连接串、库名、路径、口令都不许出现在响应里。
   PyMongo 的异常文本带 `host:port`，所以出错时只回异常类型名；
4. **副作用**：只读。探针几秒一次，不能因此往库里写任何东西；
5. **缓存**：必须是 `no-store`，否则中间层会把"已经挂了"缓存成"还是好的"。

底层 ping 的实现（真的去连数据库）由 `test_check_database_*` 覆盖；
降级分支通过替换检查函数来触发，避免依赖"把数据库弄坏"这种不可控手段。
"""

import pytest

from tests.helpers import response_json
from web_auth import core
from web_auth.services import healthcheck


def test_returns_ok_when_dependencies_available(client):
    """依赖都在时返回 200，且两个检查项都通过。"""
    resp = client.get('/healthz')

    assert resp.status_code == 200
    payload = response_json(resp)
    assert payload['status'] == 'ok'
    assert payload['checks']['database']['ok'] is True
    assert payload['checks']['algorithm_layer']['ok'] is True


def test_payload_has_stable_shape(client):
    """字段集合固定：多一个少一个都说明契约被无意改动了。"""
    payload = response_json(client.get('/healthz'))

    assert set(payload) == {
        'status', 'uptime_seconds', 'demo_mode', 'frontend_mode', 'checks',
    }
    assert set(payload['checks']) == {'database', 'algorithm_layer'}


def test_reachable_without_session(client):
    """探针没有会话：不带 Cookie、不带令牌也必须能拿到 JSON。"""
    resp = client.get('/healthz')

    assert resp.status_code == 200
    # 必须是 JSON —— 若被 SPA 的 404 兜底接管，会返回一页 HTML，
    # 而那看起来"也是 200"，探针就再也发现不了路由丢失。
    assert resp.is_json
    assert 'text/html' not in resp.headers.get('Content-Type', '')


def test_cache_is_disabled(client):
    """健康状态不能被缓存。"""
    resp = client.get('/healthz')

    assert resp.headers.get('Cache-Control') == 'no-store'


def test_degraded_when_database_unreachable(client, monkeypatch):
    """数据库不可达时 503，并指明是哪一项坏了。"""
    monkeypatch.setattr(
        healthcheck, 'check_database',
        lambda client=None: {
            'ok': False, 'latency_ms': 3001.0, 'error': 'ServerSelectionTimeoutError',
        },
    )

    resp = client.get('/healthz')

    assert resp.status_code == 503
    payload = response_json(resp)
    assert payload['status'] == 'degraded'
    assert payload['checks']['database']['ok'] is False
    # 另一项仍然如实反映自己的状态，不跟着一起"变红"
    assert payload['checks']['algorithm_layer']['ok'] is True


def test_degraded_when_algorithm_layer_missing(client, monkeypatch):
    """算法层导入失败属于"起来了但干不了活"，同样要 503。"""
    monkeypatch.setattr(core, 'SYSTEM_AVAILABLE', False)

    resp = client.get('/healthz')

    assert resp.status_code == 503
    payload = response_json(resp)
    assert payload['checks']['algorithm_layer'] == {'ok': False, 'error': 'ImportError'}


@pytest.mark.parametrize('secret', [
    'mongodb://',
    '27017',
    'ecg_auth_db',
    'pytest-secret',
    '.flask_secret_key',
])
def test_does_not_leak_deployment_details(client, secret):
    """响应里不允许出现连接串、端口、库名、密钥（含密钥文件路径）。"""
    body = client.get('/healthz').get_data(as_text=True)

    assert secret not in body


def test_check_database_reports_failure_without_raising():
    """底层 ping 失败时返回结果而不是抛异常 —— 健康检查失败是结果，不是错误。"""

    class BrokenClient:
        class admin:
            @staticmethod
            def command(name):
                raise RuntimeError('boom')

    result = healthcheck.check_database(client=BrokenClient())

    assert result['ok'] is False
    assert result['error'] == 'RuntimeError'
    assert result['latency_ms'] >= 0


def test_check_database_reports_latency():
    """成功时给出耗时，便于区分"能连但慢"与"连不上"。"""
    result = healthcheck.check_database()

    assert result['ok'] is True
    assert isinstance(result['latency_ms'], float)
    assert result['latency_ms'] >= 0


def test_misspelled_path_is_not_masked_by_spa_fallback(client):
    """
    `/healthz/` 这类拼错的路径必须得到真 404，而不是 SPA 兜底出来的 HTML 200。

    探针只看状态码：兜底成 200 + HTML 的话，端点写错了也会一直显示"健康"。
    """
    resp = client.get('/healthz/')

    assert resp.status_code == 404
    assert not resp.is_json


def test_does_not_write_anything(client, db):
    """探针是只读的：调用若干次之后库里不应多出记录。"""
    for _ in range(3):
        assert client.get('/healthz').status_code == 200

    assert db.users.count_documents({}) == 0
    assert db.auth_history.count_documents({}) == 0


def test_degraded_logging_is_throttled(monkeypatch):
    """数据库持续不可用时探针会反复命中，同一类告警不能刷屏。"""
    recorded = []
    monkeypatch.setattr(healthcheck, '_degraded_log_at', 0.0)
    monkeypatch.setattr(healthcheck.logger, 'warning',
                        lambda *args, **kwargs: recorded.append(args))

    healthcheck._log_degraded(['database(ServerSelectionTimeoutError)'])
    healthcheck._log_degraded(['database(ServerSelectionTimeoutError)'])
    healthcheck._log_degraded(['database(ServerSelectionTimeoutError)'])

    assert len(recorded) == 1
