# -*- coding: utf-8 -*-
"""
管理后台蓝图：登录、参数配置、用户管理

后台的删除类操作是**不可逆**的（同时删掉该用户的认证历史），
因此全部走 POST + CSRF + 管理员会话三重校验，不做 GET 形式的删除入口。
"""

import os

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from web_auth import state
from web_auth.config import (
    ADMIN_PASSWORD_HASH,
    ADMIN_USERNAME,
    logger,
)
from web_auth.core import (
    SYSTEM_AVAILABLE,
    admin_required,
    client_ip,
    dynamic_config,
    load_app_config,
)
from web_auth.extensions import (
    ADMIN_LOGIN_LIMITER,
    clear_session_keep_csrf,
    mongo,
)

bp = Blueprint('admin', __name__)



# 隐藏管理员入口
@bp.route('/manage/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        ip = client_ip()
        if not ADMIN_LOGIN_LIMITER.allow(ip):
            logger.warning("管理员登录尝试过于频繁，已限流: ip=%s", ip)
            flash('尝试过于频繁，请稍后再试')
            return redirect(url_for('admin.admin_login'))

        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''

        # 长度封顶：避免超长口令让口令哈希校验消耗大量 CPU
        if len(username) > 128 or len(password) > 512:
            logger.warning("管理员登录参数异常: ip=%s", ip)
            flash('管理员账号或密码错误')
            return redirect(url_for('admin.admin_login'))

        # 认证开始前先清空会话，避免会话固定（Session Fixation）
        # 同样保留 CSRF 令牌，理由见 login 处的说明。
        clear_session_keep_csrf(session)

        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session['admin'] = True
            logger.info("管理员登录成功: ip=%s username=%s", ip, username)
            return redirect(url_for('admin.admin_dashboard'))

        logger.warning("管理员登录失败: ip=%s username=%r", ip, username)
        flash('管理员账号或密码错误')
        return redirect(url_for('admin.admin_login'))
    
    return render_template('admin_login.html')


# 管理员仪表盘
@bp.route('/manage/dashboard')
@admin_required
def admin_dashboard():
    # 获取用户列表
    users = list(mongo.db.users.find())
    
    # 重新加载最新配置
    state.admin_config = load_app_config()
    
    return render_template('admin_dashboard.html', users=users, config=state.admin_config)


# 修改模型参数
@bp.route('/manage/update_params', methods=['POST'])
@admin_required
def update_params():
    try:
        # 获取更新的区域
        section = request.form.get('section', 'model')
        
        if SYSTEM_AVAILABLE:
            if section == 'model':
                # 更新所有参数（新的统一表单）
                # 模型参数
                model_threshold = float(request.form.get('model_threshold', 0.8))
                alpha = float(request.form.get('alpha', 0.6))
                beta = float(request.form.get('beta', 0.4))
                
                # 验证参数
                verification_time = int(request.form.get('verification_time', 30))
                min_verification_success = int(request.form.get('min_verification_success', 2))
                total_verification_count = int(request.form.get('total_verification_count', 3))
                
                # 设备参数
                connection_timeout = float(request.form.get('device_connection_timeout', 10.0))
                scan_timeout = float(request.form.get('device_scan_timeout', 5.0))
                
                # 训练参数
                epochs = int(request.form.get('training_epochs', 50))
                learning_rate = float(request.form.get('training_learning_rate', 0.001))
                batch_size = int(request.form.get('training_batch_size', 32))
                
                # 系统参数
                use_cuda_str = request.form.get('system_use_cuda', 'true')
                use_cuda = (use_cuda_str.lower() == 'true')
                cuda_device = int(request.form.get('system_cuda_device', 0))
                
                # 批量更新所有参数
                dynamic_config.set('model', 'threshold', model_threshold)
                dynamic_config.set('model', 'alpha', alpha)
                dynamic_config.set('model', 'beta', beta)
                
                dynamic_config.set('verification', 'time', verification_time)
                dynamic_config.set('verification', 'min_success', min_verification_success)
                dynamic_config.set('verification', 'total_count', total_verification_count)
                
                dynamic_config.set('device', 'connection_timeout', connection_timeout)
                dynamic_config.set('device', 'scan_timeout', scan_timeout)
                
                dynamic_config.set('training', 'epochs', epochs)
                dynamic_config.set('training', 'learning_rate', learning_rate)
                dynamic_config.set('training', 'batch_size', batch_size)
                
                dynamic_config.set('system', 'use_cuda', use_cuda)
                dynamic_config.set('system', 'cuda_device', cuda_device)
                
                flash('所有系统参数更新成功')
            
            # 重新加载本地配置
            state.admin_config = load_app_config()
        else:
            # 系统不可用时的处理
            flash('系统模块不可用，参数无法保存')
    except Exception as e:
        logger.error(f"更新参数失败: {e}")
        flash(f'参数更新失败: {str(e)}')
        
    return redirect(url_for('admin.admin_dashboard'))




# 管理员退出
@bp.route('/manage/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('auth.index'))


# 删除用户
@bp.route('/manage/delete_user/<username>', methods=['POST'])
@admin_required
def delete_user(username):
    try:
        # 安全检查：防止删除管理员用户
        if username == ADMIN_USERNAME:
            flash('不能删除管理员用户')
            return redirect(url_for('admin.admin_dashboard'))
        
        # 获取用户信息
        user = mongo.db.users.find_one({'username': username})
        if not user:
            flash(f'用户 {username} 不存在')
            return redirect(url_for('admin.admin_dashboard'))
        
        # 删除用户的模型文件
        if 'model_path' in user and user['model_path']:
            try:
                if os.path.exists(user['model_path']):
                    os.remove(user['model_path'])
                    logger.info(f"已删除用户 {username} 的模型文件: {user['model_path']}")
            except Exception as e:
                logger.warning(f"删除用户 {username} 的模型文件失败: {e}")
        
        # 删除数据库中的用户数据
        # 删除用户基本信息
        mongo.db.users.delete_one({'username': username})
        
        # 删除用户的认证历史记录
        mongo.db.auth_history.delete_many({'username': username})
        
        # 删除用户相关的其他数据（如果有的话）
        # 例如：用户的数据采集记录、验证记录等
        
        # 清理内存中的相关数据
        with state.registration_lock:
            if username in state.current_registration_data:
                del state.current_registration_data[username]
        
        # 清理验证结果
        with state.verification_lock:
            if username in state.verification_results:
                del state.verification_results[username]
        
        logger.info(f"用户 {username} 及其所有相关数据已成功删除")
        flash(f'用户 {username} 已成功删除')
        
    except Exception as e:
        logger.error(f"删除用户 {username} 失败: {e}")
        flash(f'删除用户失败: {str(e)}')
    
    return redirect(url_for('admin.admin_dashboard'))


# 批量删除用户
@bp.route('/manage/batch_delete_users', methods=['POST'])
@admin_required
def batch_delete_users():
    try:
        # 获取要删除的用户名列表
        usernames = request.form.getlist('usernames[]')
        
        if not usernames:
            flash('请选择要删除的用户')
            return redirect(url_for('admin.admin_dashboard'))
        
        # 安全检查：防止删除管理员用户
        if ADMIN_USERNAME in usernames:
            flash('不能删除管理员用户')
            return redirect(url_for('admin.admin_dashboard'))
        
        deleted_count = 0
        failed_count = 0
        
        for username in usernames:
            try:
                # 获取用户信息
                user = mongo.db.users.find_one({'username': username})
                if not user:
                    failed_count += 1
                    continue
                
                # 删除用户的模型文件
                if 'model_path' in user and user['model_path']:
                    try:
                        if os.path.exists(user['model_path']):
                            os.remove(user['model_path'])
                            logger.info(f"已删除用户 {username} 的模型文件: {user['model_path']}")
                    except Exception as e:
                        logger.warning(f"删除用户 {username} 的模型文件失败: {e}")
                
                # 删除数据库中的用户数据
                # 删除用户基本信息
                mongo.db.users.delete_one({'username': username})
                
                # 删除用户的认证历史记录
                mongo.db.auth_history.delete_many({'username': username})
                
                # 清理内存中的相关数据
                with state.registration_lock:
                    if username in state.current_registration_data:
                        del state.current_registration_data[username]
                
                # 清理验证结果
                with state.verification_lock:
                    if username in state.verification_results:
                        del state.verification_results[username]
                
                deleted_count += 1
                logger.info(f"用户 {username} 已成功删除")
                
            except Exception as e:
                logger.error(f"删除用户 {username} 失败: {e}")
                failed_count += 1
        
        # 显示删除结果
        if deleted_count > 0:
            flash(f'成功删除 {deleted_count} 个用户')
        if failed_count > 0:
            flash(f'删除失败 {failed_count} 个用户')
        
        logger.info(f"批量删除完成：成功 {deleted_count} 个，失败 {failed_count} 个")
        
    except Exception as e:
        logger.error(f"批量删除用户失败: {e}")
        flash(f'批量删除失败: {str(e)}')
    
    return redirect(url_for('admin.admin_dashboard'))
