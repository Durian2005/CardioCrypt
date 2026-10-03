"""
模型评估器模块

提供模型评估和验证的功能
"""

import torch
import torch.nn as nn
import numpy as np
from typing import Dict, Any

from ecgppg_system.utils.logger import logger

def validate_model(model: nn.Module, 
                  train_loader: torch.utils.data.DataLoader,
                  test_loader: torch.utils.data.DataLoader, 
                  signal_type: str, 
                  device: torch.device) -> Dict[str, Any]:
    """
    全面验证模型性能
    
    Args:
        model: 待验证的模型
        train_loader: 训练数据加载器
        test_loader: 测试数据加载器
        signal_type: 信号类型
        device: 计算设备
        
    Returns:
        dict: 包含验证结果的字典
    """
    logger.info("执行全面模型验证...")
    
    # 验证结果字典
    validation_results = {}
    
    # 1. 计算训练集和测试集的基本统计量
    train_stats = compute_dataset_stats(train_loader)
    test_stats = compute_dataset_stats(test_loader)
    
    validation_results['dataset_stats'] = {
        'train': train_stats,
        'test': test_stats
    }
    
    # 2. 检查训练集和测试集的重叠情况
    overlap_info = check_data_overlap(train_loader, test_loader)
    validation_results['data_overlap'] = overlap_info
    
    # 3. 测试模型泛化能力
    generalization_results = test_model_generalization(model, test_loader, device)
    validation_results['generalization'] = generalization_results
    
    # 4. 数据质量评估
    data_quality = validate_data_quality(train_loader, test_loader, signal_type)
    validation_results['data_quality'] = data_quality
    
    return validation_results

def evaluate_model_metrics(model: nn.Module, 
                          data_loader: torch.utils.data.DataLoader, 
                          device: torch.device) -> Dict[str, float]:
    """
    计算模型评估指标
    
    Args:
        model: 模型
        data_loader: 数据加载器
        device: 计算设备
        
    Returns:
        dict: 包含评估指标的字典
    """
    model.eval()
    total_samples = 0
    total_loss = 0
    all_preds = []
    all_targets = []
    
    # 使用MSE损失作为评估指标
    criterion = nn.MSELoss()
    
    with torch.no_grad():
        for data, target in data_loader:
            # 移动数据到设备
            data, target = data.to(device), target.to(device)
            
            # 前向传播
            output = model(data)
            
            # 如果维度不匹配，调整target维度
            if output.shape != target.shape:
                if len(output.shape) == 2 and len(target.shape) == 1:
                    target = target.view(-1, 1)
            
            # 计算损失
            loss = criterion(output, target)
            
            # 累加
            batch_size = data.size(0)
            total_loss += loss.item() * batch_size
            total_samples += batch_size
            
            # 收集预测和目标
            all_preds.append(output.cpu().numpy())
            all_targets.append(target.cpu().numpy())
    
    # 拼接所有批次的数据
    all_preds = np.concatenate(all_preds)
    all_targets = np.concatenate(all_targets)
    
    # 计算平均损失
    avg_loss = total_loss / total_samples
    
    # 计算其他指标
    mse = np.mean(np.square(all_preds - all_targets))
    mae = np.mean(np.abs(all_preds - all_targets))
    
    # 计算R方
    target_mean = np.mean(all_targets, axis=0)
    ss_tot = np.sum(np.square(all_targets - target_mean), axis=0)
    ss_res = np.sum(np.square(all_targets - all_preds), axis=0)
    r2 = 1 - (ss_res / (ss_tot + 1e-10))  # 添加小数避免除零
    
    # 如果r2是数组，取平均值
    if hasattr(r2, '__len__') and len(r2) > 1:
        r2 = np.mean(r2)
        
    # 创建结果字典
    metrics = {
        'loss': float(avg_loss),
        'mse': float(mse),
        'mae': float(mae),
        'r2': float(r2)
    }
    
    logger.info(f"评估指标: loss={avg_loss:.4f}, mse={mse:.4f}, mae={mae:.4f}, r2={r2:.4f}")
    
    return metrics

def test_model_generalization(model: nn.Module, 
                             data_loader: torch.utils.data.DataLoader, 
                             device: torch.device) -> Dict[str, Any]:
    """
    测试模型泛化能力
    
    Args:
        model: 待测试的模型
        data_loader: 数据加载器
        device: 计算设备
        
    Returns:
        dict: 包含泛化测试结果的字典
    """
    logger.info("测试模型泛化能力...")
    
    model.eval()
    generalization_results = {}
    
    with torch.no_grad():
        # 1. 获取一批测试数据
        inputs, targets = next(iter(data_loader))
        inputs = inputs.to(device)
        targets = targets.to(device)
        
        # 2. 对输入添加不同强度的噪声
        noise_levels = [0.01, 0.05, 0.1, 0.2]
        noise_robustness = {}
        
        for noise_level in noise_levels:
            # 创建噪声
            noise = torch.randn_like(inputs) * noise_level
            noisy_inputs = inputs + noise
            
            # 前向传播
            outputs = model(noisy_inputs)
            
            # 计算误差
            if hasattr(outputs, 'shape') and hasattr(targets, 'shape') and outputs.shape == targets.shape:
                mse = torch.mean((outputs - targets) ** 2).item()
                noise_robustness[f'noise_{noise_level}'] = mse
        
        generalization_results['noise_robustness'] = noise_robustness
    
    return generalization_results

