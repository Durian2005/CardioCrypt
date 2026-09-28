# -*- coding: utf-8 -*-
"""
应用配置

集中所有「来自环境变量、在进程生命周期内不变」的取值。原先这些散落在
app.py 顶部，配置与视图混在同一屏里；集中之后 `create_app()` 只负责把它们
装到 Flask 上。

约定
----
- 数值型环境变量都做**容错回退**：非法值记一条告警后使用默认值，
  而不是让进程带着 None 崩在某个看不到的地方。
- 默认值一律「安全优先」：调试关闭、只监听本机、管理员口令需要显式覆盖。
"""

import logging
import os
import re
import secrets
from datetime import timedelta

from werkzeug.security import generate_password_hash



# 创建日志目录
logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(logs_dir, exist_ok=True)

# 创建模型目录
models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models')
os.makedirs(models_dir, exist_ok=True)


# 配置日志
# 级别由 LOG_LEVEL 环境变量控制，默认 INFO。
# 不再写死 DEBUG：DEBUG 会连带打印请求体、第三方库内部状态等敏感内容，
# 只应在本机排障时临时开启，例如：LOG_LEVEL=DEBUG
_LOG_LEVEL_NAME = os.environ.get('LOG_LEVEL', 'INFO').strip().upper()

_LOG_LEVEL = getattr(logging, _LOG_LEVEL_NAME, None)

if not isinstance(_LOG_LEVEL, int):
    _LOG_LEVEL = logging.INFO
    _LOG_LEVEL_NAME = 'INFO'


_LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'


# 控制台输出始终保留；设置 LOG_FILE 时额外写入文件并自动轮转。
# 相对路径按 web_auth/logs/ 解析（该目录已加入 .gitignore）。
_log_handlers = [logging.StreamHandler()]

_log_file = os.environ.get('LOG_FILE', '').strip()

if _log_file:
    if not os.path.isabs(_log_file):
        _log_file = os.path.join(logs_dir, _log_file)
    from logging.handlers import RotatingFileHandler
    _log_handlers.append(
        RotatingFileHandler(
            _log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8'
        )
    )


logging.basicConfig(level=_LOG_LEVEL, format=_LOG_FORMAT, handlers=_log_handlers, force=True)


logger = logging.getLogger('web_auth')


# 获取当前文件所在目录
base_dir = os.path.dirname(os.path.abspath(__file__))


# 配置ecgppg_system的日志处理器，避免重复输出
try:
    from ecgppg_system.utils.logger import logger as ecgppg_logger
    # 移除现有的handlers
    for handler in ecgppg_logger.handlers[:]:
        ecgppg_logger.removeHandler(handler)
    # 添加单个处理器
    ecgppg_file_handler = logging.FileHandler(os.path.join(logs_dir, 'ecgppg_system.log'), encoding='utf-8')
    ecgppg_file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    ecgppg_logger.addHandler(ecgppg_file_handler)
except ImportError:
    pass


# 会话密钥
#
# 原先未设置 FLASK_SECRET_KEY 时用 os.urandom(24) 兜底：密钥只存在于当前进程，
# 于是「多 worker 部署」时各进程密钥互不相同 —— Flask 的 session 是签名 cookie，
# 换个 worker 校验就失败，表现为用户登录状态随机丢失，且排查起来毫无线索。
#
# 改为「环境变量优先，缺省时持久化到本地文件」：既保持开箱即用，
# 又让同一份部署的所有进程读到同一个密钥。该文件已在 .gitignore 中忽略。
def _load_or_create_secret_key():
    """返回 (密钥, 是否来自本地文件)。"""
    env_key = os.environ.get('FLASK_SECRET_KEY')
    if env_key:
        return env_key, False

    key_file = os.path.join(base_dir, '.flask_secret_key')
    try:
        if os.path.exists(key_file):
            with open(key_file, 'r', encoding='utf-8') as f:
                stored = f.read().strip()
            if stored:
                return stored, True

        generated = secrets.token_hex(32)
        with open(key_file, 'w', encoding='utf-8') as f:
            f.write(generated)
        try:
            os.chmod(key_file, 0o600)  # Windows 上不生效，POSIX 下收紧到仅属主可读
        except OSError:
            pass
        return generated, True
    except OSError as e:
        # 文件系统只读（如只读容器）时的退路，但必须让使用者知道后果
        logger.warning(
            "无法读写会话密钥文件（%s）；本次使用进程内随机密钥，"
            "多进程部署会导致登录状态随机失效。请显式设置 FLASK_SECRET_KEY。", e
        )
        return secrets.token_hex(32), False


