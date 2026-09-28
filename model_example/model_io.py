"""
模型IO模块

提供模型加载和保存的功能
"""

import os
import torch
import torch.nn as nn
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, Union, List

from ecgppg_system.models.bilstm import BiLSTMWithAttention
from ecgppg_system.utils.logger import logger
from ecgppg_system.config import settings
from ecgppg_system.devices.device_manager import EnvironmentManager

def save_model(model: nn.Module, save_path: str, metadata: Dict[str, Any] = None) -> bool:
    """
    保存模型和相关元数据
    
    Args:
        model: 要保存的模型
        save_path: 保存路径
        metadata: 要保存的元数据
        
    Returns:
        bool: 是否成功保存
    """
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        
        # 准备保存数据
        save_dict = {
            'model_state_dict': model.state_dict(),
            'save_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'metadata': metadata or {}
        }
        
        # 确保元数据中包含input_size
        if metadata and 'input_size' in metadata:
            pass
        elif hasattr(model, 'input_size'):
            save_dict['metadata']['input_size'] = model.input_size
        elif isinstance(model, BiLSTMWithAttention) and hasattr(model, 'lstm') and hasattr(model.lstm, 'input_size'):
            save_dict['metadata']['input_size'] = model.lstm.input_size
            
        # 保存模型
        torch.save(save_dict, save_path)
        logger.info(f"模型已保存到: {save_path}")
        return True
    except Exception as e:
        logger.error(f"保存模型失败: {str(e)}")
        return False

def load_model(model_path: str, device: torch.device = None) -> Tuple[nn.Module, Dict[str, Any]]:
    """
    加载模型和相关元数据
    
    Args:
        model_path: 模型路径
        device: 计算设备，如果为None则使用最优设备
        
    Returns:
        tuple: (model, metadata)
    """
    try:
        # 确定设备
        if device is None:
            device = EnvironmentManager.get_optimal_device()
        
        logger.info(f"尝试加载模型: {model_path}")
        
        # 加载检查点
        # 显式声明 weights_only=True：只反序列化张量与基础类型，不执行任意 pickle 对象。
        # torch>=2.6 已默认如此，这里写出来是为了锁定行为 ——
        # model_path 来自数据库，若将来迁移模型库或降级依赖导致默认值变化，
        # 就会变成反序列化代码执行的风险。
        checkpoint = torch.load(model_path, map_location=device, weights_only=True)
        
        # 提取元数据
        metadata = {}
        
        # 提取元数据
        metadata = checkpoint.get('metadata', {})
        state_dict = checkpoint['model_state_dict']    

        # 获取input_size
        input_size = metadata.get('input_size')
        
        # 创建模型
        model = BiLSTMWithAttention(
            input_size=input_size, 
            hidden_size=64, 
            num_layers=2, 
            output_size=1
        )
        
        # 加载权重
        model.load_state_dict(state_dict)
        
        # 移动模型到指定设备
        model.to(device)
        
        logger.info(f"成功加载模型: input_size={input_size}")
        return model, metadata
        
    except Exception as e:
        logger.error(f"加载模型失败: {str(e)}")
        return None, None

def extract_model_metadata(checkpoint: Dict[str, Any]) -> Dict[str, Any]:
    """
    提取模型元数据
    
    Args:
        checkpoint: 模型检查点字典
        
    Returns:
        dict: 元数据字典
    """
    metadata = {}
    
    # 检查是否是新格式（带元数据的字典）
    if isinstance(checkpoint, dict):
        # 直接提取元数据
        if 'metadata' in checkpoint:
            metadata = checkpoint['metadata']
        
        # 提取保存时间
        if 'save_time' in checkpoint:
            metadata['save_time'] = checkpoint['save_time']
            
    return metadata

def verify_model_compatibility(model: nn.Module, 
                              expected_input_size: int = None,
                              expected_output_size: int = None) -> Tuple[bool, str]:
    """
    验证模型与当前环境的兼容性
    
    Args:
        model: 模型实例
        expected_input_size: 期望的输入大小
        expected_output_size: 期望的输出大小
        
    Returns:
        Tuple[bool, str]: (是否兼容, 不兼容原因)
    """
    # 验证输入大小
    actual_input_size = None
    if hasattr(model, 'input_size'):
        actual_input_size = model.input_size
    elif hasattr(model, 'lstm') and hasattr(model.lstm, 'input_size'):
        actual_input_size = model.lstm.input_size
    
    if expected_input_size is not None and actual_input_size != expected_input_size:
        return False, f"输入大小不匹配: 期望 {expected_input_size}, 实际 {actual_input_size}"
    
    # 验证输出大小
    actual_output_size = None
    if hasattr(model, 'output_size'):
        actual_output_size = model.output_size
    elif hasattr(model, 'fc') and hasattr(model.fc, 'out_features'):
        actual_output_size = model.fc.out_features
    
    if expected_output_size is not None and actual_output_size != expected_output_size:
        return False, f"输出大小不匹配: 期望 {expected_output_size}, 实际 {actual_output_size}"
    
    return True, ""

def get_automatic_save_path(signal_type: str) -> str:
    """
    根据信号类型和当前时间自动生成保存路径
    
    Args:
        signal_type: 信号类型
        
    Returns:
        str: 保存路径
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{signal_type}_{timestamp}_model.pth"
    return os.path.join(settings.MODEL_DIR, filename) 