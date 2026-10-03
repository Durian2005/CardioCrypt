# -*- coding: utf-8 -*-
"""
仪表盘蓝图：用户首页与健康数据接口

只负责「取数据 + 返回 JSON / 渲染页面」，数据来源分两处：

  - `web_auth.services.stats` —— 能从数据库与进程状态算出来的**真实**数字
  - `web_auth.services.health` —— 没有真实来源的生理信号**合成**数据

⚠️ 关于数据可信度（重要）
------------------------
仪表盘上原来整页都是 `random` 生成的数字，却被当作真实统计呈现。现在按
「能算的算真、算不出的必须标注」处理：合成字段会在响应里被显式列出
（`synthetic_fields` / `synthetic_note`），前端据此提示用户。

新增字段时请想清楚它属于哪一类 —— **不要把合成数据混进真实字段**。
这条约定与 `DEMO_MODE` 的三层留痕同源：凡是可能被误当成真实结果的东西，
都得自己说明白。
"""

import random
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, redirect, render_template, session, url_for

from web_auth.services import stats
from web_auth.services.health import (
    generate_ecg_signal,
    generate_emotion_trend,
    generate_heart_rate,
    generate_heart_rate_trend,
    generate_ppg_signal,
    get_alert_level,
    get_emotion_status,
)

bp = Blueprint('dashboard', __name__)


# 没有真实来源、属于「界面示意」的字段。
#
# 列出的是**响应里的路径**，前端据此在这几块旁边打标记。补上真实数据源后
# 记得把它从这里删掉 —— 让标记与实际相符，否则就变成另一种误导。
SYNTHETIC_FIELDS = [
    'performance_data',
    'security_events',
    'system_stats.data_integrity',
    'realtime_health_data',
    'health_trends',
]

SYNTHETIC_NOTE = '标出的内容为系统合成的示意数据，不代表真实测量或统计结果'


# 路由: 仪表盘
@bp.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('auth.login'))

    return render_template('dashboard.html', username=session['username'])


# 新增：获取实时健康数据API
@bp.route('/api/realtime_health_data')
def get_realtime_health_data():
    """
    实时健康数据。

    ⚠️ **全部为合成数据**：没有接真实传感器，心率与波形都是生成出来的。
    响应里带 `synthetic` 标记，界面必须据此提示（见 SYNTHETIC_FIELDS）。
    """
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    realtime_data = {
        'heart_rate': generate_heart_rate(),
        'ecg_signal': generate_ecg_signal(),
        'ppg_signal': generate_ppg_signal(),
        'emotion_status': get_emotion_status(),
        'alert_level': get_alert_level(),
        'timestamp': datetime.now().isoformat(),
        # 设备连接情况是真实的（取自进程内的设备句柄），与上面的合成信号区分开
        'device_connected': stats.count_connected_devices() > 0,
        # 供前端标注：本响应中的生理数据不含真实测量值
        'synthetic': True,
        'synthetic_note': SYNTHETIC_NOTE,
    }

    return jsonify(realtime_data)


# 新增：获取健康趋势数据API
@bp.route('/api/health_trends')
def get_health_trends():
    """健康趋势数据（合成，带 `synthetic` 标记）。"""
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    trends_data = {
        'heart_rate_trend': generate_heart_rate_trend(),
        'emotion_trend': generate_emotion_trend(),
        'synthetic': True,
        'synthetic_note': SYNTHETIC_NOTE,
    }

    return jsonify(trends_data)


# API: 获取仪表盘数据
@bp.route('/api/dashboard_data')
def get_dashboard_data():
    """
    仪表盘数据。

    `user_stats` / `system_stats` 中的运行时长、用户数、设备数来自真实来源；
    `performance_data`、`security_events`、`data_integrity` 没有真实来源，
    由 `synthetic_fields` 标出。
    """
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    username = session['username']

    data = {
        # 真实：取自 users / auth_history 集合（无记录时如实为 0）
        'user_stats': stats.build_user_stats(username),
        # 真实：进程运行时长、注册用户数、当前已连接设备数
        # 示意：data_integrity（没有校验机制，无从计算）
        'system_stats': dict(
            stats.build_system_stats(),
            data_integrity=round(random.uniform(99.5, 99.9), 1),
        ),
        # 以下两块为示意数据，已在 synthetic_fields 中列出
        'performance_data': {
            'success_rate': round(random.uniform(94, 99), 1),
            'accuracy_rate': round(random.uniform(97, 99), 1),
            'response_time': random.randint(80, 120),
        },
        'security_events': [
            {
                'time': (datetime.now() - timedelta(seconds=15)).strftime('%H:%M:%S'),
                'event': '用户认证成功',
                'status': 'success',
            },
            {
                'time': (datetime.now() - timedelta(seconds=45)).strftime('%H:%M:%S'),
                'event': 'ECG信号采集完成',
                'status': 'success',
            },
            {
                'time': (datetime.now() - timedelta(seconds=75)).strftime('%H:%M:%S'),
                'event': '设备连接建立',
                'status': 'success',
            },
            {
                'time': (datetime.now() - timedelta(seconds=105)).strftime('%H:%M:%S'),
                'event': '系统自检完成',
                'status': 'success',
            },
            {
                'time': (datetime.now() - timedelta(seconds=135)).strftime('%H:%M:%S'),
                'event': '用户登录尝试',
                'status': 'warning',
            },
            {
                'time': (datetime.now() - timedelta(seconds=150)).strftime('%H:%M:%S'),
                'event': '系统启动完成',
                'status': 'success',
            },
        ],
        # 标注：哪些字段是示意数据，以及原因
        'synthetic_fields': SYNTHETIC_FIELDS,
        'synthetic_note': SYNTHETIC_NOTE,
    }

    return jsonify(data)
