"""
模型预测模块

提供模型预测相关的功能
"""

import torch
import torch.nn as nn
import numpy as np
from typing import Dict, Any, Optional, Tuple, List, Union

from ecgppg_system.utils.logger import logger

def predict_sequence(model: nn.Module, 
                    input_sequence: torch.Tensor, 
                    device: Optional[torch.device] = None) -> torch.Tensor:
    """
    使用模型预测序列
    
    Args:
        model: 训练好的模型
        input_sequence: 输入序列
        device: 计算设备
        
    Returns:
        torch.Tensor: 预测结果
    """
    model.eval()
    
    # 确保模型在正确的设备上
    if device is None:
        device = next(model.parameters()).device
    else:
        model = model.to(device)
    
    # 确保输入数据格式正确
    if isinstance(input_sequence, np.ndarray):
        input_sequence = torch.from_numpy(input_sequence).float()
    
    # 添加批次维度，如果需要的话
    if len(input_sequence.shape) == 2:  # [seq_len, features]
        input_sequence = input_sequence.unsqueeze(0)  # [1, seq_len, features]
    
    # 移动到设备
    input_sequence = input_sequence.to(device)
    
    # 进行预测
    with torch.no_grad():
        try:
            predictions = model(input_sequence)
            return predictions
        except Exception as e:
            logger.error(f"预测过程中出错: {str(e)}")
            # 尝试调整输入格式
            if len(input_sequence.shape) == 3:  # [batch, seq_len, features]
                try:
                    batch_size, seq_len, features = input_sequence.shape
                    # 尝试重新塑形为 [batch, features]
                    reshaped_input = input_sequence.reshape(batch_size, -1)
                    predictions = model(reshaped_input)
                    logger.info("通过重新整形输入成功预测")
                    return predictions
                except Exception as e2:
                    logger.error(f"重整形后预测仍然失败: {str(e2)}")
            
            raise RuntimeError(f"预测失败: {str(e)}")

def predict_future_values(model: nn.Module, 
                         initial_sequence: torch.Tensor, 
                         steps: int, 
                         device: Optional[torch.device] = None) -> np.ndarray:
    """
    预测未来多个步骤的值
    
    Args:
        model: 训练好的模型
        initial_sequence: 初始序列
        steps: 要预测的步数
        device: 计算设备
        
    Returns:
        np.ndarray: 预测序列
    """
    model.eval()
    
    # 确保模型在正确的设备上
    if device is None:
        device = next(model.parameters()).device
    else:
        model = model.to(device)
    
    # 确保输入数据格式正确
    if isinstance(initial_sequence, np.ndarray):
        initial_sequence = torch.from_numpy(initial_sequence).float()
    
    # 复制一份初始序列，用于累积预测
    current_sequence = initial_sequence.clone()
    
    # 添加批次维度，如果需要的话
    if len(current_sequence.shape) == 2:  # [seq_len, features]
        current_sequence = current_sequence.unsqueeze(0)  # [1, seq_len, features]
    
    # 移动到设备
    current_sequence = current_sequence.to(device)
    
    # 存储预测结果
    predictions = []
    
    # 循环预测未来步骤
    for _ in range(steps):
        with torch.no_grad():
            # 预测下一个值
            next_pred = model(current_sequence)
            
            # 将预测添加到结果列表
            predictions.append(next_pred.cpu().numpy())
            
            # 更新序列，添加新预测，移除最老的值
            # 假设模型输入是 [batch, seq_len, features]，输出是 [batch, output_size]
            if len(next_pred.shape) == 2:  # [batch, output_size]
                # 重新整形以匹配序列的特征维度
                reshaped_pred = next_pred.unsqueeze(1)  # [batch, 1, output_size]
                
                # 更新序列 - 移除最早的时间步，添加新预测
                current_sequence = torch.cat([current_sequence[:, 1:, :], reshaped_pred], dim=1)
            else:
                # 如果输出形状与预期不符，则无法继续多步预测
                logger.error(f"无法继续多步预测，输出形状不兼容: {next_pred.shape}")
                break
    
    # 合并所有预测
    if predictions:
        return np.concatenate(predictions, axis=0)
    else:
        return np.array([])

