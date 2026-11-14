# -*- coding: utf-8 -*-
"""
信号生成与心率特征判定

在没有真实硬件的场合（开发、演示、测试）用来合成 ECG / PPG 波形。
属于「算法侧工具」，与 Web 请求无关，因此不放进蓝图。
"""

import hashlib
import math
import random
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from web_auth.core import HEART_RATE_CHARACTERISTIC, HEART_RATE_SERVICE


#: 模型的时间步长 —— 一个训练样本 / 一个判定窗口包含多少个采样值。
#:
#: 这是训练与判定的**同一个形状约定**，所以放在两边的共同依赖里，而不是各写一份：
#: 训练（`blueprints/device.py`）按它切窗，验证（`blueprints/auth.py`）必须按同一
#: 长度切窗。两边不一致时，同一段信号会落在完全不同的分数区间 —— 实测把 600 点
#: 整段喂给按 10 步训练的模型，分数整体漂到 1.06~1.99，而模型的训练目标是 1.0。
#: 那种情况下阈值 0.8 拦不住任何东西，因为它低于整段口径的分数下限。
MODEL_WINDOW_LENGTH = 10



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


def filter_signal_arrays(signals):
    """
    从采集结果里挑出真正的数组，丢掉标量/异常元素。

    采集层交回来的 `points` 理论上每个都是 `np.ndarray`，但设备异常时
    可能混入标量，直接 `np.concatenate` 会抛 "zero-dimensional arrays
    cannot be concatenated"。这里先滤一遍，让调用方拿到的都是可拼接的数组。

    这段过滤原先在 `blueprints/auth.py` 与 `blueprints/device.py` 各写一遍
    （连注释都逐字相同），抽到算法侧工具模块，两端共用同一份判定。
    """
    return [s for s in signals if len(s.shape) >= 1]


# ---------------------------------------------------------------------------
# 波形形态：让「不同主体」的心电长得不一样
# ---------------------------------------------------------------------------
#
# 背景：原先 `heart_rate_to_ecg` 把 P/Q/R/S/T 各波的幅度、呼吸调制、噪声
# 全写成字面量，唯一可变的输入只有心率。结果是**任何两个主体在同一心率下
# 生成的波形几乎相同** —— 合成数据里根本不存在身份差异，因此无论用哪种
# 比对方式都测不出「同人 vs 不同人」的可分性。
#
# 这里把那些字面量提成一组命名参数，让「波形长什么样」与「心跳多快」正交。
# 默认值逐项等于原字面量，所以不传 `morphology` 时波形与改动前完全一致。
@dataclass(frozen=True)
class EcgMorphology:
    """单个主体的 ECG 形态参数（幅度类，与心率无关）。

    取名刻意贴近生理含义，便于对照：R 波振幅个体间差异大，T 波次之，
    Q/S 相对稳定；呼吸调制与噪声则同时受个体与设备影响。

    注意这只是「波形长什么样」的参数化，**不代表可区分性已经解决** ——
    在当前采样表示下这些幅度差异几乎无法被模型或相似度度量捕捉，
    实测见 `_MORPHOLOGY_SPREAD` 下方的说明。
    """

    p_amp: float = 0.15
    q_amp: float = -0.30
    r_amp: float = 1.00
    s_amp: float = -0.30
    t_amp: float = 0.30
    respiration_amp: float = 0.10
    noise_level: float = 0.05


#: 不指定主体时使用的形态 —— 就是改动前写死在函数里的那组系数。
DEFAULT_MORPHOLOGY = EcgMorphology()

#: 各参数相对默认值的漂移幅度。取值刻意保守：目标是让不同主体在参数上
#: 互不相同，不是造出临床上异常的波形。每项都留有余量，最坏情况下仍在
#: 合理范围内（如 r_amp 落在 0.75～1.25，t_amp 落在 0.18～0.42）。
#:
#: ⚠️ 实测边界（2026-11-13）：这些参数**不能**让判定真正区分主体。
#: 在 10 点/窗、10Hz 采样的表示下，QRS 最多占 1 个采样点（10 个点里 7 个
#: 落在「P/其他」区），r_amp 从 0.5 调到 2.0 时模型输出恒为 0.9945；
#: 同人 / 异人的分数分布完全重叠（5 个主体各 20 份 600 点信号，0.8 阈值下
#: 全部通过）；适用范围见 README「适用边界」。
#: 参数本身没错，是当前数据表示承载不了身份信息 —— 要真正可用，须先提高
#: 采样率并做相位对齐，而不是继续在这组参数上调范围。
_MORPHOLOGY_SPREAD = (
    ('p_amp', 0.35),
    ('q_amp', 0.20),
    ('r_amp', 0.25),
    ('s_amp', 0.20),
    ('t_amp', 0.40),
    ('respiration_amp', 0.30),
    ('noise_level', 0.40),
)


