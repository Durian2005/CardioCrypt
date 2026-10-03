"""
通用模型存取（**训练检查点**格式）

与 `model_example/model_io.py` 是两套**互不相通**的存档格式，不要混用：

* 本模块：服务于 `ecgppg_system/models/trainer.py` 的 `ModelTrainer`。元数据
  **平铺在顶层**，读回时连 `optimizer_state_dict` 与训练历史一起还原，
  用于断点续训。
* `model_io`：服务于 `web_auth` 的**用户模型**存取。元数据收在 `metadata`
  键下，读回时只取 `state_dict` 与元数据，用于身份比对。

不能互读：本模块写出的文件交给 `model_io.load_model` 时找不到 `metadata` 键，
会以 `input_size=None` 构造模型而失败。

历史原因：两处各自演化而来。既然用途确实不同（检查点 vs 部署模型），这里
保留两套并写明边界，而不是强行合并 —— 合并会改动训练检查点的读写行为。
"""

import os
import torch
from ..utils.logger import setup_logger

logger = setup_logger(__name__)

def save_model(model, save_path, metadata=None):
    """
    通用模型保存函数
    
    参数:
        model: 要保存的模型
        save_path: 保存路径
        metadata: 额外的元数据字典
    
    返回:
        bool: 是否保存成功
    """
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        # 准备保存数据
        save_data = {
            'model_state_dict': model.state_dict()
        }
            
        # 添加元数据
        if metadata and isinstance(metadata, dict):
            save_data.update(metadata)
            
        # 保存模型
        torch.save(save_data, save_path)
        logger.info(f"模型已保存至: {save_path}")
        return True
        
    except Exception as e:
        logger.error(f"保存模型失败: {str(e)}")
        return False
        
def load_model(model, load_path, device=None):
    """
    通用模型加载函数
    
    参数:
        model: 要加载的模型实例
        load_path: 加载路径
        device: 设备(可选)
    
    返回:
        tuple: (是否加载成功, 元数据字典)
    """
    try:
        if device is None:
            device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
            
        # 加载数据
        # 显式声明 weights_only=True：只反序列化张量与基础类型，不执行任意 pickle 对象。
        # torch>=2.6 已默认如此，显式写出来是为锁定行为，避免将来依赖变化失效。
        checkpoint = torch.load(load_path, map_location=device, weights_only=True)
        
        # 处理状态字典
        if isinstance(checkpoint, dict) and 'model_state_dict' in checkpoint:
            # 提取状态字典和元数据
            state_dict = checkpoint['model_state_dict']
            metadata = {k: v for k, v in checkpoint.items() if k != 'model_state_dict'}
            
            # 加载状态字典
            model.load_state_dict(state_dict, strict=False)
        else:
            # 尝试直接加载
            model.load_state_dict(checkpoint, strict=False)
            metadata = {}
            
        # 确保模型在正确的设备上
        model.to(device)
        
        logger.info(f"模型已从 {load_path} 加载")
        return True, metadata
        
    except Exception as e:
        logger.error(f"加载模型失败: {str(e)}")
        return False, {}
