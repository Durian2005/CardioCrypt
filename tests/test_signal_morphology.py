# -*- coding: utf-8 -*-
"""
合成波形的形态参数

引入 `EcgMorphology` 是为了让「不同主体」的心电长得不一样 —— 在此之前波形系数
全部写死，唯一的输入是心率，于是任何两个主体在同一心率下生成的信号几乎相同，
「同人 vs 不同人」的可分性根本无从验证。

本文件钉住四条约束：

1. **默认路径不变**：不传形态参数时，波形必须与引入该参数之前逐点相同，
   否则等于悄悄改动了所有既有结果；
2. **派生可复现**：同一主体名必须永远得到同一组参数，跨进程也一样
   （用 sha256 而非内置 `hash()`，后者带进程级随机盐）；
3. **主体之间确实不同**：否则这个参数就白加了；
4. **取值在合理范围内**：目的是让主体可区分，不是造出临床异常的波形。
"""

import hashlib
import random

import numpy as np
import pytest

from web_auth.services.signals import (
    DEFAULT_MORPHOLOGY,
    EcgMorphology,
    generate_ecg_ppg_data,
    heart_rate_to_ecg,
    morphology_for,
)

#: 派生时允许的最大相对偏移 —— 与 `signals._MORPHOLOGY_SPREAD` 对应。
#: 写在这里是刻意的重复：测试要独立于实现，改大范围时应当有人主动确认。
MAX_RELATIVE_SPREAD = {
    'p_amp': 0.35,
    'q_amp': 0.20,
    'r_amp': 0.25,
    's_amp': 0.20,
    't_amp': 0.40,
    'respiration_amp': 0.30,
    'noise_level': 0.40,
}


class TestDefaultIsUnchanged:
    """不传形态参数时，行为必须与引入前一致。"""

    def test_default_morphology_equals_literals(self):
        """DEFAULT_MORPHOLOGY 的每一项都等于原先写死在函数里的系数。"""
        assert DEFAULT_MORPHOLOGY == EcgMorphology(
            p_amp=0.15, q_amp=-0.30, r_amp=1.00, s_amp=-0.30,
            t_amp=0.30, respiration_amp=0.10, noise_level=0.05,
        )

    @pytest.mark.parametrize('heart_rate', [55, 70, 85, 98])
    def test_explicit_default_equals_omitted(self, heart_rate):
        """显式传 DEFAULT_MORPHOLOGY 与不传，逐点相同（同噪声种子）。"""
        random.seed(20261113)
        omitted = heart_rate_to_ecg(heart_rate)
        random.seed(20261113)
        explicit = heart_rate_to_ecg(heart_rate, morphology=DEFAULT_MORPHOLOGY)
        assert np.array_equal(omitted, explicit)

    def test_generate_keeps_default_when_morphology_omitted(self):
        """generate_ecg_ppg_data 不传形态时长度与数值语义不变。"""
        random.seed(7)
        ecg, ppg = generate_ecg_ppg_data(num_samples=600, base_heart_rate=70)
        assert len(ecg) == 600 and len(ppg) == 600
        assert np.all(np.isfinite(ecg))


