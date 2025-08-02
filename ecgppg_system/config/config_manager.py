"""
配置管理器模块
处理配置文件的读写操作
"""

import os
import yaml
from typing import Dict, Any, Optional
import logging
from pathlib import Path

from . import settings

logger = logging.getLogger(__name__)

class ConfigManager:
    """
    配置管理器类
    处理配置文件的读写操作
    """
    
    _instance = None
    _config = None
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._load_config()
        return cls._instance
    
    def _load_config(self):
        """从配置文件加载配置"""
        try:
            with open(settings.CONFIG_FILE, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f)
                logger.info(f"已从{settings.CONFIG_FILE}加载配置")
        except FileNotFoundError:
            logger.warning(f"配置文件{settings.CONFIG_FILE}不存在，使用默认配置")
            self._config = self._get_default_config()
            self._save_config()  # 保存默认配置到文件
        except yaml.YAMLError as e:
            logger.error(f"解析配置文件失败: {e}")
            self._config = self._get_default_config()
    
    def _save_config(self):
        """将配置保存到文件"""
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(settings.CONFIG_FILE), exist_ok=True)
            
            with open(settings.CONFIG_FILE, 'w', encoding='utf-8') as f:
                yaml.dump(self._config, f, default_flow_style=False, allow_unicode=True)
            logger.info(f"已将配置保存到{settings.CONFIG_FILE}")
            return True
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            return False
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            'model': {
                'threshold': 0.8,
                'alpha': 0.6,
                'beta': 0.4,
            },
            'verification': {
                'time': 30,
                'min_success': 2,
                'total_count': 3,
            },
            'device': {
                'connection_timeout': 10.0,
                'scan_timeout': 5.0,
            },
            'training': {
                'epochs': 50,
                'learning_rate': 0.001,
                'batch_size': 32,
            },
            'system': {
                'use_cuda': True,
                'cuda_device': 0,
            }
        }
    
    def get_config(self) -> Dict[str, Any]:
        """获取全部配置"""
        return self._config
    
    def get(self, section: str, key: str, default: Any = None) -> Any:
        """
        获取配置项
        
        参数:
            section: 配置区块
            key: 配置键
            default: 默认值
            
        返回:
            配置值或默认值
        """
        try:
            return self._config[section][key]
        except (KeyError, TypeError):
            return default
    
    def set(self, section: str, key: str, value: Any) -> bool:
        """
        设置配置项
        
        参数:
            section: 配置区块
            key: 配置键
            value: 配置值
            
        返回:
            是否成功
        """
        try:
            if section not in self._config:
                self._config[section] = {}
            self._config[section][key] = value
            return self._save_config()
        except Exception as e:
            logger.error(f"设置配置项失败: {e}")
            return False
    
    def update_section(self, section: str, values: Dict[str, Any]) -> bool:
        """
        更新配置区块
        
        参数:
            section: 配置区块
            values: 配置值字典
            
        返回:
            是否成功
        """
        try:
            if section not in self._config:
                self._config[section] = {}
            self._config[section].update(values)
            return self._save_config()
        except Exception as e:
            logger.error(f"更新配置区块失败: {e}")
            return False
    
    def reload(self) -> bool:
        """重新加载配置"""
        try:
            self._load_config()
            return True
        except Exception as e:
            logger.error(f"重新加载配置失败: {e}")
            return False

# 创建全局配置实例
config = ConfigManager()

# 导出所有符号
__all__ = ['ConfigManager', 'config'] 