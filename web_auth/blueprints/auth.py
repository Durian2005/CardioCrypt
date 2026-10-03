# -*- coding: utf-8 -*-
"""
认证蓝图：首页、注册、登录、验证、登出

这里是整条认证链路的入口，也是安全加固最密集的地方：
认证前清空会话（防会话固定）、失败提示统一措辞（防用户名枚举）、
登录与验证启动都有限流、所有写操作都过 CSRF 校验。
"""

import threading
from datetime import datetime

import numpy as np
from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from web_auth import state
from web_auth.config import USERNAME_RE, logger
from web_auth.core import (
    SYSTEM_AVAILABLE,
    authenticate_single_signal,
    client_ip,
    get_user_model,
    load_app_config,
)
from web_auth.extensions import (
    LOGIN_LIMITER,
    VERIFY_START_LIMITER,
    clear_session_keep_csrf,
    mongo,
)
from web_auth.services.collection import (
    SERIAL_VERIFICATION_SECONDS,
    CollectionAborted,
    collect_via_ble,
    collect_via_serial,
    top_up_or_abort,
)

bp = Blueprint('auth', __name__)


# ============================================================================
# 验证结果的「终态」
# ============================================================================
# 出现其中任何一个，本次验证就已经有结论，`/api/verification_status` 应当立即
# 结束轮询并如实返回，而不是继续回答「进行中」。
#
# 注意 device_error 也在其中：设备中途断开时写入的就是它。它既不是 success，
# 也不是 failed/error —— 判定表若只列后三者，它会一路落到函数末尾的「仍在进行中」
# 分支，使接口**永远**返回 {'status': 'verifying'}，调用方因此既不失败也不超时。
#
# 新增任何「有结论」的状态时，只改这一处即可。
TERMINAL_VERIFICATION_STATUSES = frozenset({
    'success',
    'failed',
    'error',
    'device_error',
})


# ============================================================================
# 采集降级的统一出口
# ============================================================================
# 采集链路里有若干条「拿不到真实数据」的分支：设备没连上、特征不支持通知、
# 采到的点数不够、串口抛异常。这些分支原来各自直接生成一段合成信号继续往下走，
# 于是「没采到数据」和「采到了数据」在结果上没有任何区别 —— 不接设备点验证，
# 也能得到一次「验证成功」。
#
# 现在把这件事收口到 web_auth/demo.py：**默认不允许模拟**，采集不到就如实失败；
# 只有显式打开 DEMO_MODE 才允许用合成信号把流程走完，且每一次降级都留痕。
#
# 注意这里改的是「数据从哪来」，不是「判定怎么下」—— 合成信号照样要过模型
# 比对，照样可能不通过。判定结论的唯一来源始终是算法输出。


# 路由: 首页
@bp.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('dashboard.dashboard'))
    return render_template('index.html')


# 路由: 注册页面
@bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        
        # 检查用户名是否已存在
        existing_user = mongo.db.users.find_one({'username': username})
        if existing_user:
            flash('用户名已存在')
            return redirect(url_for('auth.register'))
        
        # 初始化注册流程
        with state.registration_lock:
            state.current_registration_data[username] = {
                'status': 'pending',
                'data': [],
                'verification_count': 0,
                'verification_success': 0,
                'model_path': None
            }
        state.touch_state('registration', username)

        # 重定向到数据采集页面
        return redirect(url_for('auth.collect_data', username=username))
    
    return render_template('register.html')


# 路由: 数据采集页面
@bp.route('/collect_data/<username>')
def collect_data(username):
    if username not in state.current_registration_data:
        flash('注册会话已过期，请重新开始')
        return redirect(url_for('auth.register'))
    
    # 动态加载最新配置
    state.admin_config = load_app_config()
    
    return render_template('collect_data.html', username=username)


