# -*- coding: utf-8 -*-
"""
健康检查端点：`GET /healthz`

给探针、负载均衡与发布脚本用。检查逻辑在 `services/healthcheck.py`，
本文件只负责把它变成一个 HTTP 响应。

三个刻意的选择
--------------

1. **不放在 `/api/` 下**：它不是业务接口，不参与前端契约，也不该随业务接口
   一起演化。探针只需要一个稳定的 URL 和状态码。
2. **不挂任何鉴权**：探针拿不到会话，也不想拿。因此返回体里不能有敏感信息 ——
   这一点由 `services/healthcheck.py` 保证（只回异常类型名）。
3. **`Cache-Control: no-store`**：探针要的是"此刻"的状态，中间层一旦缓存，
   就会出现"服务已经挂了但监控还在报绿"。

GET 是安全方法，CSRF 校验天然放行，无需额外豁免。
"""

from flask import Blueprint, jsonify

from web_auth.services.healthcheck import collect_health

bp = Blueprint('healthz', __name__)


@bp.route('/healthz', methods=['GET'])
def healthz():
    """返回服务此刻的健康状态：正常 200，依赖异常 503。"""
    payload, status_code = collect_health()
    response = jsonify(payload)
    response.headers['Cache-Control'] = 'no-store'
    return response, status_code
