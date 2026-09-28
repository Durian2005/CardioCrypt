# -*- coding: utf-8 -*-
"""
信号相似度与阈值语义测试

认证系统的判定逻辑是整套代码里最该被锁住的部分：阈值写错一位，
现场演示就是「本人被拒、他人通过」。这里测的是相似度度量的
**性质**（同一性、有界性、单调性），而不是某个具体数值 ——
性质型断言在算法微调后仍然成立，数值型断言只会变成维护负担。

⚠️ 关于本模块的现状（测的是可用子集，不是全部）
------------------------------------------------------------------
`ecgppg_system/utils/authentication.py` 是早期基于 DTW 的原型，
当前**没有任何生产代码引用它**，且有两处使它在当前依赖组合下无法工作的缺陷：

  1. `SignalPlotter.__init__` 读取 `settings.DPI` / `settings.FIGURE_WIDTH`
     / `settings.FIGURE_HEIGHT`，但 `ecgppg_system.config.settings` 里没有这三个属性
     → `Authenticator(...)` 构造即抛 `AttributeError`；
  2. `fastdtw` 0.3.4 把**标量**喂给 `scipy.spatial.distance.euclidean`，
     而 scipy 1.16 拒绝非 1-D 输入 → DTW 分支抛 `ValueError`，
     被 `compute_signal_similarity` 捕获后静默降级为 0.0。

两条都用测试固定下来（见 `TestKnownLimitations`），这样将来若有人真的要启用
这份实现，会先看到明确的失败原因，而不是拿到一个「相似度永远偏低」的诡异结果。
"""

import matplotlib

matplotlib.use('Agg')  # 无显示环境（CI / 服务器）下也必须能导入绘图模块

import numpy as np  # noqa: E402

from ecgppg_system.config import settings  # noqa: E402
from ecgppg_system.utils.authentication import compute_signal_similarity  # noqa: E402


def _synthetic_ecg(length=300, heart_rate=70, phase=0.0, noise=0.0, seed=0):
    """生成一段类 ECG 的周期性信号（正弦基波 + 二次谐波）。"""
    rng = np.random.default_rng(seed)
    t = np.linspace(0, length / 100.0, length)
    base = np.sin(2 * np.pi * heart_rate / 60.0 * t + phase)
    harmonic = 0.3 * np.sin(4 * np.pi * heart_rate / 60.0 * t + phase)
    signal = base + harmonic
    if noise:
        signal = signal + rng.normal(0, noise, length)
    return signal


# ============================================================================
# compute_signal_similarity
# ============================================================================
class TestComputeSignalSimilarity:
    def test_identical_signal_is_most_similar(self):
        """同一段信号必须拿到最高相似度（用不依赖 DTW 的两种度量验证）。"""
        signal = _synthetic_ecg()
        for method in ('correlation', 'cosine'):
            assert compute_signal_similarity(signal, signal, method=method) >= 0.99, (
                '{} 对同一信号未给出接近 1 的相似度'.format(method)
            )

    def test_result_is_bounded_between_zero_and_one(self):
        a = _synthetic_ecg(seed=1)
        b = _synthetic_ecg(seed=2, heart_rate=100, phase=1.7)
        for method in ('all', 'dtw', 'correlation', 'cosine'):
            value = compute_signal_similarity(a, b, method=method)
            assert 0.0 <= value <= 1.0, '{} 返回越界值 {}'.format(method, value)

    def test_shifted_signal_scores_lower_than_identical(self):
        reference = _synthetic_ecg()
        shifted = _synthetic_ecg(phase=np.pi / 2)
        assert compute_signal_similarity(reference, shifted, method='cosine') < \
            compute_signal_similarity(reference, reference, method='cosine')

    def test_noise_reduces_similarity(self):
        reference = _synthetic_ecg()
        light = _synthetic_ecg(noise=0.05, seed=11)
        heavy = _synthetic_ecg(noise=1.5, seed=11)
        assert compute_signal_similarity(reference, light, method='correlation') > \
            compute_signal_similarity(reference, heavy, method='correlation')

    def test_unknown_method_falls_back_to_zero(self):
        signal = _synthetic_ecg()
        assert compute_signal_similarity(signal, signal, method='no-such-method') == 0.0

    def test_single_method_returns_float(self):
        signal = _synthetic_ecg()
        for method in ('dtw', 'correlation', 'cosine'):
            assert isinstance(
                compute_signal_similarity(signal, signal, method=method), float
            )

    def test_mismatched_lengths_are_truncated_not_raised(self):
        long_signal = _synthetic_ecg(length=400)
        short_signal = _synthetic_ecg(length=120)
        value = compute_signal_similarity(long_signal, short_signal)
        assert 0.0 <= value <= 1.0

    def test_non_finite_values_do_not_raise(self):
        reference = _synthetic_ecg()
        corrupted = reference.copy()
        corrupted[::7] = np.nan
        corrupted[1::11] = np.inf
        with np.errstate(all='ignore'):
            value = compute_signal_similarity(reference, corrupted)
        assert isinstance(value, float)

    def test_degenerate_inputs_do_not_raise(self):
        """空数组 / 全零数组是算法里最容易抛异常的两个输入。"""
        for degenerate in (np.array([]), np.zeros(1), np.zeros(50)):
            with np.errstate(all='ignore'):
                value = compute_signal_similarity(degenerate, degenerate)
            assert isinstance(value, float)

    def test_accepts_plain_lists(self):
        signal = list(_synthetic_ecg(length=64))
        assert 0.0 <= compute_signal_similarity(signal, signal, method='cosine') <= 1.0


