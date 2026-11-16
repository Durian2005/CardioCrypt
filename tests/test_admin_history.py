# -*- coding: utf-8 -*-
"""
认证历史查看页（只读）

这组用例守三件事：

1. **权限**：未登录不能看。审计数据比业务数据更敏感，不能靠"路径不好猜"。
2. **口径**：筛选、分页、排序与「当天」的边界必须和写入侧一致 ——
   日期差一天、边界差一微秒，审计结论就是另一回事了。
3. **不撒谎**：查询失败要显示告警，而不是画一张空表。空表会被读成
   「没有发生过认证」，那是把故障伪装成事实。
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.helpers import form_post

PAGE = '/manage/auth_history'


# ============================================================================
# 辅助
# ============================================================================
def _login_admin(client, csrf_token, credentials):
    return form_post(
        client, '/manage/login',
        {'username': credentials['username'], 'password': credentials['password']},
        csrf_token,
    )


@pytest.fixture()
def admin_logged_in(client, csrf_token, admin_client_flask_app):
    """已登录管理员的客户端。"""
    _login_admin(client, csrf_token, admin_client_flask_app)
    assert client.get('/manage/dashboard').status_code == 200
    return client


def _seed(db, count, result='success', prefix='u', base=None, step_minutes=1):
    """
    按固定间隔写入若干条记录，返回写入的 (username, timestamp) 列表。

    时间刻意用固定值而不是 `now()`：用例要断言"当天边界"，依赖当前时间
    会让它在某些时刻莫名失败。
    """
    start = base or datetime(2026, 3, 2, 9, 0, 0)
    docs = []
    for index in range(count):
        docs.append({
            'username': '{}{:02d}'.format(prefix, index),
            'timestamp': start + timedelta(minutes=index * step_minutes),
            'result': result,
            'duration_ms': 100 + index,
        })
    db.auth_history.insert_many(docs)
    return [(doc['username'], doc['timestamp']) for doc in docs]


def _text(resp):
    assert resp.status_code == 200, resp.status_code
    return resp.get_data(as_text=True)


# ============================================================================
# 一、权限
# ============================================================================
class TestAccessControl:
    def test_requires_login(self, client):
        resp = client.get(PAGE)
        assert resp.status_code == 302
        assert '/manage/login' in resp.headers['Location']

    def test_requires_login_even_with_filters(self, client):
        resp = client.get(PAGE + '?username=probe&result=success')
        assert resp.status_code == 302
        assert '/manage/login' in resp.headers['Location']

    def test_does_not_leak_records_to_anonymous(self, client, db):
        _seed(db, 1)
        body = client.get(PAGE, follow_redirects=True).get_data(as_text=True)
        assert 'u00' not in body


# ============================================================================
# 二、列表与空态
# ============================================================================
class TestListing:
    def test_empty_state_says_no_records(self, admin_logged_in):
        body = _text(admin_logged_in.get(PAGE))
        assert '还没有任何认证记录' in body
        assert '共 <strong>0</strong> 条记录' in body

    def test_lists_records_newest_first(self, admin_logged_in, db):
        _seed(db, 3)
        body = _text(admin_logged_in.get(PAGE))
        # 时间递增写入，最新的是 u02，页面必须按倒序排
        assert body.index('u02') < body.index('u01') < body.index('u00')

    def test_total_is_reported(self, admin_logged_in, db):
        _seed(db, 7)
        body = _text(admin_logged_in.get(PAGE))
        assert '共 <strong>7</strong> 条记录' in body

    def test_missing_duration_renders_placeholder(self, admin_logged_in, db):
        db.auth_history.insert_one({
            'username': 'no_duration',
            'timestamp': datetime(2026, 3, 2, 10, 0, 0),
            'result': 'success',
        })
        body = _text(admin_logged_in.get(PAGE))
        assert 'no_duration' in body

    def test_demo_record_is_labeled(self, admin_logged_in, db):
        db.auth_history.insert_one({
            'username': 'demo_user',
            'timestamp': datetime(2026, 3, 2, 10, 0, 0),
            'result': 'success',
            'demo': True,
        })
        body = _text(admin_logged_in.get(PAGE))
        assert '演示数据' in body


# ============================================================================
# 三、筛选
# ============================================================================
class TestFilters:
    def test_filter_by_result(self, admin_logged_in, db):
        _seed(db, 2, result='success', prefix='ok')
        _seed(db, 3, result='failure', prefix='bad',
              base=datetime(2026, 3, 2, 12, 0, 0))
        body = _text(admin_logged_in.get(PAGE + '?result=failure'))
        assert '共 <strong>3</strong> 条记录' in body
        assert 'ok00' not in body
        assert 'bad02' in body

    def test_filter_by_username(self, admin_logged_in, db):
        _seed(db, 2, prefix='alice')
        _seed(db, 2, prefix='bob', base=datetime(2026, 3, 2, 13, 0, 0))
        body = _text(admin_logged_in.get(PAGE + '?username=alice01'))
        assert '共 <strong>1</strong> 条记录' in body
        assert 'bob00' not in body

    def test_unknown_result_value_is_ignored(self, admin_logged_in, db):
        _seed(db, 2, result='success')
        _seed(db, 1, result='failure', prefix='bad',
              base=datetime(2026, 3, 2, 15, 0, 0))
        body = _text(admin_logged_in.get(PAGE + '?result=whatever'))
        # 非法取值按「不筛选」处理，而不是返回一张空表
        assert '共 <strong>3</strong> 条记录' in body

    def test_date_range_covers_the_whole_day(self, admin_logged_in, db):
        """当天 23:59:59.5 的记录必须算在当天内 —— 记录本身带微秒。"""
        db.auth_history.insert_one({
            'username': 'late_night',
            'timestamp': datetime(2026, 3, 2, 23, 59, 59, 500000),
            'result': 'success',
        })
        db.auth_history.insert_one({
            'username': 'next_day',
            'timestamp': datetime(2026, 3, 3, 0, 0, 0),
            'result': 'success',
        })
        body = _text(admin_logged_in.get(PAGE + '?start=2026-03-02&end=2026-03-02'))
        assert 'late_night' in body
        assert 'next_day' not in body

    def test_invalid_date_shows_warning(self, admin_logged_in, db):
        _seed(db, 1)
        body = _text(admin_logged_in.get(PAGE + '?start=2026-13-99'))
        assert '日期格式无效' in body
        # 无效条件被忽略，原有记录仍应显示，而不是整页空掉
        assert 'u00' in body

    def test_reversed_range_shows_warning_and_is_ignored(self, admin_logged_in, db):
        _seed(db, 1)
        body = _text(admin_logged_in.get(PAGE + '?start=2026-03-05&end=2026-03-01'))
        assert '开始日期晚于结束日期' in body
        assert 'u00' in body

    def test_no_match_reports_empty_filter_result(self, admin_logged_in, db):
        _seed(db, 1)
        body = _text(admin_logged_in.get(PAGE + '?username=nobody'))
        assert '没有符合筛选条件的记录' in body


# ============================================================================
# 四、分页
# ============================================================================
class TestPagination:
    def test_pages_split_the_records(self, admin_logged_in, db):
        _seed(db, 25)
        first = _text(admin_logged_in.get(PAGE))
        second = _text(admin_logged_in.get(PAGE + '?page=2'))

        assert '共 <strong>25</strong> 条记录' in first
        assert '当前显示第 1–20 条' in first
        assert 'u24' in first and 'u00' not in first
        assert '当前显示第 21–25 条' in second
        assert 'u00' in second and 'u24' not in second

    def test_page_out_of_range_clamps_to_last(self, admin_logged_in, db):
        """删过数据后旧链接仍应给出内容，而不是一张看起来像丢数据的空表。"""
        _seed(db, 25)
        body = _text(admin_logged_in.get(PAGE + '?page=999'))
        assert '当前显示第 21–25 条' in body
        assert 'u00' in body

    def test_non_numeric_page_is_ignored(self, admin_logged_in, db):
        _seed(db, 3)
        body = _text(admin_logged_in.get(PAGE + '?page=abc'))
        assert '共 <strong>3</strong> 条记录' in body

    def test_filters_survive_pagination(self, admin_logged_in, db):
        """翻页链接必须带回筛选条件，否则第二页会悄悄变成全量。"""
        _seed(db, 22, result='failure', prefix='bad')
        body = _text(admin_logged_in.get(PAGE + '?result=failure'))
        assert 'result=failure' in body
        assert 'page=2' in body


# ============================================================================
# 五、只读与容错
# ============================================================================
class TestReadOnlyAndFailures:
    def test_viewing_writes_nothing(self, admin_logged_in, db):
        _seed(db, 3)
        before = db.auth_history.count_documents({})
        for _ in range(3):
            admin_logged_in.get(PAGE)
            admin_logged_in.get(PAGE + '?result=success&page=1')
        assert db.auth_history.count_documents({}) == before

    def test_service_reports_failure_instead_of_empty(self, monkeypatch):
        """连不上数据库与"没有记录"必须能区分开。"""

        class Broken:
            def count_documents(self, query):
                # 用 RFC 5737 的文档保留地址，不用真实内网网段：
                # 这里要验的是"连接串不进界面"，不需要一个真实可路由的地址。
                raise RuntimeError('mongodb://192.0.2.10:27017 connection refused')

        from web_auth.services import history

        monkeypatch.setattr(
            history, 'mongo',
            SimpleNamespace(db=SimpleNamespace(auth_history=Broken())),
        )
        result = history.query_records()

        assert result['ok'] is False
        assert result['records'] == []
        # 只回异常类型名：连接串与主机端口不能出现在界面上
        assert result['error'] == 'RuntimeError'
        assert 'mongodb' not in result['error']
        assert '192.0.2.10' not in result['error']

    def test_page_renders_alert_when_query_fails(self, admin_logged_in, monkeypatch):
        from web_auth.blueprints import admin as admin_module

        monkeypatch.setattr(
            admin_module.history, 'query_records',
            lambda **kwargs: {
                'ok': False, 'error': 'ServerSelectionTimeoutError',
                'records': [], 'total': 0, 'page': 1, 'pages': 1,
                'page_size': 20, 'first_index': 0, 'last_index': 0,
            },
        )
        body = _text(admin_logged_in.get(PAGE))
        assert '查询失败' in body
        # 关键：不能把失败画成"还没有任何认证记录"
        assert '还没有任何认证记录' not in body

    def test_page_size_is_capped(self, db):
        from web_auth.services import history

        _seed(db, 1)
        assert history.query_records(page_size=100000)['page_size'] == history.MAX_PAGE_SIZE


# ============================================================================
# 六、后台首页的「最近认证记录」
# ============================================================================
class TestDashboardCard:
    def test_placeholder_rows_are_gone(self, admin_logged_in):
        body = _text(admin_logged_in.get('/manage/dashboard'))
        for fake in ('user001', 'user002', 'user005', '2025-10-09'):
            assert fake not in body

    def test_empty_card_says_no_records(self, admin_logged_in):
        body = _text(admin_logged_in.get('/manage/dashboard'))
        assert '最近认证记录' in body
        assert '暂无认证记录' in body

    def test_card_shows_real_records(self, admin_logged_in, db):
        _seed(db, 3)
        body = _text(admin_logged_in.get('/manage/dashboard'))
        assert 'u02' in body
        assert '/manage/auth_history' in body
