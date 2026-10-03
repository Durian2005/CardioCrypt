#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
文件工具模块
提供文件操作相关的工具函数
"""

import os
import glob
import json
import csv
import pandas as pd
from datetime import datetime
from ..utils.logger import logger

def ensure_dir(directory):
    """
    确保目录存在，如果不存在则创建
    
    参数:
        directory (str): 目录路径
    """
    if not os.path.exists(directory):
        os.makedirs(directory)
        logger.info(f"创建目录: {directory}")
    return directory

def get_file_list(directory, pattern="*.*"):
    """
    获取指定目录下符合模式的文件列表
    
    参数:
        directory (str): 目录路径
        pattern (str): 文件模式，例如 '*.csv'
        
    返回:
        list: 文件路径列表
    """
    if not os.path.exists(directory):
        logger.warning(f"目录不存在: {directory}")
        return []
    
    file_pattern = os.path.join(directory, pattern)
    files = glob.glob(file_pattern)
    return sorted(files)

def save_json(data, filepath, indent=4):
    """
    将数据保存为JSON文件
    
    参数:
        data: 要保存的数据
        filepath (str): 文件路径
        indent (int): 缩进空格数
        
    返回:
        bool: 是否成功保存
    """
    try:
        ensure_dir(os.path.dirname(filepath))
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        logger.info(f"已保存JSON文件: {filepath}")
        return True
    except Exception as e:
        logger.error(f"保存JSON文件失败: {filepath}, 错误: {str(e)}")
        return False

def load_json(filepath, default=None):
    """
    加载JSON文件
    
    参数:
        filepath (str): 文件路径
        default: 当文件不存在或加载失败时返回的默认值
        
    返回:
        dict/list: 加载的数据或默认值
    """
    if not os.path.exists(filepath):
        logger.warning(f"JSON文件不存在: {filepath}")
        return default
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"已加载JSON文件: {filepath}")
        return data
    except Exception as e:
        logger.error(f"加载JSON文件失败: {filepath}, 错误: {str(e)}")
        return default

def save_csv(data, filepath, headers=None):
    """
    将数据保存为CSV文件
    
    参数:
        data (list): 要保存的数据行列表
        filepath (str): 文件路径
        headers (list): CSV表头
        
    返回:
        bool: 是否成功保存
    """
    try:
        ensure_dir(os.path.dirname(filepath))
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if headers:
                writer.writerow(headers)
            writer.writerows(data)
        logger.info(f"已保存CSV文件: {filepath}")
        return True
    except Exception as e:
        logger.error(f"保存CSV文件失败: {filepath}, 错误: {str(e)}")
        return False

def load_csv(filepath, has_header=True):
    """
    加载CSV文件
    
    参数:
        filepath (str): 文件路径
        has_header (bool): 是否有表头
        
    返回:
        tuple: (headers, data) 如果有表头，否则 (None, data)
    """
    if not os.path.exists(filepath):
        logger.warning(f"CSV文件不存在: {filepath}")
        return (None, []) if has_header else ([], [])
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            data = list(reader)
        
        if has_header and data:
            headers = data[0]
            data = data[1:]
            logger.info(f"已加载CSV文件: {filepath}, {len(data)}行")
            return headers, data
        else:
            logger.info(f"已加载CSV文件: {filepath}, {len(data)}行")
            return None, data
    except Exception as e:
        logger.error(f"加载CSV文件失败: {filepath}, 错误: {str(e)}")
        return (None, []) if has_header else ([], [])

def load_dataframe(filepath, **kwargs):
    """
    加载数据到DataFrame
    
    参数:
        filepath (str): 文件路径
        **kwargs: 传递给 pandas.read_csv 或 pandas.read_excel 的参数
        
    返回:
        pandas.DataFrame: 加载的数据
    """
    if not os.path.exists(filepath):
        logger.warning(f"文件不存在: {filepath}")
        return pd.DataFrame()
    
    try:
        ext = os.path.splitext(filepath)[1].lower()
        
        if ext == '.csv':
            df = pd.read_csv(filepath, **kwargs)
        elif ext in ['.xls', '.xlsx']:
            df = pd.read_excel(filepath, **kwargs)
        else:
            logger.error(f"不支持的文件格式: {ext}")
            return pd.DataFrame()
        
        logger.info(f"已加载数据文件: {filepath}, 形状: {df.shape}")
        return df
    except Exception as e:
        logger.error(f"加载数据文件失败: {filepath}, 错误: {str(e)}")
        return pd.DataFrame()

def generate_timestamp_filename(base_name, extension, directory=None):
    """
    生成带时间戳的文件名
    
    参数:
        base_name (str): 基础名称
        extension (str): 文件扩展名（不含点）
        directory (str): 目录路径
        
    返回:
        str: 完整的文件路径
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{base_name}_{timestamp}.{extension}"
    
    if directory:
        ensure_dir(directory)
        return os.path.join(directory, filename)
    else:
        return filename

def get_chinese_fonts():
    """
    获取系统中可用的中文字体列表
    此函数作为桥接，调用font_utils中的相关功能
    
    返回:
        list: 中文字体名称列表
    """
    try:
        # 推迟导入以避免循环引用
        from .font_utils import find_available_chinese_fonts
        return find_available_chinese_fonts()
    except Exception as e:
        logger.error(f"获取中文字体列表失败: {str(e)}")
        return [] 