# -*- coding: utf-8 -*-
"""
测试辅助函数

集中处理「写请求必须携带 CSRF 令牌」这件事：项目的 CSRF 保护默认开启，
业务码里因此需要一个统一的提交入口，否则每个用例都要重复拼请求头。
"""


def json_post(client, url, payload=None, token=None, **kwargs):
    """以 JSON 体提交写请求，可选携带 CSRF 令牌（请求头方式）。"""
    headers = {'X-CSRFToken': token} if token else {}
    return client.post(url, json=payload if payload is not None else {},
                       headers=headers, **kwargs)


def json_get(client, url, token=None, **kwargs):
    """GET 请求。GET 是安全方法，CSRF 校验天然放行。"""
    headers = {'X-CSRFToken': token} if token else {}
    return client.get(url, headers=headers, **kwargs)


def form_post(client, url, data=None, token=None, **kwargs):
    """以表单方式提交（模拟旧版 Jinja2 原生 <form>），令牌走隐藏字段。"""
    body = dict(data or {})
    if token:
        body['csrf_token'] = token
    return client.post(url, data=body, **kwargs)


def response_json(resp):
    """读取响应 JSON；非 JSON 时给出可读的失败信息，便于定位。"""
    payload = resp.get_json(silent=True)
    assert payload is not None, (
        f'期望 JSON 响应，实际 status={resp.status_code} '
        f'content-type={resp.headers.get("Content-Type")} '
        f'body={resp.get_data(as_text=True)[:200]!r}'
    )
    return payload
