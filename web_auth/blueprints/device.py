# -*- coding: utf-8 -*-
"""
设备蓝图：扫描、连接、数据采集

覆盖 BLE 蓝牙与串口两条链路。设备连接状态是**进程级单例**，
所以这里对 `state.ble_device_*` 的读写要成对看待：
连接成功时写入、断开时清空，多用户并发时后连接者会打断前者
（这是已知限制，见 README 的「后续规划」）。
"""

import os
import random
import threading
import time
from datetime import datetime

import numpy as np
import torch
from flask import Blueprint, jsonify, request, session
from torch.utils.data import DataLoader, TensorDataset

from web_auth import state
from web_auth.config import logger, models_dir
from web_auth.core import (
    SYSTEM_AVAILABLE,
    authenticate_single_signal,
    configure_data_augmentation,
    create_model,
    save_model,
    setup_model_device,
    train_model,
)
from web_auth.demo import is_enabled as _demo_enabled
from web_auth.extensions import mongo
from web_auth.services.collection import (
    CollectionAborted,
    SERIAL_REGISTRATION_SECONDS,
    collect_via_ble,
    collect_via_serial,
    new_event_loop,
    top_up_or_abort,
)
from web_auth.services.signals import (
    filter_signal_arrays,
    generate_ecg_ppg_data,
    is_heart_rate_service,
)

bp = Blueprint('device', __name__)


# 注册侧的采集策略 —— 与验证侧的差异集中在这里，而不是散落在采集逻辑中：
# 采集窗口更长以积累足够的训练样本；窗口内一个点都没拿到时，一次补齐 300 点
# （验证侧只需补到判定所需的 60 点）。
SERIAL_REGISTRATION_LOG_EVERY = 50
SERIAL_REGISTRATION_FALLBACK_POINTS = 300

# BLE 等待的回退阈值：设备连上了却既不送数据、也不报断开时，到点就收，
# 让上层尽早决定「补齐还是失败」，而不是干等满 90 秒。
BLE_EARLY_FALLBACK_SECONDS = 15


# --- 训练阶段的形状与超参 ---------------------------------------------------
# 这些数字原先直接写死在 `collect_data_thread` 里，改动时无从判断
# 「600 和 10 是不是一对」；提成具名常量后，形状相关的一眼能看出配对关系。

#: 训练样本的时间步长（每个样本含多少个数据点）
#: 同时也是训练后自检的输入长度 —— 两者是同一批数据，故复用同一常量。
TRAIN_SEQUENCE_LENGTH = 10

#: 训练与自检的批大小
TRAIN_BATCH_SIZE = 32

#: 训练轮数
TRAIN_EPOCHS = 50

#: 每次自检之间的间隔（秒），给传感器一点恢复时间
VERIFY_INTERVAL_SECONDS = 2

#: 自检时合成的心率基准与抖动范围（BPM）
VERIFY_BASE_HEART_RATE = 70
VERIFY_HEART_RATE_JITTER = 5


