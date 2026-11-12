"""
身份验证模块

提供基于ECG和PPG信号的身份验证功能。

关于返回值的约定
------------------------------------------------------------------
两个认证函数的返回值都带有 ``status`` 字段，用来区分「判定为不通过」与
「这次根本没算出来」这两种完全不同的情况：

  ``status == 'ok'``     推理正常完成，``authenticated`` / ``score`` 可信；
  ``status == 'error'``  推理过程抛出异常，``score`` 固定为 0.0 —— 它**不代表**
                         相似度为零，只代表本次没有产出有效分数。

调用方若不看 ``status``，会在模型加载失败、输入维度异常等情况下把
「系统故障」读成「用户不是本人」—— 两者对用户的说法、对运维的含义都不一样。
``error`` 字段保留异常摘要供日志排查，不要直接回显给终端用户。
"""

import math

import torch
import torch.nn as nn
import numpy as np
from typing import Dict, Any, Optional
import time

from ecgppg_system.utils.logger import logger

#: 分数语义标记。
#:
#: 模型是用 ``nn.MSELoss`` 把输出回归到 **1.0** 训练出来的（见
#: ``ecgppg_system/models/trainer.py::ModelTrainer``），所以输出是
#: 「与注册样本的重构相似度」，**不是**分类概率，也不保证落在 [0, 1]。
#: 阈值因此只是这条相似度刻度上的一个切点，而不是概率意义上的置信水平。
SCORE_SEMANTICS_SIMILARITY = 'similarity_regression'

#: 支持的窗口聚合方式。默认取均值：训练目标就是「每个窗口都该接近 1.0」，
#: 均值是这个目标的直接对应物；median / min 用于需要更保守口径的场合。
AGGREGATIONS = ('mean', 'median', 'min')


def _as_1d_signal(input_signal) -> np.ndarray:
    """把各种输入整理成一维 float64 数组（不改变长度）。"""
    if torch.is_tensor(input_signal):
        return input_signal.detach().cpu().numpy().astype(np.float64, copy=False).reshape(-1)
    return np.asarray(input_signal, dtype=np.float64).reshape(-1)


def _fit_length(data: np.ndarray, target_length) -> np.ndarray:
    """把信号补齐/截断到 ``target_length``；未指定时原样返回。"""
    if target_length is None or target_length <= 0:
        return data
    if len(data) < target_length:
        padded = np.zeros(target_length, dtype=data.dtype)
        padded[:len(data)] = data
        return padded
    return data[:target_length]


def _aggregate_scores(scores: np.ndarray, method: str) -> float:
    if method == 'mean':
        return float(scores.mean())
    if method == 'median':
        return float(np.median(scores))
    if method == 'min':
        return float(scores.min())
    raise ValueError(f"不支持的聚合方式: {method!r}（可选 {AGGREGATIONS}）")


