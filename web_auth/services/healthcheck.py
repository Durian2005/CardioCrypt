# -*- coding: utf-8 -*-
"""
服务自身健康检查

与 `services/health.py` 无关：那个模块合成的是**生理数据**（心率、情绪），
本模块检查的是**这个服务还能不能干活**。命名用 healthcheck 而不是 health，
就是为了不把两个"健康"混在一起。

检查两项
--------

  - **database**：MongoDB 能否应答 `ping`。用户表、认证历史都在它上面，
    连不上等于认证功能整体不可用；
  - **algorithm_layer**：`core.SYSTEM_AVAILABLE`。算法模块导入失败时 Web 层
    仍能启动（`core.py` 里有刻意的降级设计），但注册与认证必然失败 ——
    这种"进程起来了却干不了活"的状态必须能被探针看见，否则监控全绿而业务全红。

设计约束
--------

1. **只读无副作用**：不发写操作、不加载模型、不建会话、不改配置。
   探针可能每几秒打一次，任何副作用都会被放大。
2. **不泄漏部署细节**：不返回连接串、库名、文件路径、模型名、用户名。
   PyMongo 的异常文本里带 `host:port`，所以对外只回**异常类型名**。
3. **可机器判定**：整体 `status` 取 `ok` / `degraded`，degraded 时 HTTP 503，
   探针与负载均衡不必理解业务字段。
4. **失败日志限流**：数据库一挂，探针会把同一个失败刷成日志洪水，
   因此同一条告警每 `DEGRADED_LOG_INTERVAL` 秒最多记一次。

关于响应时间
------------

`ping` 复用共享的 MongoClient，所以最坏等待时间等于
`MONGO_SERVER_SELECTION_TIMEOUT_MS`（默认 5 秒）。探针自身的超时应大于该值，
否则数据库故障时会被误判成"探针超时"而不是"依赖不可用"。
"""

import threading
import time

from web_auth import core
from web_auth.config import DEMO_MODE, FRONTEND_MODE, logger
from web_auth.extensions import mongo
from web_auth.services.stats import get_uptime_seconds

STATUS_OK = 'ok'
STATUS_DEGRADED = 'degraded'

# 同一条降级告警的最小记录间隔（秒）
DEGRADED_LOG_INTERVAL = 60

_degraded_log_lock = threading.Lock()
_degraded_log_at = 0.0


def _elapsed_ms(started):
    """把 monotonic 起点换算成毫秒（保留一位小数，够看且不噪声）。"""
    return round((time.monotonic() - started) * 1000, 1)


def check_database(client=None):
    """
    MongoDB 能否应答 ping。

    参数:
        client: 可选的 MongoClient；缺省用应用共享的那一个。
                显式传入只为让"数据库不可达"这条分支能被单元测试覆盖，
                生产路径永远是共享客户端。

    返回:
        ``{'ok': bool, 'latency_ms': float}``，失败时多一个 `error`（异常类型名）。
        这里刻意不抛异常 —— 健康检查失败是**结果**，不是程序的错误。
    """
    client = mongo.cx if client is None else client
    started = time.monotonic()
    try:
        client.admin.command('ping')
    except Exception as exc:
        # 只回类型名：异常文本里有 host:port，属于部署细节
        return {
            'ok': False,
            'latency_ms': _elapsed_ms(started),
            'error': type(exc).__name__,
        }
    return {'ok': True, 'latency_ms': _elapsed_ms(started)}


def check_algorithm_layer():
    """算法模块是否成功导入（`core.SYSTEM_AVAILABLE`）。"""
    available = bool(core.SYSTEM_AVAILABLE)
    result = {'ok': available}
    if not available:
        result['error'] = 'ImportError'
    return result


def _log_degraded(reasons):
    """记录降级原因，但按 ``DEGRADED_LOG_INTERVAL`` 限流。"""
    global _degraded_log_at

    now = time.monotonic()
    with _degraded_log_lock:
        if now - _degraded_log_at < DEGRADED_LOG_INTERVAL:
            return
        _degraded_log_at = now
    logger.warning("健康检查未通过：%s", '；'.join(reasons))


def collect_health():
    """
    汇总健康状态。

    返回:
        ``(payload, http_status)``。两个依赖都正常时 200，任一异常时 503。
    """
    checks = {
        'database': check_database(),
        'algorithm_layer': check_algorithm_layer(),
    }
    healthy = all(item['ok'] for item in checks.values())

    payload = {
        'status': STATUS_OK if healthy else STATUS_DEGRADED,
        'uptime_seconds': int(get_uptime_seconds()),
        # 下面两项不是检查项而是运行形态：演示模式开着意味着采集可能改用合成
        # 数据，运维在整体 ok 之外看到这个标记，才不会把演示结果当成真实比对。
        'demo_mode': bool(DEMO_MODE),
        'frontend_mode': FRONTEND_MODE,
        'checks': checks,
    }

    if not healthy:
        reasons = [
            '{}({})'.format(name, item.get('error', 'unavailable'))
            for name, item in checks.items() if not item['ok']
        ]
        _log_degraded(reasons)

    return payload, (200 if healthy else 503)