# API: 获取注册状态
@bp.route('/api/registration_status/<username>', methods=['GET'])
def registration_status(username):
    if username not in state.current_registration_data:
        return jsonify({'success': False, 'error': '无效的注册会话'})

    # 采集页会持续轮询本接口：刷新活跃时间，使进行中的流程不被闲置回收
    state.touch_state('registration', username)

    with state.registration_lock:
        status_data = state.current_registration_data[username].copy()
    
    # 移除不需要发送给前端的数据
    if 'data' in status_data:
        del status_data['data']
    
    return jsonify({
        'success': True,
        'status': status_data
    })


# 路由: 登录页面
@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        ip = client_ip()
        if not LOGIN_LIMITER.allow(ip):
            logger.warning("登录尝试过于频繁，已限流: ip=%s", ip)
            flash('尝试过于频繁，请稍后再试')
            return redirect(url_for('auth.login'))

        # 认证开始前先清空会话，避免会话固定（Session Fixation）：
        # 一定要在写入本次登录状态之前重置。
        # 保留 CSRF 令牌 —— 它不属于身份状态，一并清掉会让紧随其后的
        # 下一次提交因缺令牌被拒（详见 security.clear_session_keep_csrf）。
        clear_session_keep_csrf(session)

        username = (request.form.get('username') or '').strip()
        if not USERNAME_RE.match(username):
            flash('用户名或验证信息无效')
            return redirect(url_for('auth.login'))

        # 检查用户是否存在
        # 注意：对外不区分「用户不存在」与「其它失败」，避免用户名枚举
        user = mongo.db.users.find_one({'username': username})
        if not user:
            flash('用户名或验证信息无效')
            return redirect(url_for('auth.login'))

        # 重定向到验证页面
        session['pending_login'] = username
        return redirect(url_for('auth.verify'))
    
    return render_template('login.html')


# 路由: 验证页面
@bp.route('/verify')
def verify():
    if 'pending_login' not in session:
        return redirect(url_for('auth.login'))
    
    username = session['pending_login']
    return render_template('verify.html', username=username)


