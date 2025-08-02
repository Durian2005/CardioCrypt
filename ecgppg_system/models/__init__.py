"""
ECG/PPG生物特征模型模块
包含用于心电信号和脉搏血氧信号处理的模型定义和训练工具
"""

# 导出主要模型类
from .bilstm import BiLSTMWithAttention
from .trainer import ModelTrainer

# 明确指定导出的类
__all__ = [
    'BiLSTMWithAttention',
    'ModelTrainer',
] 