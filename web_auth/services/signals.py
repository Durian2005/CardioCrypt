# -*- coding: utf-8 -*-
"""
信号生成与心率特征判定

在没有真实硬件的场合（开发、演示、测试）用来合成 ECG / PPG 波形。
属于「算法侧工具」，与 Web 请求无关，因此不放进蓝图。
"""

import math
import random
from datetime import datetime

import numpy as np

from web_auth.core import HEART_RATE_CHARACTERISTIC, HEART_RATE_SERVICE



# 判断是否为心率服务
def is_heart_rate_service(service_uuid):
    """
    判断服务UUID是否为心率服务
    
    参数:
        service_uuid: 服务的UUID
        
    返回:
        是否为心率服务
    """
    return (HEART_RATE_SERVICE.lower() in service_uuid.lower() or 
            service_uuid.lower().endswith('180d'))


# 判断是否为心率特征
def is_heart_rate_characteristic(char_uuid):
    """
    判断特征UUID是否为心率特征
    
    参数:
        char_uuid: 特征的UUID
        
    返回:
        是否为心率特征
    """
    return (HEART_RATE_CHARACTERISTIC.lower() in char_uuid.lower() or 
            char_uuid.lower().endswith('2a37'))


def heart_rate_to_ecg(heart_rate, rr_interval=None):
    """
    根据心率生成模拟ECG信号
    
    参数:
        heart_rate: 心率（每分钟心跳数）
        rr_interval: RR间隔（毫秒），如果未提供则根据心率计算
        
    返回:
        ECG信号数组，包含10个数据点
    """
    if rr_interval is None:
        rr_interval = 60000.0 / heart_rate  # 将心率转换为RR间隔（毫秒）
    
    # 生成10个采样点的ECG信号，而不是100个
    ecg_array = np.zeros(10)
    
    # 基本频率与心率相关
    frequency = heart_rate / 60.0  # 每秒钟的心跳数
    
    # 为每个数据点生成信号
    for i in range(10):  # 修改为10个点
        # 将索引转换为时间点（秒）
        t = i / 10.0  # 假设10Hz的采样率
        
        # 计算在心跳周期内的相位
        phase = 2 * math.pi * frequency * t % (2 * math.pi)
        
        # 生成PQRST波形
        p_wave = 0.15 * math.sin(phase)
        qrs_complex = 0.0
        
        # QRS复合波
        if 0.0 <= phase < 0.1 * math.pi:
            qrs_complex = -0.3 * math.sin(10 * phase)  # Q波
        elif 0.1 * math.pi <= phase < 0.2 * math.pi:
            qrs_complex = 1.0 * math.sin(5 * phase)  # R波
        elif 0.2 * math.pi <= phase < 0.3 * math.pi:
            qrs_complex = -0.3 * math.sin(10 * phase)  # S波
        
        # T波
        t_wave = 0.3 * math.sin(phase - 0.5 * math.pi) if 0.3 * math.pi <= phase < 0.7 * math.pi else 0.0
        
        # 合成ECG信号
        ecg_signal = p_wave + qrs_complex + t_wave
        
        # 添加呼吸调制和噪声
        respiration = 0.1 * math.sin(phase / 5)  # 呼吸调制
        noise = 0.05 * (random.random() * 2 - 1)  # 随机噪声
        
        # 存储到数组
        ecg_array[i] = ecg_signal + respiration + noise
    
    return ecg_array


def heart_rate_to_ppg(heart_rate, rr_interval=None):
    """
    根据心率生成模拟PPG信号
    
    参数:
        heart_rate: 心率（每分钟心跳数）
        rr_interval: RR间隔（毫秒），如果未提供则根据心率计算
        
    返回:
        PPG信号值
    """
    if rr_interval is None:
        rr_interval = 60000.0 / heart_rate  # 将心率转换为RR间隔（毫秒）
    
    # 获取当前时间的微秒部分作为相位
    phase = (datetime.now().microsecond / 1000000.0) * 2 * math.pi
    
    # PPG波形（主要是收缩期和舒张期）
    ppg_base = 0.5  # 基线值
    
    # 收缩期波形（快速上升，缓慢下降）
    if 0.0 <= phase < 0.3 * math.pi:
        # 快速上升
        systolic = 0.8 * math.sin(phase / 0.3)
    elif 0.3 * math.pi <= phase < 1.0 * math.pi:
        # 缓慢下降
        systolic = 0.8 * math.cos((phase - 0.3 * math.pi) / 0.7)
    else:
        systolic = 0.0
    
    # 重搏波（二峰）
    dicrotic = 0.2 * math.sin(phase - 1.2 * math.pi) if 1.0 * math.pi <= phase < 1.5 * math.pi else 0.0
    
    # 合成PPG信号
    ppg_signal = ppg_base + systolic + dicrotic
    
    # 添加呼吸调制和噪声
    respiration = 0.1 * math.sin(phase / 5)  # 呼吸调制
    noise = 0.03 * (random.random() * 2 - 1)  # 随机噪声
    
    return ppg_signal + respiration + noise


# 从心率生成ECG和PPG数据
def generate_ecg_ppg_data(num_samples=600, base_heart_rate=70):
    """
    使用heart_beat模块中的函数生成ECG和PPG数据
    
    参数:
        num_samples: 生成的样本数量，默认为600以匹配新的序列长度
        base_heart_rate: 基础心率
    
    返回:
        ecg_data: ECG数据数组
        ppg_data: PPG数据数组
    """
    ecg_data = []
    ppg_data = []
    
    # 计算需要生成的心率点数量
    heart_rate_points = num_samples // 10  # 每个心率点生成10个ECG数据点
    if heart_rate_points < 1:
        heart_rate_points = 1
    
    # 生成心率变化，模拟真实情况
    heart_rate = base_heart_rate + random.uniform(-5, 5)
    
    # 估算RR间隔
    rr_interval = 60000.0 / heart_rate
    
    # 生成ECG和PPG数据
    for _ in range(heart_rate_points):
        ecg_values = heart_rate_to_ecg(heart_rate, rr_interval)
        ppg_value = heart_rate_to_ppg(heart_rate, rr_interval)
        
        # 添加ECG数组中的所有点
        for val in ecg_values:
            ecg_data.append(val)
        
        # 对于PPG，我们重复值以匹配ECG的点数
        for _ in range(len(ecg_values)):
            ppg_data.append(ppg_value)
        
        # 每次生成后稍微变化心率，使数据更自然
        heart_rate += random.uniform(-0.5, 0.5)
        rr_interval = 60000.0 / heart_rate
    
    # 确保数据长度正确
    if len(ecg_data) > num_samples:
        ecg_data = ecg_data[:num_samples]
        ppg_data = ppg_data[:num_samples]
    elif len(ecg_data) < num_samples:
        # 填充到所需长度
        padding_length = num_samples - len(ecg_data)
        ecg_data.extend([0] * padding_length)
        ppg_data.extend([0] * padding_length)
    
    return np.array(ecg_data), np.array(ppg_data)
