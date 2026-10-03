"""
信号可视化工具模块
提供ECG和PPG信号的可视化功能
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
import seaborn as sns
import pandas as pd
from ..utils.logger import logger
from ..config import settings
from ..utils.matplotlib_setup import configure_matplotlib
from ..utils.font_utils import get_font_prop
import os
import logging
from .auth_visualizer import AuthenticationVisualizer

# 配置matplotlib
configure_matplotlib()

# 设置中文字体支持
try:
    from ecgppg_system.utils.file_utils import get_chinese_fonts
    
    # 获取可用的中文字体
    chinese_fonts = get_chinese_fonts()
    if chinese_fonts:
        plt.rcParams['font.sans-serif'] = chinese_fonts
        plt.rcParams['axes.unicode_minus'] = False  # 正确显示负号
    else:
        logging.warning("未找到可用的中文字体，图表中的中文可能显示为方块")
except Exception as e:
    logging.warning(f"设置中文字体支持时出错: {str(e)}")

class SignalPlotter:
    """
    信号可视化工具类，提供各种信号可视化功能
    """
    
    def __init__(self, signal_type='ecg', dpi=None, figsize=None):
        """
        初始化信号可视化工具
        
        参数:
            signal_type (str): 信号类型，'ecg'或'ppg'
            dpi (int, optional): 图像DPI，默认使用settings中的设置
            figsize (tuple, optional): 图像大小，默认使用settings中的设置
        """
        self.signal_type = signal_type.upper()
        
        # 设置标题前缀
        if signal_type.lower() == 'ecg':
            self.title_prefix = "ECG "
        elif signal_type.lower() == 'ppg':
            self.title_prefix = "PPG "
        else:
            self.title_prefix = ""
        
        if dpi is None:
            self.dpi = settings.DPI
        else:
            self.dpi = dpi
            
        if figsize is None:
            self.figsize = (settings.FIGURE_WIDTH, settings.FIGURE_HEIGHT)
        else:
            self.figsize = figsize
            
        # 根据信号类型设置标题和颜色
        if self.signal_type == 'ECG':
            self.line_color = 'darkred'
            self.pred_color = 'blue'
            self.highlight_color = 'green'
        else:
            self.line_color = 'darkblue'
            self.pred_color = 'red'
            self.highlight_color = 'green'
            
        logger.info(f"初始化{self.signal_type}信号可视化工具: dpi={self.dpi}, figsize={self.figsize}")
        
    def plot_signal(self, signal, title=None, x_label="采样点", y_label="幅值", 
                   filename=None, show=True, time_axis=None):
        """
        绘制信号波形
        
        参数:
            signal (numpy.ndarray): 信号数据
            title (str, optional): 图像标题，如果不提供则使用默认标题
            x_label (str): x轴标签
            y_label (str): y轴标签
            filename (str, optional): 保存文件名，如果提供则保存图像
            show (bool): 是否显示图像
            time_axis (numpy.ndarray, optional): 时间轴数据，如果提供则使用时间轴
            
        返回:
            matplotlib.figure.Figure: 图像对象
        """
        try:
            # 检查和清理信号数据中的无效值
            signal = np.array(signal)
            if np.isnan(signal).any() or np.isinf(signal).any():
                logger.warning("信号数据中存在NaN或无穷值，进行替换处理")
                signal = np.nan_to_num(signal, nan=0.0, posinf=None, neginf=None)
            
            # 创建图像
            fig, ax = plt.subplots(figsize=self.figsize, dpi=self.dpi)
            
            # 确定x轴数据
            x = time_axis if time_axis is not None else np.arange(len(signal))
            
            # 检查x轴数据是否包含无效值
            if time_axis is not None and (np.isnan(x).any() or np.isinf(x).any()):
                logger.warning("时间轴数据中存在NaN或无穷值，进行替换处理")
                x = np.nan_to_num(x, nan=0.0, posinf=None, neginf=None)
            
            # 绘制信号
            ax.plot(x, signal, color=self.line_color, lw=1.5)
            
            # 设置标题和标签
            if title is None:
                title = f"{self.title_prefix}波形"
            ax.set_title(title, fontsize=14)
            ax.set_xlabel(x_label, fontsize=12)
            ax.set_ylabel(y_label, fontsize=12)
            
            # 添加网格
            ax.grid(True, linestyle='--', alpha=0.7)
            
            # 优化布局
            plt.tight_layout()
            
            # 保存图像
            if filename:
                plt.savefig(filename, dpi=self.dpi, bbox_inches='tight')
                logger.info(f"图像已保存到: {filename}")
                
            # 显示图像
            if show:
                plt.show()
                
            return fig
            
        except Exception as e:
            logger.error(f"绘制信号波形失败: {str(e)}")
            return None
            
    def plot_comparison(self, original, predicted, title=None, x_label="采样点", 
                       y_label="幅值", filename=None, show=True, time_axis=None):
        """
        绘制原始信号和预测信号的对比图
        
        参数:
            original (numpy.ndarray): 原始信号
            predicted (numpy.ndarray): 预测信号
            title (str, optional): 图像标题，如果不提供则使用默认标题
            x_label (str): x轴标签
            y_label (str): y轴标签
            filename (str, optional): 保存文件名
            show (bool): 是否显示图像
            time_axis (numpy.ndarray, optional): 时间轴数据
            
        返回:
            matplotlib.figure.Figure: 图像对象
        """
        try:
            # 检查和清理信号数据中的无效值
            original = np.array(original)
            predicted = np.array(predicted)
            
            if np.isnan(original).any() or np.isinf(original).any():
                logger.warning("原始信号数据中存在NaN或无穷值，进行替换处理")
                original = np.nan_to_num(original, nan=0.0, posinf=None, neginf=None)
                
            if np.isnan(predicted).any() or np.isinf(predicted).any():
                logger.warning("预测信号数据中存在NaN或无穷值，进行替换处理")
                predicted = np.nan_to_num(predicted, nan=0.0, posinf=None, neginf=None)
            
            # 创建图像
            fig, ax = plt.subplots(figsize=self.figsize, dpi=self.dpi)
            
            # 确定x轴数据
            x = time_axis if time_axis is not None else np.arange(len(original))
            
            # 检查x轴数据是否包含无效值
            if time_axis is not None and (np.isnan(x).any() or np.isinf(x).any()):
                logger.warning("时间轴数据中存在NaN或无穷值，进行替换处理")
                x = np.nan_to_num(x, nan=0.0, posinf=None, neginf=None)
            
            # 绘制原始信号
            ax.plot(x, original, color=self.line_color, lw=1.5, label="原始信号")
            
            # 绘制预测信号
            ax.plot(x, predicted, color=self.pred_color, lw=1.5, ls='--', label="预测信号")
            
            # 设置标题和标签
            if title is None:
                title = f"{self.title_prefix}原始与预测对比"
            ax.set_title(title, fontsize=14)
            ax.set_xlabel(x_label, fontsize=12)
            ax.set_ylabel(y_label, fontsize=12)
            
            # 添加图例 - 确保使用字体属性
            font_prop = get_font_prop(12)
            ax.legend(loc='best', fontsize=12, prop=font_prop)
            
            # 添加网格
            ax.grid(True, linestyle='--', alpha=0.7)
            
            # 优化布局
            plt.tight_layout()
            
            # 保存图像
            if filename:
                plt.savefig(filename, dpi=self.dpi, bbox_inches='tight')
                logger.info(f"对比图已保存到: {filename}")
                
            # 显示图像
            if show:
                plt.show()
                
            return fig
            
        except Exception as e:
            logger.error(f"绘制对比图失败: {str(e)}")
            return None
            
    def plot_multi_signals(self, signals, labels=None, title=None, x_label="采样点", 
                          y_label="幅值", filename=None, show=True, time_axis=None):
        """
        绘制多个信号的对比图
        
        参数:
            signals (list): 信号列表
            labels (list, optional): 标签列表
            title (str, optional): 图像标题
            x_label (str): x轴标签
            y_label (str): y轴标签
            filename (str, optional): 保存文件名
            show (bool): 是否显示图像
            time_axis (numpy.ndarray, optional): 时间轴数据
            
        返回:
            matplotlib.figure.Figure: 图像对象
        """
        try:
            # 创建图像
            fig, ax = plt.subplots(figsize=self.figsize, dpi=self.dpi)
            
            # 确定标签
            if labels is None:
                labels = [f"信号 {i+1}" for i in range(len(signals))]
                
            # 确定颜色
            colors = plt.cm.rainbow(np.linspace(0, 1, len(signals)))
            
            # 确定x轴数据
            x = time_axis if time_axis is not None else np.arange(len(signals[0]))
            
            # 绘制所有信号
            for i, signal in enumerate(signals):
                ax.plot(x, signal, color=colors[i], lw=1.5, label=labels[i])
                
            # 设置标题和标签
            if title is None:
                title = f"{self.title_prefix}多信号对比"
            ax.set_title(title, fontsize=14)
            ax.set_xlabel(x_label, fontsize=12)
            ax.set_ylabel(y_label, fontsize=12)
            
            # 添加图例
            font_prop = get_font_prop(12)
            ax.legend(loc='best', prop=font_prop)
            
            # 添加网格
            ax.grid(True, linestyle='--', alpha=0.7)
            
            # 优化布局
            plt.tight_layout()
            
            # 保存图像
            if filename:
                plt.savefig(filename, dpi=self.dpi, bbox_inches='tight')
                logger.info(f"多信号对比图已保存到: {filename}")
                
            # 显示图像
            if show:
                plt.show()
                
            return fig
            
        except Exception as e:
            logger.error(f"绘制多信号对比图失败: {str(e)}")
            return None
            
    def plot_training_history(self, train_loss, val_loss=None, title=None, 
                             filename=None, show=True):
        """
        绘制训练历史
        
        参数:
            train_loss (list): 训练损失列表
            val_loss (list, optional): 验证损失列表
            title (str, optional): 图像标题
            filename (str, optional): 保存文件名
            show (bool): 是否显示图像
            
        返回:
            matplotlib.figure.Figure: 图像对象
        """
        try:
            # 创建图像
            fig, ax = plt.subplots(figsize=self.figsize, dpi=self.dpi)
            
            # 绘制训练损失
            epochs = np.arange(1, len(train_loss) + 1)
            ax.plot(epochs, train_loss, 'b-', lw=2, label="训练损失")
            
            # 绘制验证损失
            if val_loss is not None:
                ax.plot(epochs, val_loss, 'r-', lw=2, label="验证损失")
                
            # 设置标题和标签
            if title is None:
                title = f"{self.title_prefix}模型训练历史"
            ax.set_title(title, fontsize=14)
            ax.set_xlabel("Epoch", fontsize=12)
            ax.set_ylabel("损失", fontsize=12)
            
            # 添加图例
            font_prop = get_font_prop(12)
            ax.legend(loc='best', prop=font_prop)
            
            # 添加网格
            ax.grid(True, linestyle='--', alpha=0.7)
            
            # 优化布局
            plt.tight_layout()
            
            # 保存图像
            if filename:
                plt.savefig(filename, dpi=self.dpi, bbox_inches='tight')
                logger.info(f"训练历史图已保存到: {filename}")
                
            # 显示图像
            if show:
                plt.show()
                
            return fig
            
        except Exception as e:
            logger.error(f"绘制训练历史失败: {str(e)}")
            return None
            
    def plot_prediction_future(self, history, predicted, title=None, x_label="采样点", 
                              y_label="幅值", filename=None, show=True, time_axis=None):
        """
        绘制历史数据和未来预测
        
        参数:
            history (numpy.ndarray): 历史数据
            predicted (numpy.ndarray): 预测数据
            title (str, optional): 图像标题
            x_label (str): x轴标签
            y_label (str): y轴标签
            filename (str, optional): 保存文件名
            show (bool): 是否显示图像
            time_axis (numpy.ndarray, optional): 时间轴数据
            
        返回:
            matplotlib.figure.Figure: 图像对象
        """
        try:
            # 创建图像
            fig, ax = plt.subplots(figsize=self.figsize, dpi=self.dpi)
            
            # 确定x轴数据
            if time_axis is not None:
                history_time = time_axis[:len(history)]
                # 假设时间轴是等间隔的
                time_step = history_time[1] - history_time[0] if len(history_time) > 1 else 1
                future_time = np.array([history_time[-1] + (i+1)*time_step for i in range(len(predicted))])
            else:
                history_time = np.arange(len(history))
                future_time = np.arange(len(history), len(history) + len(predicted))
                
            # 绘制历史数据
            ax.plot(history_time, history, color=self.line_color, lw=1.5, label="历史数据")
            
            # 绘制预测数据
            ax.plot(future_time, predicted, color=self.pred_color, lw=1.5, ls='--', label="预测数据")
            
            # 添加分隔线
            if len(history) > 0:
                ax.axvline(x=history_time[-1], color='k', linestyle=':', alpha=0.5)
            
            # 设置标题和标签
            if title is None:
                title = f"{self.title_prefix}未来预测"
            ax.set_title(title, fontsize=14)
            ax.set_xlabel(x_label, fontsize=12)
            ax.set_ylabel(y_label, fontsize=12)
            
            # 添加图例
            font_prop = get_font_prop(12)
            ax.legend(loc='best', prop=font_prop)
            
            # 添加网格
            ax.grid(True, linestyle='--', alpha=0.7)
            
            # 优化布局
            plt.tight_layout()
            
            # 保存图像
            if filename:
                plt.savefig(filename, dpi=self.dpi, bbox_inches='tight')
                logger.info(f"预测图已保存到: {filename}")
                
            # 显示图像
            if show:
                plt.show()
                
            return fig
            
        except Exception as e:
            logger.error(f"绘制预测图失败: {str(e)}")
            return None
            
    def plot_signal_with_peaks(self, signal, peaks, title=None, x_label="采样点", 
                              y_label="幅值", filename=None, show=True, time_axis=None):
        """
        绘制带峰值标记的信号
        
        参数:
            signal (numpy.ndarray): 信号数据
            peaks (numpy.ndarray): 峰值索引
            title (str, optional): 图像标题
            x_label (str): x轴标签
            y_label (str): y轴标签
            filename (str, optional): 保存文件名
            show (bool): 是否显示图像
            time_axis (numpy.ndarray, optional): 时间轴数据
            
        返回:
            matplotlib.figure.Figure: 图像对象
        """
        try:
            # 创建图像
            fig, ax = plt.subplots(figsize=self.figsize, dpi=self.dpi)
            
            # 确定x轴数据
            x = time_axis if time_axis is not None else np.arange(len(signal))
            
            # 绘制信号
            ax.plot(x, signal, color=self.line_color, lw=1.5, label="信号")
            
            # 绘制峰值
            if time_axis is not None:
                peak_times = time_axis[peaks]
            else:
                peak_times = peaks
            ax.scatter(peak_times, signal[peaks], color=self.highlight_color, s=50, 
                      label="峰值", zorder=3)
            
            # 设置标题和标签
            if title is None:
                title = f"{self.title_prefix}峰值检测"
            ax.set_title(title, fontsize=14)
            ax.set_xlabel(x_label, fontsize=12)
            ax.set_ylabel(y_label, fontsize=12)
            
            # 添加图例
            font_prop = get_font_prop(12)
            ax.legend(loc='best', fontsize=12, prop=font_prop)
            
            # 添加网格
            ax.grid(True, linestyle='--', alpha=0.7)
            
            # 优化布局
            plt.tight_layout()
            
            # 保存图像
            if filename:
                plt.savefig(filename, dpi=self.dpi, bbox_inches='tight')
                logger.info(f"峰值检测图已保存到: {filename}")
                
            # 显示图像
            if show:
                plt.show()
                
            return fig
            
        except Exception as e:
            logger.error(f"绘制峰值检测图失败: {str(e)}")
            return None
            
    def plot_correlation_heatmap(self, data, title=None, filename=None, show=True):
        """
        绘制相关性热图
        
        参数:
            data (pandas.DataFrame or numpy.ndarray): 数据
            title (str, optional): 图像标题
            filename (str, optional): 保存文件名
            show (bool): 是否显示图像
            
        返回:
            matplotlib.figure.Figure: 图像对象
        """
        try:
            # 如果输入是numpy数组，转换为DataFrame
            if isinstance(data, np.ndarray):
                data = pd.DataFrame(data)
                
            # 计算相关性矩阵
            corr = data.corr()
            
            # 创建图像
            fig, ax = plt.subplots(figsize=self.figsize, dpi=self.dpi)
            
            # 绘制热图
            sns.heatmap(corr, annot=True, cmap='coolwarm', ax=ax, fmt='.2f', 
                       linewidths=.5, cbar_kws={"shrink": .8})
            
            # 设置标题
            if title is None:
                title = f"{self.title_prefix}特征相关性热图"
            ax.set_title(title, fontsize=14)
            
            # 优化布局
            plt.tight_layout()
            
            # 保存图像
            if filename:
                plt.savefig(filename, dpi=self.dpi, bbox_inches='tight')
                logger.info(f"相关性热图已保存到: {filename}")
                
            # 显示图像
            if show:
                plt.show()
                
            return fig
            
        except Exception as e:
            logger.error(f"绘制相关性热图失败: {str(e)}")
            return None
            
    def plot_feature_importance(self, features, importances, title=None, 
                               filename=None, show=True, top_n=None):
        """
        绘制特征重要性
        
        参数:
            features (list): 特征名称列表
            importances (numpy.ndarray): 特征重要性数组
            title (str, optional): 图像标题
            filename (str, optional): 保存文件名
            show (bool): 是否显示图像
            top_n (int, optional): 显示前n个重要特征
            
        返回:
            matplotlib.figure.Figure: 图像对象
        """
        try:
            # 创建特征重要性DataFrame
            feature_importance = pd.DataFrame({
                'feature': features,
                'importance': importances
            })
            
            # 按重要性排序
            feature_importance = feature_importance.sort_values('importance', ascending=False)
            
            # 如果指定了top_n，则只显示前n个特征
            if top_n is not None:
                feature_importance = feature_importance.head(top_n)
                
            # 创建图像
            fig, ax = plt.subplots(figsize=self.figsize, dpi=self.dpi)
            
            # 绘制条形图
            sns.barplot(x='importance', y='feature', data=feature_importance, 
                       palette='viridis', ax=ax)
            
            # 设置标题和标签
            if title is None:
                title = f"{self.title_prefix}特征重要性"
            ax.set_title(title, fontsize=14)
            ax.set_xlabel("重要性", fontsize=12)
            ax.set_ylabel("特征", fontsize=12)
            
            # 优化布局
            plt.tight_layout()
            
            # 保存图像
            if filename:
                plt.savefig(filename, dpi=self.dpi, bbox_inches='tight')
                logger.info(f"特征重要性图已保存到: {filename}")
                
            # 显示图像
            if show:
                plt.show()
                
            return fig
            
        except Exception as e:
            logger.error(f"绘制特征重要性图失败: {str(e)}")
            return None
            
    def create_subplots(self, num_plots, title=None, figsize=None):
        """
        创建子图布局
        
        参数:
            num_plots (int): 子图数量
            title (str, optional): 主标题
            figsize (tuple, optional): 图像大小
            
        返回:
            tuple: (matplotlib.figure.Figure, list of matplotlib.axes.Axes)
        """
        try:
            # 确定子图布局
            if num_plots <= 3:
                nrows, ncols = 1, num_plots
            elif num_plots <= 6:
                nrows, ncols = 2, int(np.ceil(num_plots / 2))
            elif num_plots <= 9:
                nrows, ncols = 3, 3
            else:
                nrows = int(np.ceil(num_plots / 3))
                ncols = 3
                
            # 确定图像大小
            if figsize is None:
                figsize = (self.figsize[0], self.figsize[1] * nrows / 2)
                
            # 创建子图
            fig, axes = plt.subplots(nrows, ncols, figsize=figsize, dpi=self.dpi, 
                                    squeeze=False)
            
            # 设置主标题
            if title:
                fig.suptitle(title, fontsize=16)
                
            # 将多余的子图隐藏
            for i in range(num_plots, nrows * ncols):
                row = i // ncols
                col = i % ncols
                axes[row, col].axis('off')
                
            # 优化布局
            plt.tight_layout()
            if title:
                plt.subplots_adjust(top=0.9)
                
            return fig, axes
            
        except Exception as e:
            logger.error(f"创建子图布局失败: {str(e)}")
            return None, None
            
    def close_all(self):
        """
        关闭所有图像
        """
        plt.close('all')
        logger.info("已关闭所有图像")

    def get_auth_visualizer(self):
        """
        获取身份认证可视化器
        
        返回:
            AuthenticationVisualizer: 身份认证可视化器类
        """
        return AuthenticationVisualizer

    def plot_authentication_result(self, reference_data, query_data, auth_result, title=None):
        """
        可视化身份验证结果
        
        Args:
            reference_data: 参考信号数据
            query_data: 查询信号数据
            auth_result: 认证结果字典
            title: 图表标题
        """
        # 调用AuthenticationVisualizer
        AuthenticationVisualizer.plot_authentication_result(
            reference_data=reference_data,
            query_data=query_data,
            auth_result=auth_result,
            title=title
        )

    def plot_fusion_result(self, fusion_result, ecg_threshold=65.0, ppg_threshold=65.0):
        """
        可视化双信号融合认证结果
        
        Args:
            fusion_result: 融合认证结果字典
            ecg_threshold: ECG认证阈值
            ppg_threshold: PPG认证阈值
        """
        # 调用AuthenticationVisualizer
        AuthenticationVisualizer.plot_fusion_result(
            fusion_result=fusion_result,
            ecg_threshold=ecg_threshold,
            ppg_threshold=ppg_threshold
        )

    def save_signal_figure(self, signal_data, save_path, title=None, dpi=300):
        """
        保存信号图像到文件
        
        Args:
            signal_data: 信号数据
            save_path: 保存路径
            title: 图表标题
            dpi: 图像DPI
        
        Returns:
            bool: 是否成功保存
        """
        try:
            # 创建图形对象
            fig = Figure(figsize=self.figsize, dpi=dpi)
            # 必须保留这次调用：它把渲染后端绑到 fig 上，下面的 fig.savefig 依赖它。
            # 只是不需要接收返回值。
            FigureCanvas(fig)
            ax = fig.add_subplot(111)
            
            # 绘制信号
            x = np.arange(len(signal_data))
            ax.plot(x, signal_data, 'b-', linewidth=1.0)
            
            # 设置标题和网格
            if title:
                ax.set_title(title)
            ax.grid(True, linestyle='--', alpha=0.7)
            
            # 确保目录存在
            os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
            
            # 保存图像
            fig.savefig(save_path)
            logger.info(f"信号图已保存到: {save_path}")
            return True
            
        except Exception as e:
            logger.error(f"保存信号图出错: {str(e)}")
            return False

# 模块级函数 - 直接转发到AuthenticationVisualizer
def plot_authentication_result(reference_data, query_data, auth_result, title=None):
    """
    可视化身份验证结果 (模块级函数)
    
    Args:
        reference_data: 参考信号数据
        query_data: 查询信号数据
        auth_result: 认证结果字典
        title: 图表标题
    """
    AuthenticationVisualizer.plot_authentication_result(
        reference_data=reference_data,
        query_data=query_data,
        auth_result=auth_result,
        title=title
    ) 