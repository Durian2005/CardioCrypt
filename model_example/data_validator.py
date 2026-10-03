"""
数据验证模块

提供数据质量验证的功能
"""

import numpy as np
import torch
from typing import Dict, Any


def validate_data_quality(data: np.ndarray, 
                         signal_type: str, 
                         min_range: float = None, 
                         max_range: float = None) -> Dict[str, Any]:
    """
    验证信号数据质量

    注意：`model_example/model_evaluator.py` 里有一个**同名函数**，但签名与语义
    完全不同 —— 那个吃 `(train_loader, test_loader, signal_type)`，按训练/测试集
    划分评估；本函数的第一个参数是**信号数组**。两者不可互换。

    本函数当前没有生产调用方（原先只被已废弃的 `main_wrapper` 引用），
    生产链路用的是 `model_evaluator` 那份。
    
    Args:
        data: 信号数据，形状为 [samples, features]
        signal_type: 信号类型 ('ecg' 或 'ppg')
        min_range: 最小有效范围
        max_range: 最大有效范围
        
    Returns:
        dict: 包含质量评估结果的字典
    """
    quality_metrics = {}
    
    # 设置默认范围
    if min_range is None:
        min_range = -5.0 if signal_type == 'ecg' else 0.0
    if max_range is None:
        max_range = 5.0 if signal_type == 'ecg' else 2.0
    
    # 基本统计量
    mean_val = np.mean(data)
    std_val = np.std(data)
    min_val = np.min(data)
    max_val = np.max(data)
    
    quality_metrics['mean'] = float(mean_val)
    quality_metrics['std'] = float(std_val)
    quality_metrics['min'] = float(min_val)
    quality_metrics['max'] = float(max_val)
    
    # 1. 范围检查
    out_of_range = (data < min_range).sum() + (data > max_range).sum()
    out_of_range_ratio = out_of_range / data.size
    quality_metrics['out_of_range_ratio'] = float(out_of_range_ratio)
    
    # 2. 缺失值检查
    nan_count = np.isnan(data).sum()
    nan_ratio = nan_count / data.size
    quality_metrics['nan_ratio'] = float(nan_ratio)
    
    # 3. 噪声评估 - 使用能量标准差估计
    # 将数据分成若干段，计算每段的能量标准差
    if len(data) > 10:
        segments = np.array_split(data, min(10, len(data) // 10))
        segment_energy = [np.sum(segment**2) for segment in segments]
        energy_std = np.std(segment_energy)
        energy_mean = np.mean(segment_energy)
        noise_ratio = energy_std / (energy_mean + 1e-10)
        quality_metrics['noise_ratio'] = float(noise_ratio)
    else:
        quality_metrics['noise_ratio'] = -1.0  # 数据不足以评估
    
    # 4. 平稳性评估 - 通过分段均值方差估计
    if len(data) > 10:
        segments = np.array_split(data, min(10, len(data) // 10))
        segment_means = [np.mean(segment) for segment in segments]
        cv = np.std(segment_means) / (np.mean(segment_means) + 1e-10)
        quality_metrics['stationarity'] = float(cv)
    else:
        quality_metrics['stationarity'] = -1.0  # 数据不足以评估
    
    # 5. 质量评级
    if signal_type == 'ecg':
        # ECG特有的质量标准
        if out_of_range_ratio > 0.1 or nan_ratio > 0:
            quality_rating = "低"
        elif quality_metrics.get('noise_ratio', 0) > 0.5:
            quality_rating = "中"
        else:
            quality_rating = "高"
    else:  # PPG
        # PPG特有的质量标准
        if out_of_range_ratio > 0.1 or nan_ratio > 0:
            quality_rating = "低"
        elif quality_metrics.get('noise_ratio', 0) > 0.3:
            quality_rating = "中"
        else:
            quality_rating = "高"
    
    quality_metrics['quality_rating'] = quality_rating
    
    return quality_metrics

def check_data_overlap(train_data: torch.utils.data.DataLoader, 
                      test_data: torch.utils.data.DataLoader, 
                      sample_size: int = 100) -> Dict[str, Any]:
    """
    检查训练集和测试集之间的数据重叠
    
    Args:
        train_data: 训练数据集
        test_data: 测试数据集
        sample_size: 采样大小
        
    Returns:
        dict: 包含重叠分析结果的字典
    """
    # 从数据加载器中提取样本
    train_samples = []
    test_samples = []
    
    # 收集训练集样本
    for inputs, _ in train_data:
        train_samples.append(inputs)
        if len(train_samples) * inputs.shape[0] >= sample_size:
            break
    
    # 收集测试集样本
    for inputs, _ in test_data:
        test_samples.append(inputs)
        if len(test_samples) * inputs.shape[0] >= sample_size:
            break
    
    # 将样本转换为numpy数组
    train_samples = torch.cat(train_samples)[:sample_size].numpy()
    test_samples = torch.cat(test_samples)[:sample_size].numpy()
    
    # 扁平化每个样本，用于计算相似度
    train_flat = train_samples.reshape(train_samples.shape[0], -1)
    test_flat = test_samples.reshape(test_samples.shape[0], -1)
    
    # 计算相似度矩阵（使用样本间的相关系数）
    # 注意：这里简化处理，仅计算每对样本的前1000个特征
    max_features = min(1000, train_flat.shape[1], test_flat.shape[1])
    train_subset = train_flat[:, :max_features]
    test_subset = test_flat[:, :max_features]
    
    # 找到高度相似的样本对
    high_similarities = []
    similarity_threshold = 0.95
    
    # 为了效率，只检查一部分样本
    check_size = min(50, train_subset.shape[0], test_subset.shape[0])
    
    for i in range(check_size):
        for j in range(check_size):
            # 计算样本间的相关系数
            corr = np.corrcoef(train_subset[i], test_subset[j])[0, 1]
            if corr > similarity_threshold:
                high_similarities.append((i, j, corr))
    
    # 计算最高相似度
    if high_similarities:
        max_similarity = max(s[2] for s in high_similarities)
    else:
        max_similarity = 0
    
    # 风险评估
    if len(high_similarities) > check_size * 0.1:
        overlap_risk = "高"
    elif max_similarity > similarity_threshold:
        overlap_risk = "中"
    else:
        overlap_risk = "低"
        
    return {
        'high_similarity_count': len(high_similarities),
        'max_similarity': float(max_similarity),
        'overlap_risk': overlap_risk
    }

def detect_outliers(data: np.ndarray, 
                   method: str = 'zscore', 
                   threshold: float = 3.0) -> Dict[str, Any]:
    """
    检测数据中的异常值
    
    Args:
        data: 输入数据
        method: 异常值检测方法，'zscore'或'iqr'
        threshold: 异常值阈值
        
    Returns:
        dict: 包含异常值检测结果的字典
    """
    outliers_mask = np.zeros(data.shape, dtype=bool)
    
    if method == 'zscore':
        # Z-Score方法
        mean = np.mean(data, axis=0)
        std = np.std(data, axis=0)
        z_scores = np.abs((data - mean) / (std + 1e-10))
        outliers_mask = z_scores > threshold
        
    elif method == 'iqr':
        # IQR方法
        q1 = np.quantile(data, 0.25, axis=0)
        q3 = np.quantile(data, 0.75, axis=0)
        iqr = q3 - q1
        lower_bound = q1 - threshold * iqr
        upper_bound = q3 + threshold * iqr
        outliers_mask = (data < lower_bound) | (data > upper_bound)
    
    # 计算每个样本的异常值比例
    sample_outlier_ratio = np.mean(outliers_mask, axis=1)
    
    # 确定哪些样本是异常样本（超过20%的特征是异常值）
    outlier_samples = np.where(sample_outlier_ratio > 0.2)[0]
    
    return {
        'outlier_count': int(outliers_mask.sum()),
        'outlier_ratio': float(outliers_mask.sum() / data.size),
        'outlier_sample_indices': outlier_samples.tolist(),
        'outlier_sample_count': len(outlier_samples)
    }

def analyze_signal_frequency(signal: np.ndarray, 
                            fs: float = 500.0) -> Dict[str, Any]:
    """
    分析信号的频率特性
    
    Args:
        signal: 输入信号
        fs: 采样频率
        
    Returns:
        dict: 包含频率分析结果的字典
    """
    from scipy import signal as sg
    
    # 确保信号是一维的
    if len(signal.shape) > 1:
        signal = signal.flatten()
    
    # 计算功率谱
    f, Pxx = sg.welch(signal, fs=fs, nperseg=min(256, len(signal)))
    
    # 找到主频率
    main_freq_idx = np.argmax(Pxx)
    main_freq = f[main_freq_idx]
    
    # 计算信号能量
    signal_energy = np.sum(signal**2)
    
    # 计算频率带能量分布
    # 定义频段
    bands = {
        'very_low': (0, 0.5),    # 0-0.5 Hz
        'low': (0.5, 5),         # 0.5-5 Hz
        'mid': (5, 20),          # 5-20 Hz
        'high': (20, fs/2)       # 20-Nyquist Hz
    }
    
    band_energies = {}
    total_energy = np.sum(Pxx)
    
    for band_name, (low, high) in bands.items():
        # 找到频率范围内的索引
        indices = np.where((f >= low) & (f <= high))[0]
        if len(indices) > 0:
            # 计算该频段的能量比例
            band_energy = np.sum(Pxx[indices]) / total_energy
            band_energies[band_name] = float(band_energy)
        else:
            band_energies[band_name] = 0.0
    
    return {
        'main_frequency': float(main_freq),
        'signal_energy': float(signal_energy),
        'band_energies': band_energies
    } 