# -*- coding: utf-8 -*-
"""
仪表盘蓝图：用户首页与健康数据接口

只负责「取数据 + 返回 JSON / 渲染页面」，数据合成在
`web_auth.services.health` 里。
"""

from datetime import datetime

from flask import Blueprint, jsonify, redirect, render_template, session, url_for

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



# 路由: 仪表盘
@bp.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('auth.login'))
    
    return render_template('dashboard.html', username=session['username'])


# 新增：获取实时健康数据API
@bp.route('/api/realtime_health_data')
def get_realtime_health_data():
    """获取实时健康数据"""
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    username = session['username']

    # 生成模拟实时数据
    realtime_data = {
        'heart_rate': generate_heart_rate(),
        'ecg_signal': generate_ecg_signal(),
        'ppg_signal': generate_ppg_signal(),
        'emotion_status': get_emotion_status(),
        'alert_level': get_alert_level(),
        'timestamp': datetime.now().isoformat()
    }

    return jsonify(realtime_data)


# 新增：获取健康趋势数据API
@bp.route('/api/health_trends')
def get_health_trends():
    """获取健康趋势数据"""
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    # 生成模拟趋势数据
    trends_data = {
        'heart_rate_trend': generate_heart_rate_trend(),
        'emotion_trend': generate_emotion_trend(),
    }

    return jsonify(trends_data)


# API: 获取仪表盘模拟数据
@bp.route('/api/dashboard_data')
def get_dashboard_data():
    """获取仪表盘模拟数据"""
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401
    
    import random
    from datetime import datetime, timedelta
    
    # 生成模拟数据
    data = {
        'user_stats': {
            'total_logins': random.randint(150, 200),
            'successful_auths': random.randint(140, 190),
            'failed_auths': random.randint(5, 15),
            'avg_response_time': random.randint(100, 150)
        },
        'system_stats': {
            'uptime': '7天 14小时 32分钟',
            'active_users': 1,
            'total_devices': 1,
            'data_integrity': round(random.uniform(99.5, 99.9), 1)
        },
        'performance_data': {
            'success_rate': round(random.uniform(94, 99), 1),
            'accuracy_rate': round(random.uniform(97, 99), 1),
            'response_time': random.randint(80, 120)
        },
        'security_events': [
            {
                'time': (datetime.now() - timedelta(seconds=15)).strftime('%H:%M:%S'),
                'event': '用户认证成功',
                'status': 'success'
            },
            {
                'time': (datetime.now() - timedelta(seconds=45)).strftime('%H:%M:%S'),
                'event': 'ECG信号采集完成',
                'status': 'success'
            },
            {
                'time': (datetime.now() - timedelta(seconds=75)).strftime('%H:%M:%S'),
                'event': '设备连接建立',
                'status': 'success'
            },
            {
                'time': (datetime.now() - timedelta(seconds=105)).strftime('%H:%M:%S'),
                'event': '系统自检完成',
                'status': 'success'
            },
            {
                'time': (datetime.now() - timedelta(seconds=135)).strftime('%H:%M:%S'),
                'event': '用户登录尝试',
                'status': 'warning'
            },
            {
                'time': (datetime.now() - timedelta(seconds=150)).strftime('%H:%M:%S'),
                'event': '系统启动完成',
                'status': 'success'
            }
        ]
    }
    
    return jsonify(data)