# API: 扫描BLE设备
@bp.route('/api/scan_devices', methods=['POST'])
def scan_devices():
    try:
        device_type = request.json.get('device_type', 'all')  # 可以是 'ble', 'serial' 或 'all'
        devices_info = []
        
        # 扫描BLE设备
        if device_type in ['ble', 'all']:
            try:
                # 创建异步事件循环
                from bleak import BleakScanner

                # 使用BleakScanner直接扫描设备
                scan_timeout = state.admin_setting('device_scan_timeout', 5.0)
                logger.info(f"开始扫描BLE设备，超时时间: {scan_timeout}秒")

                # 用 with 包裹：退出时保证循环被关闭（见 new_event_loop 的说明）
                with new_event_loop('扫描BLE设备') as loop:
                    devices = loop.run_until_complete(
                        BleakScanner.discover(timeout=scan_timeout)
                    )
                
                # 格式化设备信息
                for device in devices:
                    # 获取广告数据，Bleak新版本中广告数据与设备分离
                    adv_data = device.advertisement_data if hasattr(device, 'advertisement_data') else None
                    
                    # 添加更多设备信息，如信号强度、服务UUID等（如果可用）
                    device_info = {
                        'address': device.address,
                        'name': device.name or '未命名设备',
                        'rssi': adv_data.rssi if adv_data else None,  # 使用AdvertisementData.rssi
                        'type': 'ble'  # 标记为BLE设备
                    }
                    
                    # 尝试获取设备的服务信息
                    if adv_data:
                        if hasattr(adv_data, 'service_uuids') and adv_data.service_uuids:
                            device_info['services'] = adv_data.service_uuids
                            # 检测是否包含心率服务
                            device_info['has_hr_service'] = any(
                                is_heart_rate_service(uuid) for uuid in adv_data.service_uuids
                            ) if adv_data.service_uuids else False
                    
                    devices_info.append(device_info)
                    
                logger.info(f"扫描到 {len(devices_info)} 个BLE设备")
                
            except Exception as e:
                logger.error(f"扫描BLE设备失败: {e}")
                # 扫描BLE设备失败，但可以继续扫描串口设备
        
        # 扫描串口设备
        if device_type in ['serial', 'all']:
            try:
                # 检查是否可以导入串口设备管理模块
                try:
                    from ecgppg_system.devices.device_manager import EnvironmentManager
                    from ecgppg_system.devices.serial_device_manager import SERIAL_DEVICE_AVAILABLE
                    
                    if SERIAL_DEVICE_AVAILABLE:
                        # 使用设备管理器发现串口设备
                        serial_devices = EnvironmentManager.discover_serial_devices()
                        devices_info.extend(serial_devices)
                        logger.info(f"扫描到 {len(serial_devices)} 个串口设备")
                    else:
                        logger.warning("串口设备支持不可用，请安装pyserial库")
                except ImportError as e:
                    logger.warning(f"导入串口设备管理模块失败: {e}")
            except Exception as e:
                logger.error(f"扫描串口设备失败: {e}")
        
        # 将设备列表保存到session中，以便后续连接时使用
        session['available_devices'] = devices_info
        
        logger.info(f"共扫描到 {len(devices_info)} 个设备")
        
        return jsonify({
            'success': True, 
            'devices': devices_info,
            'message': '请选择一个设备进行连接'
        })
    except Exception as e:
        logger.error(f"扫描设备失败: {e}")
        return jsonify({'success': False, 'error': str(e)})


