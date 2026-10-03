"""
model_example 包

这个包提供了模型创建、训练和验证的模块化实现
替代main.py中的紧耦合功能实现
"""

# 把子模块导入包命名空间 —— 这是**有意为之**的 re-export
# （`import model_example` 后可直接 `model_example.model_creator`），
# 所以它们列进 __all__：不是多余导入。
#
# 副作用要知道：导入本包会连带导入下列全部子模块，它们的依赖（pandas /
# matplotlib 等）因此也进入调用方的 import 图。生产链路是按子模块精确导入的
# （如 `from model_example.model_creator import create_model`），不受这里影响。
__all__ = [
    'model_creator',
    'model_io',
    'model_trainer',
    'model_evaluator',
    'data_validator',
    'model_predictor',
    'authentication',
]

from . import model_creator
from . import model_io
from . import model_trainer
from . import model_evaluator
from . import data_validator
from . import model_predictor
from . import authentication 