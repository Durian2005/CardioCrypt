"""
模型训练模块

提供模型训练相关的函数
"""

import torch
import torch.nn as nn
import torch.optim as optim
from typing import Dict, Any, Optional, Tuple

from ecgppg_system.config import settings
from ecgppg_system.config import config as dynamic_config
from ecgppg_system.models.trainer import ModelTrainer
from ecgppg_system.utils.logger import logger

def setup_training_environment(model: nn.Module, 
                             learning_rate: float = None, 
                             weight_decay: float = None) -> Tuple[optim.Optimizer, nn.Module]:
    """
    设置训练环境，创建优化器和损失函数
    
    Args:
        model: 模型实例
        learning_rate: 学习率，如果为None则使用默认值
        weight_decay: 权重衰减，如果为None则使用默认值
        
    Returns:
        Tuple[优化器, 损失函数]
    """
    # 设置默认值
    if learning_rate is None:
        learning_rate = settings.LEARNING_RATE
        
    if weight_decay is None:
        weight_decay = settings.WEIGHT_DECAY
    
    # 创建优化器
    optimizer = optim.Adam(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    
    # 创建损失函数（根据输出类型）
    # 对于回归任务使用MSE损失，对于二分类使用BCE损失
    # 这里简单地根据输出维度决定
    output_size = 1  # 默认值
    if hasattr(model, 'output_size'):
        output_size = model.output_size
    elif hasattr(model, 'fc') and hasattr(model.fc, 'out_features'):
        output_size = model.fc.out_features
    
    if output_size == 1:
        # 单输出，假设是二分类或回归
        criterion = nn.BCEWithLogitsLoss()  # 带有sigmoid的二元交叉熵
    else:
        # 多输出，假设是多分类
        criterion = nn.CrossEntropyLoss()
        
    logger.info(f"已设置训练环境: learning_rate={learning_rate}, weight_decay={weight_decay}")
    
    return optimizer, criterion

def train_model(model: nn.Module, 
               train_loader: torch.utils.data.DataLoader,
               val_loader: Optional[torch.utils.data.DataLoader] = None,
               epochs: int = None,
               early_stopping_patience: int = None,
               learning_rate: float = None,
               weight_decay: float = None,
               device: torch.device = None,
               use_data_augmentation: bool = False) -> Dict[str, Any]:
    """
    训练模型
    
    Args:
        model: 待训练的模型
        train_loader: 训练数据加载器
        val_loader: 验证数据加载器，可选
        epochs: 训练轮数，如果为None则使用默认值
        early_stopping_patience: 早停耐心值，如果为None则使用默认值
        learning_rate: 学习率，如果为None则使用默认值
        weight_decay: 权重衰减，如果为None则使用默认值
        device: 训练设备
        use_data_augmentation: 是否使用数据增强
        
    Returns:
        Dict[str, Any]: 训练历史
    """
    # 设置默认值
    if epochs is None:
        epochs = dynamic_config.get('training', 'epochs', 50)
        
    if early_stopping_patience is None:
        early_stopping_patience = dynamic_config.get('training', 'early_stopping_patience', 10)
        
    if learning_rate is None:
        learning_rate = dynamic_config.get('training', 'learning_rate', 0.001)
        
    if weight_decay is None:
        weight_decay = dynamic_config.get('training', 'weight_decay', 0.0001)
    
    # 创建训练器
    trainer = ModelTrainer(
        model=model,
        learning_rate=learning_rate,
        device=device,
        weight_decay=weight_decay,
        use_data_augmentation=use_data_augmentation
    )
    
    # 训练前先评估模型，作为基准
    logger.info("评估初始模型性能（基准）:")
    if val_loader:
        initial_eval = trainer.evaluate(val_loader)
        logger.info(f"  初始损失: {initial_eval['loss']:.6f}")
        logger.info(f"  初始均方误差: {initial_eval['mse']:.6f}")
        logger.info(f"  初始R方: {initial_eval['r2']:.6f}")
    
    # 开始训练
    logger.info(f"开始训练，轮数: {epochs}, 早停耐心值: {early_stopping_patience}")
    
    # 训练模型
    history = trainer.train(
        train_loader=train_loader,
        val_loader=val_loader,
        epochs=epochs,
        patience=early_stopping_patience
    )
    
    # 返回训练历史
    return history

def configure_data_augmentation(train_loader: torch.utils.data.DataLoader) -> bool:
    """
    配置数据增强策略
    
    Args:
        train_loader: 训练数据加载器
        
    Returns:
        bool: 是否启用数据增强
    """
    # 简单的启发式决定是否使用数据增强
    # 如果训练样本较少，启用增强
    sample_count = len(train_loader.dataset)
    
    use_augmentation = sample_count < 1000
    
    if use_augmentation:
        logger.info(f"训练样本数量较少({sample_count})，启用数据增强")
    else:
        logger.info(f"训练样本数量充足({sample_count})，不使用数据增强")
        
    return use_augmentation

def setup_early_stopping(validation_data_available: bool = True) -> Tuple[int, str]:
    """
    设置早停策略
    
    Args:
        validation_data_available: 是否有验证数据
        
    Returns:
        Tuple[int, str]: (耐心值, 监控指标)
    """
    # 如果有验证数据，使用val_loss作为指标
    # 否则使用train_loss
    if validation_data_available:
        monitor = 'val_loss'
        patience = dynamic_config.get('training', 'early_stopping_patience', 10)
    else:
        monitor = 'train_loss'
        # 没有验证集，增加耐心值避免过早停止
        patience = int(dynamic_config.get('training', 'early_stopping_patience', 10) * 1.5) 
        
    logger.info(f"设置早停策略: 监控指标={monitor}, 耐心值={patience}")
    
    return patience, monitor 