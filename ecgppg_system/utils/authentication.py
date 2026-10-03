#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
身份验证模块（已废弃 · 保留供参考，请勿在新代码中调用）
=========================================================================

本模块是项目早期原型中的认证实现，**当前已无任何生产调用方**：

* 应用实际使用的是 :mod:`model_example.authentication`
  —— ``web_auth`` 只从那里导入 ``authenticate_single_signal``。
* 本模块的 ``Authenticator`` / ``compute_signal_similarity`` /
  ``verify_model_prediction`` 在仓库内仅有自引用；唯一的例外是
  ``tests/test_authentication.py``，而它**刻意**导入本模块，是为了把下面两处
  缺陷固定成回归测试（characterization test），并不代表本模块可用。

已知缺陷（已由测试固化，见 ``tests/test_authentication.py::TestKnownLimitations``）：

1. ``Authenticator.__init__`` 会构造 ``SignalPlotter``，后者依赖
   ``settings.DPI`` / ``settings.FIGURE_WIDTH`` / ``settings.FIGURE_HEIGHT``，
   而这三个配置项在当前 ``ecgppg_system.config.settings`` 中并不存在 ——
   因此 ``Authenticator(...)`` 一构造就抛 ``AttributeError``。
2. ``compute_signal_similarity(..., method='dtw')`` 走 ``fastdtw`` 0.3.4，
   它会把标量喂给 scipy ≥ 1.16 的 ``scipy.spatial.distance.euclidean``，
   触发 ``Input vector should be 1-D``，随后被函数内部 ``except`` 吞掉，
   最终**静默返回 0.0**（``method='all'`` 时同样被拖低）。

保留而不删除的原因：这是项目原始贡献者提交的实现，删除会抹去他人的代码与
历史；标注废弃可以让后来者少踩一遍同样的坑。