def authenticate_single_signal(model: nn.Module, 
                              input_signal: torch.Tensor, 
                              threshold: float = 0.5,
                              signal_type: str = 'ecg',
                              device: Optional[torch.device] = None,
                              visualize: bool = False,
                              visualization_path: Optional[str] = None) -> Dict[str, Any]:
    """
    使用单一信号进行身份验证
    
    Args:
        model: 训练好的验证模型
        input_signal: 输入信号
        threshold: 身份验证阈值
        signal_type: 信号类型 ('ecg' 或 'ppg')
        device: 计算设备
        visualize: 是否可视化
        visualization_path: 可视化路径
        
    Returns:
        Dict[str, Any]: 身份验证结果
    """
    try:
        # 设置模型为评估模式
        model.eval()
        
        # 确定设备
        if device is None:
            device = next(model.parameters()).device
        
        # 获取模型的输入大小
        input_size = None
        if hasattr(model, 'input_size'):
            input_size = model.input_size
        elif hasattr(model, 'lstm') and hasattr(model.lstm, 'input_size'):
            input_size = model.lstm.input_size
        
        logger.info(f"模型输入特征维度: {input_size}")
        
        # 准备输入数据
        if isinstance(input_signal, np.ndarray):
            input_signal = torch.from_numpy(input_signal).float()
        
        # 处理输入维度
        input_shape = input_signal.shape
        logger.info(f"输入信号原始形状: {input_shape}")
        
        # 根据输入维度进行处理
        if len(input_shape) == 1:  # [sequence_length]
            # 添加批次维度和特征维度: [1, sequence_length, 1]
            input_signal = input_signal.unsqueeze(0).unsqueeze(-1)
            logger.info(f"调整后的输入形状 (1D->3D): {input_signal.shape}")
        elif len(input_shape) == 2:
            if input_shape[0] == 1:  # [1, sequence_length]
                # 添加特征维度: [1, sequence_length, 1]
                input_signal = input_signal.unsqueeze(-1)
                logger.info(f"调整后的输入形状 (2D->3D): {input_signal.shape}")
            else:  # [batch_size, sequence_length]
                # 添加特征维度: [batch_size, sequence_length, 1]
                input_signal = input_signal.unsqueeze(-1)
                logger.info(f"调整后的输入形状 (2D->3D): {input_signal.shape}")
        elif len(input_shape) == 3:  # [batch_size, sequence_length, features]
            # 检查特征维度是否与模型匹配
            if input_size is not None and input_shape[2] != input_size:
                logger.warning(f"输入特征维度 ({input_shape[2]}) 与模型期望的维度 ({input_size}) 不匹配")
                # 确保特征维度正确，这里假设input_signal已经是[batch, seq_len, features]
                # 此时不需要调整维度，保持原样即可
        else:
            raise ValueError(f"不支持的输入维度: {input_shape}")
        
        # 移动到设备
        input_signal = input_signal.to(device)
        
        # 获取预测
        with torch.no_grad():
            prediction = model(input_signal)
            
            # 确保预测是标量值
            if len(prediction.shape) > 1:
                prediction = prediction.squeeze()
            
            # 将预测转换为身份验证结果
            #
            # 分数语义见文件头部 ``SCORE_SEMANTICS_SIMILARITY``：这是 MSE 回归
            # 到 1.0 的原始输出，不是概率，也不保证落在 [0, 1] —— 实测把 600 点
            # 整段喂给按 10 步训练的模型，分数落在 1.06~1.99，此时阈值 0.8 低于
            # 分布下限、什么都拦不住。需要与训练口径一致的分数请用
            # ``authenticate_windowed_signal``。
            score = float(prediction.item())

            # NaN / Inf 不是「分数很低」，而是「这次没算出有效分数」。
            # NaN 参与 >= 比较恒为 False，若照原样返回，故障会被读成
            # 「用户不是本人」，与 status='error' 想表达的完全是两件事。
            if not math.isfinite(score):
                raise ValueError(f"模型输出不是有限数值（{score!r}），本次不产出分数")

            authenticated = score >= threshold
            
            # 构建结果字典
            result = {
                'status': 'ok',
                'authenticated': bool(authenticated),
                'score': float(score),
                'threshold': float(threshold),
                'signal_type': signal_type,
                'score_semantics': SCORE_SEMANTICS_SIMILARITY,
            }
            
            logger.info(f"{signal_type}身份验证: 得分={score:.4f}, 认证结果={'通过' if authenticated else '失败'}")
            
            if visualize:
                try:
                    import matplotlib.pyplot as plt
                    import os
                    
                    # 确保路径存在
                    if visualization_path is None:
                        # 如果未提供路径，创建默认路径
                        import tempfile
                        # 创建临时文件名
                        temp_dir = tempfile.gettempdir()
                        visualization_path = os.path.join(temp_dir, f"{signal_type}_auth_{int(time.time())}.png")
                    
                    # 确保目录存在
                    os.makedirs(os.path.dirname(os.path.abspath(visualization_path)), exist_ok=True)
                    
                    # 设置中文显示
                    plt.rcParams['font.sans-serif'] = ['SimHei']  # 设置中文字体
                    plt.rcParams['axes.unicode_minus'] = False    # 解决负号显示问题
                    
                    # 创建图形
                    plt.figure(figsize=(12, 6))
                    
                    # 绘制输入信号
                    plt.subplot(1, 2, 1)
                    input_np = input_signal.detach().cpu().numpy()
                    if len(input_np.shape) > 1:
                        input_np = input_np.reshape(-1)  # 展平为一维
                    plt.plot(input_np)
                    plt.title(f'{signal_type.upper()}信号')
                    plt.xlabel('采样点')
                    plt.ylabel('幅度')
                    
                    # 绘制认证结果
                    plt.subplot(1, 2, 2)
                    plt.barh(['认证分数'], [score], color='g' if authenticated else 'r')
                    plt.axvline(x=threshold, color='black', linestyle='--', label='阈值')
                    plt.xlim(0, 1)
                    plt.title(f'认证结果: {"通过" if authenticated else "失败"}')
                    plt.xlabel('分数')
                    plt.legend()
                    
                    # 保存图表
                    plt.tight_layout()
                    plt.savefig(visualization_path)
                    plt.close()
                    
                    logger.info(f"身份验证可视化已保存到 {visualization_path}")
                    
                    # 将可视化路径添加到结果中
                    result['visualization_path'] = visualization_path
                    
                except Exception as e:
                    logger.warning(f"生成身份验证可视化失败: {e}")
            
            return result
    
    except Exception as e:
        # 这里返回 score=0.0 是刻意 fail-closed：故障时一律不放行。
        # 但必须用 status 把「故障」与「真的判为不通过」区分开 ——
        # 否则调用方只能看到一个 0 分，分不清是模型坏了还是没比中。
        logger.error(f"身份验证过程中出错: {str(e)}")
        return {
            'status': 'error',
            'authenticated': False,
            'score': 0.0,
            'threshold': float(threshold),
            'signal_type': signal_type,
            'error': str(e)
        }

