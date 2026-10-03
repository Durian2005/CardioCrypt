"""
BiLSTM模型模块
提供双向LSTM模型，用于ECG和PPG信号的预测和分析
"""

import torch
import torch.nn as nn
from typing import Optional, Tuple

from ..utils.logger import setup_logger
from ..devices.device_manager import EnvironmentManager

logger = setup_logger(__name__)

class BiLSTMWithAttention(nn.Module):
    """
    带注意力机制的双向LSTM模型
    """
    
    def __init__(self, input_size: int = 1000, 
                hidden_size: int = 128, 
                num_layers: int = 1, 
                output_size: int = 1, 
                dropout: float = 0.1, 
                regularization: float = 0.001, 
                bidirectional: bool = True):
        """
        初始化带注意力机制的BiLSTM模型
        
        参数:
            input_size: 输入特征维度，默认1000
            hidden_size: 隐藏层大小，默认128
            num_layers: LSTM层数，默认1
            output_size: 输出维度，默认1
            dropout: Dropout比率，默认0.1
            regularization: L2正则化系数，默认0.001
            bidirectional: 是否使用双向LSTM，默认True
        """
        super(BiLSTMWithAttention, self).__init__()
        self.input_size = input_size  # 将input_size作为实例变量保存
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.output_size = output_size
        self.dropout_rate = dropout
        self.regularization = regularization
        self.bidirectional = bidirectional
        self.directions = 2 if bidirectional else 1
        
        # LSTM层
        self.lstm = nn.LSTM(
            input_size=self.input_size,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            batch_first=True,
            bidirectional=self.bidirectional,
            dropout=self.dropout_rate if self.num_layers > 1 else 0
        )
        
        # 注意力机制参数
        self.attention_weights = nn.Parameter(
            torch.Tensor(self.hidden_size * self.directions, 1)
        )
        
        # 全连接层
        self.fc = nn.Linear(self.hidden_size * self.directions, self.output_size)
        
        # Dropout层
        self.dropout = nn.Dropout(self.dropout_rate)
        
        # 初始化权重
        self.init_weights()
        
        logger.info(f"初始化BiLSTMWithAttention模型: input_size={input_size}, hidden_size={hidden_size}, "
                   f"output_size={output_size}, num_layers={num_layers}")
                   
    def set_input_size(self, new_input_size: int) -> None:
        """
        动态设置input_size，重新初始化LSTM层
        
        参数:
            new_input_size: 新的输入特征维度
        """
        if new_input_size == self.input_size:
            return  # 如果尺寸相同，不需要更改
            
        self.input_size = new_input_size
        # 重新创建LSTM层
        self.lstm = nn.LSTM(
            input_size=self.input_size,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            batch_first=True,
            bidirectional=self.bidirectional,
            dropout=self.dropout_rate if self.num_layers > 1 else 0
        )
        # 重新初始化权重
        self.init_weights()
        
    def init_weights(self) -> None:
        """初始化网络权重"""
        for name, param in self.named_parameters():
            if 'weight' in name:
                nn.init.xavier_normal_(param)
            elif 'bias' in name:
                nn.init.constant_(param, 0.0)
        
        # 特别初始化注意力权重
        nn.init.xavier_normal_(self.attention_weights)
    
    def attention_net(self, lstm_output: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        注意力机制实现
        
        参数:
            lstm_output: LSTM输出，形状为(batch_size, seq_len, hidden_size*directions)
            
        返回:
            Tuple[torch.Tensor, torch.Tensor]: (上下文向量, 注意力权重)
        """
        # 计算注意力分数
        # (batch_size, seq_len, hidden_size*directions) x (hidden_size*directions, 1)
        # -> (batch_size, seq_len, 1)
        attn_weights = torch.matmul(lstm_output, self.attention_weights)
        
        # 通过softmax获取注意力权重
        soft_attn_weights = torch.softmax(attn_weights, dim=1)
        
        # 应用注意力权重到LSTM输出
        # (batch_size, 1, seq_len) x (batch_size, seq_len, hidden_size*directions)
        # -> (batch_size, 1, hidden_size*directions)
        context = torch.bmm(soft_attn_weights.transpose(1, 2), lstm_output)
        # (batch_size, hidden_size*directions)
        context = context.squeeze(1)
        
        return context, soft_attn_weights.squeeze(-1)
        
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        前向传播
        
        参数:
            x: 输入张量，形状为 (batch_size, sequence_length, input_size)
            
        返回:
            预测输出，形状为 (batch_size, output_size)
        """
        # LSTM前向传播
        lstm_out, _ = self.lstm(x)  # lstm_out: (batch_size, seq_len, hidden_size*2)
        
        # 应用注意力机制
        context, _ = self.attention_net(lstm_out)
        
        # 应用全连接层
        context = self.dropout(context)
        output = self.fc(context)
        
        return output
        
    def predict_sequence(self, 
                         initial_sequence: torch.Tensor, 
                         future_steps: int, 
                         device: Optional[str] = None) -> torch.Tensor:
        """
        预测未来序列
        
        参数:
            initial_sequence (torch.Tensor): 初始序列，形状为[1, seq_len, input_size]
            future_steps (int): 预测的未来步数
            device (str): 设备，'cuda'或'cpu'
            
        返回:
            torch.Tensor: 预测序列，形状为[future_steps, output_size]
        """
        if device is None:
            device = EnvironmentManager.get_optimal_device()
        
        self.eval()  # 设置为评估模式
        
        with torch.no_grad():
            # 确保输入张量在正确的设备上
            current_sequence = initial_sequence.clone().to(device)
            
            # 存储预测结果
            predictions = []
            
            for _ in range(future_steps):
                # 预测下一个值
                next_pred = self(current_sequence)
                
                # 添加到预测结果列表
                predictions.append(next_pred)
                
                # 更新序列（移除最早的时间步，添加新预测的时间步）
                new_sequence = torch.cat((current_sequence[:, 1:, :], next_pred.unsqueeze(1)), dim=1)
                current_sequence = new_sequence
                
            # 将预测结果堆叠成一个张量
            predictions = torch.cat(predictions, dim=0)
            
        return predictions 