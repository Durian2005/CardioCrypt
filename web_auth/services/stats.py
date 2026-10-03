# -*- coding: utf-8 -*-
"""
仪表盘的真实统计

仪表盘上的数字分两类：**能从系统里算出来的**，和**没有真实来源的**。
本模块只负责前者 —— 算不出来的绝不用随机数凑，那些字段由
`blueprints/dashboard.py` 显式列进「示意数据」清单，界面据此提示用户。

与 `services/health.py` 的分工：

  - 本模块：取自数据库与进程状态的真实数字（用户数、认证次数、运行时长、设备连接）
  - `health.py`：没有真实来源的生理信号（心率、情绪、波形），接口层会标注为示意数据

关于 `auth_history`
------------------
该集合在 `core.init_system()` 里建了 `username + timestamp` 索引，管理后台也有
「删除某用户的全部历史」逻辑，但**原型阶段从未写入过任何一条**。因此这里的
认证次数统计目前一律是 0 —— 这是在如实反映「还没有记录」，不是在编数字。
将来补上写入点后（字段约定见下方常量），这些数字会自动变成真实值，本模块无需改动。
"""

import time

from web_auth import state
from web_auth.config import logger
from web_auth.extensions import mongo


# `auth_history` 的字段约定
#
# 这是本模块的查询口径，同时也是将来补写入点时的目标格式 —— 两边必须一致，
# 否则统计会一直查不到东西（而且不会报错，只是安静地返回 0）。
HISTORY_RESULT_SUCCESS = 'success'
HISTORY_RESULT_FAILURE = 'failure'
HISTORY_DURATION_FIELD = 'duration_ms'


def format_uptime(seconds):
    """把秒数格式化成「N天 N小时 N分钟」。"""
    total = max(0, int(seconds))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    return f'{days}天 {hours}小时 {minutes}分钟'


def get_uptime_seconds():
    """当前进程已运行的秒数。"""
    return time.monotonic() - state.process_start_time


def _safe_count(collection, query):
    """
    计数查询，失败时返回 0 并记日志。

    仪表盘不该因为数据库暂时不可达就整页 500 —— 但它也不能假装知道答案，
    所以失败时记 error，让日志里查得到。
    """
    try:
        return collection.count_documents(query)
    except Exception as exc:
        logger.error("统计查询失败 %s: %s", query, exc)
        return 0


def count_registered_users():
    """已注册的用户数（`users` 集合条目数）。"""
    return _safe_count(mongo.db.users, {})


def count_connected_devices():
    """
    当前已连接的采集设备数。

    只统计 BLE：串口连接由算法层的 `EnvironmentManager` 持有，Web 进程里
    没有这份状态 —— 与其猜一个数，不如只报能确认的那部分。
    """
    client = state.ble_device_client
    if client is not None and getattr(client, 'is_connected', False):
        return 1
    return 0


def _average_duration(query):
    """
    聚合出平均耗时（毫秒），没有带耗时的记录时返回 None。

    用 `$avg` 在数据库侧算，而不是把全部记录取回 Python 再平均 ——
    历史记录会随时间增长，拉全量迟早会变成负担。
    """
    try:
        cursor = mongo.db.auth_history.aggregate([
            {'$match': {**query, HISTORY_DURATION_FIELD: {'$exists': True}}},
            {'$group': {'_id': None, 'avg': {'$avg': f'${HISTORY_DURATION_FIELD}'}}},
        ])
        doc = next(iter(cursor), None)
        value = doc.get('avg') if doc else None
        return float(value) if value is not None else None
    except Exception as exc:
        logger.error("聚合平均认证耗时失败: %s", exc)
        return None


def aggregate_auth_history(username):
    """
    聚合某个用户在 `auth_history` 里的认证记录。

    返回 `(总次数, 成功次数, 失败次数, 平均耗时毫秒或 None)`。
    集合为空时是 `(0, 0, 0, None)` —— 如实反映「暂无记录」。
    """
    query = {'username': username}
    total = _safe_count(mongo.db.auth_history, query)
    success = _safe_count(
        mongo.db.auth_history, {**query, 'result': HISTORY_RESULT_SUCCESS}
    )
    return total, success, total - success, _average_duration(query)


def build_user_stats(username):
    """
    该用户的认证统计。

    没有任何记录时全部为 0。数字不好看，但它是真的 —— 界面会另配一句
    「暂无认证记录」，比一个凭空生成的 187 次更经得起追问。
    """
    total, success, failed, avg_ms = aggregate_auth_history(username)
    return {
        'total_logins': total,
        'successful_auths': success,
        'failed_auths': failed,
        # 无记录时为 0，配合下面的 has_history 由界面显示「暂无记录」
        'avg_response_time': round(avg_ms) if avg_ms is not None else 0,
        # 供界面区分「真的是 0 次」与「还没有任何记录」
        'has_history': total > 0,
    }


def build_system_stats():
    """进程与数据库侧能确证的系统状态。"""
    return {
        'uptime': format_uptime(get_uptime_seconds()),
        'active_users': count_registered_users(),
        'total_devices': count_connected_devices(),
    }