def score_signal_windows(model: nn.Module,
                         input_signal,
                         window_length: int = 10,
                         target_length: Optional[int] = None,
                         device: Optional[torch.device] = None) -> Dict[str, Any]:
    """
    把信号切成等长窗口，一次前向拿到**每个窗口**的分数（不作判定）。

    这是窗口口径的公共底座：单信号判定（`authenticate_windowed_signal`）与
    注册自检（把多轮样本拼成一批）都走它，避免各自复制一份切窗与前向逻辑。
    注册自检需要的是「每条样本各自的分数」，而不是一个聚合值 —— 拿聚合值去
    反推每轮是否通过，等于把判定权交给了错误的刻度。

    尾部不足一个窗口的点会被**丢弃**，不补零：补零等于往信号里塞一段模型从没
    见过的「静止段」，反而会把分数拉低。量产链路上 `target_length` 会先把长度
    对齐到窗口整数倍（600 = 60 × 10），所以不会真的丢数据。

    Returns:
        status == 'ok' 时：
            ``scores``       每个窗口的分数（长度 == windows）
            ``windows``      窗口数
            ``window_length``实际生效的窗口长度（已转成 int）
            ``data``         补齐/截断后的信号（画图与排查用）
            ``window_score_min`` / ``window_score_max``
        status == 'error' 时带 ``error`` 摘要，``scores`` 为空、``data`` 为空数组。
    """
    try:
        model.eval()

        # 窗口长度必须能当整数用：配置页填个 "10" 字符串过来时不该直接崩，
        # 填 0 或负数则必须明确拒绝，否则下面的整除会退化成除零。
        try:
            window_length = int(window_length)
        except (TypeError, ValueError):
            raise ValueError(f"窗口长度必须是正整数: {window_length!r}")
        if window_length <= 0:
            raise ValueError(f"窗口长度必须是正整数: {window_length!r}")

        if device is None:
            device = next(model.parameters()).device

        data = _fit_length(_as_1d_signal(input_signal), target_length)
        if data.size == 0:
            raise ValueError('输入信号为空，无法切窗')

        count = data.size // window_length
        if count == 0:
            # 不足一个窗口：补零凑够一个，与训练侧「数据太短就填充」同一口径
            padded = np.zeros(window_length, dtype=data.dtype)
            padded[:data.size] = data
            data = padded
            count = 1
        else:
            data = data[:count * window_length]

        tensor = torch.as_tensor(
            data.reshape(count, window_length, 1), dtype=torch.float32,
        ).to(device)

        with torch.no_grad():
            output = model(tensor)

        scores = output.detach().reshape(-1).cpu().numpy().astype(np.float64)
        if scores.size != count:
            raise ValueError(f"模型输出长度 {scores.size} 与窗口数 {count} 不一致")

        # NaN / Inf 不是「分数很低」：NaN 参与比较恒为 False，若放过去会把
        # 「没算出来」静默读成「不像」。这里直接判失败，由调用方转成 status=error。
        if not np.all(np.isfinite(scores)):
            raise ValueError('模型输出包含非有限值（NaN/Inf），本次不产出分数')

        return {
            'status': 'ok',
            'scores': [float(v) for v in scores],
            'windows': int(count),
            'window_length': int(window_length),
            'data': data,
            'window_score_min': float(scores.min()),
            'window_score_max': float(scores.max()),
        }

    except Exception as exc:
        logger.error(f"窗口打分失败: {exc}")
        return {
            'status': 'error',
            'scores': [],
            'windows': 0,
            'window_length': window_length,
            'data': np.empty(0),
            'error': str(exc),
        }


