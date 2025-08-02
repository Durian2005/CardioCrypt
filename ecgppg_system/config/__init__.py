"""
配置模块
提供系统配置参数和设置管理
"""

from . import settings
from .config_manager import config, ConfigManager

__all__ = ['settings', 'config', 'ConfigManager'] 