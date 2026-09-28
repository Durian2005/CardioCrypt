# -*- coding: utf-8 -*-
"""
认证相关安全工具

目前提供两项，均刻意不引入 Flask-Limiter / Flask-WTF 等额外依赖，
以保持 requirements 精简、行为可读：

  1. RateLimiter  —— 进程内滑动窗口限流
  2. CSRFProtector —— 会话绑定的 CSRF 令牌校验

⚠️ 部署注意：限流计数只保存在进程内存里，因此
  - 单进程（含 `gunicorn -w 1 --threads N`）部署：严格执行 limit / window；
  - 多 worker 部署：各 worker 独立计数，实际额度约为 limit × worker 数。
  若将来真的需要多 worker，应换用 Redis 等共享存储来做计数。

CSRF 令牌存在 Flask session（已签名的客户端 cookie）里，不依赖进程内存，
因此多 worker 部署下同样有效。
"""

import hmac
import secrets
import threading
import time
from collections import OrderedDict, deque
from typing import Deque, Dict, Optional


class RateLimiter:
    """
    基于时间戳队列的滑动窗口限流器（进程内、线程安全）

    与「固定窗口」相比，滑动窗口不会出现跨窗口边界的双倍突发：
    例如 limit=5 / window=60s 时，任何 60 秒区间内的放行次数都不会超过 5。
    """

    def __init__(self, limit: int, window: float, max_keys: int = 4096) -> None:
        if limit <= 0:
            raise ValueError("limit 必须为正整数")
        if window <= 0:
            raise ValueError("window 必须为正数")
        self.limit = int(limit)
        self.window = float(window)
        self.max_keys = int(max_keys)
        self._hits: "OrderedDict[str, Deque[float]]" = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """
        记录一次尝试，并判断是否放行。

        返回 True  —— 未超限，本次尝试已计入；
        返回 False —— 已达上限，本次尝试**不**计入（不延长封锁时间）。
        """
        now = time.monotonic()
        with self._lock:
            queue = self._hits.get(key)
            if queue is None:
                queue: Deque[float] = deque()
                self._hits[key] = queue
            else:
                self._hits.move_to_end(key)

            # 丢弃窗口外的历史记录
            cutoff = now - self.window
            while queue and queue[0] <= cutoff:
                queue.popleft()

            if len(queue) >= self.limit:
                return False

            queue.append(now)

            # 键数量封顶：避免大量伪造来源把内存撑爆（淘汰最久未使用的键）
            while len(self._hits) > self.max_keys:
                self._hits.popitem(last=False)
            return True

    def retry_after(self, key: str) -> int:
        """距离下一次可尝试还需多少秒；无记录时返回 0。"""
        with self._lock:
            queue = self._hits.get(key)
            if not queue:
                return 0
            elapsed = time.monotonic() - queue[0]
            return max(1, int(self.window - elapsed) + 1)

    def reset(self, key: str) -> None:
        """清空某个键的计数（例如认证成功后）。"""
        with self._lock:
            self._hits.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()

    def stats(self) -> Dict[str, int]:
        """当前被计数的键数量，便于观测。"""
        with self._lock:
            return {"keys": len(self._hits), "limit": self.limit, "window": int(self.window)}


class CSRFProtector:
    """
    会话绑定的 CSRF 令牌校验

    原理：令牌同时存在于两处 —— 服务端会话（Flask session，是**已签名**的
    cookie，JS 读不到、其它站点改不了）与请求本身（header 或表单字段）。
    攻击者站点虽然能让浏览器带着受害者的 cookie 发出请求，但它既读不到
    受害者会话里的令牌，也猜不出来，因此无法构造出一次合法请求。

    几个刻意的设计选择：

    - **不放在 cookie 里也不放在 HTML 里明文回显**：前者会被浏览器自动带上、
      失去鉴别意义；后者对 SPA 无意义（SPA 的 index.html 是静态文件）。
      故由 /api/csrf-token 下发，前端读进内存后放进请求头。
    - **常量时间比较**：用 hmac.compare_digest 而非 `==`，避免逐字节比较
      泄漏令牌前缀的时序侧信道。
    - **令牌在会话轮换时保留**（见 clear_session_keep_csrf）：登录前会
      session.clear() 以防御会话固定，若连令牌一起清掉，清空后的第一次
      提交必然失败 —— 这会让「安全加固」和「可用性」互相打架。
    """

    #: 前端与旧版页面统一使用的请求头名
    HEADER_NAME = 'X-CSRFToken'
    #: 原生表单与 JSON 体里使用的字段名
    FIELD_NAME = 'csrf_token'
    #: 令牌在 session 中的键名
    SESSION_KEY = '_csrf_token'

    #: 这些方法被规范定义为「安全方法」，不改变服务端状态，无需校验
    SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS', 'TRACE'})

    def __init__(self, token_bytes: int = 32) -> None:
        self.token_bytes = int(token_bytes)

    # ------------------------------------------------------------------
    def generate(self) -> str:
        """生成一个新令牌（URL-safe，且为纯 ASCII）。"""
        return secrets.token_urlsafe(self.token_bytes)

    def ensure(self, session) -> str:
        """取出当前会话的令牌；不存在时生成一个并写入会话。"""
        token = session.get(self.SESSION_KEY)
        if not isinstance(token, str) or len(token) < 16:
            token = self.generate()
            session[self.SESSION_KEY] = token
        return token

    def rotate(self, session) -> str:
        """强制换发令牌（例如权限提升后）。"""
        token = self.generate()
        session[self.SESSION_KEY] = token
        return token

    def submitted(self, request) -> str:
        """
        从请求里取出客户端提交的令牌。

        依次尝试：请求头 -> 表单字段 -> JSON 体字段。
        前端与旧版 ajax 走请求头，原生 <form> 走表单字段，
        脚本调用可以走 JSON 体。
        """
        token = request.headers.get(self.HEADER_NAME, '')
        if token:
            return token.strip()

        form = getattr(request, 'form', None)
        if form is not None:
            token = form.get(self.FIELD_NAME, '')
            if token:
                return token.strip()

        if request.is_json:
            body = request.get_json(silent=True)
            if isinstance(body, dict):
                value = body.get(self.FIELD_NAME)
                if isinstance(value, str):
                    return value.strip()

        return ''

    def validate(self, session, request) -> bool:
        """
        判断请求是否通过校验。

        安全方法（GET/HEAD/OPTIONS/TRACE）直接放行；其余要求会话中有令牌、
        且请求携带的令牌与之一致。
        """
        if request.method.upper() in self.SAFE_METHODS:
            return True

        expected = session.get(self.SESSION_KEY)
        if not isinstance(expected, str) or not expected:
            # 会话里没有令牌：拒绝。攻击者若能构造出「无令牌的会话」，
            # 放行就等于没有防护。
            return False

        actual = self.submitted(request)
        if not actual:
            return False

        try:
            return hmac.compare_digest(expected, actual)
        except TypeError:
            # compare_digest 只接受纯 ASCII 字符串；非 ASCII 输入必然不匹配
            return False


def clear_session_keep_csrf(session) -> None:
    """
    清空会话，但保留 CSRF 令牌

    用于「认证前重置会话」的场景：既要清掉上一段身份留下的状态（防会话固定），
    又不能让令牌一起消失 —— 否则紧接着的那次表单提交会因缺令牌被拒。

    只保留令牌这一个键，身份相关键一律清掉。
    """
    token = session.get(CSRFProtector.SESSION_KEY)
    session.clear()
    if token:
        session[CSRFProtector.SESSION_KEY] = token
