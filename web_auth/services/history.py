# -*- coding: utf-8 -*-
"""
认证历史的只读查询

`auth_history` 里一条记录就是「一次认证发生了什么」：谁、什么时候、通过还是
没通过、耗时多少。`stats.py` 只把它聚合成了几个整数，于是明细一直在写、却
没有任何读取方 —— 本模块补的就是这一层。

两条边界
--------

1. **只读。** 本模块不提供删除与修改。删除用户已有独立入口
   （`admin.py::_purge_user`，会连带清掉该用户的历史），查看页不该再开一个
   能毁数据的口子 —— 一个用来"看清楚"的页面，不该同时具备"毁掉"的能力。

2. **查询失败不能吞成空表。** 「查不到记录」和「连不上数据库」是两件事：
   前者是"没有发生认证"，后者是"不知道有没有"。后者返回 `ok=False`，
   由界面显示告警 —— 空表会被读成前者，那是把故障伪装成了事实。
"""

from pymongo import DESCENDING

from web_auth.config import logger
from web_auth.extensions import mongo
from web_auth.services.stats import (
    HISTORY_RESULT_FAILURE,
    HISTORY_RESULT_SUCCESS,
)

# 一页多少条。上限存在的意义是防止 `?page_size=100000` 把整表拉进内存。
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# 只取页面上要显示的字段。`_id` 不取：它对使用者没有意义，
# 也没必要出现在任何导出或截图里。
FIELD_PROJECTION = {
    'username': 1,
    'timestamp': 1,
    'result': 1,
    'duration_ms': 1,
    'demo': 1,
    '_id': 0,
}


def build_query(username=None, result=None, start=None, end=None):
    """
    组装查询条件。

    `start` / `end` 是 `datetime`，闭区间。调用方负责把它们换算成
    "当天 00:00:00" 与 "当天 23:59:59.999999"，本函数不再做日期推断 ——
    时间口径只在一个地方决定，避免两处各有一套理解。
    """
    query = {}
    if username:
        query['username'] = username
    if result in (HISTORY_RESULT_SUCCESS, HISTORY_RESULT_FAILURE):
        query['result'] = result

    time_range = {}
    if start is not None:
        time_range['$gte'] = start
    if end is not None:
        time_range['$lte'] = end
    if time_range:
        query['timestamp'] = time_range

    return query


def query_records(username=None, result=None, start=None, end=None,
                  page=1, page_size=DEFAULT_PAGE_SIZE):
    """
    分页查询认证历史，最新的在前。

    返回一个字典而不是元组：调用方要同时知道「有没有出错」「总共多少条」
    「当前在第几页」，元组会在调用处退化成位置参数，读的人得数数。

    `page` 超出范围时**夹到最后一页**而不是返回空列表 —— 删掉一批记录后
    收藏夹里的旧链接仍应给出内容，而不是一张让人以为数据丢了的空表。
    """
    try:
        page_size = int(page_size)
        page = int(page)
    except (TypeError, ValueError):
        page_size, page = DEFAULT_PAGE_SIZE, 1
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    page = max(1, page)

    query = build_query(username=username, result=result, start=start, end=end)
    collection = mongo.db.auth_history

    try:
        total = collection.count_documents(query)
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        cursor = (
            collection.find(query, FIELD_PROJECTION)
            .sort('timestamp', DESCENDING)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(cursor)
    except Exception as exc:
        # 只记异常类型名给界面用：PyMongo 的异常文本带 `host:port`，
        # 那是部署细节，不该出现在任何页面上。
        logger.error("查询认证历史失败 %s: %s", query, exc)
        return {
            'ok': False,
            'error': type(exc).__name__,
            'records': [],
            'total': 0,
            'page': 1,
            'pages': 1,
            'page_size': page_size,
            'first_index': 0,
            'last_index': 0,
        }

    first_index = (page - 1) * page_size + 1 if total else 0
    last_index = min(page * page_size, total)

    return {
        'ok': True,
        'error': None,
        'records': items,
        'total': total,
        'page': page,
        'pages': pages,
        'page_size': page_size,
        'first_index': first_index,
        'last_index': last_index,
    }


def recent_records(limit=8):
    """后台首页卡片用的最近若干条记录，复用同一套查询与容错。"""
    return query_records(page=1, page_size=limit)