def morphology_for(subject):
    """按主体名派生一组**稳定**的形态参数。

    同一个 `subject` 永远得到同一组参数（用 sha256 而不是内置 `hash()`
    ——后者带进程级随机盐，跨进程/重启就会变，无法复现）。

    `subject` 为 None 或空串时返回 None，表示「沿用默认波形」，
    调用方据此保持改动前的行为。

    注意：这是**人造的**差异。名字虽叫「主体」，但它不能让判定真正区分
    主体 —— 实测同人与异人的分数分布完全重叠，适用范围见 README「适用边界」。
    它只是把「波形与心率解耦」这件事做了，为将来提高采样率、做相位对齐
    留出参数位；在此之前不要据此认为可区分性已经具备。
    """
    if not subject:
        return None

    digest = hashlib.sha256(str(subject).encode('utf-8')).digest()
    values = {}
    for index, (name, spread) in enumerate(_MORPHOLOGY_SPREAD):
        base = getattr(DEFAULT_MORPHOLOGY, name)
        # 取一个字节映射到 [-1, 1]，再按比例缩放默认值
        offset = (digest[index] / 255.0) * 2.0 - 1.0
        values[name] = base * (1.0 + spread * offset)
    return EcgMorphology(**values)


def heart_rate_to_ecg(heart_rate, rr_interval=None, morphology=None):
    """
    根据心率生成模拟ECG信号
    
    参数:
        heart_rate: 心率（每分钟心跳数）
        rr_interval: RR间隔（毫秒），如果未提供则根据心率计算
        morphology: 该主体的形态参数（`EcgMorphology`）；None 表示使用
            `DEFAULT_MORPHOLOGY`，波形与未引入该参数时一致

    返回:
        ECG信号数组，包含10个数据点
    """
    if rr_interval is None:
        rr_interval = 60000.0 / heart_rate  # 将心率转换为RR间隔（毫秒）

    # 只在这里做一次 None → 默认值的归一，函数体内不再出现分支判断
    m = morphology if morphology is not None else DEFAULT_MORPHOLOGY

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
        p_wave = m.p_amp * math.sin(phase)
        qrs_complex = 0.0
        
        # QRS复合波
        if 0.0 <= phase < 0.1 * math.pi:
            qrs_complex = m.q_amp * math.sin(10 * phase)  # Q波
        elif 0.1 * math.pi <= phase < 0.2 * math.pi:
            qrs_complex = m.r_amp * math.sin(5 * phase)  # R波
        elif 0.2 * math.pi <= phase < 0.3 * math.pi:
            qrs_complex = m.s_amp * math.sin(10 * phase)  # S波
        
        # T波
        t_wave = m.t_amp * math.sin(phase - 0.5 * math.pi) if 0.3 * math.pi <= phase < 0.7 * math.pi else 0.0
        
        # 合成ECG信号
        ecg_signal = p_wave + qrs_complex + t_wave
        
        # 添加呼吸调制和噪声
        respiration = m.respiration_amp * math.sin(phase / 5)  # 呼吸调制
        noise = m.noise_level * (random.random() * 2 - 1)  # 随机噪声
        
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

    说明:
        本次未对该函数做形态参数化。PPG 目前只是占位输出（各调用方都以
        `ecg, _ = ...` 丢弃），没有参与判定，因此不值得先加一组无人验证的
        参数；将来要做双模态时再补，届时需要同时修正相位来源——当前相位取自
        `datetime.now().microsecond`，与心率无关，波形没有周期结构。
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
def generate_ecg_ppg_data(num_samples=600, base_heart_rate=70, morphology=None):
    """
    使用heart_beat模块中的函数生成ECG和PPG数据
    
    参数:
        num_samples: 生成的样本数量，默认为600以匹配新的序列长度
        base_heart_rate: 基础心率
        morphology: 该主体的形态参数（`EcgMorphology`）；None 表示使用默认波形。
            传入时只影响 ECG，PPG 仍按原逻辑生成
    
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
        ecg_values = heart_rate_to_ecg(heart_rate, rr_interval, morphology)
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
