#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
信号数据加载器模块
负责加载、预处理和转换ECG/PPG信号数据
"""

import os
import glob
import numpy as np
import pandas as pd
import torch
from torch.utils.data import TensorDataset, DataLoader

from ecgppg_system.utils.logger import logger

class SignalDataLoader:
    """
    信号数据加载器
    负责从CSV文件或目录加载ECG/PPG信号数据，
    进行预处理和转换，为模型训练和身份验证做准备
    """
    
    def __init__(self, signal_type='ecg', batch_size=32, lookback=100, test_size=0.2, shuffle=True):
        """
        初始化信号数据加载器
        
        参数:
            signal_type (str): 信号类型 ('ecg' 或 'ppg')
            batch_size (int): 批处理大小
            lookback (int): 回看窗口大小
            test_size (float): 测试集比例
            shuffle (bool): 是否打乱数据顺序
        """
        self.signal_type = signal_type.lower()
        self.batch_size = batch_size
        self.lookback = lookback
        self.test_size = test_size
        self.shuffle = shuffle
        self.min_length = 21  # 添加最小信号长度要求，用于滤波
        self.sampling_rate = 100  # 默认采样率
        
        # 检查信号类型
        if self.signal_type not in ['ecg', 'ppg']:
            logger.warning(f"不支持的信号类型: {signal_type}，默认使用'ecg'")
            self.signal_type = 'ecg'
        
        logger.info(f"初始化{self.signal_type.upper()}信号数据加载器")
    
    def load_data(self, data_path):
        """
        加载数据
        
        参数:
            data_path (str): 数据文件路径或目录，多个文件可以用逗号分隔
            
        返回:
            DataFrame: 加载的数据
        """
        logger.info(f"加载数据: {data_path}")
        
        # 检查data_path是否包含多个文件(用逗号分隔)
        if ',' in data_path:
            file_paths = [path.strip() for path in data_path.split(',')]
            logger.info(f"检测到多个文件路径: {len(file_paths)}个文件")
            
            dfs = []
            for file_path in file_paths:
                if not os.path.exists(file_path):
                    logger.warning(f"文件不存在，跳过: {file_path}")
                    continue
                    
                try:
                    df = self._load_data_file(file_path)
                    dfs.append(df)
                    logger.info(f"成功加载文件: {file_path}")
                except Exception as e:
                    logger.warning(f"加载文件失败，跳过: {file_path}, 错误: {str(e)}")
            
            if not dfs:
                raise ValueError("没有成功加载任何数据文件")
                
            # 合并所有数据框
            combined_df = pd.concat(dfs, ignore_index=True)
            logger.info(f"成功加载并合并{len(dfs)}个文件，合并数据形状: {combined_df.shape}")
            return combined_df
        
        # 单个文件或目录的处理
        # 检查数据路径
        if not os.path.exists(data_path):
            raise FileNotFoundError(f"数据路径不存在: {data_path}")
        
        # 如果是文件，直接加载
        if os.path.isfile(data_path):
            logger.info(f"加载单个数据文件: {data_path}")
            return self._load_data_file(data_path)
        
        # 如果是目录，加载所有CSV文件
        if os.path.isdir(data_path):
            logger.info(f"从目录加载数据: {data_path}")
            return self._load_directory(data_path)
        
        # 如果既不是文件也不是目录，抛出异常
        raise ValueError(f"无效的数据路径: {data_path}")
    
    def _load_data_file(self, file_path):
        """
        加载数据文件，支持CSV和Excel格式
        
        参数:
            file_path (str): 数据文件路径，支持.csv, .xlsx, .xls格式
            
        返回:
            DataFrame: 加载的数据
        """
        # 检查文件是否是Excel文件
        if file_path.endswith('.xlsx') or file_path.endswith('.xls'):
            try:
                df = pd.read_excel(file_path)
                logger.info(f"成功加载Excel文件: {file_path}")
                
                # 显示数据基本信息
                logger.info(f"数据形状: {df.shape}")
                logger.info(f"列名: {df.columns.tolist()}")
                
                return df
            except Exception as e:
                logger.error(f"加载Excel文件失败: {file_path}, 错误: {str(e)}")
                raise
        
        try:
            # 尝试不同的编码和分隔符
            for encoding in ['utf-8', 'gbk', 'latin1']:
                for sep in [',', ';', '\t']:
                    try:
                        df = pd.read_csv(file_path, encoding=encoding, sep=sep)
                        logger.info(f"成功加载CSV文件: {file_path}，编码: {encoding}，分隔符: '{sep}'")
                        
                        # 显示数据基本信息
                        logger.info(f"数据形状: {df.shape}")
                        logger.info(f"列名: {df.columns.tolist()}")
                        
                        return df
                    except Exception:
                        continue
            
            # 如果所有组合都失败，尝试一般方法
            df = pd.read_csv(file_path)
            return df
        
        except Exception as e:
            logger.error(f"加载数据文件失败: {file_path}, 错误: {str(e)}")
            raise
    
    def _load_directory(self, directory_path):
        """
        从目录加载所有CSV文件
        
        参数:
            directory_path (str): 目录路径
            
        返回:
            DataFrame: 合并后的数据
        """
        # 查找所有CSV文件和Excel文件
        csv_files = glob.glob(os.path.join(directory_path, "*.csv"))
        excel_files = glob.glob(os.path.join(directory_path, "*.xlsx")) + glob.glob(os.path.join(directory_path, "*.xls"))
        all_files = csv_files + excel_files
        
        if not all_files:
            raise FileNotFoundError(f"目录中没有CSV或Excel文件: {directory_path}")
        
        # 加载所有文件并合并
        dfs = []
        for file_path in all_files:
            try:
                df = self._load_data_file(file_path)
                dfs.append(df)
            except Exception as e:
                logger.warning(f"跳过文件 {file_path}: {str(e)}")
        
        if not dfs:
            raise ValueError(f"没有成功加载任何数据文件: {directory_path}")
        
        # 合并所有数据框
        combined_df = pd.concat(dfs, ignore_index=True)
        logger.info(f"成功加载{len(dfs)}个文件，合并数据形状: {combined_df.shape}")
        
        return combined_df
    
    def extract_signal(self, data_df):
        """
        从数据框中提取信号数据，并进行初步质量评估
        
        参数:
            data_df (DataFrame): 数据框
            
        返回:
            ndarray: 提取的信号数据
        """
        logger.info(f"提取{self.signal_type.upper()}信号数据")
        
        # 如果数据框为空，抛出异常
        if data_df.empty:
            raise ValueError("数据框为空，无法提取信号")
        
        # 定义信号质量评估函数
        def assess_signal_quality(signal):
            """评估信号质量"""
            if len(signal) < 10:
                return 0.0
                
            # 检查缺失值比例
            nan_ratio = np.isnan(signal).mean()
            if nan_ratio > 0.3:
                return 0.0
            
            # 检查信号方差（低方差可能表示信号质量差）
            var = np.var(signal)
            if var < 1e-6:
                return 0.1
                
            # 频域分析
            try:
                from scipy import signal as sig
                freq, power = sig.welch(signal, fs=100)  # 假设采样率为100Hz
                
                # 计算主要频率分量
                dominant_freq = freq[np.argmax(power)]
                
                # 如果主要频率在生理合理范围内，质量评分高
                # ECG心率正常范围：0.5-3Hz (30-180 bpm)
                # PPG心率正常范围：0.5-3Hz (30-180 bpm)
                quality_score = 0.5
                if 0.5 <= dominant_freq <= 4.0:
                    quality_score += 0.3
                    
                # 信噪比评估
                power_total = power.sum()
                if power_total > 0:
                    power_noise = power[(freq < 0.5) | (freq > 4.0)].sum()
                    snr = 1.0 - power_noise / power_total
                    quality_score += 0.2 * snr
                    
                return min(1.0, quality_score)
            except:
                # 如果频域分析失败，返回中等质量分数
                return 0.4
        
        # 尝试通过几种常见方法提取信号
        best_signal = None
        best_quality = -1
        
        # 方法1：如果数据框只有两列，假设第二列是信号
        if len(data_df.columns) == 2:
            try:
                signal_col = data_df.columns[1]
                signal = data_df[signal_col].values
                quality = assess_signal_quality(signal)
                
                if quality > best_quality:
                    best_quality = quality
                    best_signal = signal
                    logger.info(f"使用数据框中的第二列作为信号，质量评分: {quality:.3f}")
            except Exception as e:
                logger.warning(f"使用第二列作为信号失败: {str(e)}")
        
        # 方法2：寻找名称含有特定关键词的列
        signal_keywords = {
            'ecg': ['ecg', 'ekg', 'electrocardiogram', 'heart', 'cardio', 'signal', 'value'],
            'ppg': ['ppg', 'photoplethysmogram', 'pulse', 'blood', 'pleth', 'signal', 'value']
        }
        
        keywords = signal_keywords.get(self.signal_type, ['signal', 'value'])
        
        for keyword in keywords:
            matching_cols = [col for col in data_df.columns if keyword.lower() in str(col).lower()]
            if matching_cols:
                try:
                    signal = data_df[matching_cols[0]].values
                    quality = assess_signal_quality(signal)
                    
                    if quality > best_quality:
                        best_quality = quality
                        best_signal = signal
                        logger.info(f"使用关键词'{keyword}'匹配的列'{matching_cols[0]}'作为信号，质量评分: {quality:.3f}")
                except Exception as e:
                    logger.warning(f"使用关键词'{keyword}'匹配的列失败: {str(e)}")
        
        # 方法3：检查是否有多个样本列（如Sample_1, Sample_2...）
        sample_cols = [col for col in data_df.columns if 'sample' in str(col).lower()]
        if sample_cols:
            try:
                samples_df = data_df[sample_cols]
                signal = samples_df.mean(axis=1).values
                quality = assess_signal_quality(signal)
                
                if quality > best_quality:
                    best_quality = quality
                    best_signal = signal
                    logger.info(f"使用列 {sample_cols} 的均值作为信号，质量评分: {quality:.3f}")
            except Exception as e:
                logger.warning(f"使用样本列均值作为信号失败: {str(e)}")
        
        # 方法4：使用所有数值列的均值
        try:
            numeric_cols = data_df.select_dtypes(include=['number']).columns
            if len(numeric_cols) > 0:
                numeric_df = data_df[numeric_cols]
                signal = numeric_df.mean(axis=1).values
            quality = assess_signal_quality(signal)
                
            if quality > best_quality:
                    best_quality = quality
                    best_signal = signal
            logger.info(f"使用所有数值列的均值作为信号，质量评分: {quality:.3f}")
        except Exception as e:
            logger.warning(f"使用所有数值列均值作为信号失败: {str(e)}")
        
        # 如果找到了合适的信号，返回
        if best_signal is not None:
            logger.info(f"选择质量最好的信号，评分: {best_quality:.3f}")
            return best_signal
        
        # 如果无法提取信号，抛出异常
        raise ValueError(f"无法从数据框中提取{self.signal_type.upper()}信号")
    
    def _expand_data(self, signal, target_length=None):
        """
        扩展信号数据到目标长度
        
        参数:
            signal (ndarray): 原始信号数据
            target_length (int, optional): 目标长度，如果为None则使用min_length
            
        返回:
            ndarray: 扩展后的信号数据
        """
        # 设置目标长度
        if target_length is None:
            target_length = self.min_length
            
        # 如果信号长度已经足够，直接返回
        if len(signal) >= target_length:
            return signal
            
        # 计算需要重复的次数
        repeat_count = int(np.ceil(target_length / len(signal)))
        
        # 扩展数据
        expanded_signal = np.tile(signal, repeat_count)
        
        # 截取到目标长度
        expanded_signal = expanded_signal[:target_length]
        
        logger.info(f"信号数据已从{len(signal)}扩展到{len(expanded_signal)}个数据点")
        return expanded_signal
    
    def preprocess_data(self, signal_data):
        """
        对信号数据进行预处理，包括去噪、滤波和信号增强
        
        参数:
            signal_data (ndarray): 原始信号数据
            
        返回:
            ndarray: 预处理后的信号数据
        """
        logger.info("开始预处理信号数据")
        
        # 将信号数据展平为一维数组
        signal = signal_data.flatten()
        
        # 检查信号长度
        if len(signal) < self.min_length:
            logger.warning(f"信号长度({len(signal)})小于最小要求({self.min_length})，将进行数据扩充")
            signal = self._expand_data(signal)
        
        # 1. 基础预处理
        # 移除NaN值
        signal = np.nan_to_num(signal, nan=np.nanmean(signal))
        
        # 使用自适应IQR方法去除异常值
        def adaptive_iqr_clip(signal, window_size=100):
            """使用滑动窗口的自适应IQR方法去除异常值"""
            clipped_signal = signal.copy()
            for i in range(0, len(signal), window_size):
                window = signal[i:i+window_size]
                if len(window) < 10:  # 窗口太小则跳过
                    continue
                    
                q1 = np.percentile(window, 25)
                q3 = np.percentile(window, 75)
                iqr = q3 - q1
                
                # 自适应阈值
                lower_bound = q1 - 1.5 * iqr
                upper_bound = q3 + 1.5 * iqr
                
                # 使用平滑过渡而不是硬截断
                mask = (window < lower_bound) | (window > upper_bound)
                if np.any(mask):
                    clipped_signal[i:i+window_size][mask] = np.clip(
                        window[mask],
                        lower_bound,
                        upper_bound
                    )
            
            return clipped_signal
        
        signal = adaptive_iqr_clip(signal)
        
        # 2. 信号质量增强
        def enhance_signal_quality(signal):
            """增强信号质量"""
            # 使用中值滤波去除脉冲噪声
            signal_median = signal.copy()
            window_size = 5
            for i in range(window_size, len(signal) - window_size):
                signal_median[i] = np.median(signal[i-window_size:i+window_size+1])
            
            # 使用Savitzky-Golay滤波平滑信号
            try:
                from scipy.signal import savgol_filter
                signal_smooth = savgol_filter(signal_median, window_length=11, polyorder=3)
            except:
                logger.warning("Savitzky-Golay滤波失败，使用移动平均代替")
                signal_smooth = np.convolve(signal_median, np.ones(11)/11, mode='same')
            
            return signal_smooth
        
        signal = enhance_signal_quality(signal)
        
        # 3. 自适应滤波
        def adaptive_filter(signal):
            """根据信号类型应用自适应滤波"""
            if self.signal_type == 'ecg':
                # ECG信号特定处理
                try:
                    from scipy.signal import butter, filtfilt
                    # 设计带通滤波器 (0.5-40 Hz)
                    nyquist = self.sampling_rate / 2
                    low = 0.5 / nyquist
                    high = 40.0 / nyquist
                    b, a = butter(4, [low, high], btype='band')
                    signal = filtfilt(b, a, signal)
                except Exception as e:
                    logger.error(f"ECG滤波失败: {str(e)}")
            
            elif self.signal_type == 'ppg':
                # PPG信号特定处理
                try:
                    from scipy.signal import butter, filtfilt
                    # 设计带通滤波器 (0.5-5 Hz)
                    nyquist = self.sampling_rate / 2
                    low = 0.5 / nyquist
                    high = 5.0 / nyquist
                    b, a = butter(4, [low, high], btype='band')
                    signal = filtfilt(b, a, signal)
                except Exception as e:
                    logger.error(f"PPG滤波失败: {str(e)}")
            
            return signal
        
        signal = adaptive_filter(signal)
        
        # 4. 信号归一化
        def normalize_signal(signal):
            """对信号进行归一化处理"""
            # 移除基线漂移
            baseline = np.convolve(signal, np.ones(100)/100, mode='same')
            signal_detrend = signal - baseline
            
            # 归一化到[-1, 1]范围
            signal_norm = signal_detrend / (np.max(np.abs(signal_detrend)) + 1e-10)
            
            return signal_norm
        
        signal = normalize_signal(signal)
        
        # 5. 信号分段处理
        def segment_signal(signal, segment_length=1000):
            """将信号分段并处理"""
            segments = []
            for i in range(0, len(signal), segment_length):
                segment = signal[i:i+segment_length]
                if len(segment) == segment_length:
                    # 对每个分段进行额外的质量检查
                    if np.std(segment) > 0.1:  # 确保分段不是常数
                        segments.append(segment)
            
            if segments:
                # 重新组合分段
                signal = np.concatenate(segments)
            
            return signal
        
        signal = segment_signal(signal)
        
        logger.info(f"信号预处理完成，最终长度: {len(signal)}")
        return signal
    
    def split_data(self, signal_data, lookback=None):
        """
        将信号数据分割为训练样本和标签
        
        参数:
            signal_data (ndarray): 信号数据
            lookback (int, optional): 回看窗口大小
            
        返回:
            tuple: (x_train, y_train, x_test, y_test)
        """
        logger.info(f"分割{self.signal_type.upper()}信号数据为训练集和测试集")
        
        # 如果没有指定lookback，使用默认值
        if lookback is None:
            lookback = self.lookback
        
        # 检查数据长度是否足够
        required_min_length = lookback + 1  # 至少需要lookback+1的长度
        if len(signal_data) < required_min_length:
            logger.warning(f"信号数据长度({len(signal_data)})不足，要求至少{required_min_length}个数据点")
            # 处理数据不足的情况：填充数据
            if len(signal_data) > 0:
                # 通过重复现有数据来补充数据量
                repeat_count = int(np.ceil(required_min_length / len(signal_data)))
                signal_data = np.tile(signal_data, repeat_count)[:required_min_length]
                logger.info(f"已补充数据至{len(signal_data)}个数据点")
            else:
                # 如果没有数据，创建随机数据
                logger.warning("无有效数据，使用随机数据进行填充")
                signal_data = np.random.rand(required_min_length)
        
        if len(signal_data) <= lookback:
            logger.warning(f"信号数据长度({len(signal_data)})小于回看窗口大小({lookback})，调整回看窗口大小")
            lookback = max(1, len(signal_data) // 2)
        
        # 创建输入/输出序列对
        X, y = [], []
        for i in range(len(signal_data) - lookback):
            X.append(signal_data[i:i+lookback])
            y.append(signal_data[i+lookback])
        
        X = np.array(X)
        y = np.array(y)
        
        # 如果只有一个特征，添加一个维度
        if len(X.shape) == 2:
            X = X.reshape((X.shape[0], X.shape[1], 1))
        
        # 严格按时间顺序划分数据，避免随机划分导致的数据泄漏
        # 前80%作为训练集，后20%作为测试集
        split_idx = int(len(X) * (1 - self.test_size))
        logger.info(f"使用严格时序划分：前{1 - self.test_size:.0%}作为训练集，后{self.test_size:.0%}作为测试集")
        
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        # 验证划分结果，确保训练集和测试集没有时间重叠
        logger.info(f"时序划分完成 - 训练集范围: 0-{split_idx-1}, 测试集范围: {split_idx}-{len(X)-1}")
        logger.info(f"训练集形状: {X_train.shape}, 测试集形状: {X_test.shape}")
        
        # 检查训练集和测试集的时间隔离性
        # 计算训练集最后一个样本与测试集第一个样本的差异
        if len(X_train) > 0 and len(X_test) > 0:
            last_train = X_train[-1].flatten()
            first_test = X_test[0].flatten()
            
            # 检查是否有重叠（共享相同的数据点）
            overlap = np.array_equal(last_train[1:], first_test[:-1])
            if overlap:
                logger.warning("训练集最后一个样本与测试集第一个样本存在重叠，"
                              "这是由于滑动窗口创建的样本的特性导致的")
                logger.info("这种轻微重叠是预期的，不会导致严重的数据泄漏问题")
            else:
                logger.info("训练集和测试集之间存在适当的时间隔离")
        
        # 检查样本数量是否足够
        if len(X_train) < 10:
            logger.warning(f"训练样本数量过少({len(X_train)})，模型训练可能不充分")
        if len(X_test) < 5:
            logger.warning(f"测试样本数量过少({len(X_test)})，模型评估可能不可靠")
        
        logger.info(f"数据分割完成，训练集: {X_train.shape}, 测试集: {X_test.shape}")
        return X_train, y_train, X_test, y_test
    
    def create_data_loaders(self, x_train, y_train, x_test, y_test, batch_size=None):
        """
        创建PyTorch数据加载器
        
        参数:
            x_train (ndarray): 训练特征
            y_train (ndarray): 训练标签
            x_test (ndarray): 测试特征
            y_test (ndarray): 测试标签
            batch_size (int, optional): 批处理大小
            
        返回:
            tuple: (train_loader, test_loader)
        """
        logger.info(f"创建{self.signal_type.upper()}数据加载器")
        
        # 如果没有指定batch_size，使用默认值
        if batch_size is None:
            batch_size = self.batch_size
        
        # 转换为PyTorch张量
        x_train_tensor = torch.tensor(x_train, dtype=torch.float32)
        y_train_tensor = torch.tensor(y_train, dtype=torch.float32).view(-1, 1)
        x_test_tensor = torch.tensor(x_test, dtype=torch.float32)
        y_test_tensor = torch.tensor(y_test, dtype=torch.float32).view(-1, 1)
        
        # 创建数据集
        train_dataset = TensorDataset(x_train_tensor, y_train_tensor)
        test_dataset = TensorDataset(x_test_tensor, y_test_tensor)
        
        # 创建数据加载器
        train_loader = DataLoader(
            train_dataset, 
            batch_size=batch_size, 
            shuffle=self.shuffle,
            drop_last=False
        )
        
        test_loader = DataLoader(
            test_dataset, 
            batch_size=batch_size, 
            shuffle=False,
            drop_last=False
        )
        
        logger.info(f"数据加载器创建完成，训练批次: {len(train_loader)}, 测试批次: {len(test_loader)}")
        return train_loader, test_loader 