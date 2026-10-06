# -*- coding: utf-8 -*-
"""
核心能力接入层

三件事：

1. 导入 `ecgppg_system` / `model_example`，并把结果固化为 `SYSTEM_AVAILABLE`。
   算法依赖缺失时 Web 层仍要能启动，只在真正调用算法时报出明确原因 ——
   所以失败分支里会留下一组「降级占位」函数，而不是让 import 直接炸掉整个应用。
2. 用户模型的按需加载与 LRU 淘汰。
3. 视图复用的最小工具：`admin_required` / `client_ip` / `load_app_config`。
"""

import os
from functools import wraps

import pymongo
import torch
from flask import redirect, request, session, url_for

from web_auth import state
from web_auth.config import MONGO_URI, logger
from web_auth.extensions import mongo



# 导入 CardioCrypt 核心信号处理模块
try:
    from ecgppg_system.config import settings
    from ecgppg_system.config import config as dynamic_config
    # 刻意不导入 model_example.main_wrapper：它顶层依赖 EnvironmentManager
    # （串口相关），一旦那部分缺失就会让整个 try 失败、SYSTEM_AVAILABLE 被置
    # 为 False，连带拖垮 Web 层；而它导出的封装函数在本仓库内没有任何调用方
    # （见该文件顶部的废弃说明）。
    from model_example.model_creator import create_model, setup_model_device
    from model_example.model_trainer import train_model, configure_data_augmentation
    from model_example.model_evaluator import validate_model
    from model_example.authentication import authenticate_single_signal
    from model_example.model_io import save_model, load_model
    from ecgppg_system.models.bilstm import BiLSTMWithAttention
    
    # 从settings导入BLE服务和特征UUID
    HEART_RATE_SERVICE = settings.HEART_RATE_SERVICE
    HEART_RATE_CHARACTERISTIC = settings.HEART_RATE_CHARACTERISTIC
    
    SYSTEM_AVAILABLE = True
    logger.info("成功导入 CardioCrypt 核心模块")
except ImportError as e:
    logger.error(f"导入 CardioCrypt 核心模块失败: {e}")
    SYSTEM_AVAILABLE = False
    # 如果导入失败，设置默认值
    HEART_RATE_SERVICE = "0000180d-0000-1000-8000-00805f9b34fb"
    HEART_RATE_CHARACTERISTIC = "00002a37-0000-1000-8000-00805f9b34fb"

    # 降级占位：算法依赖缺失时 Web 层仍应能启动，视图要在**调用时**
    # 才拿到明确错误（原来的写法会让蓝图 import 阶段直接失败）。
    def _algorithm_module_unavailable(*args, **kwargs):
        raise RuntimeError(
            "ecgppg_system / model_example 不可用，请检查算法层依赖是否安装完整"
        )

    dynamic_config = None
    settings = None
    create_model = _algorithm_module_unavailable
    setup_model_device = _algorithm_module_unavailable
    train_model = _algorithm_module_unavailable
    configure_data_augmentation = _algorithm_module_unavailable
    validate_model = _algorithm_module_unavailable
    authenticate_single_signal = _algorithm_module_unavailable
    save_model = _algorithm_module_unavailable
    load_model = _algorithm_module_unavailable
    BiLSTMWithAttention = None



# 动态配置不可用时的兜底默认值。
#
# 原来这份字典在本文件里完整写了两遍（`SYSTEM_AVAILABLE` 为假的分支一次、
# 读取抛异常的分支又一次），14 行逐字重复 —— 改一处漏一处的典型。
#
# 做成**工厂函数**而不是模块级常量：返回值会被 `state.admin_config` 持有并
# 整体替换，若返回同一个字典对象，两处调用方就会互相污染对方的修改。
def _default_app_config():
    """返回一份全新的默认配置字典（调用方可以安全修改）。"""
    return {
        'model_threshold': 0.8,
        'alpha': 0.6,
        'beta': 0.4,
        'verification_time': 30,
        'min_verification_success': 2,
        'total_verification_count': 3,
        'device_connection_timeout': 10.0,
        'device_scan_timeout': 5.0,
        'training_epochs': 50,
        'training_learning_rate': 0.001,
        'training_batch_size': 32,
        'system_use_cuda': True,
        'system_cuda_device': 0,
    }


def client_ip():
    """取客户端 IP，用作限流的键。"""
    return (request.remote_addr or 'unknown').strip()


