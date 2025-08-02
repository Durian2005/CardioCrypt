"""
ECG/PPG信号处理系统
用于心电和光电容积脉搏信号的采集、处理和身份认证
"""

# 导入版本信息
try:
    from .config.settings import VERSION
except ImportError:
    VERSION = "未知"

__version__ = VERSION 