def compute_dataset_stats(data_loader: torch.utils.data.DataLoader) -> Dict[str, Any]:
    """
    计算数据集的基本统计量
    
    Args:
        data_loader: 数据加载器
        
    Returns:
        dict: 包含数据集统计量的字典
    """
    logger.info("计算数据集统计量...")
    
    all_inputs = []
    all_targets = []
    
    # 收集所有数据
    for inputs, targets in data_loader:
        all_inputs.append(inputs.numpy())
        all_targets.append(targets.numpy())
        
    all_inputs = np.concatenate(all_inputs, axis=0)
    all_targets = np.concatenate(all_targets, axis=0)
    
    # 计算统计量
    stats = {
        'samples': len(all_inputs),
        'input_shape': all_inputs.shape,
        'input_mean': float(np.mean(all_inputs)),
        'input_std': float(np.std(all_inputs)),
        'input_min': float(np.min(all_inputs)),
        'input_max': float(np.max(all_inputs)),
        'target_shape': all_targets.shape,
        'target_mean': float(np.mean(all_targets)),
        'target_std': float(np.std(all_targets)),
        'target_min': float(np.min(all_targets)),
        'target_max': float(np.max(all_targets))
    }
    
    return stats

def check_data_overlap(train_loader: torch.utils.data.DataLoader, 
                      test_loader: torch.utils.data.DataLoader) -> Dict[str, Any]:
    """
    检查训练集和测试集的重叠情况
    
    Args:
        train_loader: 训练数据加载器
        test_loader: 测试数据加载器
        
    Returns:
        dict: 包含重叠情况分析的字典
    """
    logger.info("检查数据集重叠...")
    
    # 获取一批数据作为样本
    train_inputs, _ = next(iter(train_loader))
    test_inputs, _ = next(iter(test_loader))
    
    train_sample = train_inputs[0].flatten().numpy()
    test_sample = test_inputs[0].flatten().numpy()
    
    # 计算样本相似度
    similarity = np.corrcoef(train_sample, test_sample)[0, 1]
    
    # 检查是否有过于相似的样本
    overlap_risk = "低" if similarity < 0.7 else ("中" if similarity < 0.9 else "高")
    
    return {
        'similarity': float(similarity) if not np.isnan(similarity) else 0.0,
        'overlap_risk': overlap_risk
    }

def validate_data_quality(train_loader: torch.utils.data.DataLoader, 
                         test_loader: torch.utils.data.DataLoader, 
                         signal_type: str) -> Dict[str, Any]:
    """
    验证数据质量
    
    Args:
        train_loader: 训练数据加载器
        test_loader: 测试数据加载器
        signal_type: 信号类型
        
    Returns:
        dict: 包含数据质量评估结果的字典
    """
    logger.info(f"验证{signal_type}数据质量...")
    
    # 获取一批数据
    inputs, _ = next(iter(train_loader))
    
    # 计算信号质量指标
    quality_metrics = {}
    
    # 1. 信噪比(SNR) - 近似计算
    # 假设信号的方差代表信号功率，残余噪声方差代表噪声功率
    batch_std = inputs.std(dim=1).mean().item()  # 每个样本的标准差的平均值
    
    # 2. 计算平稳性 - 通过分段均值方差估计
    stationarity = []
    for i in range(min(10, len(inputs))):  # 最多分析10个样本
        sample = inputs[i].flatten().numpy()
        segments = np.array_split(sample, 4)  # 将信号分成4段
        segment_means = [seg.mean() for seg in segments]
        # 计算段间均值的变异系数作为平稳性指标（越小越平稳）
        cv = np.std(segment_means) / (np.mean(segment_means) + 1e-10)
        stationarity.append(cv)
    
    mean_stationarity = float(np.mean(stationarity))
    
    # 3. 信号质量评级
    if signal_type == 'ecg':
        # 根据信号类型的不同标准评级
        if batch_std < 0.1:
            quality_rating = "低"
        elif batch_std < 0.5:
            quality_rating = "中"
        else:
            quality_rating = "高"
    else:  # ppg
        if batch_std < 0.05:
            quality_rating = "低"
        elif batch_std < 0.2:
            quality_rating = "中"
        else:
            quality_rating = "高"
    
    quality_metrics['signal_std'] = batch_std
    quality_metrics['stationarity'] = mean_stationarity
    quality_metrics['quality_rating'] = quality_rating
    
    return quality_metrics 