def authenticate_windowed_signal(model: nn.Module,
                                 input_signal,
                                 threshold: float = 0.5,
                                 window_length: int = 10,
                                 aggregation: str = 'mean',
                                 target_length: Optional[int] = None,
                                 signal_type: str = 'ecg',
                                 device: Optional[torch.device] = None,
                                 visualize: bool = False,
                                 visualization_path: Optional[str] = None) -> Dict[str, Any]:
    """
    按**训练时的窗口口径**给一段信号打分。

    为什么需要它
    ------------------------------------------------------------------
    训练是按 ``window_length`` 个采样点切窗的（`device.py::TRAIN_SEQUENCE_LENGTH`），
    而验证侧原先把整段信号（600 点）一次性喂进网络。``BiLSTMWithAttention``
    对序列长度没有约束，所以两种输入都能算出一个数 —— 但那是**两个不同的问题**：
    整段 600 点时注意力在 600 个时间步上汇聚，分数整体漂到训练目标的 1.6 倍左右，
    阈值也就失去了参照。实测同一段信号：整段口径 1.61、窗口均值口径 0.99，
    而模型训练目标正是 1.0。

    这里把信号切成等长窗口、**一次批量前向**拿到每个窗口的分数，再按
    ``aggregation`` 聚合成一个判定分数。好处有三：
      1. 判定分数与训练目标同刻度，阈值可解释；
      2. 批量前向远比「整段长序列」快（实测 600 点：约 378ms → 约 25ms）；
      3. 逐窗口分数一并返回，能看出「是一段特别像、还是整体都像」。

    Args:
        model: 训练好的模型
        input_signal: 一维信号（numpy / list / torch 均可）
        threshold: 相似度阈值（在窗口聚合后的刻度上比较）
        window_length: 每个窗口的采样点数，必须与训练侧一致
        aggregation: 窗口分数聚合方式，见 ``AGGREGATIONS``
        target_length: 先把信号补齐/截断到这个长度再切窗；None 表示不调整
        signal_type: 信号类型标记，仅用于结果与日志
        device: 计算设备，默认跟随模型所在设备
        visualize: 是否输出窗口分数分布图
        visualization_path: 图片保存路径

    Returns:
        Dict[str, Any]: 与 ``authenticate_single_signal`` 同构的结果，额外带
        ``windows`` / ``window_length`` / ``aggregation`` / ``window_scores`` /
        ``score_semantics``。推理异常或输出非有限值时 ``status == 'error'``。
    """
    try:
        if aggregation not in AGGREGATIONS:
            raise ValueError(f"不支持的聚合方式: {aggregation!r}（可选 {AGGREGATIONS}）")

        prepared = score_signal_windows(
            model, input_signal, window_length=window_length,
            target_length=target_length, device=device,
        )
        if prepared['status'] == 'error':
            raise ValueError(prepared.get('error') or '窗口打分失败')

        window_length = prepared['window_length']
        count = prepared['windows']
        scores = np.asarray(prepared['scores'], dtype=np.float64)
        data = prepared['data']

        score = _aggregate_scores(scores, aggregation)
        authenticated = score >= threshold

        result = {
            'status': 'ok',
            'authenticated': bool(authenticated),
            'score': float(score),
            'threshold': float(threshold),
            'signal_type': signal_type,
            'windows': int(count),
            'window_length': int(window_length),
            'aggregation': aggregation,
            'window_score_min': float(scores.min()),
            'window_score_max': float(scores.max()),
            'window_scores': [float(v) for v in scores],
            'score_semantics': SCORE_SEMANTICS_SIMILARITY,
        }

        logger.info(
            "%s窗口口径验证: %d 个窗口 × %d 点, 聚合=%s, 得分=%.4f "
            "(窗口区间 %.4f~%.4f), 阈值=%.2f, 结果=%s",
            signal_type.upper(), count, window_length, aggregation,
            score, result['window_score_min'], result['window_score_max'],
            threshold, '通过' if authenticated else '失败',
        )

        if visualize:
            try:
                import os
                import tempfile

                import matplotlib.pyplot as plt

                if visualization_path is None:
                    visualization_path = os.path.join(
                        tempfile.gettempdir(),
                        f"{signal_type}_windowed_auth_{int(time.time())}.png")
                os.makedirs(os.path.dirname(os.path.abspath(visualization_path)),
                            exist_ok=True)

                plt.rcParams['font.sans-serif'] = ['SimHei']
                plt.rcParams['axes.unicode_minus'] = False

                fig, axes = plt.subplots(2, 1, figsize=(12, 6))
                axes[0].plot(data)
                axes[0].set_title(f'{signal_type.upper()} 信号（{count} 个窗口）')
                axes[0].set_xlabel('采样点')

                axes[1].plot(range(count), scores, marker='o', markersize=2)
                axes[1].axhline(y=threshold, color='black', linestyle='--',
                                label='阈值')
                axes[1].axhline(y=1.0, color='gray', linestyle=':',
                                label='训练目标 1.0')
                axes[1].set_title(f'窗口分数（聚合 {aggregation} = {score:.4f}）')
                axes[1].set_xlabel('窗口序号')
                axes[1].legend()

                plt.tight_layout()
                plt.savefig(visualization_path)
                plt.close(fig)
                result['visualization_path'] = visualization_path
                logger.info(f"窗口口径验证可视化已保存到 {visualization_path}")
            except Exception as exc:
                logger.warning(f"生成窗口口径可视化失败: {exc}")

        return result

    except Exception as exc:
        # 与 authenticate_single_signal 同一口径：故障不等于「相似度为零」，
        # 用 status 把两者分开，score 仍固定 0.0（fail-closed）。
        logger.error(f"窗口口径验证过程中出错: {exc}")
        return {
            'status': 'error',
            'authenticated': False,
            'score': 0.0,
            'threshold': float(threshold),
            'signal_type': signal_type,
            'window_length': window_length,
            'aggregation': aggregation,
            'score_semantics': SCORE_SEMANTICS_SIMILARITY,
            'error': str(exc),
        }