# API: 开始验证
@bp.route('/api/start_verification', methods=['POST'])
def start_verification():
    if 'pending_login' not in session:
        return jsonify({'success': False, 'error': '无效的登录会话'})

    ip = client_ip()
    if not VERIFY_START_LIMITER.allow(ip):
        logger.warning("发起验证过于频繁，已限流: ip=%s", ip)
        return jsonify({'success': False, 'error': '操作过于频繁，请稍后再试'}), 429

    username = session['pending_login']
    
    # 获取已连接的设备信息（如果存在）并保存到线程安全的变量中
    device_info = session.get('connected_device', None)
    
    # 初始化验证结果为"进行中"
    with state.verification_lock:
        state.verification_results[username] = {
            'status': 'verifying',
            'timestamp': datetime.now()
        }
    state.touch_state('verification', username)
    
    # 启动验证线程
    def verify_thread(username, device_info):
        try:
            # 获取全局函数引用
            
            # 开始验证过程
            logger.info(f"开始为用户 {username} 验证身份")
            
            # 初始化验证数据结构（如果不存在）
            with state.verification_lock:
                if username not in state.verification_results:
                    state.verification_results[username] = {
                        'status': 'verifying',
                        'timestamp': datetime.now()
                    }
            state.touch_state('verification', username)
            
                        # 本次验证中所有「采集降级」的原因，随结果一起透出给前端
            demo_reasons = []
            
            def fail(reason, status='failed'):
                """把本次验证定格为失败并写明原因。"""
                with state.verification_lock:
                    state.verification_results[username] = {
                        'status': status,
                        'timestamp': datetime.now(),
                        'error_message': reason,
                    }
                state.touch_state('verification', username)
            
            def finish(success, score=None):
                """
                把本次验证定格为最终结论。演示模式下降级过的，
                附上标记与原因，避免前端把合成信号的结果当成真实比对。
                """
                with state.verification_lock:
                    entry = {
                        'status': 'success' if success else 'failed',
                        'timestamp': datetime.now(),
                    }
                    if score is not None:
                        entry['score'] = float(score)
                    if demo_reasons:
                        entry['demo'] = True
                        entry['demo_reasons'] = list(demo_reasons)
                    state.verification_results[username] = entry
                state.touch_state('verification', username)
            
            # 检查设备类型
            device_type = device_info.get('type', 'ble') if device_info else 'ble'
            
            # 获取用户模型
            if SYSTEM_AVAILABLE:
                # 使用按需加载获取模型
                model = get_user_model(username)
                
                if model is None:
                    # 用户没走完注册采集（库里没有对应模型文件），压根没有可比对的
                    # 参照物。这既不是「比对不通过」，也没有任何依据可以放行 ——
                    # 一律按错误处理，让用户重新完成注册采集。
                    fail(
                        '用户模型不可用：未完成注册采集或模型文件缺失',
                        status='error',
                    )
                    logger.error("验证中止：用户 %s 的模型不可用，需重新完成注册采集", username)
                    return
                else:
                    # 采集验证数据 —— BLE 与串口两条路径都收口在 services/collection.py
                    collected_data = []

                    def mark_device_error(reason):
                        """
                        设备中途断开。这与「没采到数据」不是一回事：前者是连上了又被
                        拔掉，后者可能只是设备没响应。单独记一档状态，前端据此区分。
                        """
                        with state.verification_lock:
                            entry = state.verification_results.setdefault(username, {})
                            entry['status'] = 'device_error'
                            entry['error_message'] = reason
                        state.touch_state('verification', username)

                    try:
                        if device_type == 'serial':
                            outcome = collect_via_serial(
                                seconds=SERIAL_VERIFICATION_SECONDS,
                                label='验证',
                            )
                        else:
                            outcome = collect_via_ble(
                                label='验证',
                                on_device_error=mark_device_error,
                            )
                        # 数据不够就中止（演示模式除外）—— 这是整条链路最后一道
                        # 「补齐」出口，见 collection.py::top_up_or_abort。
                        # 注意顺序：降级原因由 top_up_or_abort 追加进同一个列表，
                        # 必须在它之后再收集，否则「补过数据」不会随结果透出。
                        outcome = top_up_or_abort(outcome, label='验证')
                        demo_reasons.extend(outcome.demo_reasons)
                        collected_data = outcome.points
                    except CollectionAborted as exc:
                        fail(exc.reason, status=exc.status)
                        return
                    
                    # 如果成功采集到数据，则进行验证
                    if len(collected_data) > 0:
                        logger.info(f"验证：使用 {len(collected_data)} 个数据点进行身份验证")
                        
                        # 处理采集到的数据，用于验证
                        try:
                            # 确保collected_data中的每个元素都是数组
                            all_signals = []
                            for signal in collected_data:
                                if len(signal.shape) >= 1:  # 确认是数组而非标量
                                    all_signals.append(signal)
                            
                            # 只有当有有效数据时才处理
                            if all_signals:
                                # 拼接所有采集的信号
                                signal_data = np.concatenate(all_signals)
                                
                                # 将其转换为模型可接受的格式
                                if SYSTEM_AVAILABLE:
                                    # 设置序列长度为600
                                    sequence_length = 600
                                    
                                    # 确保数据长度适合模型输入
                                    data_length = len(signal_data)
                                    if data_length < sequence_length:
                                        # 填充
                                        padded_data = np.zeros(sequence_length)
                                        padded_data[:data_length] = signal_data
                                        signal_data = padded_data
                                    else:
                                        # 截断
                                        signal_data = signal_data[:sequence_length]
                                    
                                    # 重塑为模型需要的形状 [1, sequence_length, 1]
                                    signal_data = signal_data.reshape(1, sequence_length, 1)
                                    
                                    # 调用身份验证函数
                                    auth_result = authenticate_single_signal(model, signal_data, threshold=state.admin_config['model_threshold'])
                                    
                                    # 判定结论只来自算法输出，这里不做任何改写
                                    passed = bool(auth_result['authenticated'])
                                    finish(passed, score=auth_result['score'])
                                    logger.info(
                                        "用户 %s 验证%s，得分: %.4f",
                                        username, '成功' if passed else '失败', auth_result['score'],
                                    )
                                else:
                                    # 算法层不可用（导入失败），没有比对能力，
                                    # 也就没有任何依据可以判定通过。
                                    fail('算法层不可用，无法进行特征比对', status='error')
                                    return
                            else:
                                # 采集到的数据全都不是有效数组
                                fail('采集到的信号无效，无法完成身份验证')
                                return
                        except Exception as process_error:
                            logger.error(f"验证数据处理错误: {str(process_error)}")
                            fail('验证数据处理异常: %s' % process_error, status='error')
                            return
                    else:
                        # 走到这里说明 collected_data 仍为空：
                        # 演示模式关闭时上面已经 return，只有异常路径会落到这。
                        fail('未采集到可用于验证的信号数据')
            else:
                # 算法层不可用（导入失败），没有比对能力
                fail('算法层不可用，无法进行特征比对', status='error')
                
        except Exception as e:
            logger.error(f"验证线程错误: {e}")
            # 更新验证结果
            with state.verification_lock:
                state.verification_results[username] = {
                    'status': 'error',
                    'timestamp': datetime.now(),
                    'error': str(e)
                }
            state.touch_state('verification', username)
    
    # 启动验证线程，传入设备信息
    thread = threading.Thread(target=verify_thread, args=(username, device_info), daemon=True)
    thread.start()
    
    return jsonify({'success': True})


