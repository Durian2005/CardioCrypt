"""
工具模块
提供各种辅助功能，包括数据库操作、日志记录等

**这里的导出是惰性的（PEP 562）**：`database` 子包在导入期就会连带 pandas 与
pymongo（`database/query.py` 顶层 `import pandas`），而真正需要数据库的场景只在
离线分析脚本里。生产链路大量走的是 `from ecgppg_system.utils.logger import ...`，
它只应付出 logger 的代价 —— 实测单是 `import ecgppg_system.utils` 就会多花约
0.44 秒并让 pandas 常驻。

改成模块级 `__getattr__` 后，`from ecgppg_system.utils import MongoDBClient` 这种
写法仍然可用，只是要到真正取用时才加载 database 子包。
"""

__all__ = ['MongoDBClient', 'BioSignalQuery']


def __getattr__(name):
    if name in __all__:
        from . import database

        return getattr(database, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
