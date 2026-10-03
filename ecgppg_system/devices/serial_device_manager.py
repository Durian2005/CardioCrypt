#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
串口设备管理器模块
提供串口设备的发现、连接和数据解析功能
"""

import time
import serial
import serial.tools.list_ports
import threading
import logging
from typing import List, Dict, Callable, Any

logger = logging.getLogger(__name__)

class SerialDeviceManager:
    """串口设备管理器，处理CH340串口设备的连接和数据解析"""
    
    def __init__(self):
        """初始化串口设备管理器"""
        self.serial_port = None
        self.is_connected = False
        self.is_reading = False
        self.read_thread = None
        self.callback = None
        self.buffer = bytearray()
        self.heart_rate = 0
        self.spo2 = 0
        self.last_update_time = 0
        
    def discover_devices(self) -> List[Dict[str, str]]:
        """
        发现可用的串口设备
        
        返回:
            List[Dict[str, str]]: 串口设备列表，每个设备包含name和port信息
        """
        devices = []
        ports = serial.tools.list_ports.comports()
        
        for port in ports:
            # 查找包含CH340的设备
            if 'CH340' in port.description:
                devices.append({
                    'name': port.description,
                    'port': port.device,
                    'type': 'serial',
                    'hwid': port.hwid
                })
            else:
                # 也列出其他串口设备，但标记为可能不兼容
                devices.append({
                    'name': port.description,
                    'port': port.device,
                    'type': 'serial',
                    'hwid': port.hwid,
                    'may_not_compatible': True
                })
        
        logger.info(f"发现 {len(devices)} 个串口设备")
        return devices
    
    def connect(self, port: str, baudrate: int = 115200, timeout: float = 1.0) -> bool:
        """
        连接到串口设备
        
        参数:
            port (str): 串口设备端口名
            baudrate (int): 波特率，默认115200
            timeout (float): 超时时间，默认1秒
            
        返回:
            bool: 连接是否成功
        """
        try:
            if self.is_connected and self.serial_port:
                self.disconnect()
                
            self.serial_port = serial.Serial(port, baudrate, timeout=timeout)
            self.is_connected = True
            logger.info(f"成功连接到串口设备: {port}, 波特率: {baudrate}")
            return True
        except Exception as e:
            logger.error(f"连接串口设备失败: {str(e)}")
            self.is_connected = False
            return False
    
    def disconnect(self) -> bool:
        """
        断开与串口设备的连接
        
        返回:
            bool: 断开连接是否成功
        """
        try:
            self.stop_reading()
            
            if self.serial_port:
                self.serial_port.close()
                self.serial_port = None
            
            self.is_connected = False
            logger.info("已断开与串口设备的连接")
            return True
        except Exception as e:
            logger.error(f"断开串口设备连接失败: {str(e)}")
            return False
    
    def start_reading(self, callback: Callable[[Dict[str, Any]], None] = None) -> bool:
        """
        开始读取串口数据
        
        参数:
            callback (Callable): 数据处理回调函数
            
        返回:
            bool: 是否成功启动数据读取
        """
        if not self.is_connected or not self.serial_port:
            logger.error("未连接到串口设备，无法开始读取数据")
            return False
        
        if self.is_reading:
            logger.warning("已经在读取串口数据")
            return True
        
        self.callback = callback
        self.is_reading = True
        self.buffer.clear()
        
        # 启动读取线程
        self.read_thread = threading.Thread(target=self._read_data_loop, daemon=True)
        self.read_thread.start()
        
        logger.info("已启动串口数据读取")
        return True
    
    def stop_reading(self) -> bool:
        """
        停止读取串口数据
        
        返回:
            bool: 是否成功停止数据读取
        """
        if not self.is_reading:
            return True
            
        self.is_reading = False
        
        if self.read_thread:
            try:
                # 等待线程结束，但最多等待1秒
                self.read_thread.join(timeout=1)
            except Exception as e:
                logger.error(f"停止读取线程时出错: {str(e)}")
        
        logger.info("已停止串口数据读取")
        return True
    
    def _read_data_loop(self):
        """串口数据读取循环"""
        try:
            while self.is_reading and self.serial_port and self.serial_port.is_open:
                try:
                    # 读取数据
                    if self.serial_port.in_waiting > 0:
                        data = self.serial_port.read(self.serial_port.in_waiting)
                        if data:
                            # 将数据添加到缓冲区
                            self.buffer.extend(data)
                            
                            # 解析数据包
                            self._parse_buffer()
                    
                    # 短暂休眠，避免CPU占用过高
                    time.sleep(0.01)
                except Exception as e:
                    logger.error(f"读取串口数据时出错: {str(e)}")
                    time.sleep(0.5)  # 错误后等待一段时间再继续
        except Exception as e:
            logger.error(f"串口读取循环异常: {str(e)}")
        finally:
            logger.info("串口数据读取循环已结束")
    
    def _parse_buffer(self):
        """解析数据缓冲区，提取数据包"""
        # 循环查找完整的数据包（以0xFA开头，0xAF结尾）
        while len(self.buffer) >= 19:  # 数据包长度为19字节
            # 查找帧头
            start_idx = self.buffer.find(b'\xFA')
            if start_idx == -1:
                # 没有找到帧头，清空缓冲区
                self.buffer.clear()
                break
            
            # 如果帧头不在开始位置，移除前面的字节
            if start_idx > 0:
                self.buffer = self.buffer[start_idx:]
                continue
            
            # 确保有足够的字节可以检查完整数据包
            if len(self.buffer) < 19:
                break
                
            # 检查帧尾
            if self.buffer[18] != 0xAF:
                # 帧尾不匹配，移除帧头继续查找
                self.buffer = self.buffer[1:]
                continue
            
            # 提取完整数据包
            packet = self.buffer[:19]
            
            # 校验和检查
            checksum = sum(packet[1:17]) & 0xFF  # 排除帧头、校验和和帧尾
            if packet[17] != checksum:
                logger.warning(f"数据包校验和错误: 计算值 {checksum}, 收到值 {packet[17]}")
                self.buffer = self.buffer[1:]
                continue
            
            # 解析数据包
            self._process_packet(packet)
            
            # 移除已处理的数据包
            self.buffer = self.buffer[19:]
    
    def _process_packet(self, packet: bytearray):
        """
        处理解析出的数据包
        
        参数:
            packet (bytearray): 完整的数据包
        """
        try:
            # GSR数据（16位）
            gsr_high = packet[1]
            gsr_low = packet[2]
            gsr_value = (gsr_high << 8) | gsr_low
            
            # 加速度数据（16位，有符号）
            accel_x = self._combine_bytes_signed(packet[3], packet[4])
            accel_y = self._combine_bytes_signed(packet[5], packet[6])
            accel_z = self._combine_bytes_signed(packet[7], packet[8])
            
            # 角速度数据（16位，有符号）
            gyro_x = self._combine_bytes_signed(packet[9], packet[10])
            gyro_y = self._combine_bytes_signed(packet[11], packet[12])
            gyro_z = self._combine_bytes_signed(packet[13], packet[14])
            
            # 心率和血氧（每分钟更新一次）
            heart_rate = packet[15]
            spo2 = packet[16]
            
            # 只有当心率不为0时才更新
            if heart_rate > 0:
                self.heart_rate = heart_rate
                self.last_update_time = time.time()
                
            if spo2 > 0:
                self.spo2 = spo2
            
            # 计算实际物理值
            accel_g_x = (accel_x / 32768) * 2
            accel_g_y = (accel_y / 32768) * 2
            accel_g_z = (accel_z / 32768) * 2
            
            gyro_dps_x = (gyro_x / 32768) * 250
            gyro_dps_y = (gyro_y / 32768) * 250
            gyro_dps_z = (gyro_z / 32768) * 250
            
            # 创建数据对象
            data = {
                'heart_rate': self.heart_rate,
                'spo2': self.spo2,
                'gsr': gsr_value,
                'accel': {
                    'x': accel_g_x,
                    'y': accel_g_y,
                    'z': accel_g_z
                },
                'gyro': {
                    'x': gyro_dps_x,
                    'y': gyro_dps_y,
                    'z': gyro_dps_z
                },
                'timestamp': time.time()
            }
            
            # 调用回调函数
            if self.callback:
                self.callback(data)
                
        except Exception as e:
            logger.error(f"处理数据包时出错: {str(e)}")
    
    def _combine_bytes_signed(self, high_byte: int, low_byte: int) -> int:
        """
        将高字节和低字节组合为有符号16位整数
        
        参数:
            high_byte (int): 高字节
            low_byte (int): 低字节
            
        返回:
            int: 有符号16位整数
        """
        # 组合为16位无符号整数
        value = (high_byte << 8) | low_byte
        
        # 转换为有符号整数（二进制补码）
        if value & 0x8000:
            value = value - 0x10000
            
        return value
    
    def get_heart_rate(self) -> int:
        """
        获取最新心率值
        
        返回:
            int: 心率值
        """
        return self.heart_rate
    
    def get_spo2(self) -> int:
        """
        获取最新血氧值
        
        返回:
            int: 血氧值
        """
        return self.spo2
        
    def is_data_fresh(self, max_age_seconds: float = 60.0) -> bool:
        """
        检查数据是否是最新的
        
        参数:
            max_age_seconds (float): 数据最大年龄（秒）
            
        返回:
            bool: 数据是否是最新的
        """
        if self.heart_rate == 0:
            return False
            
        current_time = time.time()
        age = current_time - self.last_update_time
        
        return age <= max_age_seconds

# 创建全局实例
serial_manager = SerialDeviceManager()

# 导出变量，用于标识串口设备是否可用
SERIAL_DEVICE_AVAILABLE = True 