# -*- coding: utf-8 -*-
"""
设备蓝图：扫描、连接、数据采集

覆盖 BLE 蓝牙与串口两条链路。设备连接状态是**进程级单例**，
所以这里对 `state.ble_device_*` 的读写要成对看待：
连接成功时写入、断开时清空，多用户并发时后连接者会打断前者
（这是已知限制，见 README 的「后续规划」）。
"""

import asyncio
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
from web_auth.extensions import mongo
from web_auth.services.signals import (
    generate_ecg_ppg_data,
    heart_rate_to_ecg,
    is_heart_rate_characteristic,
    is_heart_rate_service,
)

bp = Blueprint('device', __name__)



# API: 扫描BLE设备
@bp.route('/api/scan_devices', methods=['POST'])
def scan_devices():
    try:
        device_type = request.json.get('device_type', 'all')  # 可以是 'ble', 'serial' 或 'all'
        devices_info = []
        
        # 扫描BLE设备
        if device_type in ['ble', 'all']:
            try:
                # 创建异步事件循环（asyncio 已在模块顶部导入）
                from bleak import BleakScanner
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # 使用BleakScanner直接扫描设备
                scan_timeout = state.admin_config['device_scan_timeout'] if 'device_scan_timeout' in state.admin_config else 5.0
                logger.info(f"开始扫描BLE设备，超时时间: {scan_timeout}秒")
                
                devices = loop.run_until_complete(BleakScanner.discover(timeout=scan_timeout))
                
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
            # 创建异步事件循环（asyncio 已在模块顶部导入）
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            logger.info(f"尝试连接BLE设备: {device_name} ({address})")
            
            # 如果已有设备连接，先断开
            if state.ble_device_client and state.ble_device_client.is_connected:
                logger.info(f"断开之前的设备连接: {state.ble_device_name} ({state.ble_device_address})")
                loop.run_until_complete(state.ble_device_client.disconnect())
            
            # 直接创建BleakClient并连接设备
            from bleak import BleakClient
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
                baudrate = state.admin_config.get('device_serial_baudrate', 115200)
                timeout = state.admin_config.get('device_serial_timeout', 1.0)
                
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
    
    # 在HTTP请求上下文中获取设备信息
    device_info = None
    if 'connected_device' in session:
        device_info = session.get('connected_device')
    
    # 验证设备连接状态
    
    # 检查设备类型
    device_type = device_info.get('type', 'ble') if device_info else 'ble'
    
    if device_type == 'ble':
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
        try:
            # 获取全局函数引用
            
            # 开始采集数据
            logger.info(f"开始为用户 {username} 采集数据")
            
            # 清空之前的数据
            with state.registration_lock:
                state.current_registration_data[username]['data'] = []
                state.current_registration_data[username]['status'] = 'collecting'
            
            # 采集数据变量
            collected_data = []
            ecg_buffer = []
            device_client = None
            notify_enabled = False  # 在函数级别初始化
            collection_complete = False
            collection_event = threading.Event()
            
            # 检查设备类型
            device_type = device_info.get('type', 'ble') if device_info else 'ble'
            
            if device_type == 'serial':
                # 使用串口设备采集数据
                try:
                    from ecgppg_system.devices.device_manager import EnvironmentManager
                    
                    logger.info("使用串口设备采集数据")
                    
                    # 检查串口连接
                    if not EnvironmentManager.is_serial_data_fresh(max_age_seconds=5.0):
                        logger.warning("串口设备未连接或未返回有效数据，使用模拟数据")
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
                                        # 获取完整数据包的所有信息 (如果API支持的话)
                                        # 这里只获取了心率，实际中可以获取更多传感器数据
                                        with buffer_lock:
                                            data_buffer.append(heart_rate)
                                            
                                        # 每采集到10个有效数据包，发出信号
                                        if len(data_buffer) % 10 == 0:
                                            data_ready_event.set()
                                            
                                    # 短暂休眠，避免占用过高CPU
                                    time.sleep(0.01)  # 10ms，足够捕获50个包/秒
                                except Exception as e:
                                    logger.error(f"数据采集错误: {str(e)}")
                                    time.sleep(0.1)
                        
                        # 启动缓冲区收集器
                        collector_thread = threading.Thread(target=buffer_collector, daemon=True)
                        collector_thread.start()
                        logger.info("启动串口数据持续采集线程")
                        
                        # 主线程处理数据，将原始数据转换为特征
                        collection_time_seconds = 60  # 固定采集90秒数据
                        logger.info(f"开始固定时间采集: {collection_time_seconds}秒")
                        
                        # 处理缓冲区数据，转换成有用的特征
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
                                    if processed_count % 50 == 0:  # 每50个包记录一次
                                        elapsed_time = time.time() - start_time
                                        logger.info(f"已采集 {processed_count} 个数据点，已用时间 {elapsed_time:.2f} 秒")
                        
                        # 停止收集器线程
                        stop_collection.set()
                        collector_thread.join(timeout=2.0)
                        
                        # 记录采集结果
                        actual_collection_time = time.time() - start_time
                        logger.info(f"数据采集完成，共采集 {processed_count} 个数据点，耗时 {actual_collection_time:.2f} 秒")
                        
                        # 无论采集了多少数据，只要时间到了就标记完成
                        if processed_count > 0:
                            logger.info(f"采集了 {processed_count} 个数据点，数据采集成功")
                            collection_complete = True
                            collection_event.set()
                        else:
                            # 没有采集到任何数据，使用模拟数据
                            logger.warning(f"在指定时间内未采集到任何数据，使用模拟数据")
                            
                            # 生成300个模拟数据点
                            needed_count = 300  # 如果没有采集到真实数据，则生成300个模拟数据点
                            for _ in range(needed_count):
                                # 随机心率变化，模拟真实注册场景
                                heart_rate = 70 + random.uniform(-10, 10)
                                
                                # 生成ECG数据
                                ecg_data = heart_rate_to_ecg(heart_rate)
                                
                                # 添加到采集数据
                                collected_data.append(ecg_data)
                            
                            logger.info(f"模拟数据生成完成，总数据点: {len(collected_data)}")
                            collection_complete = True
                            collection_event.set()
                    else:
                        # 完全使用模拟数据
                        logger.warning(f"使用模拟数据为用户 {username} 采集数据")
                        collection_complete = True
                        
                        # 清空之前可能部分采集的数据
                        collected_data = []
                        with state.registration_lock:
                            state.current_registration_data[username]['data'] = []
                        
                        # 生成60个模拟数据点
                        for _ in range(60):
                            # 随机心率变化，模拟真实注册场景
                            heart_rate = 70 + random.uniform(-10, 10)
                            
                            # 生成ECG数据
                            ecg_data = heart_rate_to_ecg(heart_rate)
                            
                            # 添加到采集数据
                            collected_data.append(ecg_data)
                            
                            # 记录心率信息
                            with state.registration_lock:
                                # 添加到用户数据
                                if 'heart_rates' not in state.current_registration_data[username]:
                                    state.current_registration_data[username]['heart_rates'] = []
                                state.current_registration_data[username]['heart_rates'].append(heart_rate)
                        
                        logger.info(f"已生成 {len(collected_data)} 个模拟ECG数据点")
                except Exception as e:
                    logger.error(f"串口设备数据采集失败: {str(e)}，使用模拟数据")
                    # 使用模拟数据
                    collection_complete = True
                    collected_data = []
                    
                    # 生成60个模拟数据点
                    for _ in range(60):
                        heart_rate = 70 + random.uniform(-10, 10)
                        ecg_data = heart_rate_to_ecg(heart_rate)
                        collected_data.append(ecg_data)
                    
                    logger.info(f"已生成 {len(collected_data)} 个模拟ECG数据点")
            else:
                # 使用BLE设备采集数据
                # 添加事件状态检查函数，方便调试
                def check_event_status():
                    logger.debug(f"采集事件状态: {'已触发' if collection_event.is_set() else '未触发'}")
                
                # 定义数据回调函数
                def notify_callback(sender, data):
                    nonlocal collection_complete, ecg_buffer, collected_data, collection_event, notify_enabled
                    
                    try:
                        # 设备错误保护
                        if collection_complete:
                            logger.debug("数据采集已完成，忽略新数据")
                            return
                        
                        # 检查是否已停止通知
                        if not notify_enabled:
                            logger.debug("通知已停止，忽略新数据")
                            return
                        
                        # 数据完整性检查
                        if not data or len(data) < 1:
                            logger.warning("收到空数据包，忽略")
                            return
                        
                        # 开始接收数据
                        logger.debug(f"收到心率数据包: {len(data)} 字节")
                        
                        # 如果数据采集已完成，忽略后续数据
                        if collection_complete:
                            logger.debug("数据采集已完成，忽略新数据")
                            return
                        
                        # 使用try-except包裹处理逻辑，防止事件循环已关闭时产生异常
                        try:
                            # 简化心率数据解析
                            if len(data) >= 2:
                                heart_rate = data[1]
                                logger.info(f"解析到心率: {heart_rate} BPM")
                                
                                # 生成ECG数据
                                ecg_data = heart_rate_to_ecg(heart_rate)
                                
                                # 直接添加到采集数据
                                collected_data.append(ecg_data)
                                
                                # 记录进度
                                if len(collected_data) % 10 == 0:
                                    logger.info(f"已收集 {len(collected_data)} 个数据点")
                                
                                # 当收集足够数据点时完成（60个数据点，约1分钟）
                                if len(collected_data) >= 60:
                                    logger.info(f"数据采集完成，已收集 {len(collected_data)} 个数据点")
                                    collection_complete = True
                                    collection_event.set()
                                    logger.info("采集完成事件已触发")
                                    try:
                                        check_event_status()  # 检查事件状态
                                    except Exception as e:
                                        logger.error(f"检查事件状态时出错: {str(e)}")
                            else:
                                logger.error("无效心率数据包，长度过短")
                        except RuntimeError as e:
                            if "Event loop is closed" in str(e):
                                logger.warning("事件循环已关闭，忽略数据处理")
                                # 设置标志防止后续回调
                                collection_complete = True
                                notify_enabled = False
                            else:
                                logger.error(f"处理数据时发生RuntimeError: {str(e)}")
                    except Exception as e:
                        logger.error(f"数据解析失败: {str(e)}")
                
                # 使用现有的事件循环而不是创建新的循环（asyncio 已在模块顶部导入）
                
                # 创建异步事件循环用于数据采集
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # 收集数据的异步函数
                async def collect_from_device():
                    nonlocal device_client, notify_enabled, collection_complete

                    try:
                        # 检查BLE设备是否可用
                        
                        if not state.ble_device_client or not state.ble_device_client.is_connected:
                            logger.warning("BLE设备未连接或不可用，使用模拟数据")
                            return (False, None)
                        
                        # 使用全局变量中的设备客户端
                        device_client = state.ble_device_client
                        device_address = state.ble_device_address
                        selected_device_name = state.ble_device_name
                        
                        logger.info(f"使用已连接的设备: {selected_device_name} ({device_address})")
                        
                        # 注意：移除冗余连接步骤，设备已经连接
                        
                        # 查找心率服务和特征 - 使用与登录验证相同的方式强制重新发现服务
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
                            logger.warning("设备不支持心率服务，使用模拟数据")
                            return (False, None)
                        
                        if not hr_char_uuid:
                            logger.warning("未找到心率特征或特征不支持通知，使用模拟数据")
                            return (False, None)
                        
                        # 直接使用device_client启用通知
                        logger.debug(f"直接启用设备心率特征通知，UUID: {hr_char_uuid}")
                        
                        # 再次检查设备连接状态，防止在操作过程中连接已断开
                        if not device_client.is_connected:
                            logger.warning(f"设备 {device_address} 连接已断开，无法启用通知")
                            with state.registration_lock:
                                state.current_registration_data[username]['status'] = 'device_error'
                                state.current_registration_data[username]['error_message'] = '设备连接已断开，无法启用通知'
                            return (False, None)
                        
                        try:
                            # 直接在特征上启用通知，绑定回调函数
                            await device_client.start_notify(hr_char_uuid, notify_callback)
                            logger.debug(f"已成功启用设备心率特征通知")
                            notify_enabled = True
                        except Exception as notify_error:
                            logger.warning(f"启用心率通知失败: {str(notify_error)}，使用模拟数据")
                            return (False, None)
                        
                        # 确保通知已启用标志被正确设置
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
                                logger.warning(f"数据采集超时 ({timeout}秒)，切换到模拟数据")
                                break
                                
                            # 检查连接状态
                            if not device_client.is_connected:
                                logger.warning("连接意外断开")
                                # 更新状态，通知前端设备连接问题
                                with state.registration_lock:
                                    state.current_registration_data[username]['status'] = 'device_error'
                                    state.current_registration_data[username]['error_message'] = '设备连接意外断开'
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
                            logger.warning("数据采集超时或失败，停止通知")
                            if notify_enabled:
                                try:
                                    await device_client.stop_notify(hr_char_uuid)
                                    logger.info("注册：已停止通知")
                                    notify_enabled = False
                                except Exception as e:
                                    logger.error(f"停止通知时出错: {str(e)}")
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
                        logger.error(f"设备通信异常: {str(e)}")
                        # 尝试清理连接
                        try:
                            if device_client and notify_enabled and hr_char_uuid:
                                await device_client.stop_notify(hr_char_uuid)
                                logger.info("注册：异常处理中已停止通知")
                                notify_enabled = False
                        except Exception as cleanup_error:
                            logger.error(f"清理设备通知失败: {str(cleanup_error)}")
                        
                        return (False, None)  # 返回失败状态和空的UUID
                
                # 尝试从设备采集数据，但在新线程中保持设备连接不断开
                success = False
                hr_char_uuid_to_cleanup = None  # 添加一个变量来保存需要停止通知的特征UUID
                
                try:
                    # 设置较短的超时时间
                    fallback_timeout = 15  # 15秒后如果设备还没有数据就回退到模拟
                    fallback_timer = threading.Timer(fallback_timeout, lambda: collection_event.set() if not collected_data else None)
                    fallback_timer.daemon = True  # 设置为守护线程
                    fallback_timer.start()
                    
                    # 运行异步任务
                    result = loop.run_until_complete(collect_from_device())
                    
                    # 获取结果，如果collect_from_device返回的是元组，表示它包含成功状态和特征UUID
                    if isinstance(result, tuple):
                        success, hr_char_uuid_to_cleanup = result
                    else:
                        success = result
                    
                    # 取消回退定时器
                    fallback_timer.cancel()
                except Exception as e:
                    logger.error(f"运行异步任务失败: {str(e)}")
                    success = False
                
                # 使用一个临时变量来确保notify_enabled在作用域中存在
                current_notify_enabled = notify_enabled

                # 数据采集后，关闭事件循环但不断开设备连接
                try:
                    # 确保在关闭事件循环前停止设备通知
                    if device_client and current_notify_enabled and hr_char_uuid_to_cleanup:
                        logger.info(f"关闭事件循环前停止设备通知，特征UUID: {hr_char_uuid_to_cleanup}")
                        try:
                            # 使用同步方法停止通知
                            loop.run_until_complete(device_client.stop_notify(hr_char_uuid_to_cleanup))
                            logger.info("成功停止设备通知")
                            notify_enabled = False  # 更新原变量
                        except Exception as e:
                            logger.error(f"停止通知失败: {str(e)}")
                    
                    # 安全关闭事件循环
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
                
                # 如果从设备采集失败，使用模拟数据
                if not success or not collected_data or len(collected_data) < 60:
                    # 如果有部分采集的数据但不足60点，则记录
                    partial_data_count = len(collected_data)
                    
                    logger.info(f"设备数据不足（获取到{partial_data_count}个点，需要60个点），使用模拟数据补充")
                    
                    # 如果需要补充数据
                    if partial_data_count > 0 and partial_data_count < 60:
                        needed_count = 60 - partial_data_count
                        logger.info(f"已收集 {partial_data_count} 个设备数据点，需要生成 {needed_count} 个模拟数据点")
                        
                        # 生成补充模拟数据
                        for _ in range(needed_count):
                            # 随机心率变化，模拟真实注册场景
                            heart_rate = 70 + random.uniform(-10, 10)
                            rr_interval = 60000.0 / heart_rate  # 将心率转换为RR间隔（毫秒）
                            
                            # 生成ECG数据
                            ecg_data = heart_rate_to_ecg(heart_rate)
                            
                            # 添加到采集数据
                            collected_data.append(ecg_data)
                            
                        logger.info(f"模拟数据补充完成，总数据点: {len(collected_data)}")
                    else:
                        # 完全使用模拟数据
                        logger.info(f"使用模拟数据为用户 {username} 采集数据")
                        collection_complete = True
                        
                        # 清空之前可能部分采集的数据
                        collected_data = []
                        with state.registration_lock:
                            state.current_registration_data[username]['data'] = []
                        
                        # 生成60个模拟数据点
                        for _ in range(60):
                            # 随机心率变化，模拟真实注册场景
                            heart_rate = 70 + random.uniform(-10, 10)
                            rr_interval = 60000.0 / heart_rate  # 将心率转换为RR间隔（毫秒）
                            
                            # 生成ECG数据
                            ecg_data = heart_rate_to_ecg(heart_rate)
                            
                            # 添加到采集数据
                            collected_data.append(ecg_data)
                            
                            # 记录心率信息
                            with state.registration_lock:
                                # 添加到用户数据
                                if 'heart_rates' not in state.current_registration_data[username]:
                                    state.current_registration_data[username]['heart_rates'] = []
                                state.current_registration_data[username]['heart_rates'].append(heart_rate)
                        
                        logger.info(f"已生成 {len(collected_data)} 个模拟ECG数据点")

            # 处理采集到的数据
            with state.registration_lock:
                # 保存当前批次的数据
                if 'data' not in state.current_registration_data[username]:
                    state.current_registration_data[username]['data'] = []
                
                # 将收集的数据转换为适当的格式
                if collected_data and len(collected_data) > 0:
                    # 确保collected_data中的每个元素都是数组
                    all_signals = []
                    for signal in collected_data:
                        if len(signal.shape) >= 1:  # 确认是数组而非标量
                            all_signals.append(signal)
                    
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
                    logger.info(f"SYSTEM_AVAILABLE = {SYSTEM_AVAILABLE}, 开始模型训练流程")
                    # 准备训练数据
                    # 将所有采集的数据合并为一个大数组
                    all_data = np.concatenate(collected_data)
                    logger.info(f"合并后的数据shape: {all_data.shape}")
                    
                    # 重塑数据为LSTM需要的格式 [batch_size, sequence_length, features]
                    # 使用较小的序列长度，每10个数据点作为一个训练样本
                    sequence_length = 10
                    
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
                    train_loader = DataLoader(dataset, batch_size=32, shuffle=True)
                    test_loader = DataLoader(dataset, batch_size=32, shuffle=False)
                    
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
                        epochs=50,  # 适当的训练轮数
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
                    total_verification_count = state.admin_config['total_verification_count']
                    for i in range(total_verification_count):
                        # 生成新的验证数据
                        verify_ecg_data, _ = generate_ecg_ppg_data(num_samples=10, base_heart_rate=70 + random.uniform(-5, 5))
                        
                        # 重塑为LSTM需要的格式 [1, sequence_length, 1]
                        verify_ecg_data = verify_ecg_data.reshape(1, 10, 1)
                        
                        # 使用模型进行验证
                        model.eval()
                        with torch.no_grad():
                            device = next(model.parameters()).device
                            verify_tensor = torch.FloatTensor(verify_ecg_data).to(device)
                            
                            # 使用模块化的身份验证函数
                            auth_result = authenticate_single_signal(
                                model=model,
                                input_signal=verify_tensor,
                                threshold=state.admin_config['model_threshold'],
                                signal_type='ecg',
                                device=device
                            )
                            confidence = auth_result['score']
                            authenticated = auth_result['authenticated']
                        
                        # 确定验证结果
                        success = authenticated
                        verification_details = {
                            'confidence': float(confidence),
                            'threshold': float(state.admin_config['model_threshold']),
                            'authenticated': success
                        }
                        
                        # 使用管理员配置的阈值
                        if auth_result['authenticated']:
                            with state.registration_lock:
                                state.current_registration_data[username]['verification_success'] += 1
                                verification_success += 1
                        
                        logger.info(f"验证 {i+1} 结果: 置信度 {confidence:.4f}")
                        
                        # 验证间隔
                        time.sleep(2)
                    
                    # 检查验证结果，使用管理员配置的最小成功次数
                    min_verification_success = state.admin_config['min_verification_success']
                    if verification_success >= min_verification_success:
                        # 更新注册状态
                        with state.registration_lock:
                            state.current_registration_data[username]['status'] = 'completed'
                            state.current_registration_data[username]['model_path'] = model_path
                        
                        # 保存用户到数据库
                        mongo.db.users.insert_one({
                            'username': username,
                            'model_path': model_path,
                            'created_at': datetime.now()
                        })
                        
                        logger.info(f"用户 {username} 注册成功")
                    else:
                        # 验证失败
                        with state.registration_lock:
                            state.current_registration_data[username]['status'] = 'failed'
                        
                        logger.warning(f"用户 {username} 验证失败")
                
                except Exception as e:
                    logger.error(f"模型训练/验证失败: {str(e)}")
                    with state.registration_lock:
                        state.current_registration_data[username]['status'] = 'error'
            else:
                # 如果系统不可用，使用模拟验证
                with state.registration_lock:
                    state.current_registration_data[username]['status'] = 'verifying'
                
                # 模拟验证
                verification_success = 0
                for i in range(3):
                    with state.registration_lock:
                        state.current_registration_data[username]['verification_count'] += 1
                        state.current_registration_data[username]['verification_success'] += 1
                        verification_success += 1
                    time.sleep(2)
                
                # 模拟模型文件
                model_filename = f"{username}_model.pth"
                model_path = os.path.join(models_dir, model_filename)
                with open(model_path, 'w') as f:
                    f.write("模拟模型文件")
                
                # 更新注册状态
                with state.registration_lock:
                    state.current_registration_data[username]['status'] = 'completed'
                    state.current_registration_data[username]['model_path'] = model_path
                
                # 保存用户到数据库
                mongo.db.users.insert_one({
                    'username': username,
                    'model_path': model_path,
                    'created_at': datetime.now()
                })
                
                logger.info(f"用户 {username} 注册成功 (模拟模式)")
        
        except Exception as e:
            logger.error(f"数据采集线程错误: {e}")
            with state.registration_lock:
                state.current_registration_data[username]['status'] = 'error'
    
    # 启动数据采集线程，传入设备信息而不是在线程中访问session
    threading.Thread(target=collect_data_thread, args=(username, device_info), daemon=True).start()
    
    return jsonify({'success': True, 'message': '开始数据采集'})