def authenticate_dual_signals(ecg_model: nn.Module, 
                             ppg_model: nn.Module, 
                             ecg_signal: torch.Tensor,
                             ppg_signal: torch.Tensor,
                             ecg_threshold: float = 0.5,
                             ppg_threshold: float = 0.5,
                             fusion_method: str = 'weighted',
                             ecg_weight: float = 0.6,
                             ppg_weight: float = 0.4,
                             device: Optional[torch.device] = None,
                             visualize: bool = False,
                             visualization_path: Optional[str] = None) -> Dict[str, Any]:
    """
    使用ECG和PPG双信号进行融合身份验证
    
    Args:
        ecg_model: ECG模型
        ppg_model: PPG模型
        ecg_signal: ECG信号
        ppg_signal: PPG信号
        ecg_threshold: ECG身份验证阈值
        ppg_threshold: PPG身份验证阈值
        fusion_method: 融合方法 ('weighted', 'majority', 'and', 'or')
        ecg_weight: ECG权重
        ppg_weight: PPG权重
        device: 计算设备
        visualize: 是否可视化
        visualization_path: 可视化路径
        
    Returns:
        Dict[str, Any]: 双信号融合身份验证结果
    """
    try:
        # 获取每个信号的身份验证结果
        ecg_result = authenticate_single_signal(
            ecg_model, ecg_signal, ecg_threshold, 'ecg', device, visualize, visualization_path
        )
        
        ppg_result = authenticate_single_signal(
            ppg_model, ppg_signal, ppg_threshold, 'ppg', device, visualize, visualization_path
        )
        
        # 根据融合方法组合结果
        if fusion_method == 'weighted':
            # 加权平均
            combined_score = ecg_result['score'] * ecg_weight + ppg_result['score'] * ppg_weight
            combined_threshold = ecg_threshold * ecg_weight + ppg_threshold * ppg_weight
            authenticated = combined_score >= combined_threshold
            
        elif fusion_method == 'majority':
            # 多数投票。只有两路信号时「多数」就等于「两者都通过」，判定与 'and' 同义。
            #
            # 综合分必须与判定同口径：旧实现用两路分数的**平均**做综合分，
            # 却拿**逻辑与**做判定，于是会出现 combined_score >= combined_threshold
            # 而 authenticated 仍为 False 的矛盾结果 —— 结论和分数互相打架，
            # 是最难排查的一类问题。改为取 min / max 后，
            # 「综合分过线」成为「两路都过线」的充分条件：口径统一且偏保守，
            # 宁可更严，不可更松。
            combined_score = min(ecg_result['score'], ppg_result['score'])
            combined_threshold = max(ecg_threshold, ppg_threshold)
            authenticated = combined_score >= combined_threshold
            
        elif fusion_method == 'and':
            # 逻辑与
            authenticated = ecg_result['authenticated'] and ppg_result['authenticated']
            combined_score = min(ecg_result['score'], ppg_result['score'])
            combined_threshold = max(ecg_threshold, ppg_threshold)
            
        elif fusion_method == 'or':
            # 逻辑或
            authenticated = ecg_result['authenticated'] or ppg_result['authenticated']
            combined_score = max(ecg_result['score'], ppg_result['score'])
            combined_threshold = min(ecg_threshold, ppg_threshold)
            
        else:
            # 默认使用加权平均
            combined_score = ecg_result['score'] * 0.6 + ppg_result['score'] * 0.4
            combined_threshold = ecg_threshold * 0.6 + ppg_threshold * 0.4
            authenticated = combined_score >= combined_threshold
        
        # 任一路推理失败时，整体不能对外宣称「正常完成」——
        # 分数虽然拼得出来，但有一半输入根本没算过。
        child_failed = any(
            isinstance(child, dict) and child.get('status') == 'error'
            for child in (ecg_result, ppg_result)
        )

        # 构建结果
        result = {
            'status': 'error' if child_failed else 'ok',
            'authenticated': bool(authenticated),
            'combined_score': float(combined_score),
            'combined_threshold': float(combined_threshold),
            'ecg_result': ecg_result,
            'ppg_result': ppg_result,
            'fusion_method': fusion_method
        }
        
        logger.info(f"双信号融合身份验证: 方法={fusion_method}, 得分={combined_score:.4f}, 认证结果={'通过' if authenticated else '失败'}")
        
        # 生成融合验证的可视化
        if visualize:
            try:
                import matplotlib.pyplot as plt
                import os
                import tempfile
                
                # 确保路径存在
                if visualization_path is None:
                    # 如果未提供路径，创建默认路径
                    temp_dir = tempfile.gettempdir()
                    visualization_path = os.path.join(temp_dir, f"dual_signal_auth_{int(time.time())}.png")
                
                # 确保目录存在
                os.makedirs(os.path.dirname(os.path.abspath(visualization_path)), exist_ok=True)
                
                # 设置中文显示
                plt.rcParams['font.sans-serif'] = ['SimHei']  # 设置中文字体
                plt.rcParams['axes.unicode_minus'] = False    # 解决负号显示问题
                
                # 创建图形
                plt.figure(figsize=(15, 10))
                
                # 绘制ECG信号
                plt.subplot(3, 2, 1)
                ecg_np = ecg_signal.detach().cpu().numpy().reshape(-1) if isinstance(ecg_signal, torch.Tensor) else ecg_signal.reshape(-1)
                plt.plot(ecg_np)
                plt.title('ECG信号')
                
                # 绘制PPG信号
                plt.subplot(3, 2, 2)
                ppg_np = ppg_signal.detach().cpu().numpy().reshape(-1) if isinstance(ppg_signal, torch.Tensor) else ppg_signal.reshape(-1)
                plt.plot(ppg_np)
                plt.title('PPG信号')
                
                # 绘制ECG认证结果
                plt.subplot(3, 2, 3)
                plt.barh(['ECG分数'], [ecg_result['score']], color='g' if ecg_result['authenticated'] else 'r')
                plt.axvline(x=ecg_threshold, color='black', linestyle='--', label='阈值')
                plt.xlim(0, 1)
                plt.title(f'ECG认证结果: {"通过" if ecg_result["authenticated"] else "失败"}')
                plt.legend()
                
                # 绘制PPG认证结果
                plt.subplot(3, 2, 4)
                plt.barh(['PPG分数'], [ppg_result['score']], color='g' if ppg_result['authenticated'] else 'r')
                plt.axvline(x=ppg_threshold, color='black', linestyle='--', label='阈值')
                plt.xlim(0, 1)
                plt.title(f'PPG认证结果: {"通过" if ppg_result["authenticated"] else "失败"}')
                plt.legend()
                
                # 绘制融合结果
                plt.subplot(3, 1, 3)
                plt.barh(['融合分数'], [combined_score], color='g' if authenticated else 'r')
                plt.axvline(x=combined_threshold, color='black', linestyle='--', label='阈值')
                plt.xlim(0, 1)
                plt.title(f'融合认证结果 (方法: {fusion_method}): {"通过" if authenticated else "失败"}')
                plt.xlabel('分数')
                plt.legend()
                
                # 添加融合方法信息
                if fusion_method == 'weighted':
                    plt.figtext(0.5, 0.01, f"加权融合: ECG权重={ecg_weight:.2f}, PPG权重={ppg_weight:.2f}", 
                               ha='center', fontsize=10)
                
                # 保存图表
                plt.tight_layout(rect=[0, 0.03, 1, 0.97])
                plt.savefig(visualization_path)
                plt.close()
                
                logger.info(f"双信号融合身份验证可视化已保存到 {visualization_path}")
                
                # 将可视化路径添加到结果中
                result['visualization_path'] = visualization_path
                
            except Exception as e:
                logger.warning(f"生成双信号融合身份验证可视化失败: {e}")
        
        return result
        
    except Exception as e:
        logger.error(f"双信号融合身份验证过程中出错: {str(e)}")
        return {
            'status': 'error',
            'authenticated': False,
            'combined_score': 0.0,
            'combined_threshold': 0.0,
            'ecg_result': ecg_result if 'ecg_result' in locals() else None,
            'ppg_result': ppg_result if 'ppg_result' in locals() else None,
            'fusion_method': fusion_method,
            'error': str(e)
        }

