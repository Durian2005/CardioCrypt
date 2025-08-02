"""
度量指标模块
提供用于评估模型性能和信号相似度的各种指标
"""

import numpy as np
from scipy.spatial.distance import euclidean
from sklearn.metrics import mean_squared_error, mean_absolute_error
import torch
from .logger import logger

def calculate_similarity_report(true_signal, pred_signal, sample_ratio=0.2, dtw_window=20):
    """
    计算心电信号相似度分析报告，支持多种评估指标
    
    参数：
        true_signal: 实际信号 (numpy数组或torch张量)
        pred_signal: 预测信号 (numpy数组或torch张量)
        sample_ratio: 采样比例(0.1-0.5)
        dtw_window: 动态时间规整窗口大小
        
    返回：
        dict: 包含评估指标的字典
    """
    try:
        # 数据转换与验证
        y_true = true_signal.cpu().numpy().flatten() if torch.is_tensor(true_signal) else true_signal.flatten()
        y_pred = pred_signal.cpu().numpy().flatten() if torch.is_tensor(pred_signal) else pred_signal.flatten()
        
        # 数据长度验证
        if len(y_true) != len(y_pred):
            min_len = min(len(y_true), len(y_pred))
            y_true = y_true[:min_len]
            y_pred = y_pred[:min_len]
            logger.warning(f"信号长度不一致，已截断至最小长度 {min_len}")

        # 动态采样
        sample_size = max(10, int(len(y_true) * sample_ratio))  # 保证最小样本量
        indices = np.random.choice(len(y_true), sample_size, replace=False)
        y_true_sampled = y_true[indices]
        y_pred_sampled = y_pred[indices]

        # 基础指标计算
        mse = mean_squared_error(y_true_sampled, y_pred_sampled)
        mae = mean_absolute_error(y_true_sampled, y_pred_sampled)
        with np.errstate(invalid='ignore'):
            pearson = np.corrcoef(y_true_sampled, y_pred_sampled)[0, 1]
        
        # 信号相似度百分比
        signal_range = np.ptp(y_true_sampled)
        similarity = 1 - (np.abs(y_true_sampled - y_pred_sampled).mean() / (signal_range + 1e-8))  # 防止除零

        # 动态时间规整（可选）
        dtw_distance = None
        try:
            from dtw import dtw
            alignment = dtw(y_true_sampled, y_pred_sampled,
                          keep_internals=True,
                          window_type="sakoechiba",
                          window_args={"window_size": dtw_window})
            dtw_distance = alignment.normalizedDistance
        except ImportError:
            logger.warning("DTW库未安装，跳过DTW距离计算")
        except Exception as e:
            logger.error(f"DTW计算失败: {str(e)}")

        # 构建报告
        report = {
            "MSE": round(mse, 4),
            "MAE": round(mae, 4),
            "Pearson": round(pearson, 4) if not np.isnan(pearson) else None,
            "DTW": round(dtw_distance, 4) if dtw_distance else None,
            "Similarity%": round(similarity*100, 2)
        }

        # 打印格式化报告
        logger.info("\n" + "═"*50)
        logger.info(f"{'ECG信号分析报告':^50}")
        logger.info("═"*50)
        logger.info(f"| {'指标':<18} | {'值':<28} |")
        logger.info("|" + "-"*20 + "|" + "-"*30 + "|")
        logger.info(f"| MSE (×10³)     | {mse*1000:.<26.4f} |")
        logger.info(f"| MAE            | {mae:.<26.4f} |")
        logger.info(f"| Pearson        | {pearson if not np.isnan(pearson) else 'N/A':.<26.4f} |")
        logger.info(f"| DTW距离        | {dtw_distance or 'N/A':.<26} |")
        logger.info(f"| 相似度 (%)     | {similarity*100:.<26.2f} |")
        logger.info("═"*50 + "\n")
        
        return report

    except Exception as e:
        logger.error(f"相似度分析失败: {str(e)}")
        return {}

def similarity_score(reference_features, query_features):
    """
    计算两组特征之间的相似度得分(0-100)
    
    参数:
        reference_features: 参考特征
        query_features: 查询特征
    
    返回:
        float: 相似度百分比(0-100)
    """
    try:
        # 使用欧氏距离计算相似度
        distance = euclidean(reference_features, query_features)
        
        # 转换为相似度得分(0-1)
        max_possible_distance = np.linalg.norm(reference_features) + np.linalg.norm(query_features)
        similarity = 1 - distance / (max_possible_distance + 1e-8)  # 防止除零
        
        # 转换为百分比
        similarity_percent = max(0, min(100, similarity * 100))
        return similarity_percent
        
    except Exception as e:
        logger.error(f"相似度得分计算失败: {str(e)}")
        return 0.0 