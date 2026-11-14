"""算法层改动前后等价性对照。

这一批改动全是「同样的结果、更少的重复计算」。pytest 与 4 套 E2E 都不覆盖
算法层可视化 / 统计模块，因此用同一份输入把「旧写法」与「新代码」逐项对照，
确认没有引入数值或行为差异。

  1. statistics.analyze_signal —— q1/q3/iqr 合并 percentile
  2. statistics._generate_plots —— 循环内 pd.concat 改为一次成型
  3. statistics.generate_report —— compare_signals 结果复用（调用次数 2x → 1x）
  4. data_validator.check_data_overlap —— O(n^2) corrcoef 改为矩阵乘法
  5. signal_plotter._finalize —— figure 不堆积，且 create_subplots 未被误伤
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault('MPLBACKEND', 'Agg')  # 必须早于 matplotlib 相关 import

from _common import ROOT, RESULTS_DIR  # noqa: E402

sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import torch
from torch.utils.data import DataLoader, TensorDataset

from ecgppg_system.utils.statistics import StatisticalAnalyzer
from ecgppg_system.visualization.signal_plotter import SignalPlotter
from model_example.data_validator import check_data_overlap

OUT = RESULTS_DIR / 'algorithm_equivalence.json'
CHECKS = []


def record(name, ok, detail):
    CHECKS.append({'name': name, 'ok': bool(ok), 'detail': detail})
    print(('[OK]   ' if ok else '[FAIL] ') + name + ' :: ' + str(detail))


def check_percentile():
    rng = np.random.default_rng(20261114)
    cases = {
        'normal': rng.normal(size=600),
        'linspace': np.linspace(-1, 1, 257),
        'constant': np.zeros(64),
        'tiny': rng.normal(size=333) * 1e-6,
    }
    rows = []
    for key, arr in cases.items():
        old = (float(np.percentile(arr, 25)),
               float(np.percentile(arr, 75)),
               float(np.percentile(arr, 75) - np.percentile(arr, 25)))
        q1, q3 = np.percentile(arr, [25, 75])
        new = (float(q1), float(q3), float(q3 - q1))
        rows.append({'case': key, 'old': old, 'new': new,
                     'equal': all(a == b for a, b in zip(old, new))})
    record('percentile 合并：q1/q3/iqr 逐位一致',
           all(r['equal'] for r in rows), rows)


def check_concat():
    rows = [
        {'name': 'a', 'mean': 1.0, 'range': 3.0, 'zero_crossing_rate': 12.5},
        {'name': 'b', 'mean': -0.5, 'range': 2.25, 'zero_crossing_rate': 7.0},
        {'name': 'c', 'mean': 0.0, 'range': 1.0, 'zero_crossing_rate': 0.0},
    ]
    old = pd.DataFrame()
    for row in rows:
        old = pd.concat([old, pd.DataFrame([row])], ignore_index=True)
    new = pd.DataFrame(rows)
    ok = old.equals(new) and list(old.columns) == list(new.columns)
    record('pd.concat → 一次成型：DataFrame.equals', ok, {
        'columns': list(new.columns),
        'shape': list(new.shape),
        'old_dtypes': {k: str(v) for k, v in old.dtypes.items()},
        'new_dtypes': {k: str(v) for k, v in new.dtypes.items()},
    })


def check_reuse():
    analyzer = StatisticalAnalyzer(signal_type='ecg')
    rng = np.random.default_rng(7)
    for i in range(3):
        analyzer.analyze_signal(rng.normal(size=256), name='s%d' % i)
    names = list(analyzer.analysis_results.keys())
    pairs = len(names) * (len(names) - 1) // 2

    calls = {'n': 0}
    original_cmp = analyzer.compare_signals

    def counting(name1, name2, custom_actual=None):
        calls['n'] += 1
        return original_cmp(name1, name2, custom_actual)

    analyzer.compare_signals = counting

    captured = {'size': None, 'second_arg': False}

    def fake_plots(output_dir, comparisons=None):
        captured['size'] = len(comparisons or {})
        captured['second_arg'] = comparisons is not None

    analyzer._generate_plots = fake_plots

    with tempfile.TemporaryDirectory() as tmp:
        report_path = analyzer.generate_report(output_dir=tmp, include_plots=True)
        report = Path(report_path).read_text(encoding='utf-8')

    has_section = '信号对比分析' in report
    ok = (calls['n'] == pairs and captured['size'] == pairs
          and captured['second_arg'] and has_section)
    record('comparison 复用：compare_signals 调用 2x → 1x', ok, {
        'signal_pairs': pairs,
        'compare_signals_calls': calls['n'],
        'pairs_passed_to_plots': captured['size'],
        'plots_received_comparisons': captured['second_arg'],
        'report_has_comparison_section': has_section,
        'expected_if_not_reused': pairs * 2,
    })


def _collect(data_loader, sample_size):
    chunks = []
    for inputs, _ in data_loader:
        chunks.append(inputs)
        if len(chunks) * inputs.shape[0] >= sample_size:
            break
    return torch.cat(chunks)[:sample_size].numpy()


def old_overlap(train_data, test_data, sample_size=50, threshold=0.95):
    """改动前的逐对 np.corrcoef 实现（数值对照基准）。"""
    train_flat = _collect(train_data, sample_size).reshape(-1, 96)
    test_flat = _collect(test_data, sample_size).reshape(-1, 96)
    max_features = min(1000, train_flat.shape[1], test_flat.shape[1])
    train_subset = train_flat[:, :max_features]
    test_subset = test_flat[:, :max_features]
    check_size = min(50, train_subset.shape[0], test_subset.shape[0])
    pairs = []
    with np.errstate(invalid='ignore', divide='ignore'):
        for i in range(check_size):
            for j in range(check_size):
                corr = np.corrcoef(train_subset[i], test_subset[j])[0, 1]
                if corr > threshold:
                    pairs.append((i, j, corr))
    max_similarity = max((p[2] for p in pairs), default=0)
    risk = ('高' if len(pairs) > check_size * 0.1 else
            '中' if max_similarity > threshold else '低')
    return {'count': len(pairs), 'max': float(max_similarity),
            'risk': risk, 'pair_index': [[p[0], p[1]] for p in pairs]}


def check_corrcoef():
    rng = np.random.default_rng(31)
    n, length, features = 24, 12, 8
    train = rng.normal(size=(n, length, features)).astype(np.float32)
    test = rng.normal(size=(n, length, features)).astype(np.float32)
    # 人为造高相似对，确保 high_similarities 非空、阈值边界被覆盖
    test[0] = train[0] + rng.normal(scale=1e-3, size=train[0].shape).astype(np.float32)
    test[1] = train[1]
    test[2] = train[2] * 0.999
    # 零方差样本：旧 np.corrcoef 返回 nan，不应被计入
    train[3] = 1.0

    def loader(arr):
        return DataLoader(
            TensorDataset(torch.from_numpy(arr), torch.zeros(n)), batch_size=8)

    train_loader, test_loader = loader(train), loader(test)
    new = check_data_overlap(train_loader, test_loader, sample_size=50)
    old = old_overlap(loader(train), loader(test), sample_size=50)

    same_count = new['high_similarity_count'] == old['count']
    same_max = abs(new['max_similarity'] - old['max']) < 1e-6
    same_risk = new['overlap_risk'] == old['risk']
    record('corrcoef 矩阵化：计数 / 最高相似度 / 风险等级一致',
           same_count and same_max and same_risk, {
               'new': new,
               'old': {'count': old['count'], 'max': old['max'],
                       'risk': old['risk']},
               'checked_pairs': 24 * 24,
           })


def check_real_plots():
    """不替换 _generate_plots，真实跑一遍报告 + 4 张图，验证 DataFrame 改法可用。"""
    analyzer = StatisticalAnalyzer(signal_type='ecg')
    rng = np.random.default_rng(11)
    for i in range(3):
        analyzer.analyze_signal(rng.normal(size=256), name='p%d' % i)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            analyzer.generate_report(output_dir=tmp, include_plots=True)
        except Exception as exc:
            record('真实绘图路径可跑通（含 pd.DataFrame(rows)）', False,
                   '%s: %s' % (type(exc).__name__, exc))
            return
        pngs = sorted(p.name for p in Path(tmp).rglob('*.png'))
    expected = ['distribution.png', 'similarity_matrix.png',
                'stats_comparison.png', 'wave_analysis.png']
    ok = all(name in pngs for name in expected)
    record('真实绘图路径可跑通（含 pd.DataFrame(rows)）', ok,
           {'generated_pngs': pngs, 'expected': expected})


def check_figures():
    plt.close('all')
    before = len(plt.get_fignums())
    plotter = SignalPlotter(signal_type='ecg', dpi=72, figsize=(4, 3))
    with tempfile.TemporaryDirectory() as tmp:
        p1 = os.path.join(tmp, 'a.png')
        fig = plotter.plot_signal(
            np.sin(np.linspace(0, 12, 200)), filename=p1, show=False)
        after = len(plt.get_fignums())
        saved = os.path.getsize(p1) if os.path.exists(p1) else 0

        p2 = os.path.join(tmp, 'b.png')
        reusable = False
        if fig is not None:
            fig.savefig(p2)
            reusable = os.path.exists(p2) and os.path.getsize(p2) > 0

        # create_subplots 返回 (fig, axes) 供调用方继续作画，不能被误关
        f2, _axes = plotter.create_subplots(2)
        during = len(plt.get_fignums())
        plt.close(f2)
        end = len(plt.get_fignums())

    ok = (fig is not None and saved > 0 and reusable
          and after == before and during == before + 1 and end == before)
    record('figure 收尾：不堆积 / 返回 fig 可用 / create_subplots 未受影响', ok, {
        'fignums_before': before,
        'fignums_after_plot_signal': after,
        'saved_png_bytes': saved,
        'returned_fig_still_usable': reusable,
        'fignums_after_create_subplots': during,
        'fignums_after_manual_close': end,
    })


def main():
    check_percentile()
    check_concat()
    check_reuse()
    check_corrcoef()
    check_real_plots()
    check_figures()
    payload = {
        'passed': sum(c['ok'] for c in CHECKS),
        'total': len(CHECKS),
        'checks': CHECKS,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding='utf-8')
    print()
    print('通过 %d/%d；结果已写入 %s' % (payload['passed'], payload['total'], OUT))
    return 0 if payload['passed'] == payload['total'] else 1


if __name__ == '__main__':
    sys.exit(main())
