# -*- coding: utf-8 -*-
"""
认证相关安全工具

目前提供**进程内滑动窗口限流**。刻意不引入 Flask-Limiter 等额外依赖：
本项目当前是单进程部署，进程内计数已经足够，也让 requirements 保持精简。

⚠️ 部署注意：计数只保存在进程内存里，因此
  - 单进程（含 `gunicorn -w 1 --threads N`）部署：严格执行 limit / window；
  - 多 worker 部署：各 worker 独立计数，实际额度约为 limit × worker 数。
  若将来真的需要多 worker，应换用 Redis 等共享存储来做计数。
"""

import threading
import time
from collections import OrderedDict, deque
from typing import Deque, Dict


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