# ============================================================================
# 阈值语义
# ============================================================================
class TestThresholdSemantics:
    def test_higher_threshold_only_makes_it_harder(self):
        """
        阈值判定必须单调：相似度不变时，提高阈值只会让通过更难。

        这是「阈值」这个概念唯一的不变式，也是调参时最容易被破坏的一条
        （例如把 `>=` 写成 `<=`，或把百分比与小数混用）。
        """
        near = _synthetic_ecg(phase=0.2, seed=7)
        far = _synthetic_ecg(heart_rate=110, phase=2.5, seed=8)
        reference = _synthetic_ecg()

        sim_near = compute_signal_similarity(reference, near, method='cosine')
        sim_far = compute_signal_similarity(reference, far, method='cosine')
        assert sim_near > sim_far, '测试数据本身未形成区分度，需要调整参数'

        def passes(similarity, threshold):
            # 显式转成 Python bool：numpy 的比较结果是 np.bool_，
            # 用 `is True/False` 判断会永远失败
            return bool(similarity >= threshold)

        assert passes(sim_near, threshold=0.5) is True
        assert passes(sim_near, threshold=0.999) is False or sim_near >= 0.999
        assert passes(sim_far, threshold=0.999) is False

    def test_percentage_and_fraction_conventions_are_distinguishable(self):
        """
        原型里阈值以「百分比」命名（默认 65.0），而本函数返回 0~1 的小数。

        这条测试把这个量纲差异固定下来：调用方必须显式换算，
        否则 0.9 会被当成 0.9%（永远通过）。
        """
        similarity = compute_signal_similarity(
            _synthetic_ecg(), _synthetic_ecg(noise=0.3, seed=3), method='cosine'
        )
        assert 0.0 <= similarity <= 1.0
        as_percent = similarity * 100
        assert as_percent >= 0.0
        # 同一个值在两种量纲下的判定结果可以完全不同 —— 这正是要当心的地方
        assert not (similarity >= 65.0)


# ============================================================================
# 已知限制（把「现在跑不起来」这件事写进测试，而不是留给下一个人踩）
# ============================================================================
class TestKnownLimitations:
    def test_plotter_depends_on_missing_settings(self):
        """
        `SignalPlotter.__init__` 依赖 settings 里不存在的绘图属性。

        这使 `Authenticator(...)` 无法实例化 —— 是这份原型当前**不可用**的
        直接原因之一。一旦有人补上 settings 属性，本测试会失败并提醒
        同步更新这条记录。
        """
        missing = [
            name for name in ('DPI', 'FIGURE_WIDTH', 'FIGURE_HEIGHT')
            if not hasattr(settings, name)
        ]
        assert missing == ['DPI', 'FIGURE_WIDTH', 'FIGURE_HEIGHT'], (
            'settings 的绘图属性已变化，请同步更新 '
            'tests/test_authentication.py 顶部关于原型现状的说明'
        )

    def test_dtw_branch_degrades_to_zero(self):
        """
        fastdtw 与新版 scipy 不兼容，DTW 分支抛错后被静默吞掉。

        结果是 `method='all'` 的加权平均里 DTW 恒为 0，
        同一段信号只得约 0.5 分而不是 1.0 —— 看起来像「算法总是不太准」，
        实际是分支根本没跑。这里的断言就是把这个坑显式化。
        """
        signal = _synthetic_ecg()
        assert compute_signal_similarity(signal, signal, method='dtw') == 0.0, (
            'DTW 分支恢复可用了 —— 请更新这条记录，'
            '并重新审视 method="all" 的加权结果'
        )
        assert compute_signal_similarity(signal, signal, method='all') < 0.7, (
            'method="all" 的结果不再被失效的 DTW 拉低，说明该分支已修复'
        )
