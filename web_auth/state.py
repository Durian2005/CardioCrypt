# -*- coding: utf-8 -*-
"""
进程内共享状态

这些状态**只存在于当前进程的内存里**：设备连接句柄、注册采集进度、
验证结果、模型缓存、管理员运行时配置。它们是「当前只能单进程部署」
这个约束的根源，也正是本模块被单独拆出来的理由 —— 集中一处，
将来要挪到 Redis / 独立服务时才有清晰的改造边界。

访问约定
--------
外部模块一律以 `state.xxx` 的**属性方式**读写，不要 `from web_auth.state import xxx`：

- 原地修改（dict 增删）用 import 也安全，但 `ble_device_client = client`
  这类重新赋值只有属性方式才作用在同一份状态上；
- 统一写法可以防止有人不小心在视图里写出一个同名局部变量，
  把「共享状态」悄悄变成「函数局部变量」。
"""

import threading
import time

from web_auth.config import (
    MAX_CACHED_MODELS,
    STATE_CLEANUP_INTERVAL,
    STATE_TTL_SECONDS,
    logger,
)



# 全局变量
current_registration_data = {}

registration_lock = threading.Lock()

user_models = {}  # 存储用户模型的字典，作为LRU缓存

user_models_lock = threading.Lock()  # 模型缓存字典的读改写锁（LRU 位置调整 / 淘汰）

verification_results = {}  # 存储验证结果的字典

verification_lock = threading.Lock()  # 验证结果的线程锁


# kind -> {username: 最后活跃时间}
_state_last_active = {'registration': {}, 'verification': {}}

_state_ts_lock = threading.Lock()


# 进程启动时刻，用于计算运行时长（仪表盘要展示的那个「系统运行时长」）。
#
# 用 monotonic 而不是 time.time()：运行时长关心的是「经过了多久」，
# 不该被系统时钟的校准或手动调整影响 —— 用 wall clock 算会出现负值。
process_start_time = time.monotonic()



def touch_state(kind, username):
    """标记某个状态条目刚刚活跃过，使其不会被回收线程清理。"""
    if not username:
        return
    with _state_ts_lock:
        bucket = _state_last_active.get(kind)
        if bucket is not None:
            bucket[username] = time.monotonic()



def collect_expired_states(now=None):
    """
    回收闲置超时的状态条目，返回 (注册条目数, 验证条目数)。

    先在时间戳锁内筛出候选并删掉时间戳，再逐个加业务锁删数据 ——
    避免为了比较时间戳而长时间持有业务锁。
    """
    now = time.monotonic() if now is None else now
    deadline = now - STATE_TTL_SECONDS

    with _state_ts_lock:
        candidates = {}
        for kind, bucket in _state_last_active.items():
            expired = [u for u, ts in bucket.items() if ts <= deadline]
            for u in expired:
                bucket.pop(u, None)
            candidates[kind] = expired

    removed_reg = 0
    for username in candidates['registration']:
        with registration_lock:
            if current_registration_data.pop(username, None) is not None:
                removed_reg += 1

    removed_ver = 0
    for username in candidates['verification']:
        with verification_lock:
            if verification_results.pop(username, None) is not None:
                removed_ver += 1

    if removed_reg or removed_ver:
        logger.info(
            "已回收闲置状态: 注册 %d 个、验证 %d 个（TTL=%d 秒）",
            removed_reg, removed_ver, STATE_TTL_SECONDS,
        )
    return removed_reg, removed_ver



def _start_state_cleanup_thread():
    """启动守护线程，周期性回收闲置状态。"""
    def _loop():
        while True:
            time.sleep(STATE_CLEANUP_INTERVAL)
            try:
                collect_expired_states()
            except Exception:
                logger.exception("回收闲置状态时出错")

    threading.Thread(target=_loop, daemon=True, name='state-cleanup').start()
    logger.info(
        "闲置状态回收线程已启动（TTL=%d 秒，扫描间隔=%d 秒）",
        STATE_TTL_SECONDS, STATE_CLEANUP_INTERVAL,
    )



_start_state_cleanup_thread()


# 单一设备连接
ble_device_client = None  # 当前连接的设备客户端

ble_device_address = None  # 当前连接的设备地址

ble_device_name = None  # 当前连接的设备名称

ble_device_session_id = None  # 当前会话ID

# 管理员运行时配置：由 create_app() 在启动时用 core.load_app_config() 填充，
# 之后管理后台的「参数修改」会重新加载它。
admin_config = None

__all__ = [
    # 注册采集进度
    'current_registration_data', 'registration_lock',
    # 用户模型 LRU 缓存
    'user_models', 'user_models_lock', 'MAX_CACHED_MODELS',
    # 验证结果
    'verification_results', 'verification_lock',
    # 设备连接（进程级单例）
    'ble_device_client', 'ble_device_address', 'ble_device_name',
    'ble_device_session_id',
    # 运行时配置
    'admin_config',
    # 进程信息
    'process_start_time',
    # 闲置回收
    'touch_state', 'collect_expired_states',
]
