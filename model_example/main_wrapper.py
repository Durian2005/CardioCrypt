"""
主封装模块（已废弃 · 保留供参考，请勿在新代码中调用）
=========================================================================

本模块是早期把 `main.py` 的流程拆成模块化实现时留下的**薄封装层**：每个函数
都只是转调 `model_example` 里对应的模块，本身不含独立逻辑。**当前无任何调用方**：

* 仓库内没有任何地方调用这里的 7 个函数。`web_auth.core` 曾导入
  `create_and_train_model` / `authenticate_user`（也因此从未被调用），现已移除。
* 生产链路走的是各模块本身：`web_auth/blueprints/device.py` 直接用
  `create_model` / `train_model` / `save_model`，验证用 `authenticate_single_signal`。

**不要让本模块重新进入 import 图。** 它在顶层导入
`ecgppg_system.devices.device_manager.EnvironmentManager`，而后者依赖串口相关的
可选依赖；一旦缺失，本模块 import 失败会顺着 `web_auth.core` 的 try 把
`SYSTEM_AVAILABLE` 置为 False，整个 Web 层跟着降级 —— 而它并不提供任何在用
的能力，代价与收益完全不成比例。

保留而不删除的原因：这是项目原始贡献者提交的实现，删除会抹去他人的代码与
历史；标注废弃可以让后来者少踩一遍同样的坑。
"""

import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from typing import Dict, Any, Optional, Tuple, List, Union
import os

from ecgppg_system.utils.logger import logger
from ecgppg_system.config import settings
from ecgppg_system.models.bilstm import BiLSTMWithAttention
from ecgppg_system.devices.device_manager import EnvironmentManager

# 导入所有模块化组件
from model_example.model_creator import create_model, configure_model_architecture, setup_model_device
from model_example.model_io import save_model, load_model, get_automatic_save_path
from model_example.model_trainer import train_model, configure_data_augmentation, setup_early_stopping
from model_example.model_evaluator import validate_model, evaluate_model_metrics
from model_example.data_validator import validate_data_quality, check_data_overlap
from model_example.model_predictor import predict_sequence, batch_predict, calculate_prediction_metrics
from model_example.authentication import authenticate_single_signal, authenticate_dual_signals

