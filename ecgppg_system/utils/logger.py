#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
日志模块
提供统一的日志配置和记录功能
"""

import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
import sys

# 全局日志记录器
logger = logging.getLogger('ecgppg_system')

def setup_logger(name=None, level=logging.INFO, log_file=None):
    """
    配置并返回日志记录器
    
    参数:
        name (str): 日志记录器名称，默认为'ecgppg_system'的子记录器
        level (int): 日志级别，默认为INFO
        log_file (str): 日志文件路径，默认为None，表示不输出到文件
        
    返回:
        logging.Logger: 配置好的日志记录器
    """
    # 使用提供的名称或默认名称
    if name is None:
        _logger = logger
    else:
        _logger = logger.getChild(name)
    
    # 设置日志级别
    _logger.setLevel(level)
    
    # 检查记录器是否已经有处理器
    if not _logger.handlers:
        # 创建控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)

        # 设置格式
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        
        # 添加处理器到记录器
        _logger.addHandler(console_handler)
        
        # 如果提供了日志文件，添加文件处理器
        if log_file:
            # 确保日志目录存在
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir)
                
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            _logger.addHandler(file_handler)
    
    return _logger

# 配置应用默认日志
def configure_default_logger():
    """配置默认日志记录器"""
    global logger
    
    # 创建logs目录
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    logs_dir = os.path.join(base_dir, 'logs')
    os.makedirs(logs_dir, exist_ok=True)

    # 生成日志文件名
    today = datetime.now().strftime('%Y-%m-%d')
    log_file = os.path.join(logs_dir, f'ecgppg_{today}.log')
    
    # 配置根日志记录器
    logger = setup_logger(level=logging.INFO, log_file=log_file)
    return logger, today, log_file

# 自动配置默认日志
logger, today, log_file = configure_default_logger()

def get_module_logger(module_name):
    """
    获取指定模块的日志记录器
    
    参数:
        module_name (str): 模块名称
        
    返回:
        logging.Logger: 日志记录器实例
    """
    module_logger = logging.getLogger(f'ecgppg.{module_name}')
    
    # 确保模块日志器也使用正确的编码处理
    if not module_logger.handlers:
        # 创建formatter变量
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 添加控制台处理器
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        module_logger.addHandler(console)
        
        # 添加文件处理器
        file_handler_copy = RotatingFileHandler(
            log_file, 
            maxBytes=10*1024*1024,
            backupCount=3,
            encoding='utf-8'
        )
        file_handler_copy.setFormatter(formatter)
        module_logger.addHandler(file_handler_copy)
    
    return module_logger

# 配置Python警告转为日志
def warning_to_logger(message, category, filename, lineno, *args, **kwargs):
    """
    将Python警告转换为日志记录
    
    参数:
        message: 警告消息
        category: 警告类别
        filename: 文件名
        lineno: 行号
    """
    module_path = filename
    if module_path.endswith('.py'):
        module_path = module_path[:-3]
    module_path = module_path.replace('/', '.').replace('\\', '.')
    
    module_logger = get_module_logger(module_path)
    try:
        # 尝试以字符串形式记录警告
        warning_msg = f"{category.__name__}: {str(message)}"
        module_logger.warning(warning_msg)
    except Exception as e:
        # 如果有任何编码问题，使用简单的消息
        module_logger.warning(f"系统警告: {category.__name__}")

    
# 设置警告过滤器
import warnings
warnings.showwarning = warning_to_logger

# 记录启动信息
logger.info("=" * 50)
logger.info("ECG/PPG系统日志启动")
logger.info(f"日期: {today}")
logger.info(f"日志文件: {log_file}")
logger.info("=" * 50)

# 导出
__all__ = ['logger', 'get_module_logger'] 