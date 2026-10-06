# -*- coding: utf-8 -*-
"""
重构回归测试：把「代码结构变了但行为不能变」这件事钉住

这些用例针对 2026-10-06 那轮整体整理。整理本身不新增功能，因此测试目标
不是「新功能能不能用」，而是**原有契约有没有被改坏** —— 尤其是那些
容易被顺手改掉的细节：

* `load_app_config()` 的默认值两份合并成一份后，返回值必须仍是**独立副本**
  （调用方会改它），且键集合不能少；
* 删除用户的五步（模型文件 / users / auth_history / 注册态 / 验证态）在
  单删与批删两条路径上必须**完全一致** —— 收口成 `_purge_user()` 后，
  这正是最该防住「改了一处漏一处」的地方；
* `admin_setting()` 必须在 `admin_config` 为 `None` 时给出默认值而不是崩
  （原先 `device.py` 里的写法在 `None` 上会 `TypeError`）；
* `start_state_cleanup_thread()` 必须幂等（重复调用只起一个线程）。
"""

import threading

import pytest

from tests.helpers import form_post


# ============================================================================
# 一、默认配置
# ============================================================================
class TestDefaultAppConfig:
    #: `core.py::_default_app_config()` 必须提供的键。
    #: 与管理后台表单、仪表盘统计用到的键一致，少一个就会有人拿到 None。
    REQUIRED_KEYS = (
        'model_threshold', 'alpha', 'beta',
        'verification_time', 'min_verification_success', 'total_verification_count',
        'device_connection_timeout', 'device_scan_timeout',
        'training_epochs', 'training_learning_rate', 'training_batch_size',
        'system_use_cuda', 'system_cuda_device',
    )

    def test_returns_all_keys(self):
        from web_auth.core import _default_app_config
        assert set(_default_app_config()) == set(self.REQUIRED_KEYS)

    def test_returns_independent_copies(self):
        """
        两次调用必须返回**不同**的字典对象。

        这是把重复的字典收口成工厂函数的原因：若返回模块级常量，
        `state.admin_config` 与任何一次 `load_app_config()` 就会共享同一份，
        管理后台改配置时会把别处的期望值一起改掉。
        """
        from web_auth.core import _default_app_config
        first, second = _default_app_config(), _default_app_config()
        assert first is not second
        assert first == second

        first['model_threshold'] = 0.01
        assert second['model_threshold'] != 0.01

    def test_load_app_config_returns_all_keys(self):
        """无论走「系统可用」还是「降级」分支，键集合都必须完整。"""
        from web_auth.core import load_app_config
        assert set(load_app_config()) == set(self.REQUIRED_KEYS)


# ============================================================================
# 二、配置读取
# ============================================================================
class TestAdminSetting:
    def test_reads_present_key(self):
        from web_auth import state
        original = state.admin_config
        try:
            state.admin_config = {'model_threshold': 0.77}
            assert state.admin_setting('model_threshold', 0.8) == 0.77
        finally:
            state.admin_config = original

    def test_missing_key_falls_back(self):
        from web_auth import state
        original = state.admin_config
        try:
            state.admin_config = {}
            assert state.admin_setting('device_scan_timeout', 5.0) == 5.0
        finally:
            state.admin_config = original

    def test_none_config_falls_back_instead_of_raising(self):
        """
        `admin_config` 为 None 时必须返回默认值。

        重构前 `device.py` 写的是 `cfg['k'] if 'k' in cfg else default`，
        而 `'k' in None` 会抛 TypeError —— 扫描设备接口会 500。
        """
        from web_auth import state
        original = state.admin_config
        try:
            state.admin_config = None
            assert state.admin_setting('device_scan_timeout', 5.0) == 5.0
        finally:
            state.admin_config = original


# ============================================================================
# 三、删除用户
# ============================================================================
def _admin_login(client, csrf_token, credentials):
    return form_post(
        client, '/manage/login',
        {'username': credentials['username'], 'password': credentials['password']},
        csrf_token,
    )


