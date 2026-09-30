# -*- coding: utf-8 -*-
"""
model_example/authentication.py 的判定契约测试

这份模块是 Web 层真正调用的认证实现 —— `web_auth/core.py` 只从这里导入
`authenticate_single_signal`，`blueprints/auth.py` 与 `blueprints/device.py`
各有一处调用。它有三条行为是「判定结论可信」的地基，这里逐条锁住：

  1. 推理失败与「判定不通过」必须能区分开 —— 否则模型加载失败时，
     系统故障会被读成「你不是本人」，用户和运维看到的是完全不同的事；
  2. 融合结果里 combined_score 与 authenticated 必须同口径 ——
     否则会输出「综合分过了阈值、结论却是失败」这类自相矛盾的结果；
  3. EER 必须是真正的等错误率，而不是某个阈值下的平均错误率 ——
     后者会随阈值漂移，拿它评价模型会得出错误结论。

前两条锁结论本身，第三条锁「用什么指标评价结论」。

关于 `_equal_error_rate` 是私有函数：这里刻意直接测它。它是 EER 的唯一实现，
经由 `calculate_authentication_metrics` 间接测会掩盖「阈值参与计算」这类错误。
"""

import numpy as np
import torch
import torch.nn as nn

from model_example.authentication import (
    _equal_error_rate,
    authenticate_dual_signals,
    authenticate_single_signal,
    calculate_authentication_metrics,
)


class _FixedScoreModel(nn.Module):
    """输出恒定分数的模型，用来构造确定性的认证场景。"""

    def __init__(self, score):
        super().__init__()
        self.lin = nn.Linear(1, 1)
        with torch.no_grad():
            self.lin.weight.fill_(0.0)
            self.lin.bias.fill_(float(score))
        self.input_size = 1

    def forward(self, x):
        return self.lin(x).mean(dim=1).squeeze(-1)


def _signal(length=600, seed=0):
    return np.random.default_rng(seed).normal(0.0, 1.0, length)


def _perfect_case():
    """完全可分：同一身份分数恒高、不同身份分数恒低。"""
    scores = np.concatenate([np.full(200, 0.9), np.full(200, 0.1)])
    labels = np.concatenate([np.ones(200), np.zeros(200)])
    return scores, labels


def _moderate_case(seed=0):
    """中等区分度：两类分数有交叠，但整体可辨。"""
    rng = np.random.default_rng(seed)
    scores = np.clip(np.concatenate([rng.normal(0.75, 0.15, 1000),
                                     rng.normal(0.25, 0.15, 1000)]), 0.0, 1.0)
    labels = np.concatenate([np.ones(1000), np.zeros(1000)])
    return scores, labels


def _random_case(seed=0):
    """无区分度：分数与身份完全无关。"""
    rng = np.random.default_rng(seed)
    return rng.random(2000), np.concatenate([np.ones(1000), np.zeros(1000)])


# ============================================================================
# 一、等错误率
# ============================================================================
class TestEqualErrorRate:
    def test_perfect_separation_gives_zero(self):
        """
        完全可分时 EER 必须为 0。

        顺带挡住「排序方向写反」这类错误 —— 方向反了的话，完美分类器会得到 1.0，
        而不是一个接近 0 的值。
        """
        scores, labels = _perfect_case()
        assert _equal_error_rate(scores, labels) == 0.0

    def test_uninformative_scores_give_about_half(self):
        """分数与身份无关时，EER 应当接近 0.5。"""
        scores, labels = _random_case()
        eer = _equal_error_rate(scores, labels)
        assert 0.44 <= eer <= 0.56, '随机分数的 EER 明显偏离 0.5：{}'.format(eer)

    def test_better_separation_gives_lower_eer(self):
        """区分度越好，EER 越小 —— 这是 EER 作为评价指标的基本单调性。"""
        moderate_scores, labels = _moderate_case()
        assert _equal_error_rate(moderate_scores, labels) < \
            _equal_error_rate(_random_case(seed=5)[0], labels)

    def test_is_nan_when_a_class_is_missing(self):
        """
        只有一类样本时 ROC 曲线不完整，EER 无定义。

        返回 nan 而不是编一个数字 —— nan 会让调用方在绘图或比较时立刻察觉，
        而 0.0 会被误读成「模型完美」。
        """
        assert np.isnan(_equal_error_rate(np.array([0.9, 0.8]), np.array([1, 1])))
        assert np.isnan(_equal_error_rate(np.array([0.1, 0.2]), np.array([0, 0])))

    def test_does_not_depend_on_threshold(self):
        """
        EER 是 ROC 曲线上的固有属性，换阈值不该变。

        这是一条**回归护栏**：旧实现写作 `(far + frr) / 2`，在同一个模型上只把
        阈值从 0.5 挪到 0.9，算出的「EER」就会从 0.047 跳到 0.42 —— 差近十倍。
        指标随阈值漂移，用它评价模型必然得出错误结论。
        """
        scores, labels = _moderate_case()
        values = {
            calculate_authentication_metrics(scores, labels, threshold=t)['eer']
            for t in (0.10, 0.30, 0.50, 0.70, 0.90)
        }
        assert len(values) == 1, 'EER 随阈值发生了变化：{}'.format(sorted(values))

    def test_threshold_dependent_metrics_do_change(self):
        """
        对照组：far / frr 本来就该随阈值变化。

        把这条和上一条放在一起，是为了说明「依赖阈值」和「不依赖阈值」是两类指标，
        不能混为一谈 —— 旧实现的问题正是把两者当成了同一个东西。
        """
        scores, labels = _moderate_case()
        low = calculate_authentication_metrics(scores, labels, threshold=0.10)
        high = calculate_authentication_metrics(scores, labels, threshold=0.90)
        assert low['far'] > high['far']
        assert low['frr'] < high['frr']


