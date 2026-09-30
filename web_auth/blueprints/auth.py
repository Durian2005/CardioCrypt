# -*- coding: utf-8 -*-
"""
认证蓝图：首页、注册、登录、验证、登出

这里是整条认证链路的入口，也是安全加固最密集的地方：
认证前清空会话（防会话固定）、失败提示统一措辞（防用户名枚举）、
登录与验证启动都有限流、所有写操作都过 CSRF 校验。
"""

import asyncio
import threading
import time
from datetime import datetime

import numpy as np
from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from web_auth import state
from web_auth.config import USERNAME_RE, logger
from web_auth.demo import (
    demo_degrade as _demo_degrade,
    synthetic_signal_series as _demo_signal_series,
)
from web_auth.core import (
    SYSTEM_AVAILABLE,
    authenticate_single_signal,
    client_ip,
    dynamic_config,
    get_user_model,
    load_app_config,
)
from web_auth.extensions import (
    LOGIN_LIMITER,
    VERIFY_START_LIMITER,
    clear_session_keep_csrf,
    mongo,
)
from web_auth.services.signals import (
    heart_rate_to_ecg,
    is_heart_rate_characteristic,
    is_heart_rate_service,
)

bp = Blueprint('auth', __name__)


# ============================================================================
# 采集降级的统一出口
# ============================================================================
# 采集链路里有若干条「拿不到真实数据」的分支：设备没连上、特征不支持通知、
# 采到的点数不够、串口抛异常。这些分支原来各自直接生成一段合成信号继续往下走，
# 于是「没采到数据」和「采到了数据」在结果上没有任何区别 —— 不接设备点验证，
# 也能得到一次「验证成功」。
#
# 现在把这件事收口到 web_auth/demo.py：**默认不允许模拟**，采集不到就如实失败；
# 只有显式打开 DEMO_MODE 才允许用合成信号把流程走完，且每一次降级都留痕。
#
# 注意这里改的是「数据从哪来」，不是「判定怎么下」—— 合成信号照样要过模型
# 比对，照样可能不通过。判定结论的唯一来源始终是算法输出。


# 路由: 首页
@bp.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('dashboard.dashboard'))
    return render_template('index.html')


# 路由: 注册页面
@bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        
        # 检查用户名是否已存在
        existing_user = mongo.db.users.find_one({'username': username})
        if existing_user:
            flash('用户名已存在')
            return redirect(url_for('auth.register'))
        
        # 初始化注册流程
        with state.registration_lock:
            state.current_registration_data[username] = {
                'status': 'pending',
                'data': [],
                'verification_count': 0,
                'verification_success': 0,
                'model_path': None
            }
        state.touch_state('registration', username)

        # 重定向到数据采集页面
        return redirect(url_for('auth.collect_data', username=username))
    
    return render_template('register.html')


# 路由: 数据采集页面
@bp.route('/collect_data/<username>')
def collect_data(username):
    if username not in state.current_registration_data:
        flash('注册会话已过期，请重新开始')
        return redirect(url_for('auth.register'))
    
    # 动态加载最新配置
    state.admin_config = load_app_config()
    
    return render_template('collect_data.html', username=username)


# API: 获取注册状态
@bp.route('/api/registration_status/<username>', methods=['GET'])
def registration_status(username):
    if username not in state.current_registration_data:
        return jsonify({'success': False, 'error': '无效的注册会话'})

    # 采集页会持续轮询本接口：刷新活跃时间，使进行中的流程不被闲置回收
    state.touch_state('registration', username)

    with state.registration_lock:
        status_data = state.current_registration_data[username].copy()
    
    # 移除不需要发送给前端的数据
    if 'data' in status_data:
        del status_data['data']
    
    return jsonify({
        'success': True,
        'status': status_data
    })


