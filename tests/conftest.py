# -*- coding: utf-8 -*-
"""
pytest 共享夹具

两条硬约束
----------

1. **环境变量必须在导入应用之前设置。**
   `web_auth/app.py` 在模块加载阶段就会读取 `MONGO_URI` / `FLASK_SECRET_KEY` 等，
   并立即创建索引、启动闲置状态回收线程。所以本文件顶部的 `os.environ` 赋值是
   **顺序敏感**的，不能改写成 fixture —— fixture 执行时模块早已导入完毕。

2. **测试库名必须带 `pytest` 字样。**
   测试结束时会把整个库 drop 掉。库名检查是一道保险，避免误删开发库
   （`ecg_auth_db`）或另一个项目的库（`AuthBaselineDb`）。

运行方式::

    venv\\Scripts\\python.exe -m pytest
"""

import importlib
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TEST_DB_NAME = 'ecg_auth_db_pytest'
MONGO_BASE = os.environ.get('PYTEST_MONGO_BASE', 'mongodb://localhost:27017')

# --- 顺序敏感：必须在 import web_auth.app 之前 ---------------------------------
os.environ['MONGO_URI'] = '{}/{}'.format(MONGO_BASE, TEST_DB_NAME)
# 固定密钥：避免测试过程读写 web_auth/.flask_secret_key，也避免随机密钥
# 让「跨客户端会话」类断言失去可重复性。
os.environ['FLASK_SECRET_KEY'] = 'pytest-secret-key-not-for-production'
os.environ['ADMIN_USERNAME'] = 'pytest_admin'
os.environ['ADMIN_PASSWORD'] = 'pytest-admin-pw'
os.environ['LOG_LEVEL'] = 'WARNING'
os.environ['CSRF_ENABLED'] = '1'
os.environ['MAX_CONTENT_LENGTH'] = str(16 * 1024 * 1024)
os.environ['MONGO_SERVER_SELECTION_TIMEOUT_MS'] = '3000'
# 回收线程在测试里没有实际用途，把间隔拉到最大，减少干扰
os.environ['STATE_TTL_SECONDS'] = '3600'
os.environ['STATE_CLEANUP_INTERVAL'] = '3600'
# 默认走 classic：用例要断言端点的真实行为，不应依赖前端构建产物是否存在。
# SPA 适配层注册的 JSON 接口与模式无关，test_spa.py 直接覆盖它们。
os.environ['FRONTEND_MODE'] = 'classic'
# 演示模式显式关闭：测试必须跑在「采集不到数据即判失败」的默认语义下。
# test_demo_mode.py 用 monkeypatch 单独打开它来验证演示路径。
os.environ['DEMO_MODE'] = '0'
# 绘图模块在无显示环境下必须走 Agg，否则 import 阶段就会失败
os.environ['MPLBACKEND'] = 'Agg'

import pytest  # noqa: E402  （必须在环境变量之后）

# 拆分蓝图前，共享状态挂在 web_auth.app 下；拆分后挪到 web_auth.state。
# 两个位置都找一遍，让这套测试在重构前后都能运行 —— 这正是它的价值所在。
_STATE_HOST_CANDIDATES = (
    'web_auth.state',
    'web_auth.extensions',
    'web_auth.app',
)
_DICT_STATES = ('current_registration_data', 'verification_results', 'user_models')
_SCALAR_STATES = ('ble_device_client', 'ble_device_address', 'ble_device_name',
                  'ble_device_session_id')
_LIMITERS = ('LOGIN_LIMITER', 'ADMIN_LOGIN_LIMITER', 'VERIFY_START_LIMITER')


def _state_hosts():
    """返回所有可能持有共享状态的模块（去重、保序）。"""
    hosts = []
    for name in _STATE_HOST_CANDIDATES:
        try:
            module = importlib.import_module(name)
        except ImportError:
            continue
        if module not in hosts:
            hosts.append(module)
    return hosts


