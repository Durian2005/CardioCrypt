# -*- coding: utf-8 -*-
"""
设备数据采集：BLE 与串口两条链路的共用实现

「连设备 → 收数据 → 凑够判定所需的点数」这件事，验证（`blueprints/auth.py`）与
注册（`blueprints/device.py`）原本各写一遍，两端结构逐行对应。这里收口成一处，
调用方只保留自己真正独有的部分：

* 采集前准备各自的运行态（验证写 `verifying`、注册写 `collecting`）；
* `on_device_error` 回调 —— 设备中途断开要写进各自那份状态结构；
* 拿到结果后决定是「比对特征」还是「训练模型」；
* 失败时的对外文案。

接口约定
--------
* **采不到数据且未开启演示模式时抛 `CollectionAborted`**，调用方据此写失败态。
  这是本模块最要紧的一条：没有采集依据就是没有依据，不能凭空得出「通过」。
* 演示模式下的补齐一律经 `demo.py::demo_degrade`，据此留痕（日志 `[DEMO]`、
  随结果透出的 `demo_reasons`）。
* 合成信号替换的是**输入数据**，模型照常真跑 —— 这与「伪造模型文件」不是一回事：
  后者伪造的是**产物**，在 `device.py` 里被明确禁止，不提供开关。
"""

import asyncio
import contextlib
import threading
import time

from web_auth import state
from web_auth.config import logger
from web_auth.demo import demo_degrade, synthetic_signal_series
from web_auth.services.signals import (
    heart_rate_to_ecg,
    is_heart_rate_characteristic,
    is_heart_rate_service,
)

__all__ = [
    'CollectionAborted',
    'CollectionResult',
    'SERIAL_REGISTRATION_SECONDS',
    'SERIAL_VERIFICATION_SECONDS',
    'TARGET_DATA_POINTS',
    'collect_via_ble',
    'collect_via_serial',
    'new_event_loop',
    'top_up_or_abort',
]

#: 判定所需的最小数据点数。低于此数：演示模式下补齐，否则中止。
TARGET_DATA_POINTS = 60

#: 串口采集窗口（秒）。注册要积累训练样本，所以比验证长。
SERIAL_REGISTRATION_SECONDS = 60
SERIAL_VERIFICATION_SECONDS = 40

#: BLE 最多等待多久（秒）
_BLE_TIMEOUT_SECONDS = 90

#: BLE 等待期间检查连接与事件的间隔（秒）
_BLE_POLL_INTERVAL = 5

#: 每积累多少个数据点记一次进度日志
_POINT_LOG_INTERVAL = 10

#: 串口读取线程的轮询间隔（秒）——10ms 足够捕获 50 包/秒
_SERIAL_POLL_INTERVAL = 0.01

#: 判定串口数据「是否新鲜」的阈值（秒）
_SERIAL_FRESHNESS_SECONDS = 5.0


class CollectionAborted(Exception):
    """
    采集无法继续。

    `reason` 直接用作对外失败原因；`status` 取 `failed` / `error` / `device_error`，
    调用方原样写进自己的状态结构即可。
    """

    def __init__(self, reason, status='failed'):
        super().__init__(reason)
        self.reason = reason
        self.status = status


class CollectionResult:
    """一次采集的结果。

    points       采集到的 ECG 数据点（可能为空、也可能不足 `TARGET_DATA_POINTS`）
    demo_reasons 本次改用合成数据的原因（空列表 = 全程真实采集）
    completed    是否按「收满 `TARGET_DATA_POINTS`」自然结束
    """

    __slots__ = ('points', 'demo_reasons', 'completed')

    def __init__(self, points=None, demo_reasons=None, completed=False):
        self.points = points if points is not None else []
        self.demo_reasons = demo_reasons if demo_reasons is not None else []
        self.completed = completed


class _BleSession:
    """
    一次 BLE 采集的共享状态。

    用对象属性而不是 `nonlocal` 在回调与协程之间共享：两处都只做属性赋值与
    列表 `append`，闭包捕获本身就够；`nonlocal` 只在名字被**重新绑定**时才必要，
    写在这里会让人误以为发生了重新绑定。
    """

    __slots__ = ('points', 'complete', 'event', 'notify_enabled', 'client')

    def __init__(self):
        self.points = []
        self.complete = False
        self.event = threading.Event()
        self.notify_enabled = False
        self.client = None


