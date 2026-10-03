"""
全局设置模块
提供系统固定的全局参数和配置
动态配置请查看dynamic_config.yaml
"""

import os
from pathlib import Path
import logging

#===============================
# 基础路径设置
#===============================
# 获取项目根目录
BASE_DIR = Path(__file__).parent.parent.parent

# 模型目录
MODEL_DIR = os.path.join(BASE_DIR, 'models')
os.makedirs(MODEL_DIR, exist_ok=True)

# 输出目录
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 数据目录
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# 配置文件路径
CONFIG_FILE = os.path.join(Path(__file__).parent, 'dynamic_config.yaml')

#===============================
# 环境配置
#===============================
# 根据环境变量加载不同的设置
ENV = os.environ.get('ENV', 'development')
DEBUG = True

#===============================
# 日志配置
#===============================
LOG_LEVEL = logging.INFO
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

#===============================
# BLE UUID 配置
#===============================
# BLE UUID通常是固定的标准
HEART_RATE_SERVICE = "0000180d-0000-1000-8000-00805f9b34fb"
HEART_RATE_CHARACTERISTIC = "00002a37-0000-1000-8000-00805f9b34fb"

# ECG相关UUID
BLE_ECG_SERVICE_UUID = "00002760-08c2-11e1-9073-0e8ac72e1011"
BLE_ECG_DATA_CHAR_UUID = "00002760-08c2-11e1-9073-0e8ac72e1012"
BLE_ECG_CONTROL_CHAR_UUID = "00002760-08c2-11e1-9073-0e8ac72e1013"

# PPG相关UUID
BLE_PPG_SERVICE_UUID = "00001822-0000-1000-8000-00805f9b34fb"
BLE_PPG_DATA_CHAR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
BLE_PPG_CONTROL_CHAR_UUID = "00002a39-0000-1000-8000-00805f9b34fb"

#===============================
# 串口设备配置
#===============================
# 串口配置
SERIAL_BAUDRATE = 115200
SERIAL_TIMEOUT = 1.0
SERIAL_DATA_FRAME_HEAD = 0xFA
SERIAL_DATA_FRAME_TAIL = 0xAF
SERIAL_DATA_FRAME_LENGTH = 19  # 帧长度（字节）

#===============================
# 模型参数
#===============================
# 通用参数
RANDOM_SEED = 42  # 随机种子

#===============================
# 信号处理参数 (从AuthConfig移植)
#===============================
SAMPLING_RATE = 100   # 采样率

#===============================
# 环境特定设置
#===============================
if ENV == 'production':
    # 生产环境设置
    DEBUG = False
    LOG_LEVEL = logging.WARNING
elif ENV == 'testing':
    # 测试环境设置
    DEBUG = True
    LOG_LEVEL = logging.DEBUG
    # 测试环境其他配置
else:
    # 开发环境设置
    DEBUG = True
    LOG_LEVEL = logging.DEBUG

#===============================
# 导出所有配置项
#===============================
__all__ = [name for name in dir() if name.isupper()] 