def clear_shared_state():
    """
    重置进程内共享状态。

    应用是模块级单例，用例之间共享同一份内存态，必须显式清空，
    否则「上一个用例注册的 username」会漏到下一个用例里。
    """
    for host in _state_hosts():
        for name in _DICT_STATES:
            obj = getattr(host, name, None)
            if isinstance(obj, dict):
                obj.clear()
        buckets = getattr(host, '_state_last_active', None)
        if isinstance(buckets, dict):
            for inner in buckets.values():
                if isinstance(inner, dict):
                    inner.clear()
        for name in _SCALAR_STATES:
            if hasattr(host, name):
                setattr(host, name, None)
        for name in _LIMITERS:
            limiter = getattr(host, name, None)
            if limiter is not None and hasattr(limiter, 'clear'):
                limiter.clear()


# ============================================================================
# 一、数据库
# ============================================================================
@pytest.fixture(scope='session')
def mongodb_available():
    """MongoDB 不可达时跳过整个测试会话，而不是抛一堆连接错误。"""
    from pymongo import MongoClient

    client = MongoClient(MONGO_BASE, serverSelectionTimeoutMS=3000)
    try:
        client.admin.command('ping')
    except Exception as exc:  # pragma: no cover - 取决于本机环境
        pytest.skip('MongoDB 不可达（{}）：{}'.format(MONGO_BASE, exc))
    finally:
        client.close()


@pytest.fixture(scope='session', autouse=True)
def test_database(mongodb_available):
    """会话结束时清掉整个临时测试库。"""
    assert 'pytest' in TEST_DB_NAME, '安全保护：拒绝操作非测试库 {}'.format(TEST_DB_NAME)

    from pymongo import MongoClient

    client = MongoClient(MONGO_BASE, serverSelectionTimeoutMS=3000)
    client.drop_database(TEST_DB_NAME)  # 从干净状态开始
    client.close()

    yield TEST_DB_NAME

    client = MongoClient(MONGO_BASE, serverSelectionTimeoutMS=3000)
    client.drop_database(TEST_DB_NAME)
    client.close()


@pytest.fixture()
def db(test_database):
    """测试库句柄；用例内可直接读写 users / auth_history。"""
    from pymongo import MongoClient

    client = MongoClient(MONGO_BASE, serverSelectionTimeoutMS=3000)
    database = client[TEST_DB_NAME]
    database.users.delete_many({})
    database.auth_history.delete_many({})
    yield database
    database.users.delete_many({})
    database.auth_history.delete_many({})
    client.close()


# ============================================================================
# 二、应用与客户端
# ============================================================================
@pytest.fixture(scope='session')
def app_module(test_database):
    """被测应用模块（模块级单例）。"""
    import web_auth.app as module

    return module


@pytest.fixture(scope='session')
def flask_app(app_module):
    app = app_module.app
    # TESTING 让异常直接抛出，避免落进一堆「500 但看不出原因」的断言
    app.config.update(TESTING=True)
    return app


@pytest.fixture()
def client(flask_app):
    with flask_app.test_client() as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def reset_shared_state(flask_app):
    """每个用例前后都重置共享状态，保证用例相互独立。"""
    clear_shared_state()
    yield
    clear_shared_state()


# ============================================================================
# 三、CSRF
# ============================================================================
@pytest.fixture()
def csrf_token(client):
    """取当前会话的 CSRF 令牌（写操作必须携带）。"""
    resp = client.get('/api/csrf-token')
    assert resp.status_code == 200, '获取 CSRF 令牌失败：{}'.format(resp.status_code)
    payload = resp.get_json()
    assert payload and payload.get('enabled'), '测试环境应启用 CSRF：{}'.format(payload)
    return payload['token']


# ============================================================================
# 四、常用数据
# ============================================================================
@pytest.fixture()
def existing_user(db):
    """在测试库中写入一个已注册用户（不含模型文件）。"""
    db.users.insert_one({
        'username': 'probe_user',
        'created_at': None,
        'model_path': None,
    })
    return 'probe_user'


@pytest.fixture()
def admin_client_flask_app(flask_app):
    """管理员相关的配置快照，供用例断言使用。"""
    return {
        'username': os.environ['ADMIN_USERNAME'],
        'password': os.environ['ADMIN_PASSWORD'],
    }
