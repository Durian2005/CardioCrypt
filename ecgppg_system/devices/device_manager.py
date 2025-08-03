#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
设备和环境检查模块
提供系统环境检查、设备检测和管理功能
"""

import os
import torch
import platform
import psutil
import logging
from ..config import settings
from ..config import config as dynamic_config

# 增加引用串口设备管理器
try:
    from .serial_device_manager import serial_manager
    SERIAL_DEVICE_AVAILABLE = True
except ImportError:
    SERIAL_DEVICE_AVAILABLE = False

logger = logging.getLogger(__name__)

class EnvironmentManager:
    """环境和设备管理类，提供系统环境检查和设备管理功能"""
    
    @staticmethod
    def check_environment():
        """
        检查运行环境
        
        返回:
            dict: 包含环境信息的字典
        """
        env_info = {}
        
        # 检查PyTorch可用性和版本
        env_info['pytorch_version'] = torch.__version__
        env_info['cuda_available'] = torch.cuda.is_available()
        
        if torch.cuda.is_available():
            env_info['cuda_version'] = torch.version.cuda
            env_info['gpu_model'] = torch.cuda.get_device_name(0)
            env_info['gpu_count'] = torch.cuda.device_count()
            env_info['gpu_memory'] = []
            for i in range(torch.cuda.device_count()):
                gpu_memory = torch.cuda.get_device_properties(i).total_memory / (1024**3)  # 转换为GB
                env_info['gpu_memory'].append(f"{gpu_memory:.2f} GB")
        
        # 检查操作系统信息
        env_info['os_name'] = platform.system()
        env_info['os_version'] = platform.version()
        env_info['os_release'] = platform.release()
        
        # 检查CPU信息
        env_info['cpu_count'] = psutil.cpu_count(logical=False)
        env_info['cpu_logical_count'] = psutil.cpu_count(logical=True)
        
        # 检查内存信息
        memory = psutil.virtual_memory()
        env_info['total_memory'] = f"{memory.total / (1024**3):.2f} GB"
        env_info['available_memory'] = f"{memory.available / (1024**3):.2f} GB"
        
        # 检查目录
        required_dirs = [
            settings.MODEL_DIR,
            settings.OUTPUT_DIR
        ]
        
        env_info['directories'] = {}
        for directory in required_dirs:
            if not os.path.exists(directory):
                os.makedirs(directory)
                env_info['directories'][directory] = "已创建"
            else:
                env_info['directories'][directory] = "已存在"
        
        # 检查串口设备可用性
        env_info['serial_device_available'] = SERIAL_DEVICE_AVAILABLE
        
        return env_info
    
    @staticmethod
    def print_environment_info(env_info=None):
        """
        打印环境信息
        
        参数:
            env_info (dict, optional): 环境信息字典，如果为None则自动调用check_environment获取
        """
        if env_info is None:
            env_info = EnvironmentManager.check_environment()
        
        print("=" * 80)
        print(" " * 30 + "环境信息")
        print("=" * 80)
        
        # 打印PyTorch信息
        print(f"PyTorch版本: {env_info['pytorch_version']}")
        print(f"CUDA是否可用: {env_info['cuda_available']}")
        if env_info['cuda_available']:
            print(f"CUDA版本: {env_info['cuda_version']}")
            print(f"GPU型号: {env_info['gpu_model']}")
            print(f"GPU数量: {env_info['gpu_count']}")
            for i, mem in enumerate(env_info['gpu_memory']):
                print(f"GPU {i} 内存: {mem}")
        
        # 打印操作系统信息
        print(f"\n操作系统: {env_info['os_name']} {env_info['os_version']} ({env_info['os_release']})")
        
        # 打印CPU信息
        print(f"CPU核心数: {env_info['cpu_count']} (逻辑核心: {env_info['cpu_logical_count']})")
        
        # 打印内存信息
        print(f"总内存: {env_info['total_memory']}")
        print(f"可用内存: {env_info['available_memory']}")
        
        # 打印目录信息
        print("\n目录信息:")
        for directory, status in env_info['directories'].items():
            print(f"  {directory}: {status}")
        
        # 打印串口设备可用性
        print(f"\n串口设备支持: {'可用' if env_info.get('serial_device_available', False) else '不可用'}")
        
        print("-" * 80)
    
    @staticmethod
    def get_optimal_device():
        """
        获取最优的计算设备
        
        返回:
            torch.device: 最优的计算设备
        """
        if torch.cuda.is_available() and dynamic_config.get('system', 'use_cuda', True):
            # 如果有多个GPU，选择内存最大的那个
            if torch.cuda.device_count() > 1:
                max_memory = 0
                best_device_id = 0
                
                for i in range(torch.cuda.device_count()):
                    mem = torch.cuda.get_device_properties(i).total_memory
                    if mem > max_memory:
                        max_memory = mem
                        best_device_id = i
                
                return torch.device(f"cuda:{best_device_id}")
            else:
                return torch.device("cuda:0")
        else:
            return torch.device("cpu")
    
    @staticmethod
    def check_device_compatibility(model):
        """
        检查模型与当前设备的兼容性
        
        参数:
            model: PyTorch模型
            
        返回:
            tuple: (compatible, device, message)
        """
        try:
            # 获取模型当前设备
            model_device = next(model.parameters()).device
            
            # 检查CUDA可用性
            if model_device.type == 'cuda' and not torch.cuda.is_available():
                return False, torch.device('cpu'), f"模型在CUDA设备({model_device})上，但CUDA不可用。建议使用CPU。"
            
            # 如果模型在CPU上但CUDA可用
            if model_device.type == 'cpu' and torch.cuda.is_available() and dynamic_config.get('system', 'use_cuda', True):
                return True, torch.device('cuda:0'), "模型当前在CPU上，但CUDA可用。建议移至GPU以提高性能。"
            
            # 其他情况，模型设备兼容
            return True, model_device, f"模型设备({model_device})兼容。"
            
        except Exception as e:
            logger.exception("检查设备兼容性时出错")
            return False, torch.device('cpu'), f"检查设备兼容性时出错: {str(e)}"
    
    @staticmethod
    def discover_serial_devices():
        """
        发现可用的串口设备
        
        返回:
            List[Dict]: 串口设备列表，如果串口设备不可用则返回空列表
        """
        if not SERIAL_DEVICE_AVAILABLE:
            logger.warning("串口设备支持不可用，请安装pyserial库")
            return []
        
        try:
            devices = serial_manager.discover_devices()
            # 确保每个设备都有address字段，与前端期望一致
            for device in devices:
                if 'port' in device and 'address' not in device:
                    device['address'] = device['port']
            return devices
        except Exception as e:
            logger.error(f"发现串口设备时出错: {str(e)}")
            return []
    
    @staticmethod
    def connect_serial_device(port, baudrate=settings.SERIAL_BAUDRATE, timeout=settings.SERIAL_TIMEOUT):
        """
        连接到串口设备
        
        参数:
            port (str): 串口设备端口
            baudrate (int): 波特率，默认从设置中获取
            timeout (float): 超时时间，默认从设置中获取
            
        返回:
            bool: 连接是否成功
        """
        if not SERIAL_DEVICE_AVAILABLE:
            logger.error("串口设备支持不可用，请安装pyserial库")
            return False
        
        try:
            return serial_manager.connect(port, baudrate, timeout)
        except Exception as e:
            logger.error(f"连接串口设备时出错: {str(e)}")
            return False
    
    @staticmethod
    def disconnect_serial_device():
        """
        断开与串口设备的连接
        
        返回:
            bool: 是否成功断开连接
        """
        if not SERIAL_DEVICE_AVAILABLE:
            return False
        
        try:
            return serial_manager.disconnect()
        except Exception as e:
            logger.error(f"断开串口设备连接时出错: {str(e)}")
            return False
    
    @staticmethod
    def start_reading_serial_data(callback=None):
        """
        开始读取串口数据
        
        参数:
            callback (Callable): 数据处理回调函数
            
        返回:
            bool: 是否成功启动数据读取
        """
        if not SERIAL_DEVICE_AVAILABLE:
            logger.error("串口设备支持不可用，请安装pyserial库")
            return False
        
        try:
            return serial_manager.start_reading(callback)
        except Exception as e:
            logger.error(f"启动串口数据读取时出错: {str(e)}")
            return False
    
    @staticmethod
    def stop_reading_serial_data():
        """
        停止读取串口数据
        
        返回:
            bool: 是否成功停止数据读取
        """
        if not SERIAL_DEVICE_AVAILABLE:
            return False
        
        try:
            return serial_manager.stop_reading()
        except Exception as e:
            logger.error(f"停止串口数据读取时出错: {str(e)}")
            return False
    
    @staticmethod
    def get_serial_heart_rate():
        """
        获取串口设备的心率值
        
        返回:
            int: 心率值，如果串口设备不可用则返回0
        """
        if not SERIAL_DEVICE_AVAILABLE:
            return 0
        
        try:
            return serial_manager.get_heart_rate()
        except Exception as e:
            logger.error(f"获取串口设备心率值时出错: {str(e)}")
            return 0
    
    @staticmethod
    def is_serial_data_fresh(max_age_seconds=60.0):
        """
        检查串口设备数据是否是最新的
        
        参数:
            max_age_seconds (float): 数据最大年龄（秒）
            
        返回:
            bool: 数据是否是最新的
        """
        if not SERIAL_DEVICE_AVAILABLE:
            return False
        
        try:
            return serial_manager.is_data_fresh(max_age_seconds)
        except Exception as e:
            logger.error(f"检查串口设备数据新鲜度时出错: {str(e)}")
            return False
