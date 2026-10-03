"""
MongoDB客户端连接模块
用于建立与MongoDB数据库的连接并提供基本操作方法
"""
import logging
from typing import Dict, Any, Optional, List, Union
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from ecgppg_system.config import settings

logger = logging.getLogger(__name__)

class MongoDBClient:
    """MongoDB客户端连接类"""
    
    def __init__(self, 
                 host: str = "localhost", 
                 port: int = 27017, 
                 database_name: str = "biosignal_db",
                 username: Optional[str] = None,
                 password: Optional[str] = None,
                 connection_timeout: int = 5000):
        """
        初始化MongoDB客户端
        
        Args:
            host: MongoDB服务器主机地址
            port: MongoDB服务器端口
            database_name: 数据库名称
            username: 用户名（如果需要认证）
            password: 密码（如果需要认证）
            connection_timeout: 连接超时时间(毫秒)
        """
        self.host = host
        self.port = port
        self.database_name = database_name
        self.username = username
        self.password = password
        self.connection_timeout = connection_timeout
        
        self.client = None
        self.db = None
        self.is_connected = False
    
    def connect(self) -> bool:
        """
        建立与MongoDB的连接
        
        Returns:
            bool: 连接是否成功
        """
        try:
            # 构建连接URI
            if self.username and self.password:
                uri = f"mongodb://{self.username}:{self.password}@{self.host}:{self.port}/{self.database_name}"
            else:
                uri = f"mongodb://{self.host}:{self.port}/{self.database_name}"
            
            # 创建客户端连接
            self.client = MongoClient(uri, serverSelectionTimeoutMS=self.connection_timeout)
            
            # 验证连接
            self.client.admin.command('ping')
            
            # 获取数据库
            self.db = self.client[self.database_name]
            
            self.is_connected = True
            logger.info(f"成功连接到MongoDB服务器: {self.host}:{self.port}/{self.database_name}")
            return True
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            self.is_connected = False
            logger.error(f"MongoDB连接失败: {str(e)}")
            return False
    
    def disconnect(self) -> None:
        """关闭MongoDB连接"""
        if self.client:
            self.client.close()
            self.is_connected = False
            logger.info("MongoDB连接已关闭")
    
    def get_collection(self, collection_name: str) -> Optional[Collection]:
        """
        获取指定的集合
        
        Args:
            collection_name: 集合名称
            
        Returns:
            Collection对象或None（如果未连接）
        """
        if not self.is_connected or self.db is None:
            logger.error("MongoDB未连接，无法获取集合")
            return None
        
        return self.db[collection_name]
    
    def insert_document(self, collection_name: str, document: Dict[str, Any]) -> Optional[str]:
        """
        向集合中插入单个文档
        
        Args:
            collection_name: 集合名称
            document: 要插入的文档
            
        Returns:
            插入文档的ID或None（如果插入失败）
        """
        collection = self.get_collection(collection_name)
        if collection is None:
            return None
        
        try:
            result = collection.insert_one(document)
            return str(result.inserted_id)
        except Exception as e:
            logger.error(f"插入文档失败: {str(e)}")
            return None
    
    def insert_many_documents(self, collection_name: str, documents: List[Dict[str, Any]]) -> Optional[List[str]]:
        """
        向集合中插入多个文档
        
        Args:
            collection_name: 集合名称
            documents: 要插入的文档列表
            
        Returns:
            插入文档的ID列表或None（如果插入失败）
        """
        collection = self.get_collection(collection_name)
        if collection is None:
            return None
        
        try:
            result = collection.insert_many(documents)
            return [str(id) for id in result.inserted_ids]
        except Exception as e:
            logger.error(f"批量插入文档失败: {str(e)}")
            return None
    
    def find_document(self, collection_name: str, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        查找单个文档
        
        Args:
            collection_name: 集合名称
            query: 查询条件
            
        Returns:
            查找到的文档或None（如果未找到）
        """
        collection = self.get_collection(collection_name)
        if collection is None:
            return None
        
        try:
            return collection.find_one(query)
        except Exception as e:
            logger.error(f"查找文档失败: {str(e)}")
            return None
    
    def find_documents(self, 
                       collection_name: str, 
                       query: Dict[str, Any],
                       projection: Optional[Dict[str, Any]] = None,
                       sort_key: Optional[Union[str, List[tuple]]] = None,
                       sort_direction: int = 1,
                       limit: int = 0) -> List[Dict[str, Any]]:
        """
        查找多个文档
        
        Args:
            collection_name: 集合名称
            query: 查询条件
            projection: 投影（指定返回的字段）
            sort_key: 排序字段或排序规则列表
            sort_direction: 排序方向 (1=升序, -1=降序)
            limit: 返回结果数量限制 (0=不限制)
            
        Returns:
            查找到的文档列表
        """
        collection = self.get_collection(collection_name)
        if collection is None:
            return []
        
        try:
            cursor = collection.find(query, projection)
            
            # 排序
            if sort_key:
                if isinstance(sort_key, str):
                    cursor = cursor.sort(sort_key, sort_direction)
                else:
                    cursor = cursor.sort(sort_key)
            
            # 限制结果数量
            if limit > 0:
                cursor = cursor.limit(limit)
            
            return list(cursor)
        except Exception as e:
            logger.error(f"查找多个文档失败: {str(e)}")
            return []
    
    def update_document(self, collection_name: str, query: Dict[str, Any], update_data: Dict[str, Any]) -> int:
        """
        更新单个文档
        
        Args:
            collection_name: 集合名称
            query: 查询条件
            update_data: 更新数据
            
        Returns:
            更新的文档数量
        """
        collection = self.get_collection(collection_name)
        if collection is None:
            return 0
        
        try:
            result = collection.update_one(query, {"$set": update_data})
            return result.modified_count
        except Exception as e:
            logger.error(f"更新文档失败: {str(e)}")
            return 0
    
    def delete_document(self, collection_name: str, query: Dict[str, Any]) -> int:
        """
        删除单个文档
        
        Args:
            collection_name: 集合名称
            query: 查询条件
            
        Returns:
            删除的文档数量
        """
        collection = self.get_collection(collection_name)
        if collection is None:
            return 0
        
        try:
            result = collection.delete_one(query)
            return result.deleted_count
        except Exception as e:
            logger.error(f"删除文档失败: {str(e)}")
            return 0
    
    def collection_exists(self, collection_name: str) -> bool:
        """
        检查集合是否存在
        
        Args:
            collection_name: 集合名称
            
        Returns:
            集合是否存在
        """
        if not self.is_connected or self.db is None:
            return False
        
        return collection_name in self.db.list_collection_names()

# 默认客户端实例
default_client = None

def get_client():
    """获取默认客户端实例"""
    global default_client
    if not default_client:
        # 从配置中获取数据库参数
        db_params = {
            "host": getattr(settings, "DB_HOST", "localhost"),
            "port": getattr(settings, "DB_PORT", 27017),
            "username": getattr(settings, "DB_USER", None),
            "password": getattr(settings, "DB_PASS", None),
            "database_name": getattr(settings, "DB_NAME", "biosignal_db")
        }
        
        default_client = MongoDBClient(**db_params)
        default_client.connect()
        
    return default_client 