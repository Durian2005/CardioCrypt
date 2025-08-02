"""
model_example 包

这个包提供了模型创建、训练和验证的模块化实现
替代main.py中的紧耦合功能实现
"""

# 导入所有子模块
from . import model_creator
from . import model_io
from . import model_trainer
from . import model_evaluator
from . import data_validator
from . import model_predictor
from . import authentication 