# 加载配置参数到本地变量中，方便使用
def load_app_config():
    """从动态配置加载应用配置参数"""
    if not SYSTEM_AVAILABLE:
        # 算法层不可用：没有 dynamic_config 可读，直接用默认值
        return _default_app_config()
    
    try:
        # 从动态配置中加载参数
        config = {
            # 模型参数
            'model_threshold': dynamic_config.get('model', 'threshold', 0.8),
            'alpha': dynamic_config.get('model', 'alpha', 0.6),
            'beta': dynamic_config.get('model', 'beta', 0.4),
            
            # 验证参数
            'verification_time': dynamic_config.get('verification', 'time', 30),
            'min_verification_success': dynamic_config.get('verification', 'min_success', 2),
            'total_verification_count': dynamic_config.get('verification', 'total_count', 3),
            
            # 设备参数
            'device_connection_timeout': dynamic_config.get('device', 'connection_timeout', 10.0),
            'device_scan_timeout': dynamic_config.get('device', 'scan_timeout', 5.0),
            
            # 训练参数
            'training_epochs': dynamic_config.get('training', 'epochs', 50),
            'training_learning_rate': dynamic_config.get('training', 'learning_rate', 0.001),
            'training_batch_size': dynamic_config.get('training', 'batch_size', 32),
            
            # 系统参数
            'system_use_cuda': dynamic_config.get('system', 'use_cuda', True),
            'system_cuda_device': dynamic_config.get('system', 'cuda_device', 0)
        }
        logger.info("已从动态配置加载应用参数")
        return config
    except Exception as e:
        logger.error(f"加载动态配置失败: {e}")
        # 配置读取失败：同样回落到默认值，但记 error 让日志里查得到
        return _default_app_config()


# 管理员访问装饰器
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin' not in session:
            return redirect(url_for('admin.admin_login'))
        return f(*args, **kwargs)
    return decorated_function


# 获取用户模型（按需加载）
def get_user_model(username):
    """
    按需加载用户模型，实现LRU缓存策略
    
    参数:
        username: 用户名
        
    返回:
        模型实例或None（如果加载失败）
    """
    
    if not SYSTEM_AVAILABLE:
        return None
    
    # 缓存命中：只锁住字典的读改写（LRU 位置调整），锁内不做 IO。
    # 否则并发线程同时 pop/insert 可能互相覆盖，导致条目丢失或淘汰顺序错乱。
    with state.user_models_lock:
        if username in state.user_models:
            # 将此用户模型移至缓存"最新"位置 (LRU策略)
            model = state.user_models.pop(username)
            state.user_models[username] = model  # 重新添加到字典末尾
            return model
    
    try:
        # 从数据库获取用户信息
        user = mongo.db.users.find_one({'username': username})
        if not user or 'model_path' not in user:
            logger.error(f"未找到用户 {username} 或其模型路径")
            return None
            
        model_path = user['model_path']
        if not os.path.exists(model_path):
            logger.error(f"用户 {username} 的模型文件不存在: {model_path}")
            return None
            
        try:
            # 设置设备
            use_cuda = dynamic_config.get('system', 'use_cuda', True)
            device = torch.device("cuda:0" if torch.cuda.is_available() and use_cuda else "cpu")
            
            # 使用模块化的加载模型函数
            model, metadata = load_model(model_path, device)
            
            if model is None:
                logger.error(f"加载用户 {username} 的模型失败")
                return None
            
            # 设置模型为评估模式
            model.eval()
            
            # 写入缓存：长度检查与插入/淘汰必须原子，
            # 否则并发下"缓存已满"的判断会失效，字典长度可能超出上限。
            # 模型加载本身是重 IO，刻意留在锁外，避免把并发加载串行化。
            with state.user_models_lock:
                # 如果缓存已满，移除最久未使用的模型
                if len(state.user_models) >= state.MAX_CACHED_MODELS:
                    oldest_user = next(iter(state.user_models))
                    del state.user_models[oldest_user]
                    logger.info(f"缓存已满，移除最久未使用的模型: {oldest_user}")

                # 添加到缓存
                state.user_models[username] = model

            logger.info(f"已加载用户 {username} 的模型")
            return model
            
        except Exception as e:
            logger.error(f"加载用户 {username} 的模型失败: {e}")
            return None
            
    except Exception as e:
        logger.error(f"获取用户模型失败: {e}")
        return None


# 初始化系统组件
def init_system():
    try:
        # 检查索引是否存在，不存在则创建
        mongo.db.users.create_index([("username", pymongo.ASCENDING)], unique=True)
        mongo.db.auth_history.create_index([("username", pymongo.ASCENDING), ("timestamp", pymongo.DESCENDING)])
        
        logger.info("系统初始化成功")
        return True
    except Exception as e:
        logger.error(f"初始化系统组件失败: {e}")
        return False


# --- 启动期初始化 -----------------------------------------------------------
# 索引创建必须发生在「进程启动」阶段，而不能留在 __main__ 分支里。
#
# 原因：生产部署由 WSGI 服务器（gunicorn 等）导入模块来获取 app，
# 那时 `if __name__ == '__main__'` 内的代码根本不会执行 ——
# 而 username 的 unique 索引正是当前防止用户名重复的唯一保障。
#
# 失败不阻断启动：数据库暂时不可达时应用仍应能起来，并给出明确告警。
#
# 注意：它由 `create_app()` 调用，而不是在模块导入时执行 ——
# 索引依赖已绑定配置的 mongo 实例（mongo.init_app 发生在工厂里）。
def init_system_on_startup():
    if init_system():
        return
    logger.warning(
        "系统初始化未完成，索引可能尚未创建。请确认 MongoDB 可访问：%s",
        MONGO_URI,
    )