# 路由: 登录页面
@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        ip = client_ip()
        if not LOGIN_LIMITER.allow(ip):
            logger.warning("登录尝试过于频繁，已限流: ip=%s", ip)
            flash('尝试过于频繁，请稍后再试')
            return redirect(url_for('auth.login'))

        # 认证开始前先清空会话，避免会话固定（Session Fixation）：
        # 一定要在写入本次登录状态之前重置。
        # 保留 CSRF 令牌 —— 它不属于身份状态，一并清掉会让紧随其后的
        # 下一次提交因缺令牌被拒（详见 security.clear_session_keep_csrf）。
        clear_session_keep_csrf(session)

        username = (request.form.get('username') or '').strip()
        if not USERNAME_RE.match(username):
            flash('用户名或验证信息无效')
            return redirect(url_for('auth.login'))

        # 检查用户是否存在
        # 注意：对外不区分「用户不存在」与「其它失败」，避免用户名枚举
        user = mongo.db.users.find_one({'username': username})
        if not user:
            flash('用户名或验证信息无效')
            return redirect(url_for('auth.login'))

        # 重定向到验证页面
        session['pending_login'] = username
        return redirect(url_for('auth.verify'))
    
    return render_template('login.html')


# 路由: 验证页面
@bp.route('/verify')
def verify():
    if 'pending_login' not in session:
        return redirect(url_for('auth.login'))
    
    username = session['pending_login']
    return render_template('verify.html', username=username)