class TestPurgeUserConsistency:
    """
    单删与批删现在共用 `_purge_user()`。

    这里断言两条路径的**效果完全一致** —— 尤其是进程内共享状态与
    活跃时间戳都要清掉：漏清时间戳的话，回收线程会对着早已删除的条目
    空跑到 TTL 结束。
    """

    @pytest.fixture()
    def admin(self, client, csrf_token, admin_client_flask_app):
        _admin_login(client, csrf_token, admin_client_flask_app)
        return client

    @pytest.fixture()
    def victim(self, db):
        from web_auth import state

        db.users.insert_one({
            'username': 'purge_me',
            'created_at': None,
            'model_path': None,
        })
        db.auth_history.insert_one({'username': 'purge_me', 'result': 'success'})
        with state.registration_lock:
            state.current_registration_data['purge_me'] = {'status': 'pending'}
        with state.verification_lock:
            state.verification_results['purge_me'] = {'status': 'verifying'}
        state.touch_state('registration', 'purge_me')
        state.touch_state('verification', 'purge_me')
        return 'purge_me'

    def _assert_fully_purged(self, db, username):
        from web_auth import state

        assert db.users.count_documents({'username': username}) == 0, 'users 未清除'
        assert db.auth_history.count_documents({'username': username}) == 0, \
            'auth_history 未清除'
        with state.registration_lock:
            assert username not in state.current_registration_data, '注册态未清除'
        with state.verification_lock:
            assert username not in state.verification_results, '验证态未清除'

    def test_single_delete_purges_everything(self, admin, csrf_token, db, victim):
        admin.post('/manage/delete_user/{}'.format(victim), data={'csrf_token': csrf_token})
        self._assert_fully_purged(db, victim)

    def test_batch_delete_purges_everything(self, admin, csrf_token, db, victim):
        admin.post('/manage/batch_delete_users',
                   data={'csrf_token': csrf_token, 'usernames[]': victim})
        self._assert_fully_purged(db, victim)

    def test_active_timestamps_are_cleared(self, admin, csrf_token, db, victim):
        """
        时间戳必须与数据一起清掉。

        这条比数据本身更隐蔽：数据删了但时间戳留着，回收线程会一直
        尝试 pop 一个早已不存在的键，直到 TTL 耗尽。
        """
        from web_auth import state

        admin.post('/manage/delete_user/{}'.format(victim), data={'csrf_token': csrf_token})
        with state._state_ts_lock:
            for kind, bucket in state._state_last_active.items():
                assert victim not in bucket, '{} 的活跃时间戳未清除'.format(kind)

    def test_admin_account_is_protected(self, admin, csrf_token, db,
                                        admin_client_flask_app):
        """管理员账号不能被删 —— 两条路径都要挡。"""
        name = admin_client_flask_app['username']
        db.users.insert_one({'username': name, 'created_at': None, 'model_path': None})

        admin.post('/manage/delete_user/{}'.format(name),
                   data={'csrf_token': csrf_token})
        admin.post('/manage/batch_delete_users',
                   data={'csrf_token': csrf_token, 'usernames[]': name})

        assert db.users.count_documents({'username': name}) == 1

    def test_missing_user_is_reported_not_crashed(self, admin, csrf_token):
        """删不存在的用户应给出提示并重定向，而不是 500。"""
        resp = admin.post('/manage/delete_user/ghost_user',
                          data={'csrf_token': csrf_token})
        assert resp.status_code == 302


# ============================================================================
# 四、回收线程
# ============================================================================
class TestStateCleanupThread:
    def test_start_is_idempotent(self):
        """
        重复调用只应起一个线程。

        回收线程原先在 `import web_auth.state` 时自启，每次导入都起一个；
        改成由 `create_app()` 显式启动后必须幂等，否则「重复建应用」
        （测试里很常见）会叠出多个回收线程。
        """
        from web_auth import state

        before = sum(1 for t in threading.enumerate()
                     if t.name == 'state-cleanup')

        state.start_state_cleanup_thread()
        state.start_state_cleanup_thread()

        after = sum(1 for t in threading.enumerate() if t.name == 'state-cleanup')
        # 不得超过启动前的数量 + 1（本次调用至多新增一个）
        assert after <= before + 1


# ============================================================================
# 五、事件循环收尾
# ============================================================================
class TestEventLoopHelper:
    def test_loop_is_closed_after_use(self):
        """退出上下文后循环必须已关闭 —— 这是本次修复的资源泄漏点。"""
        from web_auth.services.collection import new_event_loop

        with new_event_loop('测试') as loop:
            assert not loop.is_closed()
        assert loop.is_closed()

    def test_loop_closed_even_when_body_raises(self):
        """with 的 finally 分支要保证异常路径下也关闭。"""
        from web_auth.services.collection import new_event_loop

        captured = {}
        with pytest.raises(ValueError):
            with new_event_loop('测试') as loop:
                captured['loop'] = loop
                raise ValueError('故意抛出')

        assert captured['loop'].is_closed()


# ============================================================================
# 六、信号过滤
# ============================================================================
class TestFilterSignalArrays:
    def test_keeps_arrays(self):
        import numpy as np

        from web_auth.services.signals import filter_signal_arrays

        arrays = [np.zeros(10), np.ones(10)]
        assert filter_signal_arrays(arrays) == arrays

    def test_drops_zero_dim_scalars(self):
        """标量会让 np.concatenate 抛异常，必须在拼接前滤掉。"""
        import numpy as np

        from web_auth.services.signals import filter_signal_arrays

        mixed = [np.zeros(10), np.array(1.0), np.ones(10)]
        kept = filter_signal_arrays(mixed)
        assert len(kept) == 2
        # 滤完之后必须能正常拼接
        assert np.concatenate(kept).shape == (20,)

    def test_empty_input(self):
        from web_auth.services.signals import filter_signal_arrays
        assert filter_signal_arrays([]) == []