def create_and_train_model(train_loader: torch.utils.data.DataLoader,
                          val_loader: Optional[torch.utils.data.DataLoader] = None,
                          test_loader: Optional[torch.utils.data.DataLoader] = None,
                          signal_type: str = 'ecg',
                          input_size: int = 1000,
                          epochs: int = None,
                          patience: int = None,
                          learning_rate: float = None,
                          weight_decay: float = None,
                          save_path: str = None,
                          device: torch.device = None,
                          visualize: bool = False) -> Tuple[nn.Module, Dict[str, Any], Dict[str, Any]]:
    """
    创建并训练模型

    Args:
        train_loader: 训练数据加载器
        val_loader: 验证数据加载器
        test_loader: 测试数据加载器
        signal_type: 信号类型 ('ecg' 或 'ppg')
        input_size: 输入特征维度
        epochs: 训练轮数
        patience: 早停耐心值
        learning_rate: 学习率
        weight_decay: 权重衰减
        save_path: 模型保存路径
        device: 计算设备
        visualize: 是否生成训练过程的可视化图表

    Returns:
        Tuple[nn.Module, Dict[str, Any], Dict[str, Any]]: (训练好的模型, 训练历史, 验证结果)
    """
    logger.info(f"创建并训练{signal_type}模型...")
    
    # 1. 创建模型
    model = create_model(input_size=input_size)
    
    # 2. 设置模型设备
    model, device = setup_model_device(model, device)
    
    # 3. 配置数据增强
    use_data_augmentation = configure_data_augmentation(train_loader)
    
    # 4. 训练模型
    history = train_model(
        model=model,
        train_loader=train_loader,
        val_loader=val_loader,
        epochs=epochs,
        early_stopping_patience=patience,
        learning_rate=learning_rate,
        weight_decay=weight_decay,
        device=device,
        use_data_augmentation=use_data_augmentation
    )
    
    # 5. 验证模型
    validation_results = {}
    if test_loader:
        validation_results = validate_model(
            model=model,
            train_loader=train_loader,
            test_loader=test_loader,
            signal_type=signal_type,
            device=device
        )
    
    # 6. 保存模型
    if save_path is None:
        save_path = get_automatic_save_path(signal_type)
    
    metadata = {
        'signal_type': signal_type,
        'input_size': input_size,
        'epochs_trained': history.get('epochs_trained', 0),
        'final_train_loss': history.get('train_loss', [])[-1] if history.get('train_loss') else None,
        'final_val_loss': history.get('val_loss', [])[-1] if history.get('val_loss') else None
    }
    
    save_success = save_model(model, save_path, metadata)
    
    if save_success:
        logger.info(f"{signal_type}模型训练完成，已保存到{save_path}")
    else:
        logger.warning(f"{signal_type}模型训练完成，但保存失败")
    
    # 7. 可视化训练过程（如果需要）
    if visualize:
        try:
            import matplotlib.pyplot as plt
            
            # 设置中文显示
            plt.rcParams['font.sans-serif'] = ['SimHei']  # 设置中文字体
            plt.rcParams['axes.unicode_minus'] = False    # 解决负号显示问题
            
            # 创建图形
            plt.figure(figsize=(12, 8))
            
            # 绘制损失曲线
            plt.subplot(2, 2, 1)
            plt.plot(history['train_loss'], label='训练损失')
            if 'val_loss' in history and history['val_loss']:
                plt.plot(history['val_loss'], label='验证损失')
            plt.xlabel('轮次')
            plt.ylabel('损失')
            plt.title('训练和验证损失')
            plt.legend()
            
            # 如果有验证结果，绘制更多图表
            if validation_results:
                # 绘制预测与实际值对比
                if 'predictions' in validation_results and 'actuals' in validation_results:
                    plt.subplot(2, 2, 2)
                    plt.scatter(validation_results['actuals'], validation_results['predictions'], alpha=0.5)
                    plt.xlabel('实际值')
                    plt.ylabel('预测值')
                    plt.title('预测与实际值对比')
                    
                    # 添加对角线
                    min_val = min(validation_results['actuals'].min(), validation_results['predictions'].min())
                    max_val = max(validation_results['actuals'].max(), validation_results['predictions'].max())
                    plt.plot([min_val, max_val], [min_val, max_val], 'r--')
            
            # 保存图表
            visualization_path = f"{os.path.splitext(save_path)[0]}_training_viz.png"
            plt.tight_layout()
            plt.savefig(visualization_path)
            plt.close()
            
            logger.info(f"训练可视化已保存到 {visualization_path}")
            
        except Exception as e:
            logger.warning(f"生成训练可视化失败: {e}")
    
    return model, history, validation_results

def load_and_evaluate_model(model_path: str,
                           test_loader: torch.utils.data.DataLoader,
                           device: torch.device = None) -> Tuple[nn.Module, Dict[str, Any]]:
    """
    加载并评估模型

    Args:
        model_path: 模型路径
        test_loader: 测试数据加载器
        device: 计算设备

    Returns:
        Tuple[nn.Module, Dict[str, Any]]: (加载的模型, 评估结果)
    """
    # 1. 加载模型
    model, metadata = load_model(model_path, device)
    
    if model is None:
        logger.error(f"无法加载模型: {model_path}")
        return None, {}
    
    # 2. 评估模型
    metrics = evaluate_model_metrics(model, test_loader, device)
    
    logger.info(f"模型评估: loss={metrics['loss']:.4f}, mse={metrics['mse']:.4f}, r2={metrics['r2']:.4f}")
    
    return model, metrics

def predict_with_model(model: nn.Module,
                      input_data: Union[np.ndarray, torch.Tensor],
                      device: torch.device = None) -> np.ndarray:
    """
    使用模型进行预测

    Args:
        model: 模型
        input_data: 输入数据
        device: 计算设备

    Returns:
        np.ndarray: 预测结果
    """
    # 使用预测模块的函数
    predictions = predict_sequence(model, input_data, device)
    
    # 转换为numpy数组
    if isinstance(predictions, torch.Tensor):
        predictions = predictions.cpu().numpy()
    
    return predictions

