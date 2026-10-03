# -*- coding: utf-8 -*-
"""
仪表盘接口的数据可信度契约

这里断言的核心不是「数字是多少」，而是**数字是哪来的**：

  - `user_stats`、运行时长、用户数、设备数必须取自数据库与进程状态；
  - 没有真实来源的字段必须出现在 `synthetic_fields` 里。

背景：这几个接口原先把 `random` 生成的数字直接当作真实统计返回
（"累计登录 187 次"、"数据完整性 99.7%"），界面上没有任何标注 ——
与项目对演示模式立下的「三层留痕」约定直接冲突。本文件把
「能算的算真、算不出的必须标注」这条规则钉住，避免以后又悄悄混进假数据。
"""

import re

import pytest


DASHBOARD_KEYS = {
    'user_stats', 'system_stats', 'performance_data',
    'security_events', 'synthetic_fields', 'synthetic_note',
}
USER_STATS_KEYS = {
    'total_logins', 'successful_auths', 'failed_auths',
    'avg_response_time', 'has_history',
}
SYSTEM_STATS_KEYS = {'uptime', 'active_users', 'total_devices', 'data_integrity'}

# 运行时长必须长这样。原来这里是写死的 '7天 14小时 32分钟'。
UPTIME_PATTERN = re.compile(r'^\d+天 \d+小时 \d+分钟$')


class _ConnectedDevice:
    """替身：只用于让 `state.ble_device_client.is_connected` 为真。"""

    is_connected = True


@pytest.fixture()
def logged_in(client, existing_user):
    """
    把会话置为「已通过身份认证」。

    `/login` 只写入 `pending_login`，真正设置 `username` 要等验证通过 ——
    本文件关心的是仪表盘，不是认证流程，所以直接改会话。
    """
    with client.session_transaction() as sess:
        sess['username'] = existing_user
    return existing_user


# ============================================================================
# 一、访问控制
# ============================================================================
class TestAuthRequired:
    """三个接口都含用户名与设备状态，必须要求登录。"""

    @pytest.mark.parametrize('path', [
        '/api/dashboard_data',
        '/api/realtime_health_data',
        '/api/health_trends',
    ])
    def test_anonymous_is_rejected(self, client, path):
        assert client.get(path).status_code == 401


# ============================================================================
# 二、形状契约
# ============================================================================
class TestShape:
    def test_top_level_keys(self, client, logged_in):
        payload = client.get('/api/dashboard_data').get_json()
        assert DASHBOARD_KEYS <= set(payload)

    def test_nested_keys(self, client, logged_in):
        payload = client.get('/api/dashboard_data').get_json()
        assert USER_STATS_KEYS <= set(payload['user_stats'])
        assert SYSTEM_STATS_KEYS <= set(payload['system_stats'])

    def test_security_events_keep_their_shape(self, client, logged_in):
        """安全事件仍是「时间 + 事件 + 状态」的列表（内容为示意）。"""
        events = client.get('/api/dashboard_data').get_json()['security_events']
        assert events and all({'time', 'event', 'status'} <= set(e) for e in events)