class TestMorphologyDerivation:
    """按主体名派生形态参数。"""

    def test_none_and_empty_mean_default(self):
        """没有主体标识时返回 None，由调用方沿用默认波形。"""
        assert morphology_for(None) is None
        assert morphology_for('') is None

    def test_same_subject_is_stable(self):
        assert morphology_for('alice') == morphology_for('alice')

    def test_different_subjects_differ(self):
        subjects = ['alice', 'bob', 'carol', 'dave', '张三']
        rendered = {morphology_for(s) for s in subjects}
        assert len(rendered) == len(subjects), '不同主体的形态参数不应重复'

    def test_matches_sha256_derivation(self):
        """锁定「用摘要而非内置 hash」的契约。

        这里独立按 sha256 复算一遍期望值：若有人把实现换回 `hash()`，
        跨进程结果会随 PYTHONHASHSEED 漂移，本断言即会失败。
        """
        digest = hashlib.sha256('alice'.encode('utf-8')).digest()
        order = ['p_amp', 'q_amp', 'r_amp', 's_amp', 't_amp',
                 'respiration_amp', 'noise_level']
        expected = {}
        for index, name in enumerate(order):
            base = getattr(DEFAULT_MORPHOLOGY, name)
            offset = (digest[index] / 255.0) * 2.0 - 1.0
            expected[name] = base * (1.0 + MAX_RELATIVE_SPREAD[name] * offset)
        assert morphology_for('alice') == EcgMorphology(**expected)

    def test_parameters_stay_within_spread(self):
        """每个参数相对默认值的偏移不超过声明的范围。"""
        for subject in ('alice', 'bob', 'carol', 'dave', 'erin', '张三', '李四'):
            morph = morphology_for(subject)
            for name, spread in MAX_RELATIVE_SPREAD.items():
                base = getattr(DEFAULT_MORPHOLOGY, name)
                value = getattr(morph, name)
                assert abs(value - base) <= abs(base) * spread + 1e-9, (
                    f'{subject}.{name} = {value} 超出了 ±{spread:.0%} 的范围')

    def test_no_parameter_collapses_to_zero(self):
        """派生不应把某个幅度压成 0 —— 那会让对应波形整段消失。"""
        for subject in ('alice', 'bob', 'carol'):
            morph = morphology_for(subject)
            for name in MAX_RELATIVE_SPREAD:
                assert abs(getattr(morph, name)) > 1e-6


class TestMorphologyAffectsWaveform:
    """形态参数要真的体现在波形上。"""

    def test_waveform_differs_from_default(self):
        morph = morphology_for('carol')
        random.seed(11)
        shaped = heart_rate_to_ecg(70, morphology=morph)
        random.seed(11)
        default = heart_rate_to_ecg(70)
        assert not np.array_equal(shaped, default)

    def test_same_subject_reproduces_waveform(self):
        """同主体、同心率、同噪声种子 → 波形逐点相同，形态因此可复现。"""
        morph = morphology_for('bob')
        random.seed(5)
        first = heart_rate_to_ecg(70, morphology=morph)
        random.seed(5)
        second = heart_rate_to_ecg(70, morphology=morph)
        assert np.array_equal(first, second)

    def test_morphology_is_orthogonal_to_heart_rate(self):
        """同一形态在不同心率下都生成形状合法（有限值、长度固定）的信号。"""
        morph = morphology_for('dave')
        for heart_rate in (50, 70, 100):
            wave = heart_rate_to_ecg(heart_rate, morphology=morph)
            assert wave.shape == (10,)
            assert np.all(np.isfinite(wave))

    def test_generate_accepts_morphology(self):
        morph = morphology_for('alice')
        random.seed(3)
        shaped, _ = generate_ecg_ppg_data(
            num_samples=600, base_heart_rate=70, morphology=morph)
        random.seed(3)
        default, _ = generate_ecg_ppg_data(num_samples=600, base_heart_rate=70)
        assert len(shaped) == 600
        assert not np.array_equal(shaped, default)


class TestDemoSeriesPassthrough:
    """演示采集链路能按主体生成不同波形。"""

    def test_subject_is_passed_through(self):
        from web_auth import demo

        # 同一随机种子 → 心率序列与噪声完全一致，此时波形的差异只可能
        # 来自形态参数本身。演示模式开关只影响调用方，本函数不限模式。
        def series(subject):
            random.seed(42)
            return demo.synthetic_signal_series(5, subject=subject)

        same_a = series('alice')
        same_b = series('alice')
        other = series('bob')
        default = series(None)

        assert all(np.array_equal(x, y) for x, y in zip(same_a, same_b))
        assert not all(np.array_equal(x, y) for x, y in zip(same_a, other))
        # 不传 subject 时仍沿用默认波形，与 alice 不同
        assert not all(np.array_equal(x, y) for x, y in zip(default, same_a))

    def test_series_length_matches_request(self):
        from web_auth import demo
        assert len(demo.synthetic_signal_series(60)) == 60