# ============================================================================
# 二、故障与「判定不通过」可区分
# ============================================================================
class TestFailureIsDistinguishableFromRejection:
    def test_successful_inference_reports_ok(self):
        result = authenticate_single_signal(_FixedScoreModel(0.9), _signal(), threshold=0.5)
        assert result['status'] == 'ok'
        assert result['authenticated'] is True

    def test_low_score_is_ok_not_error(self):
        """分数低是一个正常结论，不能被当成故障。"""
        result = authenticate_single_signal(_FixedScoreModel(0.1), _signal(), threshold=0.5)
        assert result['status'] == 'ok'
        assert result['authenticated'] is False

    def test_inference_failure_reports_error(self):
        """传入不具备模型接口的对象，推理必然抛异常。"""
        result = authenticate_single_signal(object(), _signal(), threshold=0.5)
        assert result['status'] == 'error'
        assert 'error' in result

    def test_failure_is_fail_closed(self):
        """故障时必须拒绝 —— 绝不能因为「算不出来」反而放行。"""
        result = authenticate_single_signal(object(), _signal(), threshold=0.5)
        assert result['authenticated'] is False
        assert result['score'] == 0.0

    def test_rejection_and_failure_share_the_same_verdict(self):
        """
        两者结论相同（都拒绝）、但 status 不同。

        这正是本次修复的核心：调用方靠 status 决定对用户说什么 ——
        「认证未通过」和「系统异常，请稍后重试」是完全不同的两句话。
        """
        signal = _signal()
        rejected = authenticate_single_signal(_FixedScoreModel(0.1), signal, threshold=0.5)
        errored = authenticate_single_signal(object(), signal, threshold=0.5)
        assert rejected['authenticated'] == errored['authenticated'] is False
        assert rejected['status'] != errored['status']


# ============================================================================
# 三、融合结果的内部自洽
# ============================================================================
class TestFusionConsistency:
    def _fuse(self, ecg_score, ppg_score, method, ecg_threshold=0.5, ppg_threshold=0.5):
        signal = _signal()
        return authenticate_dual_signals(
            _FixedScoreModel(ecg_score), _FixedScoreModel(ppg_score),
            signal, signal,
            ecg_threshold=ecg_threshold, ppg_threshold=ppg_threshold,
            fusion_method=method,
        )

    def test_majority_verdict_matches_combined_score(self):
        """
        majority 下「综合分过线」与「判定通过」必须一致。

        旧实现用两路分数的**平均**做综合分、却用**逻辑与**做判定，于是会出现
        combined_score >= combined_threshold 而 authenticated 仍为 False ——
        结论和分数互相打架，调用方不知道该信哪个。
        """
        cases = ((0.9, 0.1), (0.1, 0.9), (0.9, 0.9), (0.2, 0.2), (0.6, 0.4))
        for ecg_score, ppg_score in cases:
            result = self._fuse(ecg_score, ppg_score, 'majority')
            derived = result['combined_score'] >= result['combined_threshold']
            assert derived == result['authenticated'], (
                'ecg={} ppg={} 时综合分与判定不一致：score={} threshold={} authenticated={}'.format(
                    ecg_score, ppg_score, result['combined_score'],
                    result['combined_threshold'], result['authenticated'],
                )
            )

    def test_majority_rejects_when_one_signal_fails(self):
        """两路信号时「多数」即「都通过」，一路不过就不该放行。"""
        assert self._fuse(0.9, 0.1, 'majority')['authenticated'] is False
        assert self._fuse(0.1, 0.9, 'majority')['authenticated'] is False

    def test_majority_accepts_when_both_pass(self):
        assert self._fuse(0.9, 0.8, 'majority')['authenticated'] is True

    def test_weighted_stays_self_consistent(self):
        """weighted 本来就是同口径的，顺带一起锁住，防止将来被改坏。"""
        for ecg_score, ppg_score in ((0.9, 0.1), (0.1, 0.9), (0.9, 0.9), (0.2, 0.2)):
            result = self._fuse(ecg_score, ppg_score, 'weighted')
            derived = result['combined_score'] >= result['combined_threshold']
            assert derived == result['authenticated']

    def test_child_failure_propagates_to_fusion(self):
        """
        任一路推理失败时，融合结果不能对外宣称「正常完成」。

        分数虽然拼得出来（失败那一路会给出 0.0），但有一半输入根本没算过 ——
        这种结果只能算「没算出来」，不能算「判定为不通过」。
        """
        signal = _signal()
        result = authenticate_dual_signals(
            object(), _FixedScoreModel(0.9), signal, signal,
            fusion_method='weighted',
        )
        assert result['status'] == 'error'
        assert result['authenticated'] is False

    def test_ok_when_both_children_succeed(self):
        assert self._fuse(0.9, 0.9, 'weighted')['status'] == 'ok'