# API: 开始验证
@bp.route('/api/start_verification', methods=['POST'])
def start_verification():
    if 'pending_login' not in session:
        return jsonify({'success': False, 'error': '无效的登录会话'})

    ip = client_ip()
    if not VERIFY_START_LIMITER.allow(ip):
        logger.warning("发起验证过于频繁，已限流: ip=%s", ip)
        return jsonify({'success': False, 'error': '操作过于频繁，请稍后再试'}), 429

    username = session['pending_login']
    
    # 获取已连接的设备信息（如果存在）并保存到线程安全的变量中
    device_info = session.get('connected_device', None)
    
    # 初始化验证结果为"进行中"
    with state.verification_lock:
        state.verification_results[username] = {
            'status': 'verifying',
            'timestamp': datetime.now()
        }
    state.touch_state('verification', username)
    
    # 启动验证线程
    def verify_thread(username, device_info):
        try:
            # 获取全局函数引用
            
            # 开始验证过程
            logger.info(f"开始为用户 {username} 验证身份")
            
            # 初始化验证数据结构（如果不存在）
            with state.verification_lock:
                if username not in state.verification_results:
                    state.verification_results[username] = {
                        'status': 'verifying',
                        'timestamp': datetime.now()
                    }
            state.touch_state('verification', username)
            
            # 本地引用，方便访问
            current_verification_data = state.verification_results[username]
            
            # 本次验证中所有「采集降级」的原因，随结果一起透出给前端
            demo_reasons = []
            
            def fail(reason, status='failed'):
                """把本次验证定格为失败并写明原因。"""
                with state.verification_lock:
                    state.verification_results[username] = {
                        'status': status,
                        'timestamp': datetime.now(),
                        'error_message': reason,
                    }
                state.touch_state('verification', username)
            
            def finish(success, score=None):
                """
                把本次验证定格为最终结论。演示模式下降级过的，
                附上标记与原因，避免前端把合成信号的结果当成真实比对。
                """
                with state.verification_lock:
                    entry = {
                        'status': 'success' if success else 'failed',
                        'timestamp': datetime.now(),
                    }
                    if score is not None:
                        entry['score'] = float(score)
                    if demo_reasons:
                        entry['demo'] = True
                        entry['demo_reasons'] = list(demo_reasons)
                    state.verification_results[username] = entry
                state.touch_state('verification', username)
            
            # 检查设备类型
            device_type = device_info.get('type', 'ble') if device_info else 'ble'
            
            # 获取用户模型
            if SYSTEM_AVAILABLE:
                # 使用按需加载获取模型
                model = get_user_model(username)
                
                if model is None:
                    # 用户没走完注册采集（库里没有对应模型文件），压根没有可比对的
                    # 参照物。这既不是「比对不通过」，也没有任何依据可以放行 ——
                    # 一律按错误处理，让用户重新完成注册采集。
                    fail(
                        '用户模型不可用：未完成注册采集或模型文件缺失',
                        status='error',
                    )
                    logger.error("验证中止：用户 %s 的模型不可用，需重新完成注册采集", username)
                    return
                else:
                    # 确定序列长度，使用配置中的值
                    sequence_length = dynamic_config.get('signal', 'length', 1000)
                    
                    # 采集验证数据
                    collected_data = []
                    device_client = None
                    notify_enabled = False
                    collection_complete = False
                    collection_event = threading.Event()
                    data_collected_successfully = False  # 添加标志，表示是否已成功采集数据
                    data_collected = False  # BLE 采集结果；串口分支不使用，先给默认值避免下方引用未定义
                    
                    # 检查设备类型并选择数据收集方式
                    if device_type == 'serial':
                        # 使用串口设备收集验证数据
                        try:
                            from ecgppg_system.devices.device_manager import EnvironmentManager
                            
                            logger.info("使用串口设备收集验证数据")
                            
                            # 检查串口连接
                            if not EnvironmentManager.is_serial_data_fresh(max_age_seconds=5.0):
                                if not _demo_degrade('串口设备未连接或未返回有效数据', demo_reasons):
                                    fail('未检测到串口设备数据，无法完成身份验证')
                                    return
                                use_simulated_data = True
                            else:
                                use_simulated_data = False
                            
                            if not use_simulated_data:
                                # 创建一个后台线程持续读取数据到缓冲区
                                data_ready_event = threading.Event()
                                stop_collection = threading.Event()
                                buffer_lock = threading.Lock()
                                data_buffer = []
                                
                                def buffer_collector():
                                    nonlocal data_buffer
                                    while not stop_collection.is_set():
                                        try:
                                            # 读取一个数据包
                                            heart_rate = EnvironmentManager.get_serial_heart_rate()
                                            if heart_rate > 0:
                                                # 获取完整数据包的所有信息
                                                with buffer_lock:
                                                    data_buffer.append(heart_rate)
                                                    
                                                # 每采集到10个有效数据包，发出信号
                                                if len(data_buffer) % 10 == 0:
                                                    data_ready_event.set()
                                                    
                                            # 短暂休眠，避免占用过高CPU
                                            time.sleep(0.01)  # 10ms，足够捕获50个包/秒
                                        except Exception as e:
                                            logger.error(f"验证：数据采集错误: {str(e)}")
                                            time.sleep(0.1)
                                
                                # 启动缓冲区收集器
                                collector_thread = threading.Thread(target=buffer_collector, daemon=True)
                                collector_thread.start()
                                logger.info("验证：启动串口数据持续采集线程")
                                
                                # 主线程处理数据，将原始数据转换为特征
                                collection_time_seconds = 40  # 固定采集30秒数据(验证需要的时间比注册短)
                                logger.info(f"验证：开始固定时间采集: {collection_time_seconds}秒")
                                
                                # 处理缓冲区数据
                                processed_count = 0
                                start_time = time.time()
                                
                                # 只根据时间来判断是否继续采集，不再考虑数据点数量
                                while (time.time() - start_time) < collection_time_seconds:
                                    # 等待新数据或超时
                                    data_ready_event.wait(timeout=1.0)
                                    data_ready_event.clear()
                                    
                                    # 处理缓冲区中的数据
                                    with buffer_lock:
                                        # 复制数据并清空缓冲区
                                        current_batch = data_buffer.copy()
                                        data_buffer.clear()
                                    
                                    # 处理批次数据
                                    if current_batch:
                                        for heart_rate in current_batch:
                                            # 生成ECG数据
                                            ecg_data = heart_rate_to_ecg(heart_rate)
                                            
                                            # 添加到采集数据
                                            collected_data.append(ecg_data)
                                            processed_count += 1
                                            
                                            # 记录进度
                                            if processed_count % 10 == 0:  # 每10个包记录一次
                                                elapsed_time = time.time() - start_time
                                                logger.info(f"验证：已采集 {processed_count} 个数据点，已用时间 {elapsed_time:.2f} 秒")
                                            
                                            # 不再根据数据点数量提前结束数据采集
                                            # 而是让固定时间采集完成
                                
                                # 停止收集器线程
                                stop_collection.set()
                                collector_thread.join(timeout=2.0)
                                
                                # 记录采集结果
                                actual_collection_time = time.time() - start_time
                                logger.info(f"验证：数据采集完成，共采集 {processed_count} 个数据点，耗时 {actual_collection_time:.2f} 秒")
                                
                                # 无论采集了多少数据，只要时间到了或采集了足够数据就标记完成
                                if processed_count > 0:
                                    logger.info(f"验证：采集了 {processed_count} 个数据点，数据采集成功")
                                    collection_complete = True
                                    collection_event.set()
                                    data_collected_successfully = True  # 标记数据已成功采集
                                else:
                                    logger.warning("验证：串口未采集到任何数据点")
                                
                                # 数据不足 60 点：默认判失败，只有演示模式才补齐
                                if len(collected_data) < 60:
                                    if not _demo_degrade(
                                        '串口仅提供 %d 个数据点（需要 60 个）' % len(collected_data),
                                        demo_reasons,
                                    ):
                                        fail('串口采集的数据量不足，无法完成身份验证')
                                        return
                                    
                                    needed_count = 60 - len(collected_data)
                                    collected_data.extend(_demo_signal_series(needed_count))
                                    
                                    logger.info(f"验证：[DEMO] 已补齐 {needed_count} 个合成数据点，总数据点: {len(collected_data)}")
                                    collection_complete = True
                                    collection_event.set()
                            else:
                                # 设备未就绪即进入演示分支（_demo_degrade 已确认演示模式开启）
                                logger.warning("验证：[DEMO] 串口不可用，改用合成信号完成流程")
                                
                                collected_data = _demo_signal_series(60)
                                
                                logger.info(f"验证：[DEMO] 已生成 {len(collected_data)} 个合成数据点")
                                collection_complete = True
                                collection_event.set()
                        except Exception as e:
                            if not _demo_degrade('串口数据采集异常: %s' % e, demo_reasons):
                                fail('串口数据采集失败，无法完成身份验证')
                                return
                            
                            collected_data = _demo_signal_series(60)
                            
                            logger.info(f"验证：[DEMO] 已生成 {len(collected_data)} 个合成数据点")
                            collection_complete = True
                            collection_event.set()
                        
                        # 定义数据回调函数
                    def notify_callback(sender, data):
                        nonlocal collection_complete, collected_data, collection_event, notify_enabled
                        try:
                            # 处理数据回调逻辑
                            # 开始接收数据
                            logger.debug(f"验证：收到心率数据包: {len(data)} 字节")
                            
                            # 如果数据采集已完成，忽略后续数据
                            if collection_complete:
                                logger.debug("验证数据采集已完成，忽略新数据")
                                return
                                
                            # 检查是否已停止通知
                            if not notify_enabled:
                                logger.debug("验证：通知已停止，忽略新数据")
                                return
                            
                            try:
                                # 解析心率数据（这里简化处理）
                                if len(data) >= 2:
                                    heart_rate = data[1]
                                    logger.info(f"验证：解析到心率 {heart_rate} BPM")
                                    
                                    # 生成验证用的ECG数据
                                    ecg_data = heart_rate_to_ecg(heart_rate)
                                    
                                    # 添加到采集数据
                                    collected_data.append(ecg_data)
                                    
                                    # 记录进度
                                    if len(collected_data) % 10 == 0:
                                        logger.info(f"验证：已收集 {len(collected_data)} 个数据点")
                                    
                                    # 当收集足够数据点时完成（60个数据点，约1分钟）
                                    if len(collected_data) >= 60:
                                        logger.info(f"验证：数据采集完成，已收集 {len(collected_data)} 个数据点")
                                        collection_complete = True
                                        collection_event.set()
                                        logger.info("验证：采集完成事件已触发")
                                        try:
                                            check_event_status()  # 检查事件状态
                                        except Exception as e:
                                            logger.error(f"验证：检查事件状态时出错: {str(e)}")
                            except RuntimeError as e:
                                if "Event loop is closed" in str(e):
                                    logger.warning("验证：事件循环已关闭，忽略数据处理")
                                    # 设置标志防止后续回调
                                    collection_complete = True
                                    notify_enabled = False
                                else:
                                    logger.error(f"验证：处理数据时发生RuntimeError: {str(e)}")
                        except Exception as e:
                            logger.error(f"验证：数据解析失败: {str(e)}")
                    
                    # 尝试连接蓝牙设备并采集数据
                    async def collect_from_device():
                        nonlocal device_client, notify_enabled, collection_complete, collection_event
                        try:
                            # 检查BLE设备是否可用
                            
                            if not state.ble_device_client or not state.ble_device_client.is_connected:
                                logger.warning("BLE 设备未连接或不可用，无法采集真实数据")
                                return (False, None)
                            
                            # 使用全局变量中的设备客户端
                            device_client = state.ble_device_client
                            device_address = state.ble_device_address
                            selected_device_name = state.ble_device_name
                            
                            logger.info(f"使用已连接的设备: {selected_device_name} ({device_address})")
                            
                            # 查找心率服务和特征
                            services = await device_client.get_services()
                            
                            # 查找心率服务
                            hr_service_found = False
                            hr_char_uuid = None
                            
                            for service in services:
                                # 检查是否是心率服务
                                if is_heart_rate_service(service.uuid):
                                    hr_service_found = True
                                    # 查找心率特征
                                    for char in service.characteristics:
                                        if is_heart_rate_characteristic(char.uuid) and 'notify' in char.properties:
                                            hr_char_uuid = char.uuid
                                            break
                                    if hr_char_uuid:
                                        break
                            
                            if not hr_service_found:
                                logger.warning("设备不支持心率服务，无法采集真实数据")
                                return (False, None)
                            
                            if not hr_char_uuid:
                                logger.warning("未找到心率特征或特征不支持通知，无法采集真实数据")
                                return (False, None)
                            
                            # 直接使用device_client启用通知
                            logger.debug(f"直接启用设备心率特征通知，UUID: {hr_char_uuid}")
                            
                            # 再次检查设备连接状态，防止在操作过程中连接已断开
                            if not device_client.is_connected:
                                logger.warning(f"设备 {device_address} 连接已断开，无法启用通知")
                                with state.verification_lock:
                                    state.verification_results[username]['status'] = 'device_error'
                                    state.verification_results[username]['error_message'] = '设备连接已断开，无法启用通知'
                                return (False, None)
                            
                            try:
                                # 直接在特征上启用通知，绑定回调函数
                                await device_client.start_notify(hr_char_uuid, notify_callback)
                                logger.debug(f"已成功启用设备心率特征通知")
                                notify_enabled = True
                            except Exception as notify_error:
                                logger.warning(f"启用心率通知失败: {str(notify_error)}，无法采集真实数据")
                                return (False, None)
                            
                            notify_enabled = True
                            logger.info(f"已启用设备心率通知，开始采集数据")
                            
                            # 等待数据采集完成或超时
                            timeout = 90  # 最多等待90秒
                            start_time = time.time()
                            
                            # 添加保持连接功能，每5秒检查一次连接状态
                            for _ in range(timeout // 5 + 1):
                                # 检查是否已经超时
                                elapsed_time = time.time() - start_time
                                if elapsed_time >= timeout:
                                    logger.warning(f"数据采集超时 ({timeout}秒)，未取到足够数据")
                                    break
                                    
                                # 检查连接状态
                                if not device_client.is_connected:
                                    logger.warning("连接意外断开")
                                    # 更新验证状态，通知前端设备连接问题
                                    with state.verification_lock:
                                        state.verification_results[username]['status'] = 'device_error'
                                        state.verification_results[username]['error_message'] = '设备连接意外断开'
                                    break
                                    
                                # 检查数据采集是否完成
                                if collection_event.is_set():
                                    logger.info("数据采集已完成")
                                    check_event_status()  # 检查事件状态
                                    break
                                    
                                # 等待5秒或直到事件被触发
                                try:
                                    # 使用wait_for来支持事件和超时
                                    await asyncio.wait_for(
                                        asyncio.create_task(asyncio.sleep(5)),  # 简单等待5秒
                                        timeout=5.0
                                    )
                                    # 在等待后检查事件是否被设置
                                    if collection_event.is_set():
                                        logger.info("数据采集已完成（5秒检查）")
                                        check_event_status()  # 再次检查事件状态
                                        break
                                    else:
                                        # 添加调试信息，看看为什么事件没有被触发
                                        check_event_status()
                                except asyncio.TimeoutError:
                                    # 超时但继续循环
                                    pass
                            
                            # 数据采集完成或超时后，检查结果
                            if not collection_event.is_set():
                                logger.warning("验证：数据采集超时或失败，停止通知")
                                if notify_enabled:
                                    try:
                                        await device_client.stop_notify(hr_char_uuid)
                                        logger.info("验证：已停止通知")
                                        notify_enabled = False
                                    except Exception as e:
                                        logger.error(f"验证：停止通知时出错: {str(e)}")
                            else:
                                # 数据采集成功完成，也需要停止通知
                                logger.info("数据采集成功完成，停止通知")
                                if notify_enabled:
                                    try:
                                        await device_client.stop_notify(hr_char_uuid)
                                        logger.info("注册：数据采集完成后已停止通知")
                                        notify_enabled = False
                                    except Exception as e:
                                        logger.error(f"停止通知时出错: {str(e)}")
                            
                            # 返回成功状态和特征UUID以便后续清理
                            return (collection_event.is_set(), hr_char_uuid)
                        
                        except Exception as e:
                            logger.error(f"验证：设备通信异常: {str(e)}")
                            # 尝试清理连接
                            try:
                                if device_client and notify_enabled and hr_char_uuid:
                                    await device_client.stop_notify(hr_char_uuid)
                                    logger.info("验证：异常处理中已停止通知")
                                    notify_enabled = False
                            except Exception as cleanup_error:
                                logger.error(f"验证：清理设备通知失败: {str(cleanup_error)}")
                            
                            return (False, None)  # 返回失败状态和空的UUID

                                    # 添加事件状态检查函数，方便调试
                    
                    def check_event_status():
                        logger.debug(f"采集事件状态: {'已触发' if collection_event.is_set() else '未触发'}")

                    if device_type == 'ble':
                        # 运行异步函数采集数据
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        
                        hr_char_uuid_to_cleanup = None  # 添加一个变量来保存需要停止通知的特征UUID
                        result = loop.run_until_complete(collect_from_device())
                        
                        # 获取结果，如果collect_from_device返回的是元组，表示它包含成功状态和特征UUID
                        if isinstance(result, tuple):
                            data_collected, hr_char_uuid_to_cleanup = result
                        else:
                            data_collected = result
                        
                        # 创建一个临时变量来确保notify_enabled在作用域中存在
                        current_notify_enabled = notify_enabled
                        
                        # 确保在关闭事件循环之前停止通知
                        if current_notify_enabled and device_client and device_client.is_connected:
                            if hr_char_uuid_to_cleanup:
                                # 使用返回的hr_char_uuid直接停止通知
                                try:
                                    # 使用当前事件循环停止通知
                                    loop.run_until_complete(device_client.stop_notify(hr_char_uuid_to_cleanup))
                                    logger.info("已停止设备通知")
                                    notify_enabled = False  # 更新原变量
                                except Exception as e:
                                    logger.error(f"停止设备通知时出错: {str(e)}")
                            else:
                                # 如果没有返回hr_char_uuid，尝试查找心率特征UUID并停止通知
                                try:
                                    # 获取心率特征UUID
                                    hr_char_uuid = None
                                    for service in device_client.services:
                                        if is_heart_rate_service(service.uuid):
                                            for char in service.characteristics:
                                                if is_heart_rate_characteristic(char.uuid):
                                                    hr_char_uuid = char.uuid
                                                    break
                                            if hr_char_uuid:
                                                break
                                    
                                    # 停止通知
                                    if hr_char_uuid:
                                        try:
                                            # 使用当前事件循环停止通知
                                            loop.run_until_complete(device_client.stop_notify(hr_char_uuid))
                                            logger.info("已停止设备通知")
                                            notify_enabled = False
                                        except Exception as e:
                                            logger.error(f"停止设备通知时出错: {str(e)}")
                                except Exception as e:
                                    logger.error(f"获取心率特征UUID失败: {str(e)}")
                        
                        # 安全关闭事件循环
                        try:
                            if not loop.is_closed():
                                # 确保所有任务都已完成
                                pending = asyncio.all_tasks(loop) if hasattr(asyncio, 'all_tasks') else asyncio.Task.all_tasks(loop)
                                for task in pending:
                                    task.cancel()
                                # 运行直到所有任务都被取消
                                if pending:
                                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                                loop.close()
                        except Exception as e:
                            logger.error(f"关闭事件循环时出错: {str(e)}")
                        
                        # 设置一个标志，表示通知已停止，防止回调函数继续处理数据
                        notify_enabled = False
                    
                    # 处理采集到的数据
                    # 如果数据采集失败或不足，需要补充模拟数据
                    if (not data_collected_successfully and not data_collected) or len(collected_data) < 60:
                        partial_data_count = len(collected_data)
                        
                        # 设备没给够数据 —— 这是整条链路最后一道「补齐」出口，
                        # 也是原先「不接设备也能验证成功」的来源。默认判失败，
                        # 只有演示模式才允许用合成信号凑够 60 点。
                        reason = (
                            '设备仅提供 %d 个数据点（需要 60 个）' % partial_data_count
                            if partial_data_count > 0 else
                            '未采集到任何设备数据'
                        )
                        if not _demo_degrade(reason, demo_reasons):
                            fail('未采集到足够的设备数据，无法完成身份验证')
                            return
                        
                        needed_count = max(0, 60 - partial_data_count)
                        if partial_data_count > 0:
                            logger.info(f"验证：[DEMO] 已收集 {partial_data_count} 个设备数据点，补齐 {needed_count} 个合成数据点")
                            collected_data.extend(_demo_signal_series(needed_count))
                        else:
                            logger.info("验证：[DEMO] 无设备数据，全部使用合成数据")
                            collected_data = _demo_signal_series(60)
                        
                        logger.info(f"验证：[DEMO] 合成数据准备完成，总数据点: {len(collected_data)}")
                    
                    # 如果成功采集到数据，则进行验证
                    if len(collected_data) > 0:
                        logger.info(f"验证：使用 {len(collected_data)} 个数据点进行身份验证")
                        
                        # 处理采集到的数据，用于验证
                        try:
                            # 确保collected_data中的每个元素都是数组
                            all_signals = []
                            for signal in collected_data:
                                if len(signal.shape) >= 1:  # 确认是数组而非标量
                                    all_signals.append(signal)
                            
                            # 只有当有有效数据时才处理
                            if all_signals:
                                # 拼接所有采集的信号
                                signal_data = np.concatenate(all_signals)
                                
                                # 将其转换为模型可接受的格式
                                if SYSTEM_AVAILABLE:
                                    # 设置序列长度为600
                                    sequence_length = 600
                                    
                                    # 确保数据长度适合模型输入
                                    data_length = len(signal_data)
                                    if data_length < sequence_length:
                                        # 填充
                                        padded_data = np.zeros(sequence_length)
                                        padded_data[:data_length] = signal_data
                                        signal_data = padded_data
                                    else:
                                        # 截断
                                        signal_data = signal_data[:sequence_length]
                                    
                                    # 重塑为模型需要的形状 [1, sequence_length, 1]
                                    signal_data = signal_data.reshape(1, sequence_length, 1)
                                    
                                    # 调用身份验证函数
                                    auth_result = authenticate_single_signal(model, signal_data, threshold=state.admin_config['model_threshold'])
                                    
                                    # 判定结论只来自算法输出，这里不做任何改写
                                    passed = bool(auth_result['authenticated'])
                                    finish(passed, score=auth_result['score'])
                                    logger.info(
                                        "用户 %s 验证%s，得分: %.4f",
                                        username, '成功' if passed else '失败', auth_result['score'],
                                    )
                                else:
                                    # 算法层不可用（导入失败），没有比对能力，
                                    # 也就没有任何依据可以判定通过。
                                    fail('算法层不可用，无法进行特征比对', status='error')
                                    return
                            else:
                                # 采集到的数据全都不是有效数组
                                fail('采集到的信号无效，无法完成身份验证')
                                return
                        except Exception as process_error:
                            logger.error(f"验证数据处理错误: {str(process_error)}")
                            fail('验证数据处理异常: %s' % process_error, status='error')
                            return
                    else:
                        # 走到这里说明 collected_data 仍为空：
                        # 演示模式关闭时上面已经 return，只有异常路径会落到这。
                        fail('未采集到可用于验证的信号数据')
            else:
                # 算法层不可用（导入失败），没有比对能力
                fail('算法层不可用，无法进行特征比对', status='error')
                
        except Exception as e:
            logger.error(f"验证线程错误: {e}")
            # 更新验证结果
            with state.verification_lock:
                state.verification_results[username] = {
                    'status': 'error',
                    'timestamp': datetime.now(),
                    'error': str(e)
                }
            state.touch_state('verification', username)
    
    # 启动验证线程，传入设备信息
    thread = threading.Thread(target=verify_thread, args=(username, device_info), daemon=True)
    thread.start()
    
    return jsonify({'success': True})


# API: 获取验证状态
@bp.route('/api/verification_status', methods=['GET'])
def verification_status():
    if 'pending_login' not in session:
        return jsonify({'success': False, 'error': '无效的登录会话'})
    
    username = session['pending_login']

    # 验证页会持续轮询本接口：刷新活跃时间，使进行中的验证不被闲置回收
    state.touch_state('verification', username)

    # 确保使用最新配置
    state.admin_config = load_app_config()
    
    # 检查是否已登录成功
    if 'username' in session:
        return jsonify({
            'success': True,
            'status': 'completed',
            'redirect': url_for('dashboard.dashboard')
        })
    
    # 检查验证结果字典
    with state.verification_lock:
        if username in state.verification_results:
            # 获取原始验证结果
            result = state.verification_results[username].copy()
            
            # 检查是否处于状态已确定阶段（成功或失败）
            if result['status'] == 'success' or result['status'] == 'failed' or result['status'] == 'error':
                # 认证结果以真实比对结果为准，不做任何改写
                demo = bool(result.get('demo'))
                
                if result['status'] == 'success':
                    # 设置登录会话
                    session.permanent = True
                    session['username'] = username
                    session.pop('pending_login', None)
                    state.verification_results.pop(username, None)
                    
                    payload = {
                        'success': True,
                        'status': 'completed',
                        'redirect': url_for('dashboard.dashboard')
                    }
                    if demo:
                        # 演示模式下本次用了合成信号，如实告知前端
                        payload['demo'] = True
                    return jsonify(payload)
                    
                elif result['status'] == 'failed' or result['status'] == 'error':
                    reason = result.get('error_message')
                    # 清除登录会话与验证结果
                    session.pop('pending_login', None)
                    state.verification_results.pop(username, None)
                    
                    payload = {
                        'success': True,
                        'status': 'failed',
                        'redirect': url_for('auth.login')
                    }
                    if reason:
                        payload['reason'] = reason
                    if demo:
                        payload['demo'] = True
                    return jsonify(payload)
            else:
                # 验证仍在进行中
                return jsonify({
                    'success': True,
                    'status': 'verifying'
                })
    
    # 仍在验证中
    return jsonify({
        'success': True,
        'status': 'verifying'
    })


# 路由: 退出登录
@bp.route('/logout')
def logout():
    # 与 /api/logout_json 保持一致：除了已认证身份，登录中的「待认证」状态
    # 也要一起清掉。否则登出后仍能回到 /verify 页面（该页面只检查 pending_login），
    # 留下一段谁也不该看到的状态。
    session.pop('username', None)
    session.pop('pending_login', None)
    return redirect(url_for('auth.index'))
