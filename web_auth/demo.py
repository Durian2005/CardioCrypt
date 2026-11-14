# -*- coding: utf-8 -*-
"""
演示模式（DEMO_MODE）：让没有采集设备时也能把流程走完

背景
----
采集链路里原本散落着若干「拿不到真实数据就生成一段合成信号继续走」的分支，
注册流程在算法层不可用时还会写一个内容为「模拟模型文件」的 .pth 占位文件，
并照样报告注册成功。合起来的效果是：不接设备也能注册、也能验证通过，而且这些
结果在返回值上与真实采集完全无法区分 —— 演示时看不出，评审时更看不出。

本模块把这件事收口成一个显式开关：

    默认（不设置）  采集不到数据即判定失败，不做任何模拟
    DEMO_MODE=1     允许改用合成信号把流程走完，但每一步降级都会留痕

改的是**数据从哪来**，不是**判定怎么下**：合成信号同样要过模型比对，同样
可能不通过；模型文件也不会再被伪造。判定结论的唯一来源始终是算法输出。

留痕方式
--------
- 日志：降级时以 ``[DEMO]`` 前缀记一条 WARNING，非演示模式记 ERROR；
- 结果：调用方把收集到的降级原因附在结果上，接口透出给前端；
- 前端：据此显示「演示模式」提示，避免把合成数据当成真实生物特征采集。
"""

import random

from web_auth.config import DEMO_MODE, logger
from web_auth.services.signals import heart_rate_to_ecg, morphology_for

__all__ = ['DEMO_MODE', 'demo_degrade', 'is_enabled', 'synthetic_signal_series']


def is_enabled():
    """
    当前是否处于演示模式。

    每次调用都读模块全局，而不是在导入处被固化成常量 —— 这样测试可以
    覆盖它来验证两条分支，运行时行为与 `demo_degrade` 也始终一致。
    """
    return DEMO_MODE


# 合成心率范围（BPM）：70±10，与原型里的做法一致。波形形状像样的 ECG，
# 但不来自任何真实受试者。
_SYNTHETIC_BPM_CENTER = 70.0
_SYNTHETIC_BPM_JITTER = 10.0


def synthetic_signal_series(count, subject=None):
    """
    生成 count 个合成数据点（随机心率经「心率 → ECG」变换）。

    仅在演示模式下调用。

    参数:
        count: 生成的数据点个数
        subject: 主体标识。给出时按它派生一组稳定的形态参数，使不同主体
            的合成波形互不相同；不给出（默认）则沿用原有的统一波形。

            ⚠️ 波形不同**不等于**判定能区分主体。实测在 10 点/窗的表示下
            同人与异人的分数分布完全重叠，二者都远超阈值（适用范围见
            README「适用边界」）。这个参数只用于让「波形与心率解耦」，
            不具备演示「拒绝他人」的能力。

    形态参数按 subject 派生后只算一次，不在逐点循环里重复计算。
    """
    morphology = morphology_for(subject)
    return [
        heart_rate_to_ecg(
            _SYNTHETIC_BPM_CENTER
            + random.uniform(-_SYNTHETIC_BPM_JITTER, _SYNTHETIC_BPM_JITTER),
            morphology=morphology,
        )
        for _ in range(count)
    ]


def demo_degrade(reason, reasons):
    """
    采集降级的统一出口。返回 True 表示「可以改用合成信号继续」。

    只有演示模式开启时才返回 True；默认返回 False —— 采集不到数据就是没有
    判定依据，必须如实失败，不能凭空得出「通过」。

    两种情况下都会留痕，便于在日志里区分「设备问题」和「设备问题被演示模式接管」。
    """
    if DEMO_MODE:
        reasons.append(reason)
        logger.warning(
            "[DEMO] %s —— 演示模式已开启，改用合成信号继续；"
            "本次结果不代表真实生物特征采集", reason
        )
        return True
    logger.error("[流程中止] %s —— 未开启演示模式，不使用任何模拟数据", reason)
    return False