# API: 连接设备
@bp.route('/api/connect_device', methods=['POST'])
def connect_device():
    
    address = request.json.get('address')
    device_type = request.json.get('type', 'ble')  # 默认为BLE设备
    
    if not address:
        return jsonify({'success': False, 'error': '未提供设备地址'})
    
    # 获取设备名称（如果在session中有保存）
    device_name = '未知设备'
    if 'available_devices' in session:
        for device in session['available_devices']:
            if device['address'] == address:
                device_name = device['name']
                # 如果设备类型没有指定，从session中获取
                if 'type' in device:
                    device_type = device['type']
                break
    
    try:
        # 获取用户名
        username = None
        if 'pending_login' in session:
            username = session['pending_login']
        elif 'username' in session:
            username = session['username']
        else:
            username = f"guest_{int(time.time())}"
        
        # 根据设备类型选择连接方法
        if device_type == 'ble':
            # 连接BLE设备
            logger.info(f"尝试连接BLE设备: {device_name} ({address})")

            # 直接创建BleakClient并连接设备
            from bleak import BleakClient

            # with 保证循环关闭：断开旧连接与建立新连接都要跑异步，
            # 两者放在同一个循环里，避免中途换循环导致状态错乱。
            with new_event_loop('连接BLE设备') as loop:
                # 如果已有设备连接，先断开
                if state.ble_device_client and state.ble_device_client.is_connected:
                    logger.info(f"断开之前的设备连接: {state.ble_device_name} ({state.ble_device_address})")
                    loop.run_until_complete(state.ble_device_client.disconnect())

                client = BleakClient(address)
                connected = loop.run_until_complete(client.connect())
            
            if connected:
                # 保存设备信息到全局变量
                state.ble_device_client = client
                state.ble_device_address = address
                state.ble_device_name = device_name
                state.ble_device_session_id = f"session_{int(time.time())}_{username}"
                
                # 存储已连接设备和会话信息到session中
                session['connected_device'] = {
                    'address': address,
                    'name': device_name,
                    'connected_at': datetime.now().isoformat(),
                    'session_id': state.ble_device_session_id,
                    'type': 'ble'
                }
                
                if 'pending_login' in session:
                    logger.info(f"已将BLE设备 {device_name} ({address}) 关联到用户 {session['pending_login']}")
                
                return jsonify({
                    'success': True, 
                    'device': {
                        'name': device_name,
                        'address': address,
                        'session_id': state.ble_device_session_id,
                        'type': 'ble'
                    },
                    'message': f'已成功连接到BLE设备: {device_name}'
                })
            else:
                return jsonify({
                    'success': False, 
                    'error': f'连接BLE设备 {device_name} 失败',
                    'error_code': 'CONNECTION_FAILED'
                })
        elif device_type == 'serial':
            # 连接串口设备
            try:
                # 检查是否可以导入串口设备管理模块
                from ecgppg_system.devices.device_manager import EnvironmentManager
                
                logger.info(f"尝试连接串口设备: {device_name} ({address})")
                
                # 连接串口设备
                baudrate = state.admin_setting('device_serial_baudrate', 115200)
                timeout = state.admin_setting('device_serial_timeout', 1.0)
                
                # 从会话中获取正确的端口信息
                port = address
                for device in session.get('available_devices', []):
                    if device.get('address') == address and device.get('type') == 'serial' and 'port' in device:
                        port = device['port']
                        logger.info(f"找到设备端口: {port}")
                        break
                
                logger.info(f"使用端口 {port} 连接串口设备")
                connected = EnvironmentManager.connect_serial_device(port, baudrate, timeout)
                
                if connected:
                    # 存储已连接设备和会话信息到session中
                    serial_session_id = f"serial_{int(time.time())}_{username}"
                    session['connected_device'] = {
                        'address': address,
                        'name': device_name,
                        'connected_at': datetime.now().isoformat(),
                        'session_id': serial_session_id,
                        'type': 'serial'
                    }
                    
                    # 启动数据读取
                    EnvironmentManager.start_reading_serial_data()
                    
                    if 'pending_login' in session:
                        logger.info(f"已将串口设备 {device_name} ({address}) 关联到用户 {session['pending_login']}")
                    
                    return jsonify({
                        'success': True, 
                        'device': {
                            'name': device_name,
                            'address': address,
                            'session_id': serial_session_id,
                            'type': 'serial'
                        },
                        'message': f'已成功连接到串口设备: {device_name}'
                    })
                else:
                    return jsonify({
                        'success': False, 
                        'error': f'连接串口设备 {device_name} 失败',
                        'error_code': 'CONNECTION_FAILED'
                    })
            except Exception as e:
                logger.error(f"连接串口设备失败: {e}")
                return jsonify({
                    'success': False, 
                    'error': f'连接串口设备时出错: {str(e)}',
                    'error_code': 'SERIAL_CONNECTION_ERROR'
                })
        else:
            return jsonify({
                'success': False, 
                'error': f'不支持的设备类型: {device_type}',
                'error_code': 'UNSUPPORTED_DEVICE_TYPE'
            })
    except Exception as e:
        logger.error(f"连接设备失败: {e}")
        return jsonify({
            'success': False, 
            'error': f'连接设备时出错: {str(e)}',
            'error_code': 'CONNECTION_ERROR'
        })