def _equal_error_rate(scores: np.ndarray, labels: np.ndarray) -> float:
    """
    计算等错误率（EER, Equal Error Rate）。

    EER 与下面 ``calculate_authentication_metrics`` 里那对 far / frr 有本质区别：
    后者是**当前阈值下**的两个错误率，换个阈值就变；EER 则是 ROC 曲线上的固有
    属性，描述「FAR 恰好等于 FRR」时那个点的错误率，与传入阈值无关。

    做法：把所有候选分割点扫一遍，找到 FAR - FRR 变号的位置，再在相邻两点间
    线性插值。复杂度 O(n log n)，不构造 n×阈值 的大矩阵。

    常见误写是把 ``(far + frr) / 2`` 当作 EER —— 那只是某个阈值下的平均错误率，
    无论模型区分度好还是差，都会明显偏离真实的 EER。

    Args:
        scores: 身份匹配分数（本项目模型输出落在 0~1）
        labels: 真实标签，1 表示同一身份（genuine），0 表示不同身份（impostor）

    Returns:
        float: EER；当样本中缺少 genuine 或 impostor 任一类时返回 ``nan`` ——
            此时 ROC 曲线不完整，EER 无定义，编不出一个诚实的数字。
    """
    scores = np.asarray(scores, dtype=np.float64).ravel()
    labels = np.asarray(labels).ravel()
    is_genuine = labels == 1

    n_pos = int(np.count_nonzero(is_genuine))
    n_neg = int(scores.size - n_pos)
    if n_pos == 0 or n_neg == 0:
        return float('nan')

    # 按分数**降序**排列：这样「取前 i 个判为匹配」才等价于「把阈值设在第 i 与
    # 第 i+1 个分数之间」。若按升序，前 i 个会是最低分的样本，方向正好反了。
    order = np.argsort(-scores, kind='mergesort')
    sorted_genuine = is_genuine[order]

    tp = np.cumsum(sorted_genuine, dtype=np.float64)
    accepted = np.arange(1, scores.size + 1, dtype=np.float64)
    fp = accepted - tp
    fn = float(n_pos) - tp

    # 补上 i = 0：阈值高于所有分数，全部判为不匹配
    far = np.concatenate(([0.0], fp / n_neg))
    frr = np.concatenate(([1.0], fn / float(n_pos)))
    diff = far - frr

    crossing = np.flatnonzero(diff >= 0)
    if crossing.size == 0:
        # 理论上到不了这里：i = 0 时 diff = -1，i = n 时 diff = +1，必然变号。
        # 留作数值异常的兜底 —— 退化为取最接近相等的那一点。
        k = int(np.argmin(np.abs(diff)))
        return float((far[k] + frr[k]) / 2.0)

    k = int(crossing[0])
    if k == 0:
        return float((far[0] + frr[0]) / 2.0)

    d0, d1 = float(diff[k - 1]), float(diff[k])
    if d1 <= d0:
        return float((far[k] + frr[k]) / 2.0)

    weight = -d0 / (d1 - d0)                      # 落在 [0, 1]
    far_at_cross = float(far[k - 1] + weight * (far[k] - far[k - 1]))
    frr_at_cross = float(frr[k - 1] + weight * (frr[k] - frr[k - 1]))
    return (far_at_cross + frr_at_cross) / 2.0


