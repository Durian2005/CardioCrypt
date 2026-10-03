"""
统计分析和报告生成模块
提供信号数据的统计分析、报告生成和结果汇总功能
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os
import sys
from datetime import datetime
from typing import Dict
import json
import csv

from .logger import logger
from .matplotlib_setup import configure_matplotlib

# 确保matplotlib配置正确
configure_matplotlib()

# 获取中文字体
def get_chinese_font():
    """
    获取中文字体
    
    返回:
        FontProperties: 字体属性对象，如果没有找到则返回None
    """
    # 查找字体文件
    system_fonts = {
        'windows': [
            'C:/Windows/Fonts/msyh.ttc',     # 微软雅黑
            'C:/Windows/Fonts/simsun.ttc',   # 宋体
            'C:/Windows/Fonts/simhei.ttf',   # 黑体
        ],
        'linux': [
            '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        ],
        'darwin': [
            '/Library/Fonts/Arial Unicode.ttf',
            '/System/Library/Fonts/PingFang.ttc',
        ]
    }
    
    # 检测当前系统
    if sys.platform.startswith('win'):
        system = 'windows'
    elif sys.platform.startswith('linux'):
        system = 'linux'
    elif sys.platform.startswith('darwin'):
        system = 'darwin'
    else:
        system = 'unknown'
    
    # 尝试系统字体
    font_path = None
    for font in system_fonts.get(system, []):
        if os.path.exists(font):
            font_path = font
            logger.info(f"使用系统中文字体: {font}")
            break
    
    if not font_path:
        logger.warning("未找到可用的中文字体文件，图表可能无法正确显示中文")
        return None
    
    # 创建字体属性对象
    from matplotlib.font_manager import FontProperties
    return FontProperties(fname=font_path)

# 获取全局字体对象
CHINESE_FONT = get_chinese_font()

class StatisticalAnalyzer:
    """信号数据统计分析器"""
    
    def __init__(self, signal_type: str = 'ecg'):
        """
        初始化统计分析器
        
        参数:
            signal_type: 信号类型 ('ecg' 或 'ppg')
        """
        self.signal_type = signal_type
        self.analysis_results = {}
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        logger.info(f"初始化{signal_type.upper()}统计分析器")
    
    def analyze_signal(self, signal: np.ndarray, name: str = None) -> Dict:
        """
        对信号数据进行统计分析
        
        参数:
            signal: 信号数据
            name: 数据集名称
            
        返回:
            Dict: 分析结果
        """
        if name is None:
            name = f"dataset_{len(self.analysis_results) + 1}"
        
        # 确保信号是一维数组
        signal = np.asarray(signal).flatten()
        
        # 基础统计量
        stats = {
            'length': len(signal),
            'mean': float(np.mean(signal)),
            'std': float(np.std(signal)),
            'min': float(np.min(signal)),
            'max': float(np.max(signal)),
            'median': float(np.median(signal)),
            'skewness': float(self._calculate_skewness(signal)),
            'kurtosis': float(self._calculate_kurtosis(signal)),
            'range': float(np.ptp(signal)),
            'q1': float(np.percentile(signal, 25)),
            'q3': float(np.percentile(signal, 75)),
            'iqr': float(np.percentile(signal, 75) - np.percentile(signal, 25)),
            'missing_values': int(np.sum(np.isnan(signal))),
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # 信号波动性分析
        # 计算一阶差分（速率）
        diff1 = np.diff(signal)
        stats['mean_rate'] = float(np.mean(diff1))
        stats['max_rate'] = float(np.max(diff1))
        stats['min_rate'] = float(np.min(diff1))
        
        # 计算二阶差分（加速度）
        diff2 = np.diff(diff1)
        stats['mean_acceleration'] = float(np.mean(diff2))
        stats['max_acceleration'] = float(np.max(diff2))
        stats['min_acceleration'] = float(np.min(diff2))
        
        # 计算过零率（信号穿过均值的频率）
        zero_crossings = np.where(np.diff(np.signbit(signal - np.mean(signal))))[0]
        stats['zero_crossing_rate'] = float(len(zero_crossings) / len(signal))
        
        # 频域分析
        try:
            from scipy import fft
            signal_fft = fft.fft(signal)
            signal_psd = np.abs(signal_fft) ** 2
            signal_freq = fft.fftfreq(len(signal))
            
            # 仅使用正频率
            positive_freq_idx = np.where(signal_freq > 0)[0]
            positive_freq = signal_freq[positive_freq_idx]
            positive_psd = signal_psd[positive_freq_idx]
            
            # 找出功率最大的频率
            if len(positive_freq) > 0:
                max_power_idx = np.argmax(positive_psd)
                stats['dominant_frequency'] = float(positive_freq[max_power_idx])
                
                # 计算频域能量分布
                total_power = np.sum(positive_psd)
                
                # 低频带能量比例 (0-1/4 fmax)
                low_freq_idx = np.where(positive_freq <= np.max(positive_freq)/4)[0]
                if len(low_freq_idx) > 0:
                    low_freq_power = np.sum(positive_psd[low_freq_idx])
                    stats['low_freq_power_ratio'] = float(low_freq_power / total_power)
                
                # 中频带能量比例 (1/4-1/2 fmax)
                mid_freq_idx = np.where((positive_freq > np.max(positive_freq)/4) & 
                                      (positive_freq <= np.max(positive_freq)/2))[0]
                if len(mid_freq_idx) > 0:
                    mid_freq_power = np.sum(positive_psd[mid_freq_idx])
                    stats['mid_freq_power_ratio'] = float(mid_freq_power / total_power)
                
                # 高频带能量比例 (>1/2 fmax)
                high_freq_idx = np.where(positive_freq > np.max(positive_freq)/2)[0]
                if len(high_freq_idx) > 0:
                    high_freq_power = np.sum(positive_psd[high_freq_idx])
                    stats['high_freq_power_ratio'] = float(high_freq_power / total_power)
        except Exception as e:
            logger.warning(f"频域分析失败: {str(e)}")
        
        # 保存结果
        self.analysis_results[name] = stats
        
        logger.info(f"信号 '{name}' 分析完成，长度: {stats['length']}，均值: {stats['mean']:.3f}，标准差: {stats['std']:.3f}")
        return stats
    
    def _calculate_skewness(self, x):
        """计算偏度 (skewness)"""
        x = np.asarray(x)
        n = len(x)
        if n < 3:
            return 0
        m2 = np.mean((x - np.mean(x))**2)
        m3 = np.mean((x - np.mean(x))**3)
        if m2 == 0:
            return 0
        return m3 / m2**1.5
    
    def _calculate_kurtosis(self, x):
        """计算峰度 (kurtosis)"""
        x = np.asarray(x)
        n = len(x)
        if n < 4:
            return 0
        m2 = np.mean((x - np.mean(x))**2)
        m4 = np.mean((x - np.mean(x))**4)
        if m2 == 0:
            return 0
        return m4 / m2**2 - 3  # 减去3使正态分布的峰度为0
    
    def compare_signals(self, signal1_name: str, signal2_name: str, custom_actual: np.ndarray = None) -> Dict:
        """
        比较两个信号的统计特性
        
        参数:
            signal1_name: 第一个信号的名称（通常是预测信号）
            signal2_name: 第二个信号的名称（通常是原始信号）
            custom_actual: 可选的自定义实际值数组，用于替代从signal2_name获取的值
            
        返回:
            Dict: 比较结果
        """
        if signal1_name not in self.analysis_results:
            raise ValueError(f"信号 '{signal1_name}' 未找到")
        
        stats1 = self.analysis_results[signal1_name]
        
        # 如果提供了自定义实际值数组，使用它进行临时分析
        if custom_actual is not None:
            # 临时分析custom_actual数组
            temp_name = f"{signal2_name}_temp"
            self.analyze_signal(custom_actual, name=temp_name)
            stats2 = self.analysis_results[temp_name]
            logger.info(f"使用自定义实际值数组替代 '{signal2_name}' 进行比较")
        else:
            # 使用已有的信号数据
            if signal2_name not in self.analysis_results:
                raise ValueError(f"信号 '{signal2_name}' 未找到")
            stats2 = self.analysis_results[signal2_name]
        
        # 计算差异和相对差异
        comparison = {}
        
        # 比较基础统计量
        for key in ['mean', 'std', 'median', 'range', 'skewness', 'kurtosis']:
            if key in stats1 and key in stats2:
                abs_diff = stats2[key] - stats1[key]
                if stats1[key] != 0:
                    rel_diff = abs_diff / abs(stats1[key]) * 100
                else:
                    rel_diff = float('inf') if abs_diff != 0 else 0
                
                comparison[f'{key}_abs_diff'] = float(abs_diff)
                comparison[f'{key}_rel_diff'] = float(rel_diff)
        
        # 计算综合相似度分数
        similarities = []
        
        # 均值相似度（基于相对差异）
        if 'mean_rel_diff' in comparison:
            mean_similarity = 100 / (1 + abs(comparison['mean_rel_diff'])/10)
            similarities.append(mean_similarity)
        
        # 标准差相似度
        if 'std_rel_diff' in comparison:
            std_similarity = 100 / (1 + abs(comparison['std_rel_diff'])/20)
            similarities.append(std_similarity)
        
        # 中位数相似度
        if 'median_rel_diff' in comparison:
            median_similarity = 100 / (1 + abs(comparison['median_rel_diff'])/10)
            similarities.append(median_similarity)
        
        # 峰度和偏度相似度
        if 'skewness_abs_diff' in comparison and 'kurtosis_abs_diff' in comparison:
            shape_similarity = 100 / (1 + (abs(comparison['skewness_abs_diff']) + abs(comparison['kurtosis_abs_diff']))/2)
            similarities.append(shape_similarity)
        
        # 计算平均相似度
        if similarities:
            comparison['similarity_score'] = float(np.mean(similarities))
        else:
            comparison['similarity_score'] = 0.0
        
        comparison['signal1'] = signal1_name
        comparison['signal2'] = signal2_name
        comparison['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        logger.info(f"信号 '{signal1_name}' 和 '{signal2_name}' 比较完成，相似度: {comparison['similarity_score']:.2f}%")
        return comparison
    
    def generate_report(self, output_dir: str = None, 
                      include_plots: bool = True) -> str:
        """
        生成统计分析报告
        
        参数:
            output_dir: 输出目录
            include_plots: 是否包含可视化图表
            
        返回:
            str: 报告文件路径
        """
        if not self.analysis_results:
            logger.warning("没有分析结果可生成报告")
            return None
        
        # 如果未指定输出目录，使用当前目录
        if output_dir is None:
            output_dir = os.getcwd()
        
        # 创建输出目录
        os.makedirs(output_dir, exist_ok=True)
        
        # 生成报告文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = os.path.join(output_dir, f"{self.signal_type}_stats_report_{timestamp}.txt")
        
        # 准备报告内容
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write(f"{self.signal_type.upper()}信号统计分析报告\n")
            f.write("=" * 80 + "\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"分析信号数量: {len(self.analysis_results)}\n")
            f.write("-" * 80 + "\n\n")
            
            # 添加每个信号的统计结果
            for name, stats in self.analysis_results.items():
                f.write(f"信号: {name}\n")
                f.write("=" * 50 + "\n")
                
                # 基础统计量
                f.write("基本统计量:\n")
                f.write(f"  数据长度: {stats['length']}\n")
                f.write(f"  均值: {stats['mean']:.4f}\n")
                f.write(f"  标准差: {stats['std']:.4f}\n")
                f.write(f"  最小值: {stats['min']:.4f}\n")
                f.write(f"  最大值: {stats['max']:.4f}\n")
                f.write(f"  中位数: {stats['median']:.4f}\n")
                f.write(f"  偏度: {stats['skewness']:.4f}\n")
                f.write(f"  峰度: {stats['kurtosis']:.4f}\n")
                f.write(f"  范围: {stats['range']:.4f}\n")
                f.write(f"  四分位数Q1: {stats['q1']:.4f}\n")
                f.write(f"  四分位数Q3: {stats['q3']:.4f}\n")
                f.write(f"  四分位距IQR: {stats['iqr']:.4f}\n")
                f.write(f"  缺失值数量: {stats['missing_values']}\n")
                
                # 信号波动性分析
                f.write("\n信号波动性分析:\n")
                f.write(f"  平均变化率: {stats['mean_rate']:.4f}\n")
                f.write(f"  最大变化率: {stats['max_rate']:.4f}\n")
                f.write(f"  最小变化率: {stats['min_rate']:.4f}\n")
                f.write(f"  平均加速度: {stats['mean_acceleration']:.4f}\n")
                f.write(f"  最大加速度: {stats['max_acceleration']:.4f}\n")
                f.write(f"  最小加速度: {stats['min_acceleration']:.4f}\n")
                f.write(f"  过零率: {stats['zero_crossing_rate']:.4f}\n")
                
                # 频域分析
                if 'dominant_frequency' in stats:
                    f.write("\n频域分析:\n")
                    f.write(f"  主频率: {stats['dominant_frequency']:.6f}\n")
                    
                    if 'low_freq_power_ratio' in stats:
                        f.write(f"  低频功率比: {stats['low_freq_power_ratio']:.4f}\n")
                    if 'mid_freq_power_ratio' in stats:
                        f.write(f"  中频功率比: {stats['mid_freq_power_ratio']:.4f}\n")
                    if 'high_freq_power_ratio' in stats:
                        f.write(f"  高频功率比: {stats['high_freq_power_ratio']:.4f}\n")
                
                f.write("\n" + "-" * 50 + "\n\n")
            
            # 如果有多个信号，添加信号对比结果
            signal_names = list(self.analysis_results.keys())
            if len(signal_names) > 1:
                f.write("\n信号对比分析\n")
                f.write("=" * 50 + "\n")
                
                for i in range(len(signal_names)):
                    for j in range(i+1, len(signal_names)):
                        try:
                            comparison = self.compare_signals(signal_names[i], signal_names[j])
                            
                            f.write(f"比较: {signal_names[i]} vs {signal_names[j]}\n")
                            f.write(f"  相似度评分: {comparison['similarity_score']:.2f}%\n")
                            f.write("  差异分析:\n")
                            
                            for key in comparison:
                                if key.endswith('_abs_diff') or key.endswith('_rel_diff'):
                                    stat_name = key.split('_')[0]
                                    diff_type = '_'.join(key.split('_')[1:])
                                    
                                    if diff_type == 'abs_diff':
                                        f.write(f"    {stat_name}绝对差异: {comparison[key]:.4f}\n")
                                    elif diff_type == 'rel_diff':
                                        f.write(f"    {stat_name}相对差异: {comparison[key]:.2f}%\n")
                            
                            f.write("\n")
                        except Exception as e:
                            f.write(f"  无法比较 {signal_names[i]} 和 {signal_names[j]}: {str(e)}\n\n")
        
        # 如果需要，生成可视化图表
        if include_plots:
            plots_dir = os.path.join(output_dir, f"stats_plots_{timestamp}")
            os.makedirs(plots_dir, exist_ok=True)
            
            self._generate_plots(plots_dir)
            
            # 添加图表信息到报告
            with open(report_file, 'a', encoding='utf-8') as f:
                f.write("\n可视化图表\n")
                f.write("=" * 50 + "\n")
                f.write(f"图表保存路径: {plots_dir}\n")
                f.write("包含以下图表:\n")
                f.write("  - 信号分布直方图\n")
                f.write("  - 统计量对比图\n")
                f.write("  - 波动性分析图\n")
                if len(self.analysis_results) > 1:
                    f.write("  - 相似度矩阵热图\n")
        
        # 同时保存结果到JSON和CSV
        json_file = os.path.join(output_dir, f"{self.signal_type}_stats_{timestamp}.json")
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(self.analysis_results, f, indent=2)
        
        csv_file = os.path.join(output_dir, f"{self.signal_type}_stats_{timestamp}.csv")
        self._save_results_to_csv(csv_file)
        
        logger.info(f"统计分析报告已保存到 {report_file}")
        return report_file
    
    def _generate_plots(self, output_dir: str) -> None:
        """
        生成分析图表
        
        参数:
            output_dir: 输出目录
        """
        # 设置绘图样式
        sns.set_style("whitegrid")
        
        # 1. 生成分布直方图
        plt.figure(figsize=(12, 8))
        
        for i, (name, stats) in enumerate(self.analysis_results.items()):
            # 提取统计量
            mean = stats['mean']
            std = stats['std']
            median = stats['median']
            q1 = stats['q1']
            q3 = stats['q3']
            
            # 生成正态分布曲线
            x = np.linspace(mean - 3*std, mean + 3*std, 100)
            y = np.exp(-(x - mean)**2 / (2 * std**2)) / (std * np.sqrt(2 * np.pi))
            
            # 绘制正态分布
            plt.plot(x, y, label=f"{name} (μ={mean:.2f}, σ={std:.2f})")
            
            # 标记均值、中位数和四分位数
            plt.axvline(mean, color=f'C{i}', linestyle='-', alpha=0.5, label=f"{name} 均值")
            plt.axvline(median, color=f'C{i}', linestyle='--', alpha=0.5, label=f"{name} 中位数")
            plt.axvline(q1, color=f'C{i}', linestyle=':', alpha=0.5, label=f"{name} Q1")
            plt.axvline(q3, color=f'C{i}', linestyle=':', alpha=0.5, label=f"{name} Q3")
        
        # 设置标题和标签，使用中文字体
        if CHINESE_FONT:
            plt.title(f"{self.signal_type.upper()}信号分布特性", 
                     fontproperties=CHINESE_FONT, fontsize=14)
            plt.xlabel("数值", fontproperties=CHINESE_FONT, fontsize=12)
            plt.ylabel("概率密度", fontproperties=CHINESE_FONT, fontsize=12)
        else:
            plt.title(f"{self.signal_type.upper()}信号分布特性", fontsize=14)
            plt.xlabel("数值", fontsize=12)
            plt.ylabel("概率密度", fontsize=12)
            
        plt.legend()
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, "distribution.png"), dpi=300)
        plt.close()
        
        # 2. 生成统计量对比图
        if len(self.analysis_results) > 1:
            # 准备数据
            stats_df = pd.DataFrame()
            for name, stats in self.analysis_results.items():
                stats_subset = {
                    'name': name,
                    'mean': stats['mean'],
                    'std': stats['std'],
                    'median': stats['median'],
                    'skewness': stats['skewness'],
                    'kurtosis': stats['kurtosis'],
                    'range': stats['range']
                }
                stats_df = pd.concat([stats_df, pd.DataFrame([stats_subset])], ignore_index=True)
            
            # 绘制相对比较图
            plt.figure(figsize=(15, 10))
            
            # 中文化统计量名称映射
            stat_names = {
                'mean': '均值',
                'median': '中位数',
                'std': '标准差',
                'range': '范围',
                'skewness': '偏度',
                'kurtosis': '峰度'
            }
            
            # 基础统计量比较
            for i, stat in enumerate(['mean', 'median', 'std', 'range', 'skewness', 'kurtosis']):
                plt.subplot(2, 3, i+1)
                sns.barplot(x='name', y=stat, data=stats_df)
                
                # 设置标题和标签，使用中文字体
                if CHINESE_FONT:
                    plt.title(f"{stat_names[stat]}", 
                             fontproperties=CHINESE_FONT, fontsize=12)
                    plt.xlabel("信号", fontproperties=CHINESE_FONT, fontsize=10)
                    plt.ylabel(f"{stat_names[stat]}", 
                              fontproperties=CHINESE_FONT, fontsize=10)
                else:
                    plt.title(f"{stat_names[stat]}", fontsize=12)
                    plt.xlabel("信号", fontsize=10)
                    plt.ylabel(f"{stat_names[stat]}", fontsize=10)
                    
                plt.xticks(rotation=30)
            
            plt.tight_layout()
            plt.savefig(os.path.join(output_dir, "stats_comparison.png"), dpi=300)
            plt.close()
            
            # 3. 生成相似度矩阵热图
            signal_names = list(self.analysis_results.keys())
            n_signals = len(signal_names)
            similarity_matrix = np.zeros((n_signals, n_signals))
            
            for i in range(n_signals):
                similarity_matrix[i, i] = 100  # 自己和自己的相似度是100%
                for j in range(i+1, n_signals):
                    try:
                        comparison = self.compare_signals(signal_names[i], signal_names[j])
                        similarity_matrix[i, j] = comparison['similarity_score']
                        similarity_matrix[j, i] = comparison['similarity_score']  # 对称矩阵
                    except Exception:
                        similarity_matrix[i, j] = np.nan
                        similarity_matrix[j, i] = np.nan
            
            plt.figure(figsize=(10, 8))
            mask = np.triu(np.ones_like(similarity_matrix, dtype=bool), k=1)
            sns.heatmap(similarity_matrix, annot=True, fmt=".1f", cmap="YlGnBu",
                        xticklabels=signal_names, yticklabels=signal_names,
                        vmin=0, vmax=100, mask=mask)
            
            # 设置标题，使用中文字体
            if CHINESE_FONT:
                plt.title(f"{self.signal_type.upper()}信号相似度矩阵 (%)", 
                         fontproperties=CHINESE_FONT, fontsize=14)
            else:
                plt.title(f"{self.signal_type.upper()}信号相似度矩阵 (%)", fontsize=14)
                
            plt.tight_layout()
            plt.savefig(os.path.join(output_dir, "similarity_matrix.png"), dpi=300)
            plt.close()
        
        # 4. 波动性分析图
        plt.figure(figsize=(12, 6))
        
        # 准备数据
        wave_df = pd.DataFrame()
        for name, stats in self.analysis_results.items():
            wave_subset = {
                'name': name,
                'mean_rate': stats['mean_rate'],
                'mean_acceleration': stats['mean_acceleration'],
                'zero_crossing_rate': stats['zero_crossing_rate'] * 100  # 转为百分比
            }
            wave_df = pd.concat([wave_df, pd.DataFrame([wave_subset])], ignore_index=True)
        
        # 中文化指标名称
        metric_names = {
            'mean_rate': '平均变化率',
            'mean_acceleration': '平均加速度',
            'zero_crossing_rate': '过零率(%)'
        }
        
        # 变换数据格式并重命名列
        wave_df_melted = pd.melt(wave_df, id_vars=['name'], 
                              value_vars=['mean_rate', 'mean_acceleration', 'zero_crossing_rate'],
                              var_name='metric', value_name='value')
        
        # 将指标名称转换为中文显示
        wave_df_melted['metric'] = wave_df_melted['metric'].map(metric_names)
        
        # 绘图
        sns.barplot(x='name', y='value', hue='metric', data=wave_df_melted)
        
        # 设置标题和标签，使用中文字体
        if CHINESE_FONT:
            plt.title(f"{self.signal_type.upper()}信号波动性分析", 
                     fontproperties=CHINESE_FONT, fontsize=14)
            plt.xlabel("信号", fontproperties=CHINESE_FONT, fontsize=12)
            plt.ylabel("值", fontproperties=CHINESE_FONT, fontsize=12)
            # 设置图例字体
            legend = plt.legend(title="指标")
            plt.setp(legend.get_title(), fontproperties=CHINESE_FONT)
        else:
            plt.title(f"{self.signal_type.upper()}信号波动性分析", fontsize=14)
            plt.xlabel("信号", fontsize=12)
            plt.ylabel("值", fontsize=12)
            plt.legend(title="指标")
            
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, "wave_analysis.png"), dpi=300)
        plt.close()
    
    def _save_results_to_csv(self, csv_file: str) -> None:
        """
        将分析结果保存为CSV格式
        
        参数:
            csv_file: CSV文件路径
        """
        if not self.analysis_results:
            return
        
        # 找出所有可能的字段
        all_fields = set()
        for stats in self.analysis_results.values():
            all_fields.update(stats.keys())
        
        # 将时间戳放在最后
        if 'timestamp' in all_fields:
            all_fields.remove('timestamp')
            fields = sorted(list(all_fields)) + ['timestamp']
        else:
            fields = sorted(list(all_fields))
        
        # 写入CSV
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # 写入标题行
            writer.writerow(['name'] + fields)
            
            # 写入数据行
            for name, stats in self.analysis_results.items():
                row = [name]
                for field in fields:
                    row.append(stats.get(field, ''))
                writer.writerow(row)
        
        logger.info(f"统计分析结果已保存到CSV文件 {csv_file}")


class ReportGenerator:
    """结果报告生成器，支持多种格式的报告生成"""
    
    def __init__(self, output_dir: str = None, report_title: str = "信号处理系统报告"):
        """
        初始化报告生成器
        
        参数:
            output_dir: 输出目录
            report_title: 报告标题
        """
        self.output_dir = output_dir or os.getcwd()
        self.report_title = report_title
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.sections = []
        
        # 创建输出目录
        os.makedirs(self.output_dir, exist_ok=True)
        
        logger.info(f"初始化报告生成器，输出目录: {self.output_dir}")
    
    def add_section(self, title: str, content: str = None, 
                  data: Dict = None, image_path: str = None) -> None:
        """
        添加报告部分
        
        参数:
            title: 部分标题
            content: 文本内容
            data: 数据字典
            image_path: 图像路径
        """
        section = {
            'title': title,
            'content': content,
            'data': data,
            'image_path': image_path,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.sections.append(section)
        logger.info(f"添加报告部分: {title}")
    
    def generate_text_report(self) -> str:
        """
        生成文本格式报告
        
        返回:
            str: 报告文件路径
        """
        report_file = os.path.join(self.output_dir, f"report_{self.timestamp}.txt")
        
        with open(report_file, 'w', encoding='utf-8') as f:
            # 报告标题
            f.write("=" * 80 + "\n")
            f.write(" " * ((80 - len(self.report_title)) // 2) + self.report_title + "\n")
            f.write("=" * 80 + "\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("-" * 80 + "\n\n")
            
            # 添加各部分内容
            for section in self.sections:
                f.write(section['title'] + "\n")
                f.write("=" * len(section['title']) + "\n")
                
                if section['content']:
                    f.write(section['content'] + "\n")
                
                if section['data']:
                    f.write("\n数据:\n")
                    for key, value in section['data'].items():
                        if isinstance(value, (int, float)):
                            f.write(f"  {key}: {value}\n")
                        elif isinstance(value, dict):
                            f.write(f"  {key}:\n")
                            for k, v in value.items():
                                f.write(f"    {k}: {v}\n")
                        else:
                            f.write(f"  {key}: {value}\n")
                
                if section['image_path']:
                    f.write(f"\n图像: {section['image_path']}\n")
                
                f.write("\n" + "-" * 80 + "\n\n")
        
        logger.info(f"文本报告已生成: {report_file}")
        return report_file
    
    def generate_html_report(self) -> str:
        """
        生成HTML格式报告
        
        返回:
            str: 报告文件路径
        """
        report_file = os.path.join(self.output_dir, f"report_{self.timestamp}.html")
        
        with open(report_file, 'w', encoding='utf-8') as f:
            # HTML头部
            f.write("<!DOCTYPE html>\n")
            f.write("<html>\n<head>\n")
            f.write(f"<title>{self.report_title}</title>\n")
            f.write("<meta charset='utf-8'>\n")
            f.write("<style>\n")
            f.write("body { font-family: Arial, sans-serif; margin: 20px; }\n")
            f.write("h1 { color: #2c3e50; text-align: center; }\n")
            f.write("h2 { color: #3498db; border-bottom: 1px solid #3498db; padding-bottom: 5px; }\n")
            f.write("table { border-collapse: collapse; width: 100%; margin: 15px 0; }\n")
            f.write("th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }\n")
            f.write("th { background-color: #f2f2f2; }\n")
            f.write("img { max-width: 100%; height: auto; margin: 10px 0; }\n")
            f.write("pre { background-color: #f8f9fa; padding: 10px; border-radius: 5px; overflow-x: auto; }\n")
            f.write("</style>\n")
            f.write("</head>\n<body>\n")
            
            # 报告标题
            f.write(f"<h1>{self.report_title}</h1>\n")
            f.write(f"<p style='text-align: center;'>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>\n")
            
            # 目录
            f.write("<h2>目录</h2>\n")
            f.write("<ul>\n")
            for i, section in enumerate(self.sections):
                f.write(f"<li><a href='#section{i+1}'>{section['title']}</a></li>\n")
            f.write("</ul>\n")
            
            # 添加各部分内容
            for i, section in enumerate(self.sections):
                f.write(f"<h2 id='section{i+1}'>{section['title']}</h2>\n")
                
                if section['content']:
                    f.write(f"<pre>{section['content']}</pre>\n")
                
                if section['data']:
                    f.write("<h3>数据</h3>\n")
                    f.write("<table>\n")
                    f.write("<tr><th>参数</th><th>值</th></tr>\n")
                    
                    for key, value in section['data'].items():
                        if isinstance(value, dict):
                            f.write(f"<tr><td colspan='2'><b>{key}</b></td></tr>\n")
                            for k, v in value.items():
                                f.write(f"<tr><td style='padding-left: 20px;'>{k}</td><td>{v}</td></tr>\n")
                        else:
                            f.write(f"<tr><td>{key}</td><td>{value}</td></tr>\n")
                    
                    f.write("</table>\n")
                
                if section['image_path']:
                    # 获取相对路径或绝对路径
                    if os.path.isabs(section['image_path']):
                        img_path = section['image_path']
                    else:
                        img_path = os.path.relpath(section['image_path'], self.output_dir)
                    
                    f.write("<div style='text-align: center;'>\n")
                    f.write(f"<img src='{img_path}' alt='{section['title']}' />\n")
                    f.write("</div>\n")
            
            # HTML尾部
            f.write("</body>\n</html>\n")
        
        logger.info(f"HTML报告已生成: {report_file}")
        return report_file
    
    def generate_all_reports(self) -> Dict[str, str]:
        """
        生成所有格式的报告
        
        返回:
            Dict[str, str]: 报告文件路径字典
        """
        reports = {
            'text': self.generate_text_report(),
            'html': self.generate_html_report()
        }
        
        logger.info(f"已生成所有格式的报告: {reports}")
        return reports 