# ---------------------------------------------------------------------------
# 串口
# ---------------------------------------------------------------------------

def collect_via_serial(*, seconds, label, log_every=_POINT_LOG_INTERVAL,
                       empty_fallback_points=0, on_synthetic=None):
    """
    从串口按固定时间窗口采集。

    只在采集窗口内「一个点都没拿到」且 `empty_fallback_points > 0` 时做局部补齐
    （注册侧用它一次补足训练样本）；给 0 表示不做局部处理，交由调用方的
    `top_up_or_abort` 统一补齐 —— 验证侧走的就是这条。

    `on_synthetic()` 在「串口不可用、直接改用合成信号」时调用，供注册侧清理
    自己那几个只在真实采集时才有意义的字段。
    """
    demo_reasons = []

    try:
        from ecgppg_system.devices.device_manager import EnvironmentManager

        logger.info("%s：使用串口设备采集数据", label)

        if not EnvironmentManager.is_serial_data_fresh(
            max_age_seconds=_SERIAL_FRESHNESS_SECONDS
        ):
            if not demo_degrade('串口设备未连接或未返回有效数据', demo_reasons):
                raise CollectionAborted('未检测到串口设备数据')
            logger.warning("%s：[DEMO] 串口不可用，改用合成信号完成流程", label)
            if on_synthetic is not None:
                on_synthetic()
            points = synthetic_signal_series(TARGET_DATA_POINTS)
            logger.info("%s：[DEMO] 已生成 %d 个合成数据点", label, len(points))
            return CollectionResult(points=points, demo_reasons=demo_reasons,
                                    completed=True)

        points, processed_count = _drain_serial(
            EnvironmentManager, seconds=seconds, log_every=log_every, label=label,
        )
    except CollectionAborted:
        raise
    except Exception as exc:
        if not demo_degrade('串口数据采集异常: %s' % exc, demo_reasons):
            raise CollectionAborted('串口数据采集失败: %s' % exc,
                                    status='error') from exc
        logger.warning("%s：[DEMO] 串口采集异常，改用合成信号完成流程", label)
        if on_synthetic is not None:
            on_synthetic()
        points = synthetic_signal_series(TARGET_DATA_POINTS)
        logger.info("%s：[DEMO] 已生成 %d 个合成数据点", label, len(points))
        return CollectionResult(points=points, demo_reasons=demo_reasons,
                                completed=True)

    if processed_count == 0:
        logger.warning("%s：串口在采集窗口内未返回任何数据", label)
        if empty_fallback_points <= 0:
            # 留给调用方的统一补齐：这里如实返回「什么也没采到」
            return CollectionResult(points=points, demo_reasons=demo_reasons,
                                    completed=False)
        if not demo_degrade('串口在采集窗口内未返回任何数据', demo_reasons):
            raise CollectionAborted('串口未采集到任何数据')
        points.extend(synthetic_signal_series(empty_fallback_points))
        logger.info("%s：[DEMO] 已生成 %d 个合成数据点", label, empty_fallback_points)
        return CollectionResult(points=points, demo_reasons=demo_reasons,
                                completed=True)

    logger.info("%s：采集了 %d 个数据点，数据采集成功", label, processed_count)
    return CollectionResult(points=points, demo_reasons=demo_reasons, completed=True)


def _drain_serial(environment_manager, *, seconds, log_every, label):
    """
    起一个后台线程持续读串口，主线程按固定时间窗口把心率转成 ECG。

    返回 `(points, processed_count)`。注意「按时间而非点数结束」是原设计的刻意
    选择：无论设备给得快还是慢，窗口长度都一样，单次采集的耗时可预期。
    """
    data_ready_event = threading.Event()
    stop_collection = threading.Event()
    buffer_lock = threading.Lock()
    data_buffer = []

    def buffer_collector():
        while not stop_collection.is_set():
            try:
                heart_rate = environment_manager.get_serial_heart_rate()
                if heart_rate > 0:
                    with buffer_lock:
                        data_buffer.append(heart_rate)
                    if len(data_buffer) % 10 == 0:
                        data_ready_event.set()
                time.sleep(_SERIAL_POLL_INTERVAL)
            except Exception as exc:
                logger.error("%s：数据采集错误: %s", label, exc)
                time.sleep(0.1)

    collector_thread = threading.Thread(target=buffer_collector, daemon=True)
    collector_thread.start()
    logger.info("%s：启动串口数据持续采集线程", label)
    logger.info("%s：开始固定时间采集: %s秒", label, seconds)

    points = []
    processed_count = 0
    start_time = time.time()

    while (time.time() - start_time) < seconds:
        data_ready_event.wait(timeout=1.0)
        data_ready_event.clear()

        with buffer_lock:
            current_batch = data_buffer.copy()
            data_buffer.clear()

        for heart_rate in current_batch:
            points.append(heart_rate_to_ecg(heart_rate))
            processed_count += 1
            if processed_count % log_every == 0:
                logger.info(
                    "%s：已采集 %d 个数据点，已用时间 %.2f 秒",
                    label, processed_count, time.time() - start_time,
                )

    stop_collection.set()
    collector_thread.join(timeout=2.0)
    logger.info(
        "%s：数据采集完成，共采集 %d 个数据点，耗时 %.2f 秒",
        label, processed_count, time.time() - start_time,
    )
    return points, processed_count