def calculate_authentication_metrics(predictions: np.ndarray, 
                                    ground_truth: np.ndarray, 
                                    threshold: float = 0.5) -> Dict[str, float]:
    """
    计算身份验证性能指标
    
    Args:
        predictions: 预测的身份匹配分数
        ground_truth: 真实身份标签 (0=不匹配, 1=匹配)
        threshold: 身份验证阈值
        
    Returns:
        Dict[str, float]: 性能指标。``accuracy`` ~ ``frr`` 依赖传入的 ``threshold``；
            ``eer`` 不依赖它 —— EER 刻画的是整条 ROC 曲线，在样本缺少任一类时
            为 ``nan``。
    """
    # 转换预测为二元决策
    binary_preds = predictions >= threshold
    
    # 确保都是布尔值或0/1值
    binary_preds = binary_preds.astype(np.int32)
    ground_truth = ground_truth.astype(np.int32)
    
    # 计算度量
    # 真阳性 (TP): 正确识别为匹配
    tp = np.sum((binary_preds == 1) & (ground_truth == 1))
    
    # 真阴性 (TN): 正确识别为不匹配
    tn = np.sum((binary_preds == 0) & (ground_truth == 0))
    
    # 假阳性 (FP): 错误识别为匹配
    fp = np.sum((binary_preds == 1) & (ground_truth == 0))
    
    # 假阴性 (FN): 错误识别为不匹配
    fn = np.sum((binary_preds == 0) & (ground_truth == 1))
    
    # 计算指标
    # 准确率：所有预测中正确的比例
    accuracy = (tp + tn) / (tp + tn + fp + fn + 1e-10)
    
    # 精确率：预测为匹配的样本中，实际匹配的比例
    precision = tp / (tp + fp + 1e-10)
    
    # 召回率：实际匹配的样本中，被正确识别的比例
    recall = tp / (tp + fn + 1e-10)
    
    # F1分数：精确率和召回率的调和平均
    f1 = 2 * precision * recall / (precision + recall + 1e-10)
    
    # 错误接受率 (FAR)：不匹配样本被错误接受的比例
    far = fp / (fp + tn + 1e-10)
    
    # 错误拒绝率 (FRR)：匹配样本被错误拒绝的比例
    frr = fn / (fn + tp + 1e-10)
    
    # 相等错误率 (EER)：由全体分数分布算出，与当前 threshold 无关。
    # 它并不等于上面那对 far / frr 的平均值 —— 那是「当前阈值下的平均错误率」，
    # 换个阈值就变，而 EER 不会。
    eer = _equal_error_rate(predictions, ground_truth)
    
    return {
        'accuracy': float(accuracy),
        'precision': float(precision), 
        'recall': float(recall),
        'f1': float(f1),
        'far': float(far),
        'frr': float(frr),
        'eer': float(eer)
    }

