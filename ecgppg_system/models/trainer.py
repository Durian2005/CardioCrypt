#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
模型训练模块
提供模型训练和评估功能
"""

import os
import copy
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from typing import Dict, Any, Optional, Union

from ..utils.logger import logger
from ..config import settings
from ..config import config as dynamic_config
from ..devices.device_manager import EnvironmentManager

class ModelTrainer:
    """
    模型训练器类，封装模型训练和评估的功能
    """
    
    def __init__(self, 
                 model: nn.Module, 
                 learning_rate: Optional[float] = None, 
                 device: Optional[Union[str, torch.device]] = None, 
                 weight_decay: Optional[float] = None, 
                 use_data_augmentation: bool = False):
        """
        初始化模型训练器
        
        参数:
            model (nn.Module): 要训练的模型
            learning_rate (float, optional): 学习率
            device (str, optional): 训练设备
            weight_decay (float, optional): 权重衰减参数，用于L2正则化
            use_data_augmentation (bool, optional): 是否使用数据增强，默认为False
        """
        if learning_rate is None:
            learning_rate = dynamic_config.get('training', 'learning_rate', 0.001)
            
        if device is None:
            # 使用EnvironmentManager获取最优设备
            device = EnvironmentManager.get_optimal_device()
            
        if weight_decay is None:
            weight_decay = dynamic_config.get('training', 'weight_decay', 0.0001)
            
        self.model = model
        self.device = device
        self.learning_rate = learning_rate
        self.weight_decay = weight_decay
        self.use_data_augmentation = use_data_augmentation
        
        # 将模型移动到指定设备
        self.model.to(self.device)
        
        # 设置优化器，添加weight_decay参数
        self.optimizer = optim.Adam(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
        
        # 设置损失函数
        self.criterion = nn.MSELoss()
        
        # 初始化训练历史
        self.train_losses = []
        self.val_losses = []
        
        logger.info(f"初始化模型训练器: model={type(model).__name__}, learning_rate={learning_rate}, "
                   f"weight_decay={weight_decay}, device={device}, use_data_augmentation={use_data_augmentation}")
        
    def train_epoch(self, data_loader) -> float:
        """
        训练一个周期
        
        参数:
            data_loader (DataLoader): 训练数据加载器
            
        返回:
            float: 平均训练损失
        """
        self.model.train()  # 设置为训练模式
        total_loss = 0
        
        for batch_idx, (data, target) in enumerate(data_loader):
            # 移动数据到设备
            data, target = data.to(self.device), target.to(self.device)
            
            # 如果启用数据增强，对输入数据进行增强
            if self.use_data_augmentation:
                data = self._augment_data(data)
            
            # 确保目标维度与模型输出一致
            if len(target.shape) == 1 and hasattr(self.model, 'output_size') and self.model.output_size > 0:
                # 如果目标是一维的，但模型输出是多维的，扩展目标维度
                target = target.view(-1, 1)
            
            # 清零梯度
            self.optimizer.zero_grad()
            
            # 前向传播
            output = self.model(data)
            
            # 计算损失
            loss = self.criterion(output, target)
            
            # 反向传播
            loss.backward()
            
            # 更新权重
            self.optimizer.step()
            
            # 累加损失
            total_loss += loss.item()
            
        # 计算平均损失
        avg_loss = total_loss / len(data_loader)
        self.train_losses.append(avg_loss)
        
        return avg_loss
        
    def _augment_data(self, data: torch.Tensor) -> torch.Tensor:
        """
        对数据进行增强
        
        参数:
            data (torch.Tensor): 输入数据
            
        返回:
            torch.Tensor: 增强后的数据
        """
        batch_size = data.size(0)
        
        # 随机选择增强方法，每个批次可能应用不同的增强
        augmentation_choice = torch.randint(0, 4, (batch_size,))
        
        # 为每个样本创建增强副本
        augmented_data = data.clone()
        
        for i in range(batch_size):
            choice = augmentation_choice[i].item()
            
            if choice == 0:
                # 随机噪声添加
                noise = torch.randn_like(data[i]) * 0.03  # 3%强度的高斯噪声
                augmented_data[i] = data[i] + noise
            elif choice == 1:
                # 随机振幅缩放
                scale = torch.FloatTensor(1).uniform_(0.9, 1.1).to(self.device)  # 随机缩放因子
                augmented_data[i] = data[i] * scale
            elif choice == 2:
                # 时间偏移(随机移动序列位置)
                if len(data[i].shape) > 1 and data[i].shape[0] > 10:
                    shift = torch.randint(-3, 4, (1,)).item()  # 随机偏移量
                    if shift > 0:
                        augmented_data[i, shift:] = data[i, :-shift]
                        augmented_data[i, :shift] = data[i, :shift]
                    elif shift < 0:
                        shift = abs(shift)
                        augmented_data[i, :-shift] = data[i, shift:]
                        augmented_data[i, -shift:] = data[i, -shift:]
            # choice == 3时不做任何增强，保持原样
        
        logger.debug(f"已应用数据增强，原始形状: {data.shape}")
        return augmented_data
        
    def validate(self, data_loader) -> float:
        """
        验证模型性能
        
        参数:
            data_loader (DataLoader): 验证数据加载器
            
        返回:
            float: 平均验证损失
        """
        self.model.eval()  # 设置为评估模式
        total_loss = 0
        
        with torch.no_grad():
            for data, target in data_loader:
                # 移动数据到设备
                data, target = data.to(self.device), target.to(self.device)
                
                # 确保目标维度与模型输出一致
                if len(target.shape) == 1 and hasattr(self.model, 'output_size') and self.model.output_size > 0:
                    # 如果目标是一维的，但模型输出是多维的，扩展目标维度
                    target = target.view(-1, 1)
                
                # 前向传播
                output = self.model(data)
                
                # 计算损失
                loss = self.criterion(output, target)
                
                # 累加损失
                total_loss += loss.item()
                
        # 计算平均损失
        avg_loss = total_loss / len(data_loader)
        self.val_losses.append(avg_loss)
        
        return avg_loss
        
    def train(self, train_loader, val_loader=None, epochs=None, patience=None) -> Dict[str, Any]:
        """
        训练模型
        
        参数:
            train_loader (DataLoader): 训练数据加载器
            val_loader (DataLoader, optional): 验证数据加载器
            epochs (int, optional): 训练轮数
            patience (int, optional): 早停耐心值
            
        返回:
            dict: 训练历史记录
        """
        # 设置轮数
        if epochs is None:
            epochs = dynamic_config.get('training', 'epochs', 50)
            
        # 设置早停耐心值
        if patience is None:
            patience = dynamic_config.get('training', 'early_stopping_patience', 10)
            
        logger.info(f"开始训练模型: epochs={epochs}, patience={patience}")
        
        # 记录最佳验证损失和对应的轮数
        best_val_loss = float('inf')
        best_epoch = 0
        no_improve_count = 0
        
        # 保存最佳模型的状态字典
        best_model_state = None
        
        # 初始化保存路径
        best_model_path = os.path.join(settings.MODEL_DIR, 'BiLSTMWithAttention_best.pth')
        final_model_path = os.path.join(settings.MODEL_DIR, 'BiLSTMWithAttention_final.pth')
        os.makedirs(settings.MODEL_DIR, exist_ok=True)
        
        for epoch in range(1, epochs + 1):
            # 训练一个周期
            train_loss = self.train_epoch(train_loader)
            
            # 如果有验证集，进行验证
            if val_loader is not None:
                val_loss = self.validate(val_loader)
                
                # 检查是否是最佳模型
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    best_epoch = epoch
                    no_improve_count = 0
                    
                    # 保存最佳模型状态
                    best_model_state = copy.deepcopy(self.model.state_dict())
                    
                    # 保存最佳模型
                    torch.save(self.model.state_dict(), best_model_path)
                    logger.info(f"模型已保存到: {best_model_path} (Epoch {epoch}, 验证损失: {val_loss:.4f})")
                else:
                    no_improve_count += 1
                    
                # 输出训练信息
                logger.info(f"Epoch {epoch}/{epochs}, 训练损失: {train_loss:.4f}, 验证损失: {val_loss:.4f}")
                
                # 检查是否早停
                if patience > 0 and no_improve_count >= patience:
                    logger.info(f"早停: {patience}个epoch没有改进")
                    break
            else:
                # 如果没有验证集，只输出训练损失
                logger.info(f"Epoch {epoch}/{epochs}, 训练损失: {train_loss:.4f}")
                
                # 如果没有验证集，每个epoch都保存模型
                if train_loss < best_val_loss:
                    best_val_loss = train_loss
                    best_epoch = epoch
                    
                    # 保存最佳模型状态
                    best_model_state = copy.deepcopy(self.model.state_dict())
                    
                    # 保存最佳模型
                    torch.save(self.model.state_dict(), best_model_path)
                    logger.info(f"模型已保存到: {best_model_path} (Epoch {epoch}, 训练损失: {train_loss:.4f})")
        
        # 训练结束，保存最终模型
        torch.save(self.model.state_dict(), final_model_path)
        logger.info(f"最终模型已保存到: {final_model_path}")
        
        # 重要：加载最佳模型而不是使用最终状态
        if best_model_state is not None:
            logger.info(f"加载最佳模型 (Epoch {best_epoch})")
            self.model.load_state_dict(best_model_state)
        
        # 准备返回的训练历史记录
        history = {
            'train_losses': self.train_losses,
            'val_losses': self.val_losses if val_loader is not None else [],
            'best_epoch': best_epoch,
            'best_val_loss': best_val_loss if val_loader is not None else None
        }
        
        return history
        
    def save_model(self, filename: str) -> bool:
        """
        保存模型
        
        参数:
            filename (str): 文件名
            
        返回:
            bool: 是否成功保存
        """
        from ..utils.model_utils import save_model
        
        # 完整路径
        filepath = os.path.join(settings.MODEL_DIR, filename)
        
        # 准备元数据
        metadata = {
            'optimizer_state_dict': self.optimizer.state_dict(),
            'train_losses': self.train_losses,
            'val_losses': self.val_losses,
            'model_config': {
                'input_size': getattr(self.model, 'input_size', 0),
                'hidden_size': getattr(self.model, 'hidden_size', 0),
                'output_size': getattr(self.model, 'output_size', 0),
                'num_layers': getattr(self.model, 'num_layers', 0)
            }
        }
        
        # 使用通用保存函数
        return save_model(self.model, filepath, metadata=metadata)
        
    def load_model(self, filename: str) -> bool:
        """
        加载模型
        
        参数:
            filename (str): 文件名
            
        返回:
            bool: 是否成功加载
        """
        from ..utils.model_utils import load_model
        
        # 完整路径
        filepath = os.path.join(settings.MODEL_DIR, filename)
        
        # 使用通用加载函数
        success, metadata = load_model(self.model, filepath, device=self.device)
        
        if success and metadata:
            # 加载优化器状态和训练历史
            if 'optimizer_state_dict' in metadata:
                self.optimizer.load_state_dict(metadata['optimizer_state_dict'])
            
            if 'train_losses' in metadata:
                self.train_losses = metadata['train_losses']
                
            if 'val_losses' in metadata:
                self.val_losses = metadata['val_losses']
                
        return success
            
    def evaluate(self, test_loader) -> Dict[str, Any]:
        """
        在测试集上评估模型
        
        参数:
            test_loader (DataLoader): 测试数据加载器
            
        返回:
            dict: 评估结果
        """
        self.model.eval()  # 设置为评估模式
        
        total_loss = 0
        all_preds = []
        all_targets = []
        
        with torch.no_grad():
            for data, target in test_loader:
                # 将数据移动到设备上
                data, target = data.to(self.device), target.to(self.device)
                
                # 前向传播
                output = self.model(data)
                
                # 计算损失
                loss = self.criterion(output, target)
                
                # 累加损失
                total_loss += loss.item()
                
                # 收集预测和目标
                all_preds.append(output.cpu().numpy())
                all_targets.append(target.cpu().numpy())
                
        # 计算平均损失
        avg_loss = total_loss / len(test_loader)
        
        # 将预测和目标转换为numpy数组
        all_preds = np.concatenate(all_preds, axis=0)
        all_targets = np.concatenate(all_targets, axis=0)
        
        # 计算均方误差
        mse = np.mean(np.square(all_preds - all_targets))
        
        # 计算平均绝对误差
        mae = np.mean(np.abs(all_preds - all_targets))
        
        # 计算R方值
        target_mean = np.mean(all_targets, axis=0)
        ss_tot = np.sum(np.square(all_targets - target_mean), axis=0)
        ss_res = np.sum(np.square(all_targets - all_preds), axis=0)
        r2 = 1 - (ss_res / ss_tot)
        
        # 确保指标是标量而非数组
        if isinstance(mse, np.ndarray):
            mse = float(np.mean(mse))
        if isinstance(mae, np.ndarray):
            mae = float(np.mean(mae))
        if isinstance(r2, np.ndarray):
            r2 = float(np.mean(r2))
        
        # 评估结果
        results = {
            'loss': avg_loss,
            'mse': mse,
            'mae': mae,
            'r2': r2,
            'predictions': all_preds,
            'targets': all_targets
        }
        
        logger.info(f"模型评估结果: loss={avg_loss:.4f}, mse={mse:.4f}, mae={mae:.4f}, r2={r2:.4f}")
        
        return results 