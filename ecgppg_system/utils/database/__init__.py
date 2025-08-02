"""
数据库模块
提供MongoDB数据库连接和查询功能
"""

from .mongo_client import MongoDBClient, get_client
from .query import BioSignalQuery, query_database, plot_signal

# 创建便捷别名
BioSignalDB = BioSignalQuery

__all__ = [
    'MongoDBClient',
    'get_client',
    'BioSignalQuery',
    'BioSignalDB',
    'query_database',
    'plot_signal'
] 