def optimize_authentication_threshold(model: nn.Module, 
                                     validation_loader: torch.utils.data.DataLoader,
                                     target_far: float = 0.01,
                                     device: Optional[torch.device] = None) -> float:
    """
    优化身份验证阈值以达到目标的错误接受率(FAR)
    
    Args:
        model: 模型
        validation_loader: 验证数据集
        target_far: 目标错误接受率
        device: 计算设备
        
    Returns:
        float: 最佳阈值
    """
    model.eval()
    
    # 确定设备
    if device is None:
        device = next(model.parameters()).device
    
    # 收集所有预测和真实标签
    all_preds = []
    all_labels = []
    
    with torch.no_grad():
        for inputs, labels in validation_loader:
            inputs = inputs.to(device)
            outputs = model(inputs).cpu().numpy()
            
            all_preds.extend(outputs)
            all_labels.extend(labels.numpy())
    
    # 转换为numpy数组
    all_preds = np.array(all_preds)
    all_labels = np.array(all_labels)
    
    # 尝试不同的阈值
    thresholds = np.arange(0, 1.01, 0.01)
    best_threshold = 0.5  # 默认值
    min_diff = float('inf')
    
    for threshold in thresholds:
        metrics = calculate_authentication_metrics(all_preds, all_labels, threshold)
        
        # 计算当前FAR与目标FAR的差值
        far_diff = abs(metrics['far'] - target_far)
        
        if far_diff < min_diff:
            min_diff = far_diff
            best_threshold = threshold
            
    logger.info(f"最佳身份验证阈值: {best_threshold:.4f}, 对应目标FAR: {target_far:.4f}")
    
    return float(best_threshold) 