# ---------------------------------------------------------------------------
# BLE
# ---------------------------------------------------------------------------

def collect_via_ble(*, on_device_error, label, early_fallback_seconds=None):
    """
    从已连接的 BLE 设备采集。

    `on_device_error(reason)` 在设备中途断开时调用 —— 断开属于**设备侧**失败，
    与「没采到数据」不同，调用方需要把它写成自己的 `device_error` 状态。

    `early_fallback_seconds` 给出时，若此时长内一个点都没收到就提前结束等待：
    设备可能连上了却既不送数据也不报断开，到点收手比让用户干等满 90 秒好。
    """
    demo_reasons = []
    session = _BleSession()

    def check_event_status():
        logger.debug(
            "%s：采集事件状态: %s", label,
            '已触发' if session.event.is_set() else '未触发',
        )

    def notify_callback(sender, data):
        try:
            if session.complete:
                logger.debug("%s：数据采集已完成，忽略新数据", label)
                return
            if not session.notify_enabled:
                logger.debug("%s：通知已停止，忽略新数据", label)
                return
            if not data or len(data) < 1:
                logger.warning("%s：收到空数据包，忽略", label)
                return

            logger.debug("%s：收到心率数据包: %d 字节", label, len(data))
            try:
                if len(data) < 2:
                    logger.error("%s：无效心率数据包，长度过短", label)
                    return
                heart_rate = data[1]
                logger.info("%s：解析到心率 %s BPM", label, heart_rate)
                session.points.append(heart_rate_to_ecg(heart_rate))

                if len(session.points) % _POINT_LOG_INTERVAL == 0:
                    logger.info("%s：已收集 %d 个数据点", label, len(session.points))

                if len(session.points) >= TARGET_DATA_POINTS:
                    logger.info("%s：数据采集完成，已收集 %d 个数据点",
                                label, len(session.points))
                    session.complete = True
                    session.event.set()
                    try:
                        check_event_status()
                    except Exception as exc:
                        logger.error("%s：检查事件状态时出错: %s", label, exc)
            except RuntimeError as exc:
                # 事件循环已关闭时回调仍可能被触发，属预期内的收尾噪音
                if "Event loop is closed" in str(exc):
                    logger.warning("%s：事件循环已关闭，忽略数据处理", label)
                    session.complete = True
                    session.notify_enabled = False
                else:
                    logger.error("%s：处理数据时发生 RuntimeError: %s", label, exc)
        except Exception as exc:
            logger.error("%s：数据解析失败: %s", label, exc)

    async def collect_from_device():
        hr_char_uuid = None
        try:
            if not state.ble_device_client or not state.ble_device_client.is_connected:
                logger.warning("%s：BLE 设备未连接或不可用，无法采集真实数据", label)
                return (False, None)

            session.client = state.ble_device_client
            device_client = session.client
            device_address = state.ble_device_address
            selected_device_name = state.ble_device_name
            logger.info("%s：使用已连接的设备: %s (%s)",
                        label, selected_device_name, device_address)

            # 重新发现服务：设备可能增删过特征，缓存的列表未必还准
            services = await device_client.get_services()

            hr_service_found = False
            for service in services:
                if is_heart_rate_service(service.uuid):
                    hr_service_found = True
                    for char in service.characteristics:
                        if is_heart_rate_characteristic(char.uuid) and 'notify' in char.properties:
                            hr_char_uuid = char.uuid
                            break
                    if hr_char_uuid:
                        break

            if not hr_service_found:
                logger.warning("%s：设备不支持心率服务，无法采集真实数据", label)
                return (False, None)
            if not hr_char_uuid:
                logger.warning("%s：未找到心率特征或特征不支持通知，无法采集真实数据", label)
                return (False, None)

            logger.debug("%s：直接启用设备心率特征通知，UUID: %s", label, hr_char_uuid)

            # 服务发现本身要花时间，期间设备可能已经掉线，启用通知前再查一次
            if not device_client.is_connected:
                logger.warning("%s：设备 %s 连接已断开，无法启用通知", label, device_address)
                on_device_error('设备连接已断开，无法启用通知')
                return (False, None)

            try:
                await device_client.start_notify(hr_char_uuid, notify_callback)
                logger.debug("%s：已成功启用设备心率特征通知", label)
            except Exception as notify_error:
                logger.warning("%s：启用心率通知失败: %s，无法采集真实数据",
                               label, notify_error)
                return (False, None)

            session.notify_enabled = True
            logger.info("%s：已启用设备心率通知，开始采集数据", label)

            start_time = time.time()
            for _ in range(_BLE_TIMEOUT_SECONDS // _BLE_POLL_INTERVAL + 1):
                if (time.time() - start_time) >= _BLE_TIMEOUT_SECONDS:
                    logger.warning("%s：数据采集超时 (%s秒)，未取到足够数据",
                                   label, _BLE_TIMEOUT_SECONDS)
                    break
                if not device_client.is_connected:
                    logger.warning("%s：连接意外断开", label)
                    on_device_error('设备连接意外断开')
                    break
                if session.event.is_set():
                    logger.info("%s：数据采集已完成", label)
                    check_event_status()
                    break

                try:
                    await asyncio.wait_for(
                        asyncio.create_task(asyncio.sleep(_BLE_POLL_INTERVAL)),
                        timeout=float(_BLE_POLL_INTERVAL),
                    )
                    if session.event.is_set():
                        logger.info("%s：数据采集已完成（%d秒检查）",
                                    label, _BLE_POLL_INTERVAL)
                        check_event_status()
                        break
                    check_event_status()
                except asyncio.TimeoutError:
                    pass

            # 收尾一律停通知：采集成功、超时、断开都要停。
            await _stop_notify(session, hr_char_uuid, label)
            return (session.event.is_set(), hr_char_uuid)

        except Exception as exc:
            logger.error("%s：设备通信异常: %s", label, exc)
            try:
                if session.client and session.notify_enabled and hr_char_uuid:
                    await session.client.stop_notify(hr_char_uuid)
                    logger.info("%s：异常处理中已停止通知", label)
                    session.notify_enabled = False
            except Exception as cleanup_error:
                logger.error("%s：清理设备通知失败: %s", label, cleanup_error)
            return (False, None)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    fallback_timer = None
    data_collected = False
    hr_char_uuid_to_cleanup = None

    try:
        if early_fallback_seconds:
            fallback_timer = threading.Timer(
                early_fallback_seconds,
                lambda: session.event.set() if not session.points else None,
            )
            fallback_timer.daemon = True
            fallback_timer.start()

        result = loop.run_until_complete(collect_from_device())
        if isinstance(result, tuple):
            data_collected, hr_char_uuid_to_cleanup = result
        else:
            data_collected = bool(result)
    except Exception as exc:
        logger.error("%s：运行异步任务失败: %s", label, exc)
        data_collected = False
    finally:
        if fallback_timer is not None:
            fallback_timer.cancel()
        _close_loop(loop, session, hr_char_uuid_to_cleanup, label)

    return CollectionResult(points=session.points, demo_reasons=demo_reasons,
                            completed=data_collected)


async def _stop_notify(session, hr_char_uuid, label):
    """已启用通知就停掉。重复调用是安全的（停过之后标志即为 False）。"""
    if not session.notify_enabled:
        return
    try:
        await session.client.stop_notify(hr_char_uuid)
        logger.info("%s：已停止通知", label)
        session.notify_enabled = False
    except Exception as exc:
        logger.error("%s：停止通知时出错: %s", label, exc)


def _close_loop(loop, session, hr_char_uuid, label):
    """
    关闭本次采集的事件循环。

    `collect_from_device` 内部已经停过通知，但若它是因异常提前返回的，
    这里再兜一次：先尽力停通知，再取消残留任务并关循环。
    """
    try:
        if session.notify_enabled and session.client and session.client.is_connected:
            target = hr_char_uuid or _find_heart_rate_characteristic(session.client)
            if target:
                loop.run_until_complete(session.client.stop_notify(target))
                logger.info("%s：已停止设备通知", label)
                session.notify_enabled = False
    except Exception as exc:
        logger.error("%s：停止设备通知时出错: %s", label, exc)

    try:
        if not loop.is_closed():
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
    except Exception as exc:
        logger.error("%s：关闭事件循环时出错: %s", label, exc)

    # 循环已关，回调不该再处理数据
    session.notify_enabled = False


def _find_heart_rate_characteristic(device_client):
    """从已完成服务发现的客户端里再找一次心率特征 UUID，用于兜底停通知。"""
    for service in getattr(device_client, 'services', None) or []:
        if is_heart_rate_service(service.uuid):
            for char in service.characteristics:
                if is_heart_rate_characteristic(char.uuid):
                    return char.uuid
    return None


@contextlib.contextmanager
def new_event_loop(label):
    """
    建一个事件循环，用完保证关闭。

    bleak 的异步 API 要在自己的循环里跑，本项目三处（BLE 扫描、连接、
    采集）都是 `new_event_loop()` + `run_until_complete()`。原先只有采集这处
    做了收尾，扫描与连接建完就不管了 —— 每次调用泄漏一个循环对象及其
    持有的 selector/epoll 句柄。反复扫描设备时这些句柄会一直累积，
    在 Windows 上表现为句柄数缓慢上涨。

    与 `_close_loop` 的区别：那处还要停设备通知、取消残留任务，属于采集
    专属收尾；这里只管循环自身的开关，供没有设备连接的场合使用。
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield loop
    finally:
        try:
            if not loop.is_closed():
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                loop.close()
        except Exception as exc:
            logger.error("%s：关闭事件循环时出错: %s", label, exc)
        finally:
            # 让下一次 asyncio 调用能重新建循环，而不是拿到这个已关闭的
            asyncio.set_event_loop(None)


# ---------------------------------------------------------------------------
# 收尾：不足则补齐，否则中止
# ---------------------------------------------------------------------------

#: 降级原因里的措辞。整段存下来而不是拼接 ——「BLE」是缩写，与中文之间要不要
#: 空格、要几个，拼接时总有一边不对（「任何BLE 设备数据」就是这么来的）。
_SOURCE_LABELS = {
    'ble': ('BLE 设备仅提供 %d 个数据点（需要 %d 个）', '未采集到任何 BLE 设备数据'),
    'serial': ('串口设备仅提供 %d 个数据点（需要 %d 个）', '未采集到任何串口设备数据'),
    'generic': ('设备仅提供 %d 个数据点（需要 %d 个）', '未采集到任何设备数据'),
}


def top_up_or_abort(result, *, label, kind='generic'):
    """
    把不足 `TARGET_DATA_POINTS` 的采集结果补齐，或抛 `CollectionAborted`。

    这是整条链路最后一道「补齐」出口，也是原先「不接设备也能验证成功」的来源。
    默认判失败，只有演示模式才允许用合成信号凑够点数 —— 与 `demo.py` 同一口径：
    合成信号替换的是**输入数据**，模型照样要真跑，照样可能不通过。
    """
    partial = len(result.points)
    if partial >= TARGET_DATA_POINTS:
        return result

    partial_msg, empty_msg = _SOURCE_LABELS.get(kind, _SOURCE_LABELS['generic'])
    reason = partial_msg % (partial, TARGET_DATA_POINTS) if partial > 0 else empty_msg
    if not demo_degrade(reason, result.demo_reasons):
        raise CollectionAborted('未采集到足够的设备数据')

    needed = max(0, TARGET_DATA_POINTS - partial)
    if partial > 0:
        logger.info("%s：[DEMO] 已收集 %d 个设备数据点，补齐 %d 个合成数据点",
                    label, partial, needed)
        result.points.extend(synthetic_signal_series(needed))
    else:
        logger.info("%s：[DEMO] 无设备数据，全部使用合成数据", label)
        result.points = synthetic_signal_series(TARGET_DATA_POINTS)

    logger.info("%s：[DEMO] 合成数据准备完成，总数据点: %d", label, len(result.points))
    return result