def authenticate_user(reference_data: Union[np.ndarray, torch.Tensor] = None, 
                     query_data: Union[np.ndarray, torch.Tensor] = None, 
                     signal_type: str = 'ecg', 
                     user_id: str = None,
                     model: nn.Module = None,
                     threshold: float = 0.5, 
                     device: torch.device = None,
                     visualize: bool = False) -> Dict[str, Any]:
    """
    使用单一信号进行用户身份验证

    Args:
        reference_data: 参考信号数据（可选）
        query_data: 查询信号数据
        signal_type: 信号类型 ('ecg' 或 'ppg')
        user_id: 用户ID
        model: 用于验证的模型
        threshold: 验证阈值
        device: 计算设备
        visualize: 是否可视化

    Returns:
        Dict[str, Any]: 身份验证结果
    """
    # 初始化结果字典
    result = {
        'success': False,
        'user_id': user_id,
        'confidence': 0.0,
        'threshold': threshold,
        'similarity': 0.0,
        'message': ""
    }
    
    try:
        # 参数验证
        if query_data is None:
            result['message'] = "缺少查询数据"
            logger.error(result['message'])
            return result
        
        # 如果未提供模型或阈值，使用默认设置
        if threshold is None:
            if signal_type == 'ecg':
                threshold = settings.ECG_AUTH_THRESHOLD
            elif signal_type == 'ppg':
                threshold = settings.PPG_AUTH_THRESHOLD
            else:
                threshold = 0.5
                
        result['threshold'] = threshold
            
        # 使用authenticate_single_signal函数进行验证
        auth_result = authenticate_single_signal(
            model=model,
            input_signal=query_data,
            threshold=threshold,
            signal_type=signal_type,
            device=device,
            visualize=visualize
        )
        
        # 更新结果
        result['success'] = auth_result['authenticated']
        result['similarity'] = auth_result['score']
        result['confidence'] = auth_result['score']
        
        if result['success']:
            result['message'] = f"验证成功，用户ID: {user_id}, 相似度: {result['similarity']:.4f}"
            logger.info(result['message'])
        else:
            result['message'] = f"验证失败，相似度 {result['similarity']:.4f} 低于阈值 {threshold}"
            logger.warning(result['message'])
        
        return result
        
    except Exception as e:
        result['message'] = f"身份验证过程发生错误: {str(e)}"
        logger.exception(result['message'])
        return result

# 保留原来的dual_signal身份验证函数，但重命名为authenticate_with_dual_signals
def authenticate_with_dual_signals(ecg_model: nn.Module,
                     ppg_model: nn.Module,
                     ecg_data: Union[np.ndarray, torch.Tensor],
                     ppg_data: Union[np.ndarray, torch.Tensor],
                     ecg_threshold: float = 0.5,
                     ppg_threshold: float = 0.5,
                     fusion_method: str = 'weighted',
                     device: torch.device = None) -> Dict[str, Any]:
    """
    使用ECG和PPG数据验证用户身份

    Args:
        ecg_model: ECG模型
        ppg_model: PPG模型
        ecg_data: ECG数据
        ppg_data: PPG数据
        ecg_threshold: ECG验证阈值
        ppg_threshold: PPG验证阈值
        fusion_method: 融合方法
        device: 计算设备

    Returns:
        Dict[str, Any]: 身份验证结果
    """
    # 使用验证模块的函数
    result = authenticate_dual_signals(
        ecg_model=ecg_model,
        ppg_model=ppg_model,
        ecg_signal=ecg_data,
        ppg_signal=ppg_data,
        ecg_threshold=ecg_threshold,
        ppg_threshold=ppg_threshold,
        fusion_method=fusion_method,
        device=device
    )
    
    return result

def validate_data(data: Union[np.ndarray, torch.Tensor],
                 signal_type: str) -> Dict[str, Any]:
    """
    验证数据质量

    Args:
        data: 要验证的数据
        signal_type: 信号类型

    Returns:
        Dict[str, Any]: 验证结果
    """
    # 使用数据验证模块的函数
    return validate_data_quality(data, signal_type)

def save_trained_model(model: nn.Module,
                      save_path: str,
                      metadata: Dict[str, Any] = None) -> bool:
    """
    保存训练好的模型

    Args:
        model: 训练好的模型
        save_path: 保存路径
        metadata: 元数据

    Returns:
        bool: 是否成功保存
    """
    return save_model(model, save_path, metadata) 