若确需恢复使用，请先修掉上述两点，再把调用方从
``model_example.authentication`` 迁回本模块。
"""

import gc
import traceback
import numpy as np
import matplotlib.pyplot as plt
import torch
from matplotlib.gridspec import GridSpec

from ecgppg_system.data.transformers.signal_analyzer import SignalAnalyzer
from ecgppg_system.visualization.signal_plotter import SignalPlotter
from ecgppg_system.utils.logger import logger

class Authenticator:
    """
    生物信号身份验证器
    
    使用动态时间规整（DTW）算法对信号进行比较，
    评估待验证信号与参考信号的相似度。
    """
    
    def __init__(self, signal_type='ecg', similarity_threshold=65.0):
        """
        初始化身份验证器
        
        参数:
            signal_type (str): 信号类型 ('ecg' 或 'ppg')
            similarity_threshold (float): 身份验证相似度阈值（百分比）
        """
        self.signal_type = signal_type.lower()
        self.similarity_threshold = similarity_threshold
        self.reference_signal = None
        self.reference_periods = None
        self.signal_analyzer = SignalAnalyzer(signal_type=signal_type)
        self.plotter = SignalPlotter()
        
        logger.info(f"初始化{signal_type.upper()}信号身份验证器，相似度阈值: {similarity_threshold}%")
    
    def find_period(self, signal):
        """
        查找信号的周期
        
        参数:
            signal (array): 信号数据
            
        返回:
            int: 信号周期（采样点数）
        """
        # 使用信号分析器检测信号周期
        period = self.signal_analyzer.find_period(signal)
        logger.info(f"检测到{self.signal_type.upper()}信号周期: {period}采样点")
        return period
    
    def split_by_periods(self, signal, period=None, num_periods=5):
        """
        将信号分割为多个周期
        
        参数:
            signal (array): 信号数据
            period (int, optional): 周期大小（采样点数）
            num_periods (int): 要返回的周期数量
            
        返回:
            list: 信号周期列表
        """
        # 如果未提供周期，自动检测
        if period is None:
            period = self.find_period(signal)
        
        # 使用信号分析器提取周期
        periods = self.signal_analyzer.extract_periods(signal, period)
        
        # 限制返回的周期数量
        if len(periods) > num_periods:
            periods = periods[:num_periods]
        
        if len(periods) < num_periods:
            logger.warning(f"请求{num_periods}个周期，但只找到{len(periods)}个")
        
        logger.info(f"从{self.signal_type.upper()}信号中提取了{len(periods)}个周期")
        return periods
    
    def set_reference(self, reference_signal, period=None, num_periods=10):
        """
        设置参考信号
        
        参数:
            reference_signal (array): 参考信号数据
            period (int, optional): 周期大小（采样点数）
            num_periods (int): 要提取的周期数量
            
        返回:
            bool: 是否成功设置
        """
        try:
            # 检查参考信号是否有效
            if reference_signal is None or len(reference_signal) == 0:
                logger.error("参考信号无效或为空")
                return False
            
            # 保存参考信号
            self.reference_signal = reference_signal
            
            # 如果未提供周期，自动检测
            if period is None:
                period = self.find_period(reference_signal)
            
            # 提取参考信号周期
            self.reference_periods = self.split_by_periods(
                reference_signal, 
                period=period, 
                num_periods=num_periods
            )
            
            if len(self.reference_periods) == 0:
                logger.error("无法从参考信号中提取周期")
                return False
                
            logger.info(f"成功设置{self.signal_type.upper()}参考信号，提取了{len(self.reference_periods)}个周期")
            return True
            
        except Exception as e:
            logger.exception(f"设置参考信号时出错: {str(e)}")
            return False
    
    def authenticate(self, query_signal, period=None, num_periods=5, visualize=False):
        """
        验证查询信号与参考信号的匹配度
        
        参数:
            query_signal (array): 待验证的查询信号
            period (int, optional): 周期大小（采样点数）
            num_periods (int): 要提取的周期数量
            visualize (bool): 是否可视化结果
            
        返回:
            dict: 验证结果
        """
        try:
            # 检查参考信号是否已设置
            if self.reference_periods is None or len(self.reference_periods) == 0:
                error_msg = "未设置参考信号，请先调用set_reference方法"
                logger.error(error_msg)
                return {"success": False, "message": error_msg, "similarity": 0, "threshold": self.similarity_threshold}
            
            # 检查查询信号是否有效
            if query_signal is None or len(query_signal) == 0:
                error_msg = "查询信号无效或为空"
                logger.error(error_msg)
                return {"success": False, "message": error_msg, "similarity": 0, "threshold": self.similarity_threshold}
            
            # 验证参考信号和查询信号是否是同一数据集
            if isinstance(query_signal, np.ndarray) and isinstance(self.reference_signal, np.ndarray):
                # 如果长度相同，检查是否完全相同
                if len(query_signal) == len(self.reference_signal) and np.array_equal(query_signal, self.reference_signal):
                    logger.warning("检测到查询信号与参考信号完全相同，这可能表明使用了相同的数据集进行测试")
                    logger.warning("为防止误导的相似度结果，将引入轻微扰动到查询信号")
                    # 添加微小扰动以避免完全匹配
                    noise_level = 0.01 * np.std(query_signal)
                    query_signal = query_signal + np.random.normal(0, noise_level, size=query_signal.shape)
                    logger.info(f"已添加随机噪声到查询信号，噪声水平: {noise_level:.6f}")
            
            # 提取查询信号周期
            query_periods = self.split_by_periods(
                query_signal, 
                period=period, 
                num_periods=num_periods
            )
            
            if len(query_periods) == 0:
                error_msg = "无法从查询信号中提取周期"
                logger.error(error_msg)
                return {"success": False, "message": error_msg, "similarity": 0, "threshold": self.similarity_threshold}
            
            # 计算相似度
            similarities = []
            alignment_paths = []
            
            # 取两个列表中较小的长度
            num_to_compare = min(len(self.reference_periods), len(query_periods))
            logger.info(f"比较{num_to_compare}个信号周期")
            
            # 存储每个周期的详细对比结果
            period_comparisons = []
            
            for i in range(num_to_compare):
                ref_period = self.reference_periods[i]
                query_period = query_periods[i]
                
                # 使用DTW计算相似度
                # 确保输入是一维数组
                ref_period_1d = np.asarray(ref_period).flatten()
                query_period_1d = np.asarray(query_period).flatten()
                
                # 输出信号周期的基本统计信息，便于调试
                ref_stats = {
                    "mean": np.mean(ref_period_1d),
                    "std": np.std(ref_period_1d),
                    "min": np.min(ref_period_1d),
                    "max": np.max(ref_period_1d),
                    "len": len(ref_period_1d)
                }
                
                query_stats = {
                    "mean": np.mean(query_period_1d),
                    "std": np.std(query_period_1d),
                    "min": np.min(query_period_1d),
                    "max": np.max(query_period_1d),
                    "len": len(query_period_1d)
                }
                
                logger.info(f"周期 {i+1} - 参考信号统计: {ref_stats}, 查询信号统计: {query_stats}")
                
                # 计算信号分布差异系数
                distribution_diff = abs(ref_stats["std"] - query_stats["std"]) / max(ref_stats["std"], query_stats["std"]) if max(ref_stats["std"], query_stats["std"]) > 0 else 0
                if distribution_diff > 0.5:
                    logger.warning(f"周期 {i+1} 的信号分布差异较大 ({distribution_diff:.2f})，可能不是来自同一用户")
                
                # 确保数组不包含NaN值
                ref_period_1d = np.nan_to_num(ref_period_1d)
                query_period_1d = np.nan_to_num(query_period_1d)
                
                # 标准化数据，减少幅度差异的影响
                ref_norm = (ref_period_1d - np.mean(ref_period_1d)) / (np.std(ref_period_1d) + 1e-10)
                query_norm = (query_period_1d - np.mean(query_period_1d)) / (np.std(query_period_1d) + 1e-10)
                
                # 计算多种相似度指标
                # 1. DTW距离及相似度
                try:
                    # 确保输入向量是一维的
                    if ref_norm.ndim > 1:
                        ref_norm = np.ravel(ref_norm)
                    if query_norm.ndim > 1:
                        query_norm = np.ravel(query_norm)
                    
                    # 确保数据不是复数类型
                    ref_norm = np.real(ref_norm).astype(np.float64)
                    query_norm = np.real(query_norm).astype(np.float64)
                    
                    # 检查输入是否包含NaN或无穷值
                    if np.isnan(ref_norm).any() or np.isinf(ref_norm).any():
                        ref_norm = np.nan_to_num(ref_norm)
                    if np.isnan(query_norm).any() or np.isinf(query_norm).any():
                        query_norm = np.nan_to_num(query_norm)
                    
                    # 记录维度信息，用于调试
                    logger.info(f"ref_norm维度: {ref_norm.ndim}, shape: {ref_norm.shape}, 类型: {ref_norm.dtype}")
                    logger.info(f"query_norm维度: {query_norm.ndim}, shape: {query_norm.shape}, 类型: {query_norm.dtype}")

                    # 处理长度不一致问题
                    min_len = min(len(ref_norm), len(query_norm))
                    ref_norm_len = ref_norm[:min_len].copy()
                    query_norm_len = query_norm[:min_len].copy()
                    
                    # 使用dtw-python库
                    try:
                        from dtw import dtw
                        alignment = dtw(ref_norm_len, query_norm_len, keep_internals=True)
                        distance = alignment.normalizedDistance
                        logger.info("成功使用dtw-python计算距离")
                    except Exception as e:
                        logger.warning(f"dtw-python调用失败: {str(e)}，尝试使用简单欧氏距离替代")
                        # 使用简单的欧氏距离
                        euclidean_dist = np.sqrt(np.sum((ref_norm_len - query_norm_len) ** 2))
                        distance = euclidean_dist
                        logger.info(f"使用欧氏距离作为备选: {distance:.4f}")
                    
                    # 归一化DTW距离
                    max_dist = len(ref_norm) + len(query_norm)  # 最坏情况的DTW距离
                    normalized_distance = distance / max_dist if max_dist > 0 else 1.0
                    
                    # 将距离转换为相似度得分 (0-100%)
                    dtw_similarity = (1 - normalized_distance) * 100
                    
                    # 添加余弦相似度作为辅助指标
                    cosine_similarity = 0.0
                    try:
                        # 处理零向量情况
                        if np.all(ref_norm_len == 0) or np.all(query_norm_len == 0):
                            cosine_similarity = 0.0
                        else:
                            dot_product = np.dot(ref_norm_len, query_norm_len)
                            norm_ref = np.linalg.norm(ref_norm_len)
                            norm_query = np.linalg.norm(query_norm_len)
                            
                            if norm_ref > 0 and norm_query > 0:
                                cosine_similarity = (dot_product / (norm_ref * norm_query)) * 100
                            else:
                                cosine_similarity = 0.0
                                
                        logger.info(f"余弦相似度: {cosine_similarity:.2f}%")
                    except Exception as e:
                        logger.error(f"余弦相似度计算错误: {str(e)}")
                        cosine_similarity = 0.0
                    
                    # 计算最终相似度（DTW和余弦相似度的加权平均）
                    final_similarity = 0.7 * dtw_similarity + 0.3 * cosine_similarity
                    
                    logger.info(f"DTW相似度: {dtw_similarity:.2f}%, 余弦相似度: {cosine_similarity:.2f}%, 最终相似度: {final_similarity:.2f}%")
                    
                except Exception as e:
                    logger.error(f"周期 {i+1} 计算相似度失败: {str(e)}")
                    continue
            
            if not similarities:
                error_msg = "无法计算任何相似度，身份验证失败"
                logger.error(error_msg)
                return {"success": False, "message": error_msg, "similarity": 0, "threshold": self.similarity_threshold}
            
            # 综合所有周期的相似度
            # 使用加权平均，较新的周期权重更高
            weights = np.linspace(0.5, 1.0, len(similarities))
            weights = weights / np.sum(weights)  # 归一化权重
            
            # 计算加权平均相似度
            weighted_similarity = np.average([comp["combined_similarity"] for comp in period_comparisons], weights=weights)
            
            # 限制相似度在0-100范围内
            weighted_similarity = max(0, min(100, weighted_similarity))
            
            # 判断认证成功或失败
            success = weighted_similarity >= self.similarity_threshold
            
            # 动态调整认证阈值
            adjusted_threshold = self.similarity_threshold
            
            # 基于信号质量和一致性调整阈值
            # 1. 计算周期间相似度的一致性
            if len(similarities) > 1:
                similarity_std = np.std([comp["combined_similarity"] for comp in period_comparisons])
                # 如果周期间差异很大，提高阈值
                if similarity_std > 15:  # 15%的标准差被认为是较高的不一致性
                    adjustment = min(10, similarity_std / 3)  # 最多提高10%
                    adjusted_threshold += adjustment
                    logger.info(f"周期间相似度不一致性较高(标准差={similarity_std:.2f}%)，阈值提高了{adjustment:.2f}%")
            
            # 2. 基于分布差异调整阈值
            avg_distribution_diff = np.mean([comp["distribution_diff"] for comp in period_comparisons])
            if avg_distribution_diff > 0.3:
                adjustment = min(5, avg_distribution_diff * 10)
                adjusted_threshold += adjustment
                logger.info(f"信号分布差异较大({avg_distribution_diff:.2f})，阈值提高了{adjustment:.2f}%")
            
            # 确保调整后的阈值在合理范围内
            adjusted_threshold = min(95, max(50, adjusted_threshold))
            
            # 重新评估认证结果
            final_success = weighted_similarity >= adjusted_threshold
            
            # 如果相似度异常高（>95%），进行额外检查
            if weighted_similarity > 95:
                logger.warning(f"检测到异常高的相似度({weighted_similarity:.2f}%)，进行额外验证")
                # 检查是否可能使用了相同的数据
                same_data_likelihood = "高" if avg_distribution_diff < 0.1 else "中" if avg_distribution_diff < 0.3 else "低"
                logger.warning(f"使用相同数据的可能性: {same_data_likelihood} (分布差异={avg_distribution_diff:.2f})")
                
                # 对于高可能性的情况，适当降低相似度
                if same_data_likelihood == "高":
                    weighted_similarity = max(80, weighted_similarity * 0.9)
                    logger.warning(f"由于可能使用了相同数据，相似度已调整为{weighted_similarity:.2f}%")
                    final_success = weighted_similarity >= adjusted_threshold
            
            result = {
                "success": final_success,
                "original_success": success,
                "similarity": weighted_similarity,
                "threshold": adjusted_threshold,
                "original_threshold": self.similarity_threshold,
                "period_comparisons": period_comparisons,
                "num_periods_compared": len(similarities),
                "message": "身份认证成功" if final_success else "身份认证失败"
            }
            
            # 输出认证结果
            threshold_msg = ""
            if adjusted_threshold != self.similarity_threshold:
                threshold_msg = f" (原始阈值: {self.similarity_threshold}%)"
            
            logger.info(f"身份认证{'成功' if final_success else '失败'}, 相似度: {weighted_similarity:.2f}%, "
                       f"阈值: {adjusted_threshold}%{threshold_msg}")
            
            # 可视化认证结果
            if visualize:
                self.visualize_authentication(self.reference_periods, query_periods, 
                                            similarities, alignment_paths, result)
            
            return result
        
        except Exception as e:
            logger.exception(f"身份认证过程出现异常: {str(e)}")
            return {
                "success": False,
                "message": f"认证过程出错: {str(e)}",
                "similarity": 0,
                "threshold": self.similarity_threshold
            }
    
    def visualize_authentication(self, reference_periods, query_periods, similarities, alignment_paths, result):
        """
        可视化身份验证结果
        
        参数:
            reference_periods: 参考信号周期列表
            query_periods: 查询信号周期列表
            similarities: 相似度列表
            alignment_paths: DTW对齐路径列表
            result: 验证结果
        """
        try:
            # 创建更复杂的图形布局
            fig = plt.figure(figsize=(14, 8))
            gs = GridSpec(2, 3, figure=fig)
            
            # 主图 - 信号对比
            ax_main = fig.add_subplot(gs[0, :])
            
            # 绘制参考信号和查询信号
            for i in range(len(reference_periods)):
                ax_main.plot(reference_periods[i], 'b-', label=f"参考信号周期 {i+1}", linewidth=1.5)
                ax_main.plot(query_periods[i], 'r-', label=f"查询信号周期 {i+1}", linewidth=1.5)
            
            # 设置标题和标签
            ax_main.set_title("参考信号和查询信号对比", fontsize=15)
            ax_main.set_xlabel("样本点", fontsize=12)
            ax_main.set_ylabel("振幅", fontsize=12)
            ax_main.grid(True, alpha=0.3)
            ax_main.legend(fontsize=12)
            
            # 提取结果指标
            success = result.get("success", False)
            similarity = result.get("similarity", 0)
            threshold = result.get("threshold", 0)
            original_threshold = result.get("original_threshold", threshold)
            metrics = result.get("metrics", {})
            
            # 绘制相似度仪表盘
            ax_gauge = fig.add_subplot(gs[1, 0], polar=True)
            _plot_similarity_gauge(ax_gauge, similarity, threshold, "相似度评分")
            
            # 信号统计数据
            ax_stats = fig.add_subplot(gs[1, 1])
            ax_stats.axis('off')
            
            # 统计信息表格
            stats_text = "信号统计信息:\n\n"
            stats_text += f"样本长度: {len(similarities)}\n"
            stats_text += f"相似度范围: {np.ptp(similarities):.4f}\n"
            
            if 'signal_range' in metrics:
                stats_text += f"信号范围: {metrics['signal_range']:.4f}\n"
            
            if 'var_ratio' in metrics and metrics['var_ratio'] is not None:
                stats_text += f"方差比例: {metrics['var_ratio']:.4f}\n"
            
            # 如果阈值被调整了，显示调整信息
            if original_threshold != threshold:
                stats_text += f"\n阈值调整: {original_threshold:.2f}% → {threshold:.2f}%"
                stats_text += "\n(基于信号质量动态调整)"
            
            ax_stats.text(0.1, 0.5, stats_text, horizontalalignment='left', 
                         verticalalignment='center', fontsize=12, transform=ax_stats.transAxes)
            
            # 指标评分详情
            ax_metrics = fig.add_subplot(gs[1, 2])
            ax_metrics.axis('off')
            
            metrics_text = "指标详情:\n\n"
            
            if 'cosine_similarity' in metrics:
                metrics_text += f"余弦相似度: {metrics['cosine_similarity']:.4f}\n"
            
            if 'dtw_similarity' in metrics:
                metrics_text += f"DTW相似度: {metrics['dtw_similarity']:.4f}\n"
            
            # 结果评价
            metrics_text += f"\n验证结果: {'通过' if success else '未通过'}\n"
            metrics_text += f"相似度: {similarity:.2f}%\n"
            metrics_text += f"阈值: {threshold:.2f}%"
            
            # 根据验证结果设置颜色
            result_color = 'green' if success else 'red'
            
            ax_metrics.text(0.1, 0.5, metrics_text, horizontalalignment='left', 
                           verticalalignment='center', fontsize=12, transform=ax_metrics.transAxes,
                           color=result_color if 'verification' in metrics_text.lower() else 'black')
            
            # 添加总结性评价
            if success:
                if similarity > 90:
                    summary = "身份验证结果: 高度匹配"
                else:
                    summary = "身份验证结果: 匹配"
            else:
                if similarity > threshold - 10:
                    summary = "身份验证结果: 接近匹配但未通过阈值"
                else:
                    summary = "身份验证结果: 不匹配"
                
            fig.suptitle(summary, fontsize=16, color=result_color, fontweight='bold')
            
            # 优化布局
            plt.tight_layout()
            plt.subplots_adjust(top=0.93)
            
            # 显示图形
            plt.show()
            
        except Exception as e:
            logger.error(f"可视化身份验证结果时出错: {str(e)}")


def _plot_similarity_gauge(ax, value, threshold, title, color_good='green', color_bad='red'):
    """
    在极坐标轴上绘制指针式相似度仪表盘。

    绘制口径与 ``visualization.auth_visualizer.AuthenticationVisualizer._create_gauge``
    保持一致：``value`` / ``threshold`` 均按百分比（0~100）解释。

    参数:
        ax: matplotlib 极坐标子图（``polar=True``）
        value: 当前相似度（百分比）
        threshold: 判定阈值（百分比）
        title: 仪表盘标题
        color_good: 达标时的指针颜色
        color_bad: 未达标时的指针颜色
    """
    theta = np.linspace(0, 180, 100) * np.pi / 180
    r = np.ones_like(theta)

    # 极坐标参数：0 度朝正上方、逆时针展开，只保留上半圈
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_rlim(0, 1.5)
    ax.set_thetamin(0)
    ax.set_thetamax(180)

    # 盘面背景
    ax.fill_between(theta, 0, r, color='lightgray', alpha=0.3)

    # 阈值刻度线
    threshold_angle = threshold * np.pi / 100
    ax.plot([threshold_angle, threshold_angle], [0, 1], 'k--', linewidth=2)

    # 当前值指针
    value_angle = min(value, 100) * np.pi / 100
    color = color_good if value >= threshold else color_bad
    ax.arrow(
        np.pi / 2, 0, (value_angle - np.pi / 2), 0.8,
        head_width=0.1, head_length=0.1, fc=color, ec=color, linewidth=2,
    )

    # 刻度标签
    angles = np.array([0, 45, 90, 135, 180]) * np.pi / 180
    ax.set_xticks(angles)
    ax.set_xticklabels(['0%', '25%', '50%', '75%', '100%'])
    plt.setp(ax.yaxis.get_ticklabels(), visible=False)
    ax.set_title(title, pad=15, fontsize=14)

    # 数值与判定结果
    verdict = '通过' if value >= threshold else '未通过'
    ax.text(
        np.pi / 2, -0.2, f"{value:.1f}% ({verdict})",
        horizontalalignment='center', fontsize=12, color=color, fontweight='bold',
    )

    # 阈值标签
    ax.text(
        threshold_angle, 1.1, f"阈值: {threshold:.1f}%",
        horizontalalignment='center', fontsize=10,
        rotation=threshold * 180 / 100 - 90,
    )


def compute_signal_similarity(signal1, signal2, method='all'):
    """
    计算两个信号之间的相似度
    
    参数:
        signal1, signal2: 待比较的信号数组
        method: 使用的方法 ('dtw', 'correlation', 'cosine', 'all')
        
    返回:
        float: 归一化相似度(0-1)
    """
    import numpy as np
    from scipy.spatial.distance import euclidean, cosine
    from scipy.stats import pearsonr
    from fastdtw import fastdtw
    from scipy import signal as scipy_signal
    
    # 预处理步骤
    def normalize_signal(sig):
        # 确保数据格式正确
        if not isinstance(sig, np.ndarray):
            sig = np.array(sig)
        
        # 转换为一维数组
        if sig.ndim > 1:
            sig = sig.flatten()
        
        # 去除NaN和无穷大
        sig = np.nan_to_num(sig)
        
        # 如果是空数组或全为零，直接返回
        if len(sig) == 0 or np.all(sig == 0):
            return np.zeros(1)
        
        # 信号去除线性趋势
        sig = scipy_signal.detrend(sig)
        
        # Z-score归一化，确保均值为0，标准差为1
        if np.std(sig) > 1e-10:
            sig = (sig - np.mean(sig)) / np.std(sig)
        
        return sig
    
    # 预处理信号
    signal1_norm = normalize_signal(signal1)
    signal2_norm = normalize_signal(signal2)
    
    # 确保两个信号长度一致
    min_len = min(len(signal1_norm), len(signal2_norm))
    if min_len == 0:
        return 0.0  # 无法计算相似度
    
    signal1_norm = signal1_norm[:min_len]
    signal2_norm = signal2_norm[:min_len]
    
    # 计算不同的相似度指标
    similarities = {}
        
    # DTW相似度
    if method in ['dtw', 'all']:
        try:
            distance, _ = fastdtw(signal1_norm, signal2_norm, dist=euclidean)
            # 归一化DTW距离
            max_dist = min_len * 2  # 最坏情况
            normalized_dist = distance / max_dist if max_dist > 0 else 1.0
            # 转换为相似度 (0-1)
            similarities['dtw'] = 1.0 - min(normalized_dist, 1.0)
        except Exception as e:
            logger.warning(f"DTW相似度计算失败: {str(e)}")
            similarities['dtw'] = 0.0
        
    # 相关系数
    if method in ['correlation', 'all']:
        try:
            corr, _ = pearsonr(signal1_norm, signal2_norm)
            # 转换为[0,1]范围
            similarities['correlation'] = (corr + 1) / 2
        except Exception as e:
            logger.warning(f"相关系数计算失败: {str(e)}")
            similarities['correlation'] = 0.0
    
    # 余弦相似度
    if method in ['cosine', 'all']:
        try:
            cos_dist = cosine(signal1_norm, signal2_norm)
            # 余弦距离转换为相似度 (0-1)
            similarities['cosine'] = 1.0 - min(cos_dist, 1.0)
        except Exception as e:
            logger.warning(f"余弦相似度计算失败: {str(e)}")
            similarities['cosine'] = 0.0
        
    # 计算最终相似度
    if method == 'all':
        # 加权平均，对不同指标赋予不同权重
        weights = {
            'dtw': 0.5,         # DTW对形态差异更敏感
            'correlation': 0.3,  # 相关系数对趋势匹配更好
            'cosine': 0.2       # 余弦相似度作为补充
        }
        
        weighted_sum = sum(similarities[m] * weights[m] for m in similarities)
        total_weight = sum(weights[m] for m in similarities if m in similarities)
            
        if total_weight > 0:
            final_similarity = weighted_sum / total_weight
        else:
            final_similarity = 0.0
    else:
        # 使用指定的单一方法
        final_similarity = similarities.get(method, 0.0)
    
    # 返回相似度值 (0-1范围)
    return min(max(final_similarity, 0.0), 1.0)

def verify_model_prediction(model, reference_data, query_data, max_retries=3):
    """
    验证模型预测结果与查询数据之间的相似度
    
    参数:
        model (torch.nn.Module): 用于预测的模型
        reference_data (numpy.ndarray): 参考数据
        query_data (numpy.ndarray): 查询数据
        max_retries (int): 最大重试次数
        
    返回:
        dict: 验证结果
    """
    result = {
        'success': False,
        'similarity': 0.0,
        'similarity_details': {
            'dtw': None,
            'cosine': None,
            'correlation': None
        },
        'error': None,
        'pred_length': 0,
        'query_length': 0
    }
    
    try:
        # 输入验证
        if reference_data is None or query_data is None:
            result['error'] = "参考数据或查询数据不能为空"
            logger.error(result['error'])
            return result
        
        # 确保数据是numpy数组
        if not isinstance(reference_data, np.ndarray):
            reference_data = np.array(reference_data)
        if not isinstance(query_data, np.ndarray):
            query_data = np.array(query_data)
        
        # 确保数据是一维的
        reference_data = reference_data.flatten()
        query_data = query_data.flatten()
        
        # 检查数据长度
        if len(reference_data) < 10 or len(query_data) < 10:
            result['error'] = "数据长度太短，无法进行可靠预测"
            logger.error(result['error'])
            return result
        
        # 确保模型处于评估模式
        model.eval()
        
        # 获取模型设备
        device = next(model.parameters()).device
        
        # 预处理数据
        ref_tensor = torch.tensor(reference_data, dtype=torch.float32).reshape(1, -1, 1)
        ref_tensor = ref_tensor.to(device)
        
        # 进行预测
        prediction = None
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                with torch.no_grad():
                    prediction = model(ref_tensor)
                    if prediction is None or prediction.nelement() == 0:
                        raise ValueError("模型返回了空预测")
                    prediction = prediction.cpu().numpy().flatten()
                break
            except Exception as e:
                retry_count += 1
                logger.warning(f"预测尝试 {retry_count}/{max_retries} 失败: {str(e)}")
                if retry_count >= max_retries:
                    result['error'] = f"模型预测失败: {str(e)}"
                    return result
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    gc.collect()
        
        # 记录预测和查询数据长度
        result['pred_length'] = len(prediction)
        result['query_length'] = len(query_data)
        
        # 确保长度匹配
        min_length = min(len(prediction), len(query_data))
        prediction = prediction[:min_length]
        query_data = query_data[:min_length]
        
        # 标准化数据
        def normalize_data(data):
            if np.all(data == 0):
                return np.zeros_like(data)
            mean = np.mean(data)
            std = np.std(data)
            if std == 0:
                return np.zeros_like(data)
            return (data - mean) / std
        
        norm_prediction = normalize_data(prediction)
        norm_query = normalize_data(query_data)
        
        # 计算相似度
        similarity_result = compute_signal_similarity(norm_prediction, norm_query)
        
        if similarity_result['error'] is None:
            result['similarity'] = similarity_result['similarity']
            result['similarity_details'] = similarity_result['details']
            result['success'] = True
        else:
            result['error'] = similarity_result['error']
        
        return result
        
    except Exception as e:
        error_msg = f"验证过程发生异常: {str(e)}"
        result['error'] = error_msg
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return result 