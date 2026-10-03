"""
身份认证可视化模块
提供身份认证结果的可视化功能
"""

import numpy as np
import matplotlib.pyplot as plt
from ..utils.logger import setup_logger

logger = setup_logger(__name__)

class AuthenticationVisualizer:
    """身份验证结果可视化工具类"""
    
    @staticmethod
    def plot_authentication_result(reference_data, query_data, auth_result, title=None):
        """
        可视化身份验证结果
        
        Args:
            reference_data: 参考信号数据
            query_data: 查询信号数据
            auth_result: 认证结果字典
            title: 图表标题
        """
        try:
            # 数据校验
            if reference_data is None or query_data is None:
                logger.warning("无法显示结果：参考数据或查询数据为空")
                return
                
            # 创建图表
            plt.figure(figsize=(12, 8))
            
            # 创建子图
            ax1 = plt.subplot(3, 1, 1)  # 参考信号
            ax2 = plt.subplot(3, 1, 2)  # 查询信号
            ax3 = plt.subplot(3, 1, 3)  # 对比结果
            
            # 获取认证信息
            similarity = auth_result.get('similarity', 0) * 100  # 转为百分比
            threshold = auth_result.get('threshold', 0) * 100  # 转为百分比
            success = auth_result.get('success', False)
            user_id = auth_result.get('user_id', '未知')
            
            # 绘制参考信号
            x1 = np.arange(len(reference_data))
            ax1.plot(x1, reference_data, 'b-', linewidth=1.5)
            ax1.set_title("参考信号")
            ax1.set_xlim(0, len(reference_data))
            
            # 绘制查询信号
            x2 = np.arange(len(query_data))
            ax2.plot(x2, query_data, 'r-', linewidth=1.5)
            ax2.set_title("查询信号")
            ax2.set_xlim(0, len(query_data))
            
            # 绘制对比结果 - 使用柱状图显示相似度
            labels = ['相似度', '阈值']
            values = [similarity, threshold]
            colors = ['green' if success else 'red', 'blue']
            
            ax3.bar(labels, values, color=colors, width=0.4)
            ax3.set_ylim(0, 100)  # 百分比范围
            ax3.set_ylabel('百分比 (%)')
            ax3.set_title(f"认证结果 - {'通过' if success else '未通过'}")
            
            # 在柱状图上显示具体数值
            for i, v in enumerate(values):
                ax3.text(i, v + 2, f"{v:.1f}%", ha='center')
            
            # 设置图表标题
            if title:
                plt.suptitle(title, fontsize=16)
            else:
                plt.suptitle(f"用户{user_id}身份验证结果", fontsize=16)
                
            # 调整布局
            plt.tight_layout()
            plt.subplots_adjust(top=0.9)
            
            # 显示图表
            plt.show()
            
        except Exception as e:
            logger.exception(f"可视化认证结果时出错: {str(e)}")
    
    @staticmethod
    def plot_fusion_result(fusion_result, ecg_threshold=65.0, ppg_threshold=65.0):
        """
        可视化双信号融合认证结果
        
        Args:
            fusion_result: 融合认证结果字典
            ecg_threshold: ECG认证阈值 (百分比)
            ppg_threshold: PPG认证阈值 (百分比)
        """
        try:
            # 提取结果数据
            fusion_similarity = fusion_result.get('similarity', 0)
            fusion_threshold = fusion_result.get('threshold', 0)
            ecg_result = fusion_result.get('ecg_result', {})
            ppg_result = fusion_result.get('ppg_result', {})
            
            # 创建图表
            plt.figure(figsize=(12, 8))
            
            # 创建指针式仪表盘子图
            ax1 = plt.subplot(2, 2, (1, 2), polar=True)
            ax2 = plt.subplot(2, 2, 3, polar=True)
            ax3 = plt.subplot(2, 2, 4, polar=True)
            
            # 使用辅助函数创建仪表盘
            AuthenticationVisualizer._create_gauge(ax1, fusion_similarity, fusion_threshold, "双信号融合认证")
            AuthenticationVisualizer._create_gauge(ax2, ecg_result.get('similarity', 0), ecg_threshold, "ECG认证")
            AuthenticationVisualizer._create_gauge(ax3, ppg_result.get('similarity', 0), ppg_threshold, "PPG认证")
            
            # 调整布局并显示
            plt.tight_layout()
            plt.subplots_adjust(top=0.9)
            plt.suptitle("双信号融合身份认证结果", fontsize=16)
            plt.show()
            
        except Exception as e:
            logger.exception(f"可视化融合结果时出错: {str(e)}")
    
    @staticmethod
    def _create_gauge(ax, value, threshold, title, color_good='green', color_bad='red'):
        """
        创建指针式仪表盘
        
        Args:
            ax: matplotlib子图对象
            value: 当前值
            threshold: 阈值
            title: 标题
            color_good: 达标时的颜色
            color_bad: 未达标时的颜色
        """
        # 将百分比转换为弧度
        theta = np.linspace(0, 180, 100) * np.pi / 180
        r = np.ones_like(theta)
        
        # 设置极坐标参数
        ax.set_theta_zero_location("N")  # 零度位于北方（顶部）
        ax.set_theta_direction(-1)  # 逆时针方向
        ax.set_rlim(0, 1.5)  # 设置半径范围
        ax.set_thetamin(0)  # 最小角度
        ax.set_thetamax(180)  # 最大角度
        
        # 绘制仪表盘背景
        ax.fill_between(theta, 0, r, color='lightgray', alpha=0.3)
        
        # 绘制阈值线
        threshold_angle = threshold * np.pi / 100
        ax.plot([threshold_angle, threshold_angle], [0, 1], 'k--', linewidth=2)
        
        # 绘制当前值的指针
        value_angle = min(value, 100) * np.pi / 100
        color = color_good if value >= threshold else color_bad
        ax.arrow(np.pi/2, 0, (value_angle - np.pi/2), 0.8, 
                 head_width=0.1, head_length=0.1, fc=color, ec=color, linewidth=2)
        
        # 添加刻度标签
        angles = np.array([0, 45, 90, 135, 180]) * np.pi / 180
        labels = ['0%', '25%', '50%', '75%', '100%']
        ax.set_xticks(angles)
        ax.set_xticklabels(labels)
        
        # 设置标题
        plt.setp(ax.yaxis.get_ticklabels(), visible=False)
        ax.set_title(title, pad=15, fontsize=14)
        
        # 添加值标签
        result_text = f"{value:.1f}% "
        result_text += f"({'通过' if value >= threshold else '未通过'})"
        ax.text(np.pi/2, -0.2, result_text, 
                horizontalalignment='center', fontsize=12, 
                color=color, fontweight='bold')
        
        # 添加阈值标签
        ax.text(threshold_angle, 1.1, f"阈值: {threshold:.1f}%", 
                horizontalalignment='center', fontsize=10, rotation=threshold*180/100-90) 