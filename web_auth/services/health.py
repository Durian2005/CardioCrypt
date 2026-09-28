# -*- coding: utf-8 -*-
"""
用户仪表盘的模拟数据

心率、情绪、告警等级与历史趋势都在这里合成。这段逻辑与 Web 请求无关，
拆出来之后蓝图只剩「取数据 + 返回 JSON」。
"""

import random
from datetime import datetime



# 新增：模拟数据生成函数
def get_simulated_health_data(username):
    """生成模拟健康数据"""
    return {
        'current_heart_rate': 72,
        'heart_rate_status': '正常',
        'emotion_status': '平静',
        'alert_level': '低风险',
        'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'device_status': '已连接',
        'today_summary': {
            'avg_heart_rate': 75,
            'max_heart_rate': 85,
            'min_heart_rate': 65,
            'abnormal_events': 2
        }
    }


def generate_health_report(username):
    """生成健康报告"""
    return {
        'period': '最近7天',
        'summary': {
            'avg_heart_rate': 74,
            'abnormal_days': 1,
            'risk_assessment': '低风险'
        },
        'daily_data': [
            {'date': '2024-01-01', 'avg_hr': 72, 'status': '正常'},
            {'date': '2024-01-02', 'avg_hr': 75, 'status': '正常'},
            {'date': '2024-01-03', 'avg_hr': 85, 'status': '偏高'},
            {'date': '2024-01-04', 'avg_hr': 70, 'status': '正常'},
            {'date': '2024-01-05', 'avg_hr': 73, 'status': '正常'},
            {'date': '2024-01-06', 'avg_hr': 76, 'status': '正常'},
            {'date': '2024-01-07', 'avg_hr': 71, 'status': '正常'}
        ]
    }


def generate_heart_rate():
    """生成模拟心率数据"""
    return 70 + random.randint(-5, 5)


def generate_ecg_signal():
    """生成模拟ECG信号"""
    return [random.uniform(-0.5, 0.5) for _ in range(100)]


def generate_ppg_signal():
    """生成模拟PPG信号"""
    return [random.uniform(0.1, 0.9) for _ in range(100)]



def get_emotion_status():
    """获取情绪状态"""
    statuses = ['平静', '轻度紧张', '放松', '专注']
    return random.choice(statuses)


def get_alert_level():
    """获取预警等级"""
    levels = ['正常', '低风险', '中风险', '高风险']
    return random.choice(levels)



def generate_heart_rate_trend():
    """生成心率趋势数据"""
    return [70 + random.randint(-8, 8) for _ in range(24)]


def generate_emotion_trend():
    """生成情绪趋势数据"""
    emotions = [1, 2, 1, 3, 2, 1, 2]  # 1:平静, 2:轻度紧张, 3:放松
    return emotions