def batch_predict(model: nn.Module, 
                 data_loader: torch.utils.data.DataLoader,
                 device: Optional[torch.device] = None) -> Tuple[np.ndarray, np.ndarray]:
    """
    批量预测整个数据集
    
    Args:
        model: 训练好的模型
        data_loader: 数据加载器
        device: 计算设备
        
    Returns:
        Tuple[np.ndarray, np.ndarray]: (预测值, 真实值)
    """
    model.eval()
    
    # 确保模型在正确的设备上
    if device is None:
        device = next(model.parameters()).device
    else:
        model = model.to(device)
    
    all_predictions = []
    all_targets = []
    
    # 批量预测
    with torch.no_grad():
        for inputs, targets in data_loader:
            # 移动到设备
            inputs = inputs.to(device)
            
            # 前向传播
            outputs = model(inputs)
            
            # 收集预测和目标
            all_predictions.append(outputs.cpu().numpy())
            all_targets.append(targets.cpu().numpy())
    
    # 合并所有批次的结果
    all_predictions = np.concatenate(all_predictions, axis=0)
    all_targets = np.concatenate(all_targets, axis=0)
    
    return all_predictions, all_targets

def calculate_prediction_metrics(predictions: np.ndarray, 
                                targets: np.ndarray) -> Dict[str, float]:
    """
    计算预测性能指标
    
    Args:
        predictions: 预测值
        targets: 真实值
        
    Returns:
        Dict[str, float]: 指标字典
    """
    # 确保维度匹配
    if predictions.shape != targets.shape:
        if len(predictions.shape) == 2 and len(targets.shape) == 1:
            # 调整目标维度
            targets = targets.reshape(-1, 1)
        elif len(targets.shape) == 2 and len(predictions.shape) == 1:
            # 调整预测维度
            predictions = predictions.reshape(-1, 1)
    
    # 计算均方误差
    mse = np.mean((predictions - targets) ** 2)
    
    # 计算平均绝对误差
    mae = np.mean(np.abs(predictions - targets))
    
    # 计算R方
    target_mean = np.mean(targets, axis=0)
    ss_tot = np.sum((targets - target_mean) ** 2, axis=0)
    ss_res = np.sum((targets - predictions) ** 2, axis=0)
    r2 = 1 - (ss_res / (ss_tot + 1e-10))
    
    # 如果r2是数组，取平均值
    if hasattr(r2, '__len__') and len(r2) > 1:
        r2 = np.mean(r2)
    
    # 计算相关系数
    if len(predictions.flatten()) > 1:  # 避免单个值的情况
        corr = np.corrcoef(predictions.flatten(), targets.flatten())[0, 1]
    else:
        corr = 0.0
    
    # 计算误差的标准差
    error_std = np.std(predictions - targets)
    
    metrics = {
        'mse': float(mse),
        'mae': float(mae),
        'r2': float(r2),
        'correlation': float(corr) if not np.isnan(corr) else 0.0,
        'error_std': float(error_std)
    }
    
    return metrics

def make_ensemble_prediction(models: List[nn.Module], 
                            inputs: torch.Tensor,
                            device: Optional[torch.device] = None) -> torch.Tensor:
    """
    使用模型集成进行预测
    
    Args:
        models: 模型列表
        inputs: 输入数据
        device: 计算设备
        
    Returns:
        torch.Tensor: 集成预测结果
    """
    all_predictions = []
    
    # 确保输入在正确的设备上
    if device is None and len(models) > 0:
        device = next(models[0].parameters()).device
    
    if device is not None:
        inputs = inputs.to(device)
    
    # 收集每个模型的预测
    for model in models:
        model.eval()
        if device is not None:
            model = model.to(device)
        
        with torch.no_grad():
            predictions = model(inputs)
            all_predictions.append(predictions)
    
    # 计算平均预测
    if all_predictions:
        # 确保所有预测形状相同
        if all(pred.shape == all_predictions[0].shape for pred in all_predictions):
            # 计算平均值
            ensemble_prediction = torch.mean(torch.stack(all_predictions), dim=0)
            return ensemble_prediction
        else:
            logger.error("不能进行集成预测：模型输出形状不一致")
            return all_predictions[0]  # 返回第一个模型的预测作为回退
    else:
        logger.error("没有可用的模型进行预测")
        return torch.tensor([]) 