# API: 开始数据采集
@bp.route('/api/start_data_collection', methods=['POST'])
def start_data_collection():
    username = request.json.get('username')
    if not username or username not in state.current_registration_data:
        return jsonify({'success': False, 'error': '无效的注册会话'})
    
    # 在HTTP请求上下文中获取设备信息（线程内不再访问 session）
    device_info = session.get('connected_device')

    # 检查设备类型
    device_type = device_info.get('type', 'ble') if device_info else 'ble'
    
    # 演示模式下允许「没有设备就注册」——否则无硬件时连流程入口都进不去，
    # 采集线程里的降级逻辑也就无从生效。降级本身仍会逐条留痕（见 demo.py）。
    if _demo_enabled():
        logger.warning(
            "[DEMO] 演示模式已开启：跳过设备连接检查，"
            "本次注册将使用合成数据（type=%s）", device_type
        )
    elif device_type == 'ble':
        # 对于BLE设备，检查BLE客户端连接状态
        if not state.ble_device_client or not state.ble_device_client.is_connected:
            return jsonify({'success': False, 'error': 'BLE设备未连接，请先连接设备'})
    elif device_type == 'serial':
        # 对于串口设备，检查串口连接状态
        try:
            from ecgppg_system.devices.device_manager import EnvironmentManager
            if not EnvironmentManager.is_serial_data_fresh():
                return jsonify({'success': False, 'error': '串口设备未连接或未返回有效数据，请先连接设备'})
        except Exception as e:
            logger.error(f"检查串口设备连接状态时出错: {str(e)}")
            return jsonify({'success': False, 'error': '检查串口设备连接状态时出错，请重新连接设备'})
    else:
        return jsonify({'success': False, 'error': f'不支持的设备类型: {device_type}'})
    
    # 定义数据采集线程函数
    def collect_data_thread(username, device_info):
        # 本次注册中所有「采集降级」的原因，随结果一起透出给前端
        demo_reasons = []
        
        def fail(reason, status='failed'):
            """
            把注册定格为失败并写明原因。
            
            注册失败意味着「没有生成任何模型」—— 这是与「注册成功但模型
            不准确」完全不同的状态，必须让前端能区分出来。
            """
            with state.registration_lock:
                # setdefault：状态条目正常由 POST /register 建立，但回收线程
                # 理论上可能在采集期间把它清掉 —— 那时直接索引会 KeyError，
                # 把一次「注册失败」变成 500。
                entry = state.current_registration_data.setdefault(username, {})
                entry['status'] = status
                entry['error_message'] = reason
            logger.error("注册中止：%s", reason)
        
        try:
            # 获取全局函数引用
            
            # 开始采集数据
            logger.info(f"开始为用户 {username} 采集数据")
            
            # 清空之前的数据
            with state.registration_lock:
                state.current_registration_data[username]['data'] = []
                state.current_registration_data[username]['status'] = 'collecting'
            
            # 采集数据 —— BLE 与串口两条路径都收口在 services/collection.py
            device_type = device_info.get('type', 'ble') if device_info else 'ble'

            def mark_device_error(reason):
                """设备中途断开：单独记一档状态，前端据此与「没采到数据」区分。"""
                with state.registration_lock:
                    entry = state.current_registration_data.setdefault(username, {})
                    entry['status'] = 'device_error'
                    entry['error_message'] = reason
                state.touch_state('registration', username)

            def clear_partial_data():
                """
                串口不可用、直接改用合成信号时，清掉上一轮可能残留的原始数据 ——
                它们与本次结果已经无关，留着会被误读成本次采集到的。
                """
                with state.registration_lock:
                    entry = state.current_registration_data.setdefault(username, {})
                    entry['data'] = []
                    entry['heart_rates'] = []

            try:
                if device_type == 'serial':
                    outcome = collect_via_serial(
                        seconds=SERIAL_REGISTRATION_SECONDS,
                        log_every=SERIAL_REGISTRATION_LOG_EVERY,
                        label='注册',
                        empty_fallback_points=SERIAL_REGISTRATION_FALLBACK_POINTS,
                        on_synthetic=clear_partial_data,
                    )
                else:
                    outcome = collect_via_ble(
                        label='注册',
                        on_device_error=mark_device_error,
                        early_fallback_seconds=BLE_EARLY_FALLBACK_SECONDS,
                    )
            except CollectionAborted as exc:
                fail(exc.reason, status=exc.status)
                return

            if device_type != 'serial':
                # 串口分支已在自己的采集窗口内补齐（见 collection.py）；
                # BLE 分支在这里统一补齐。
                outcome = top_up_or_abort(outcome, label='注册', kind='ble')
            # 降级原因由 top_up_or_abort 追加进同一列表，必须在它之后再收集
            demo_reasons.extend(outcome.demo_reasons)
            collected_data = outcome.points

            # 处理采集到的数据
            with state.registration_lock:
                # 保存当前批次的数据
                if 'data' not in state.current_registration_data[username]:
                    state.current_registration_data[username]['data'] = []
                
                # 将收集的数据转换为适当的格式
                if collected_data and len(collected_data) > 0:
                    # 滤掉标量，只留可拼接的数组
                    all_signals = filter_signal_arrays(collected_data)
                    
                    # 只有当有有效数据时才处理
                    if all_signals:
                        # 拼接所有采集的信号
                        combined_signal = np.concatenate(all_signals)
                        state.current_registration_data[username]['data'].append(combined_signal)
                        logger.info(f"成功将用户 {username} 的{len(all_signals)}个信号数据合并为一个数组")
                
                # 更新状态为训练中
                state.current_registration_data[username]['status'] = 'training'
                logger.info(f"用户 {username} 状态更新为训练中")
            
            if SYSTEM_AVAILABLE:
                try:
                    logger.info("开始模型训练流程")
                    # 准备训练数据
                    # 将所有采集的数据合并为一个大数组
                    all_data = np.concatenate(collected_data)
                    logger.info(f"合并后的数据shape: {all_data.shape}")

                    # 重塑数据为LSTM需要的格式 [batch_size, sequence_length, features]
                    # 使用较小的序列长度，每10个数据点作为一个训练样本
                    sequence_length = TRAIN_SEQUENCE_LENGTH
                    
                    # 确保数据长度是序列长度的整数倍
                    data_length = len(all_data)
                    num_sequences = data_length // sequence_length
                    
                    if num_sequences == 0:
                        # 如果数据不够一个序列，则填充
                        padded_data = np.zeros(sequence_length)
                        padded_data[:data_length] = all_data
                        all_data = padded_data
                        num_sequences = 1
                        logger.info(f"数据长度不足，已填充至{sequence_length}个点")
                    else:
                        # 截断为序列长度的整数倍
                        all_data = all_data[:num_sequences * sequence_length]
                        logger.info(f"数据已截断为序列长度的整数倍: {all_data.shape}")

                    logger.info(f"创建了{num_sequences}个训练样本，每个样本包含{sequence_length}个数据点")
                    
                    # 创建标签（全部为1，表示本人）
                    labels = np.ones(num_sequences)
                    
                    # 创建PyTorch数据集和加载器
                    x_tensor = torch.FloatTensor(all_data.reshape(num_sequences, sequence_length, 1))
                    y_tensor = torch.FloatTensor(labels).unsqueeze(1)
                    dataset = TensorDataset(x_tensor, y_tensor)
                    train_loader = DataLoader(dataset, batch_size=TRAIN_BATCH_SIZE, shuffle=True)
                    test_loader = DataLoader(dataset, batch_size=TRAIN_BATCH_SIZE, shuffle=False)

                    # 使用main中的create_and_train_model函数创建和训练模型
                    logger.info(f"开始为用户 {username} 训练模型")
                    
                    try:
                        # 创建模型 - 使用模块化实现替代直接调用main中的函数
                        # 特征维度是1，但需要设置输入序列长度为10
                        logger.info("尝试创建模型...")
                        model = create_model(input_size=1)  # 特征维度是1
                        logger.info(f"模型创建成功: {type(model)}")
                        
                        # 设置模型的输入大小为新的序列长度
                        if hasattr(model, 'set_input_size'):
                            model.set_input_size(1)  # 设置为1，因为我们的特征维度是1
                            logger.info("已设置模型输入大小为1")
                        model, device = setup_model_device(model)
                        logger.info(f"模型已设置到设备: {device}")
                    except Exception as model_error:
                        logger.error(f"模型创建失败: {str(model_error)}")
                        raise
                    
                    # 配置数据增强
                    use_data_augmentation = configure_data_augmentation(train_loader)
                    
                    # 训练模型
                    history = train_model(
                        model=model,
                        train_loader=train_loader,
                        val_loader=test_loader,
                        epochs=TRAIN_EPOCHS,
                        device=device,
                        use_data_augmentation=use_data_augmentation
                    )
                    
                    # 验证模型 - 这是可选的，根据需要决定是否调用
                    # validation_results = validate_model(model, train_loader, test_loader, signal_type="ecg", device=device)
                    
                    # 保存模型
                    model_filename = f"{username}_model.pth"
                    model_path = os.path.join(models_dir, model_filename)
                    
                    # 构建保存的元数据
                    metadata = {
                        'signal_type': 'ecg',
                        'input_size': 1,
                        'epochs_trained': history.get('epochs_trained', 0),
                        'final_train_loss': history.get('train_loss', [])[-1] if history.get('train_loss') else None,
                        'final_val_loss': history.get('val_loss', [])[-1] if history.get('val_loss') else None,
                        'model_config': {'input_size': 1}
                    }
                    
                    # 保存模型和元数据
                    save_model(model, model_path, metadata)
                    
                    # 添加到用户模型缓存
                    state.user_models[username] = model
                    
                    # 更新注册状态
                    with state.registration_lock:
                        state.current_registration_data[username]['status'] = 'verifying'
                    
                    # 执行验证，使用管理员配置的验证次数
                    verification_success = 0
                    total_verification_count = state.admin_setting(
                        'total_verification_count', 3
                    )
                    for i in range(total_verification_count):
                        # 生成新的验证数据
                        verify_ecg_data, _ = generate_ecg_ppg_data(
                            num_samples=TRAIN_SEQUENCE_LENGTH,
                            base_heart_rate=VERIFY_BASE_HEART_RATE
                            + random.uniform(-VERIFY_HEART_RATE_JITTER,
                                              VERIFY_HEART_RATE_JITTER),
                        )

                        # 重塑为LSTM需要的格式 [1, sequence_length, 1]
                        verify_ecg_data = verify_ecg_data.reshape(
                            1, TRAIN_SEQUENCE_LENGTH, 1
                        )
                        
                        # 使用模型进行验证
                        model.eval()
                        with torch.no_grad():
                            device = next(model.parameters()).device
                            verify_tensor = torch.FloatTensor(verify_ecg_data).to(device)
                            
                            # 使用模块化的身份验证函数
                            # 判定结论只来自算法输出，这里不参与任何改写
                            auth_result = authenticate_single_signal(
                                model=model,
                                input_signal=verify_tensor,
                                threshold=state.admin_setting('model_threshold', 0.8),
                                signal_type='ecg',
                                device=device
                            )
                            confidence = auth_result['score']

                        # 使用管理员配置的阈值
                        if auth_result['authenticated']:
                            with state.registration_lock:
                                state.current_registration_data[username]['verification_success'] += 1
                                verification_success += 1
                        
                        logger.info(f"验证 {i+1} 结果: 置信度 {confidence:.4f}")
                        
                        # 验证间隔
                        time.sleep(VERIFY_INTERVAL_SECONDS)

                    # 检查验证结果，使用管理员配置的最小成功次数
                    min_verification_success = state.admin_setting(
                        'min_verification_success', 2
                    )
                    if verification_success >= min_verification_success:
                        # 更新注册状态
                        with state.registration_lock:
                            state.current_registration_data[username]['status'] = 'completed'
                            state.current_registration_data[username]['model_path'] = model_path
                            if demo_reasons:
                                # 采集阶段降级过：如实标记，前端据此提示「基于合成数据」
                                state.current_registration_data[username]['demo'] = True
                                state.current_registration_data[username]['demo_reasons'] = list(demo_reasons)
                        
                        # 保存用户到数据库
                        mongo.db.users.insert_one({
                            'username': username,
                            'model_path': model_path,
                            'created_at': datetime.now()
                        })
                        
                        logger.info(f"用户 {username} 注册成功")
                    else:
                        # 训练完成但自检未达标：不写入用户，如实报告
                        logger.warning(f"用户 {username} 训练后自检未通过")
                        fail(
                            '训练后自检未通过（成功 {}/{} 次）'.format(
                                verification_success, min_verification_success
                            )
                        )
                
                except Exception as e:
                    logger.error(f"模型训练/验证失败: {str(e)}")
                    fail('模型训练或验证失败: %s' % e, status='error')
            else:
                # 算法层不可用（导入失败）：训练模型的能力根本不存在。
                #
                # 这里原本会写一个内容为「模拟模型文件」的 .pth 占位文件，再把
                # 用户写进数据库、报告「注册成功 (模拟模式)」—— 等于凭空造出一个
                # 并不存在的「生物特征模型」，而后续验证会真的去加载它。
                #
                # 注意这与「用合成信号代替采集」不是一回事：后者替换的是**输入
                # 数据**（模型照样要真跑），这里伪造的是**产物**（模型本身）。
                # 因此不提供演示模式开关，一律中止。
                fail('算法层不可用，无法训练身份模型，注册中止', status='error')
        
        except Exception as e:
            logger.error(f"数据采集线程错误: {e}")
            with state.registration_lock:
                state.current_registration_data[username]['status'] = 'error'
    
    # 启动数据采集线程，传入设备信息而不是在线程中访问session
    # 刻意起名：采集要跑一两分钟，出问题时线程名是日志里唯一能定位到
    # 「是哪个用户在采集」的线索（栈里 `Thread-N` 只会给编号）
    threading.Thread(
        target=collect_data_thread,
        args=(username, device_info),
        daemon=True,
        name=f'collect-{username}',
    ).start()
    
    return jsonify({'success': True, 'message': '开始数据采集'})
