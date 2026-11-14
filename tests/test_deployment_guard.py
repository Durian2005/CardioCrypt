# -*- coding: utf-8 -*-
"""部署形态护栏的行为契约。

护栏只回答一个问题：显式声明对外监听时，是否还允许沿用默认管理员口令。
它是纯函数，测试不需要 reload 配置模块或改动进程级环境变量。
"""
import pytest

from web_auth.config import (
    ADMIN_PASSWORD_IS_DEFAULT,
    FLASK_HOST,
    LOOPBACK_HOSTS,
    check_deployment_guard,
    password_is_default,
)


@pytest.mark.parametrize('host', sorted(LOOPBACK_HOSTS))
def test_loopback_allows_default_password(host):
    """本机试用是默认口令的唯一合法场景。"""
    assert check_deployment_guard(host, True) is True


@pytest.mark.parametrize('host', ['0.0.0.0', '[::]', '192.0.2.20', '203.0.113.7'])
def test_external_bind_rejects_default_password(host):
    """对外监听 + 默认口令必须拒绝，且错误信息给出可执行的指引。"""
    with pytest.raises(RuntimeError) as exc:
        check_deployment_guard(host, True)
    message = str(exc.value)
    assert host in message
    assert 'ADMIN_PASSWORD' in message
    assert 'FLASK_HOST' in message


@pytest.mark.parametrize('host', ['0.0.0.0', '[::]', '192.0.2.20'])
def test_external_bind_allows_explicit_password(host):
    """显式设置管理员口令后，对外监听不再被拦截。"""
    assert check_deployment_guard(host, False) is True


def test_loopback_allows_explicit_password():
    assert check_deployment_guard('127.0.0.1', False) is True


def test_config_defaults_are_local_only():
    """测试会话的默认监听地址必须是回环地址。"""
    assert FLASK_HOST in LOOPBACK_HOSTS


@pytest.mark.parametrize('value', ['', '   ', 'admin123', ' admin123 '])
def test_default_password_detection_covers_empty_value(value):
    """空值等同于默认口令 —— 空口令比默认口令更危险，不能绕过护栏。"""
    assert password_is_default(value) is True


@pytest.mark.parametrize('value', ['S3cret!pass', 'admin1234', 'Admin123'])
def test_custom_password_is_not_default(value):
    """改过内容就算显式设置（区分大小写，前后空白不影响判定）。"""
    assert password_is_default(value) is False


def test_test_session_uses_explicit_admin_password():
    """夹具显式设置了管理员口令，因此护栏不会影响任何现有用例。"""
    assert ADMIN_PASSWORD_IS_DEFAULT is False


def test_factory_starts_under_test_configuration(flask_app):
    """应用工厂在当前配置下正常组装（护栏未误拦本地/测试形态）。"""
    assert flask_app.config['TESTING'] is True
    assert flask_app.config['CSRF_ENABLED'] is True
