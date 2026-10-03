"""
结果可视化模块
提供训练历史、性能指标等结果的可视化功能
"""

import os
import numpy as np
import matplotlib.pyplot as plt
from ..utils.logger import setup_logger

logger = setup_logger(__name__)

class ResultsVisualizer:
    """结果可视化工具类"""
    
    def __init__(self, output_dir=None, dpi=150, figsize=(12, 8)):
        """
        初始化结果可视化器
        
        Args:
            output_dir: 输出目录，用于保存图表
            dpi: 图像DPI
            figsize: 图像大小
        """
        plt.ioff()  # 禁用交互模式，避免调试时自动显示空白图像
        self.output_dir = output_dir
        self.dpi = dpi
        self.figsize = figsize
        
        # 创建输出目录
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
    
    def plot_training_history(self, history, val_history=None, title=None, xlabel=None, ylabel=None,
                        save_path=None, show=True):
        """
        绘制训练历史
        
        Args:
            history: 训练损失列表
            val_history: 验证损失列表
            title: 图表标题
            xlabel: x轴标签
            ylabel: y轴标签
            save_path: 保存路径
            show: 是否显示图表
            
        Returns:
            matplotlib.figure.Figure: 图表对象
        """
        try:
            # 创建图表
            fig, ax = plt.subplots(figsize=self.figsize, dpi=self.dpi)
            
            # 绘制训练损失
            epochs = range(1, len(history) + 1)
            ax.plot(epochs, history, 'b-', label='训练损失')
            
            # 如果有验证损失，也绘制出来
            if val_history is not None:
                val_epochs = range(1, len(val_history) + 1)
                ax.plot(val_epochs, val_history, 'r-', label='验证损失')
            
            # 设置标题
            if title is None:
                title = "训练历史"
            ax.set_title(title)
            
            # 设置x轴标签
            if xlabel is None:
                xlabel = "轮次"
            ax.set_xlabel(xlabel)
            
            # 设置y轴标签
            if ylabel is None:
                ylabel = "损失"
            ax.set_ylabel(ylabel)
            
            # 添加图例
            ax.legend()
            
            # 添加网格
            ax.grid(True, linestyle='--', alpha=0.7)
            
            # 优化布局
            plt.tight_layout()
            
            # 保存图表
            if save_path:
                plt.savefig(save_path, dpi=self.dpi, bbox_inches='tight')
                logger.info(f"训练历史图表已保存至: {save_path}")
            
            # 显示图表
            if show:
                plt.show()
                
            return fig
            
        except Exception as e:
            logger.error(f"绘制训练历史失败: {str(e)}")
            return None
    
    def plot_metrics_comparison(self, metrics_dict, title=None, save_path=None, show=True):
        """
        绘制性能指标比较图
        
        Args:
            metrics_dict: 性能指标字典，键为指标名称，值为指标值
            title: 图表标题
            save_path: 保存路径
            show: 是否显示图表
            
        Returns:
            matplotlib.figure.Figure: 图表对象
        """
        try:
            # 创建图表
            fig, ax = plt.subplots(figsize=self.figsize, dpi=self.dpi)
            
            # 提取指标名和值
            metrics = list(metrics_dict.keys())
            values = list(metrics_dict.values())
            
            # 创建条形图
            bars = ax.bar(metrics, values, color='skyblue')
            
            # 添加数值标签
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{height:.4f}', ha='center', va='bottom')
            
            # 设置标题
            if title is None:
                title = "性能指标比较"
            ax.set_title(title)
            
            # 设置y轴范围
            ax.set_ylim(0, max(values) * 1.2)
            
            # 设置y轴标签
            ax.set_ylabel("指标值")
            
            # 添加网格
            ax.grid(True, linestyle='--', alpha=0.7, axis='y')
            
            # 优化布局
            plt.tight_layout()
            
            # 保存图表
            if save_path:
                plt.savefig(save_path, dpi=self.dpi, bbox_inches='tight')
                logger.info(f"性能指标比较图表已保存至: {save_path}")
            
            # 显示图表
            if show:
                plt.show()
                
            return fig
            
        except Exception as e:
            logger.error(f"绘制性能指标比较失败: {str(e)}")
            return None
    
    def plot_confusion_matrix(self, cm, classes=None, normalize=False, title=None, 
                          cmap=plt.cm.Blues, save_path=None, show=True):
        """
        绘制混淆矩阵
        
        Args:
            cm: 混淆矩阵
            classes: 类别标签
            normalize: 是否归一化
            title: 图表标题
            cmap: 颜色映射
            save_path: 保存路径
            show: 是否显示图表
            
        Returns:
            matplotlib.figure.Figure: 图表对象
        """
        try:
            # 如果需要归一化
            if normalize:
                cm = cm.astype('float') / cm.sum(axis=1)[:, np.newaxis]
                
            # 创建图表
            fig, ax = plt.subplots(figsize=self.figsize, dpi=self.dpi)
            
            # 绘制混淆矩阵
            im = ax.imshow(cm, interpolation='nearest', cmap=cmap)
            
            # 添加颜色条
            plt.colorbar(im)
            
            # 设置类别标签
            if classes is not None:
                tick_marks = np.arange(len(classes))
                ax.set_xticks(tick_marks)
                ax.set_yticks(tick_marks)
                ax.set_xticklabels(classes)
                ax.set_yticklabels(classes)
            
            # 设置标题
            if title is None:
                title = "混淆矩阵"
                if normalize:
                    title = "归一化" + title
            ax.set_title(title)
            
            # 设置坐标轴标签
            ax.set_ylabel('真实标签')
            ax.set_xlabel('预测标签')
            
            # 添加数值标签
            fmt = '.2f' if normalize else 'd'
            thresh = cm.max() / 2.
            for i in range(cm.shape[0]):
                for j in range(cm.shape[1]):
                    ax.text(j, i, format(cm[i, j], fmt),
                           horizontalalignment="center",
                           color="white" if cm[i, j] > thresh else "black")
            
            # 优化布局
            plt.tight_layout()
            
            # 保存图表
            if save_path:
                plt.savefig(save_path, dpi=self.dpi, bbox_inches='tight')
                logger.info(f"混淆矩阵图表已保存至: {save_path}")
            
            # 显示图表
            if show:
                plt.show()
                
            return fig
            
        except Exception as e:
            logger.error(f"绘制混淆矩阵失败: {str(e)}")
            return None

    def plot_prediction_future(self, history, predicted, title=None, xlabel=None, ylabel=None,
                          save_path=None, show=True):
        """
        绘制未来预测图
        
        Args:
            history: 历史数据
            predicted: 预测数据
            title: 图表标题
            xlabel: x轴标签
            ylabel: y轴标签
            save_path: 保存路径
            show: 是否显示图表
            
        Returns:
            matplotlib.figure.Figure: 图表对象
        """
        try:
            # 创建图表
            fig, ax = plt.subplots(figsize=self.figsize, dpi=self.dpi)
            
            # 设置x轴范围
            x_history = np.arange(len(history))
            x_future = np.arange(len(history) - 1, len(history) + len(predicted) - 1)
            
            # 绘制历史数据
            ax.plot(x_history, history, 'b-', label='历史数据')
            
            # 绘制预测数据
            ax.plot(x_future, predicted, 'r-', label='预测数据')
            
            # 绘制分界线
            ax.axvline(x=len(history) - 1, color='k', linestyle='--')
            
            # 设置标题
            if title is None:
                title = "未来值预测"
            ax.set_title(title)
            
            # 设置x轴标签
            if xlabel is None:
                xlabel = "时间点"
            ax.set_xlabel(xlabel)
            
            # 设置y轴标签
            if ylabel is None:
                ylabel = "值"
            ax.set_ylabel(ylabel)
            
            # 添加图例
            ax.legend()
            
            # 添加网格
            ax.grid(True, linestyle='--', alpha=0.7)
            
            # 优化布局
            plt.tight_layout()
            
            # 保存图表
            if save_path:
                plt.savefig(save_path, dpi=self.dpi, bbox_inches='tight')
                logger.info(f"未来预测图表已保存至: {save_path}")
            
            # 显示图表
            if show:
                plt.show()
                
            return fig
            
        except Exception as e:
            logger.error(f"绘制未来预测失败: {str(e)}")
            return None
            
    def plot_comparison(self, original, predicted, title=None, xlabel=None, ylabel=None,
                    save_path=None, show=True):
        """
        绘制对比图，用于比较原始数据和预测数据
        
        Args:
            original: 原始数据
            predicted: 预测数据
            title: 图表标题
            xlabel: x轴标签
            ylabel: y轴标签
            save_path: 保存路径
            show: 是否显示图表
            
        Returns:
            matplotlib.figure.Figure: 图表对象
        """
        try:
            # 创建图表
            fig, ax = plt.subplots(figsize=self.figsize, dpi=self.dpi)
            
            # 设置x轴范围
            x = np.arange(len(original))
            
            # 绘制原始数据
            ax.plot(x, original, 'b-', label='原始数据')
            
            # 绘制预测数据
            ax.plot(x, predicted, 'r-', label='预测数据')
            
            # 计算误差指标
            mse = np.mean((original - predicted) ** 2)
            mae = np.mean(np.abs(original - predicted))
            
            # 设置标题
            if title is None:
                title = f"数据对比 (MSE: {mse:.4f}, MAE: {mae:.4f})"
            ax.set_title(title)
            
            # 设置x轴标签
            if xlabel is None:
                xlabel = "时间点"
            ax.set_xlabel(xlabel)
            
            # 设置y轴标签
            if ylabel is None:
                ylabel = "值"
            ax.set_ylabel(ylabel)
            
            # 添加图例
            ax.legend()
            
            # 添加网格
            ax.grid(True, linestyle='--', alpha=0.7)
            
            # 优化布局
            plt.tight_layout()
            
            # 保存图表
            if save_path:
                plt.savefig(save_path, dpi=self.dpi, bbox_inches='tight')
                logger.info(f"数据对比图表已保存至: {save_path}")
            
            # 显示图表
            if show:
                plt.show()
                
            return fig
            
        except Exception as e:
            logger.error(f"绘制数据对比失败: {str(e)}")
            return None 