"""
模型创建模块

提供创建和配置模型的函数
"""

import torch
import torch.nn as nn
from typing import Dict, Any, Optional, Tuple, Union

from ecgppg_system.models.bilstm import BiLSTMWithAttention
from ecgppg_system.utils.logger import logger
from ecgppg_system.devices.device_manager import EnvironmentManager

def create_model(input_size: int, hidden_size: int = 64, 
                num_layers: int = 2, output_size: int = 1) -> nn.Module:
    """
    创建模型实例
    
    Args:
        input_size: 输入特征维度
        hidden_size: 隐藏层大小
        num_layers: LSTM层数
        output_size: 输出维度
        
    Returns:
        模型实例
    """
    try:
        # 创建模型实例
        model = BiLSTMWithAttention(
            input_size=input_size, 
            hidden_size=hidden_size, 
            num_layers=num_layers, 
            output_size=output_size
        )
        logger.info(f"创建BiLSTM模型，输入特征维度: {input_size}")
        return model
    except Exception as e:
        logger.error(f"创建模型失败: {str(e)}")
        raise

def configure_model_architecture(base_model: nn.Module, config: Dict[str, Any]) -> nn.Module:
    """
    配置模型架构细节
    
    Args:
        base_model: 基础模型实例
        config: 配置参数字典
        
    Returns:
        配置后的模型
    """
    # 这个函数目前只是占位符，可以在未来实现更多复杂的架构配置
    # 例如：调整dropout率、激活函数、添加/移除层等
    return base_model

def setup_model_device(model: nn.Module, device: Optional[torch.device] = None) -> Tuple[nn.Module, torch.device]:
    """
    将模型移动到指定设备（CPU/GPU）
    
    Args:
        model: 模型实例
        device: 设备，如果为None则自动选择最优设备
        
    Returns:
        (model, device): 移动后的模型和设备
    """
    # 如果没有指定设备，则自动选择
    if device is None:
        device = EnvironmentManager.get_optimal_device()
        logger.info(f"自动选择设备: {device}")
    
    # 尝试将模型移动到设备
    try:
        model.to(device)
        logger.info(f"模型已移至设备: {device}")
    except Exception as e:
        logger.error(f"将模型移至{device}失败: {str(e)}")
        if str(device).startswith('cuda'):
            logger.info("尝试回退到CPU...")
            device = torch.device('cpu')
            model.to(device)
            logger.info(f"模型已回退到CPU")
    
    return model, device

def handle_cuda_memory_error(model: nn.Module, 
                            function_to_run: callable, 
                            *args, **kwargs) -> Any:
    """
    处理CUDA内存错误，回退到CPU并重试
    
    Args:
        model: 模型实例
        function_to_run: 要执行的函数
        *args, **kwargs: 函数参数
        
    Returns:
        函数执行结果
    """
    try:
        # 尝试在当前设备上运行函数
        return function_to_run(*args, **kwargs)
    except RuntimeError as e:
        # 检查是否是CUDA内存错误
        if "CUDA out of memory" in str(e):
            logger.error(f"CUDA内存不足: {str(e)}")
            logger.info("尝试在CPU上重新运行...")
            
            # 移动模型到CPU
            current_device = next(model.parameters()).device
            model.to('cpu')
            
            # 更新参数中的设备相关参数（如果有）
            updated_kwargs = kwargs.copy()
            if 'device' in updated_kwargs:
                updated_kwargs['device'] = torch.device('cpu')
            
            # 在CPU上重新运行函数
            result = function_to_run(*args, **updated_kwargs)
            
            # 恢复模型到原始设备（如果可能）
            try:
                model.to(current_device)
            except:
                pass
                
            return result
        else:
            # 非内存错误，重新抛出
            raise 