# ============================================================================
# 三、真实字段确实来自真实来源
# ============================================================================
class TestRealNumbers:
    """
    判据是「跟着数据源变」—— 只有写死的常数才不会被数据库影响。
    """

    def test_active_users_follows_the_database(self, client, db, logged_in):
        assert client.get('/api/dashboard_data').get_json()['system_stats']['active_users'] == 1

        db.users.insert_one(
            {'username': 'second_user', 'created_at': None, 'model_path': None}
        )
        assert client.get('/api/dashboard_data').get_json()['system_stats']['active_users'] == 2

    def test_uptime_comes_from_the_process(self, client, logged_in):
        uptime = client.get('/api/dashboard_data').get_json()['system_stats']['uptime']
        assert UPTIME_PATTERN.match(uptime), '运行时长格式异常：{}'.format(uptime)

    def test_device_count_follows_process_state(self, client, logged_in):
        from web_auth import state

        assert client.get('/api/dashboard_data').get_json()['system_stats']['total_devices'] == 0

        state.ble_device_client = _ConnectedDevice()
        assert client.get('/api/dashboard_data').get_json()['system_stats']['total_devices'] == 1

    def test_counts_are_zero_when_there_is_no_history(self, client, logged_in):
        """没有记录时如实为 0，并用 has_history 把它与「真的一次都没有」区分开。"""
        stats = client.get('/api/dashboard_data').get_json()['user_stats']
        assert stats['total_logins'] == 0
        assert stats['successful_auths'] == 0
        assert stats['failed_auths'] == 0
        assert stats['has_history'] is False

    def test_counts_follow_auth_history(self, client, db, logged_in):
        db.auth_history.insert_many([
            {'username': logged_in, 'result': 'success', 'duration_ms': 120},
            {'username': logged_in, 'result': 'success', 'duration_ms': 180},
            {'username': logged_in, 'result': 'failure', 'duration_ms': 200},
        ])

        stats = client.get('/api/dashboard_data').get_json()['user_stats']
        assert stats['total_logins'] == 3
        assert stats['successful_auths'] == 2
        assert stats['failed_auths'] == 1
        assert stats['avg_response_time'] == 167  # (120+180+200)/3
        assert stats['has_history'] is True

    def test_counts_are_scoped_to_the_current_user(self, client, db, logged_in):
        """统计只算当前用户，否则仪表盘会把别人的记录算进来。"""
        db.auth_history.insert_one(
            {'username': 'someone_else', 'result': 'success', 'duration_ms': 90}
        )
        stats = client.get('/api/dashboard_data').get_json()['user_stats']
        assert stats['total_logins'] == 0
        assert stats['has_history'] is False

    def test_missing_duration_does_not_break_the_average(self, client, db, logged_in):
        """历史记录不一定都带耗时，缺耗时的记录不该把平均算成 0。"""
        db.auth_history.insert_many([
            {'username': logged_in, 'result': 'success', 'duration_ms': 100},
            {'username': logged_in, 'result': 'success'},
        ])
        stats = client.get('/api/dashboard_data').get_json()['user_stats']
        assert stats['total_logins'] == 2
        assert stats['avg_response_time'] == 100


# ============================================================================
# 四、示意数据必须被标注
# ============================================================================
class TestSyntheticIsDisclosed:
    """本次改造的核心约定：没有真实来源的字段要自己说明白。"""

    def test_dashboard_lists_its_synthetic_blocks(self, client, logged_in):
        payload = client.get('/api/dashboard_data').get_json()
        assert {
            'performance_data',
            'security_events',
            'system_stats.data_integrity',
        } <= set(payload['synthetic_fields'])
        assert payload['synthetic_note']

    def test_realtime_and_trends_are_flagged(self, client, logged_in):
        assert client.get('/api/realtime_health_data').get_json()['synthetic'] is True
        assert client.get('/api/health_trends').get_json()['synthetic'] is True

    def test_real_blocks_are_not_flagged_as_synthetic(self, client, logged_in):
        """
        反向断言：真实字段不能被误标。

        标错方向同样是一种误导 —— 把真实数据说成合成的，和不标合成数据一样糟。
        """
        fields = set(client.get('/api/dashboard_data').get_json()['synthetic_fields'])
        assert 'user_stats' not in fields
        assert 'system_stats.uptime' not in fields
        assert 'system_stats.active_users' not in fields
        assert 'system_stats.total_devices' not in fields


# ============================================================================
# 五、实时数据接口
# ============================================================================
class TestRealtimeHealth:
    def test_field_names_match_what_consumers_read(self, client, logged_in):
        """
        字段名是接口的一部分。

        classic 页面（`static/js/dashboard.js`）按这些名字取值，改名或改大小写
        会让那几张卡片一直停在初始值 —— 而且不报错，只是安静地显示旧内容。
        """
        payload = client.get('/api/realtime_health_data').get_json()
        assert {'heart_rate', 'emotion_status', 'alert_level'} <= set(payload)
        assert isinstance(payload['ecg_signal'], list)
        assert isinstance(payload['ppg_signal'], list)

    def test_device_connected_is_real_not_generated(self, client, logged_in):
        """设备连接情况是这一响应里唯一的真实字段，必须跟着进程状态走。"""
        from web_auth import state

        assert client.get('/api/realtime_health_data').get_json()['device_connected'] is False

        state.ble_device_client = _ConnectedDevice()
        assert client.get('/api/realtime_health_data').get_json()['device_connected'] is True


# ============================================================================
# 六、运行时长的格式化
# ============================================================================
class TestUptimeFormat:
    @pytest.mark.parametrize('seconds,expected', [
        (0, '0天 0小时 0分钟'),
        (59, '0天 0小时 0分钟'),
        (60, '0天 0小时 1分钟'),
        (3661, '0天 1小时 1分钟'),
        (90061, '1天 1小时 1分钟'),
        (-5, '0天 0小时 0分钟'),  # 时钟被回拨时不出现负数
    ])
    def test_format(self, seconds, expected):
        from web_auth.services.stats import format_uptime

        assert format_uptime(seconds) == expected
