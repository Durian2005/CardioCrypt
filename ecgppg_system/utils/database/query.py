"""
数据库查询模块
提供从MongoDB查询生物信号数据的功能
"""

from datetime import datetime
import pandas as pd
from .mongo_client import get_client
import logging

logger = logging.getLogger(__name__)

class BioSignalQuery:
    """生物信号查询类"""
    
    def __init__(self, client=None):
        """
        初始化查询类
        
        参数:
            client: MongoDB客户端实例，如果为None则使用默认客户端
        """
        self.client = client or get_client()
        
    def query_signals(self, signal_type="ecg", limit=10, start_time=None, end_time=None,
                     user_id=None, sort_by="timestamp", sort_direction=-1):
        """
        查询信号数据
        
        参数:
            signal_type: 信号类型 (ecg/ppg)
            limit: 返回的最大记录数
            start_time: 开始时间
            end_time: 结束时间
            user_id: 用户ID
            sort_by: 排序字段
            sort_direction: 排序方向 (1:升序 -1:降序)
            
        返回:
            DataFrame: 包含查询结果的DataFrame
        """
        if not self.client.is_connected:
            logger.error("数据库未连接")
            return pd.DataFrame()
            
        # 构建集合名称
        collection_name = f"raw_{signal_type}_signals"
        
        # 构建查询条件
        query = {}
        
        if start_time and end_time:
            query["timestamp"] = {"$gte": start_time, "$lte": end_time}
        elif start_time:
            query["timestamp"] = {"$gte": start_time}
        elif end_time:
            query["timestamp"] = {"$lte": end_time}
            
        if user_id:
            query["device_id"] = user_id
            
        # 执行查询
        try:
            # 排序参数
            sort_params = [(sort_by, sort_direction)]
            
            # 查询文档
            results = self.client.find_documents(
                collection_name=collection_name,
                query=query,
                sort_key=sort_params,
                limit=limit
            )
            
            # 转换为DataFrame
            df = pd.DataFrame(results)
            
            if not df.empty:
                logger.info(f"查询到 {len(df)} 条 {signal_type.upper()} 记录")
            else:
                logger.info(f"未找到匹配的 {signal_type.upper()} 记录")
                
            return df
            
        except Exception as e:
            logger.error(f"查询 {signal_type.upper()} 数据失败: {str(e)}")
            return pd.DataFrame()
    
    def get_recent_signals(self, signal_type="ecg", limit=100, user_id=None):
        """
        获取最近的信号数据
        
        参数:
            signal_type: 信号类型 (ecg/ppg)
            limit: 返回的最大记录数
            user_id: 用户ID
            
        返回:
            DataFrame: 包含查询结果的DataFrame
        """
        return self.query_signals(
            signal_type=signal_type,
            limit=limit,
            user_id=user_id,
            sort_by="timestamp",
            sort_direction=-1
        )
    
    def get_signals_by_date_range(self, signal_type="ecg", start_date=None, end_date=None, 
                                 limit=100, user_id=None):
        """
        按日期范围获取信号数据
        
        参数:
            signal_type: 信号类型 (ecg/ppg)
            start_date: 开始日期 (str YYYY-MM-DD 或 datetime对象)
            end_date: 结束日期 (str YYYY-MM-DD 或 datetime对象)
            limit: 返回的最大记录数
            user_id: 用户ID
            
        返回:
            DataFrame: 包含查询结果的DataFrame
        """
        # 转换日期字符串为datetime对象
        if isinstance(start_date, str):
            start_time = datetime.strptime(start_date, "%Y-%m-%d")
        else:
            start_time = start_date
            
        if isinstance(end_date, str):
            end_time = datetime.strptime(end_date, "%Y-%m-%d")
            # 设置为当天结束时间
            end_time = end_time.replace(hour=23, minute=59, second=59)
        else:
            end_time = end_date
            
        return self.query_signals(
            signal_type=signal_type,
            limit=limit,
            start_time=start_time,
            end_time=end_time,
            user_id=user_id
        )
    
    def get_signal_by_id(self, signal_type="ecg", document_id=None):
        """
        通过ID获取单个信号记录
        
        参数:
            signal_type: 信号类型 (ecg/ppg)
            document_id: 文档ID
            
        返回:
            dict: 文档记录或None
        """
        if not document_id:
            return None
            
        collection_name = f"raw_{signal_type}_signals"
        
        return self.client.find_one(
            collection_name=collection_name,
            query={"_id": document_id}
        )
        
# 导出查询函数，便于直接调用
def query_database(signal_type="ecg", limit=10, start_time=None, end_time=None, user_id=None):
    """
    查询数据库中的信号数据
    
    参数:
        signal_type: 信号类型 (ecg/ppg)
        limit: 返回的最大记录数
        start_time: 开始时间
        end_time: 结束时间
        user_id: 用户ID
        
    返回:
        DataFrame: 包含查询结果的DataFrame
    """
    query = BioSignalQuery()
    df = query.query_signals(
        signal_type=signal_type,
        limit=limit,
        start_time=start_time,
        end_time=end_time,
        user_id=user_id
    )
    
    if not df.empty and "timestamp" in df.columns and "value" in df.columns:
        print(f"找到 {len(df)} 条{signal_type.upper()}记录")
        print(df[["timestamp", "value"]].head())
    else:
        print("未找到匹配的记录")
        
    return df

def plot_signal(df):
    """
    绘制信号波形
    
    参数:
        df: 包含信号数据的DataFrame
    """
    try:
        import matplotlib.pyplot as plt
        
        if df.empty or "timestamp" not in df.columns or "value" not in df.columns:
            print("无法绘图：数据为空或缺少必要字段")
            return
            
        plt.figure(figsize=(12, 4))
        plt.plot(df["timestamp"], df["value"], label="Signal")
        plt.xlabel("时间")
        plt.ylabel("幅值")
        plt.title("生物信号波形")
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        plt.show()
        
    except ImportError:
        print("缺少matplotlib库，无法绘制图形")
    except Exception as e:
        print(f"绘图错误: {str(e)}") 