# API: 获取验证状态
@bp.route('/api/verification_status', methods=['GET'])
def verification_status():
    if 'pending_login' not in session:
        return jsonify({'success': False, 'error': '无效的登录会话'})
    
    username = session['pending_login']

    # 验证页会持续轮询本接口：刷新活跃时间，使进行中的验证不被闲置回收
    state.touch_state('verification', username)

    # 确保使用最新配置
    state.admin_config = load_app_config()
    
    # 检查是否已登录成功
    if 'username' in session:
        return jsonify({
            'success': True,
            'status': 'completed',
            'redirect': url_for('dashboard.dashboard')
        })
    
    # 检查验证结果字典
    with state.verification_lock:
        if username in state.verification_results:
            # 获取原始验证结果
            result = state.verification_results[username].copy()
            
            # 检查是否处于状态已确定阶段（成功或失败）
            if result['status'] in TERMINAL_VERIFICATION_STATUSES:
                # 认证结果以真实比对结果为准，不做任何改写
                demo = bool(result.get('demo'))
                
                if result['status'] == 'success':
                    # 设置登录会话
                    session.permanent = True
                    session['username'] = username
                    session.pop('pending_login', None)
                    state.verification_results.pop(username, None)
                    
                    payload = {
                        'success': True,
                        'status': 'completed',
                        'redirect': url_for('dashboard.dashboard')
                    }
                    if demo:
                        # 演示模式下本次用了合成信号，如实告知前端
                        payload['demo'] = True
                    return jsonify(payload)
                    
                elif result['status'] in TERMINAL_VERIFICATION_STATUSES:
                    # 除 success 外的终态按失败处理：failed / error / device_error。
                    # 返回给调用方时统一为 'failed'，原因写在 reason 里 ——
                    # 设备断开与判定不通过对用户是两件事，但都不该被当成"已完成"。
                    reason = result.get('error_message')
                    # 清除登录会话与验证结果
                    session.pop('pending_login', None)
                    state.verification_results.pop(username, None)
                    
                    payload = {
                        'success': True,
                        'status': 'failed',
                        'redirect': url_for('auth.login')
                    }
                    if reason:
                        payload['reason'] = reason
                    if demo:
                        payload['demo'] = True
                    return jsonify(payload)
            else:
                # 验证仍在进行中
                return jsonify({
                    'success': True,
                    'status': 'verifying'
                })
    
    # 仍在验证中
    return jsonify({
        'success': True,
        'status': 'verifying'
    })


# 路由: 退出登录
@bp.route('/logout')
def logout():
    # 与 /api/logout_json 保持一致：除了已认证身份，登录中的「待认证」状态
    # 也要一起清掉。否则登出后仍能回到 /verify 页面（该页面只检查 pending_login），
    # 留下一段谁也不该看到的状态。
    session.pop('username', None)
    session.pop('pending_login', None)
    return redirect(url_for('auth.index'))