# ---------------------------------------------------------------------------
# 数据库
# ---------------------------------------------------------------------------
MONGO_URI = os.environ.get(
    "MONGO_URI", "mongodb://localhost:27017/ecg_auth_db"
)

# PyMongo 默认的 serverSelectionTimeoutMS 是 30 秒。启动期会建索引
# （见 core.init_system），数据库不可达时会让进程启动白等 30 秒，
# 多 worker 部署下这个代价会被放大。这里给一个更适合本机/内网的默认值。
# 注意：若 MONGO_URI 中已显式指定超时选项，以 URI 为准（PyMongo 既有规则）。
try:
    MONGO_SERVER_SELECTION_TIMEOUT_MS = int(
        os.environ.get('MONGO_SERVER_SELECTION_TIMEOUT_MS', '5000')
    )
except ValueError:
    logger.warning("MONGO_SERVER_SELECTION_TIMEOUT_MS 不是合法整数，回退到 5000")
    MONGO_SERVER_SELECTION_TIMEOUT_MS = 5000

# 会话有效期
PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)

# 请求体大小上限：本应用只接收 JSON 信号数据与普通表单，16MB 足够宽裕。
# 未设限时超大请求体会被整体读入内存，足以拖垮进程。
try:
    MAX_CONTENT_LENGTH = int(
        os.environ.get('MAX_CONTENT_LENGTH', str(16 * 1024 * 1024))
    )
except ValueError:
    logger.warning("MAX_CONTENT_LENGTH 不是合法整数，回退到 16MB")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

# 用户模型缓存上限（LRU 淘汰阈值）
MAX_CACHED_MODELS = 50


# --- 闲置状态回收 -----------------------------------------------------------
# current_registration_data 与 verification_results 原先只在「管理员删除用户」
# 时才被清理：注册中途放弃、采集失败、验证结束后关掉页面，条目都会永久留在
# 内存里 —— 长期运行会持续增长。
#
# 这里补一个基于「闲置时长」的回收：
#   - 每个条目记录最后一次活跃时间（time.monotonic，不受系统时钟调整影响）；
#   - 前端轮询的状态接口会刷新它，所以正在进行的流程不会被误清；
#   - 守护线程按固定间隔扫描，超时条目连同时间戳一起删除。
#
# 默认 TTL 1 小时：正常流程几分钟就结束，留足余量给「用户中途去干别的」。
try:
    STATE_TTL_SECONDS = max(5, int(os.environ.get('STATE_TTL_SECONDS', '3600')))
except ValueError:
    logger.warning("STATE_TTL_SECONDS 不是合法整数，回退到 3600")
    STATE_TTL_SECONDS = 3600


try:
    STATE_CLEANUP_INTERVAL = max(2, int(os.environ.get('STATE_CLEANUP_INTERVAL', '300')))
except ValueError:
    logger.warning("STATE_CLEANUP_INTERVAL 不是合法整数，回退到 300")
    STATE_CLEANUP_INTERVAL = 300


# 管理员相关常量
# 生产部署请通过环境变量覆盖：ADMIN_USERNAME / ADMIN_PASSWORD
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")

ADMIN_PASSWORD_HASH = generate_password_hash(
    os.environ.get("ADMIN_PASSWORD", "admin123")
)  # 默认口令仅供本地开发，部署前务必修改


# --- CSRF 保护 -------------------------------------------------------------
# 所有写操作（POST/PUT/PATCH/DELETE）都必须携带与会话绑定的令牌，
# 否则一律按跨站请求伪造拒绝。GET/HEAD/OPTIONS/TRACE 是规范定义的
# 「安全方法」，不改变服务端状态，天然豁免。
#
# 令牌的获取方式（详见 web_auth/security.py::CSRFProtector）：
#   - SPA：启动时 GET /api/csrf-token，之后放进 X-CSRFToken 请求头
#   - 旧版页面：模板渲染时注入隐藏字段与 meta 标签，ajax 由全局钩子带上
CSRF_ENABLED = os.environ.get('CSRF_ENABLED', '1').strip().lower() not in (
    '0', 'false', 'no', 'off'
)


# 用户名白名单：允许中英文、数字、下划线、点、连字符，并封顶长度。
# 只用来挡掉明显异常的输入（超长串、控制字符等），不额外施加业务限制。
USERNAME_RE = re.compile(r'^[\w.\-]{1,64}$', re.UNICODE)


FRONTEND_MODE = os.environ.get('FRONTEND_MODE', 'spa').lower()

# 会话密钥：环境变量优先，缺省时持久化到本地文件（见 _load_or_create_secret_key）
SECRET_KEY, SECRET_KEY_FROM_FILE = _load_or_create_secret_key()
