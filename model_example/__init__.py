"""
model_example 包

这个包提供了模型创建、训练和验证的模块化实现
替代main.py中的紧耦合功能实现
"""

# 子模块导出是**惰性**的（PEP 562）：导入本包本身不再连带加载全部子模块。
#
# 这里原先在模块顶层 `from . import model_creator ...` 七个，旁边写着「生产链路
# 按子模块精确导入，不受这里影响」—— 这句是错的：Python 在执行
# `from model_example.model_creator import create_model` 之前，一定会先执行包的
# __init__，于是另外六个子模块（model_evaluator / data_validator / model_predictor
# 等，生产零调用）也一起进了 import 图。实测 1.88s / 1430 个模块；跳过这层
# re-export 后是 1.62s / 1423 个。
#
# 改成 __getattr__ 后，`model_example.model_creator` 这种属性访问照样可用，
# 只是第一次访问才加载对应子模块。
import importlib

__all__ = [
    'model_creator',
    'model_io',
    'model_trainer',
    'model_evaluator',
    'data_validator',
    'model_predictor',
    'authentication',
]


def __getattr__(name):
    if name in __all__:
        module = importlib.import_module(f'.{name}', __name__)
        # 缓存进模块命名空间：之后同名访问不再触发 __getattr__
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
