import subprocess
import sys
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from scripts import run_local_wechat_qa as local_qa


def test_local_qa_script_is_directly_runnable():
    result = subprocess.run(
        [sys.executable, "scripts/run_local_wechat_qa.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--user-id" in result.stdout


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://velo_heatmap_qa:secret@127.0.0.1:55435/velo_heatmap_real_qa",
        "postgresql+psycopg://velo_heatmap_qa:secret@localhost:55435/velo_heatmap_real_qa",
    ],
)
def test_validate_local_qa_database_accepts_only_local_postgres_qa(database_url):
    local_qa.validate_local_qa_database(database_url)


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://velo:secret@db.internal:5432/velo_qa",
        "postgresql://velo:secret@127.0.0.1:5432/velo",
        "postgresql://velo_heatmap_qa:secret@127.0.0.1:5432/velo_heatmap_real_qa",
        "postgresql://velo:secret@127.0.0.1:55435/velo_heatmap_real_qa",
        "sqlite:///velo_qa.db",
        "not-a-database-url",
        "postgresql://velo_heatmap_qa:secret@127.0.0.1:55435/velo_heatmap_real_qa?host=db.internal",
        "postgresql://velo_heatmap_qa:secret@127.0.0.1:55435/velo_heatmap_real_qa?hostaddr=10.0.0.8",
        "postgresql://velo_heatmap_qa:secret@127.0.0.1:55435/velo_heatmap_real_qa?dbname=production",
        "postgresql://velo_heatmap_qa:secret@127.0.0.1:55435/velo_heatmap_real_qa?service=production",
    ],
)
def test_validate_local_qa_database_fails_closed(database_url):
    with pytest.raises(local_qa.LocalQAConfigError):
        local_qa.validate_local_qa_database(database_url)


@pytest.mark.parametrize(
    "server_address",
    ["127.0.0.1", "::1", "172.21.0.3/32"],
)
def test_validate_connected_local_qa_database_accepts_local_container(server_address):
    local_qa.validate_connected_local_qa_database(
        "velo_heatmap_real_qa",
        "velo_heatmap_qa",
        server_address,
    )


@pytest.mark.parametrize(
    ("database_name", "database_user", "server_address"),
    [
        ("velo", "velo_heatmap_qa", "127.0.0.1"),
        ("velo_heatmap_real_qa", "velo", "127.0.0.1"),
        ("velo_heatmap_real_qa", "velo_heatmap_qa", "8.8.8.8"),
        ("velo_heatmap_real_qa", "velo_heatmap_qa", None),
    ],
)
def test_validate_connected_local_qa_database_fails_closed(
    database_name,
    database_user,
    server_address,
):
    with pytest.raises(local_qa.LocalQAConfigError):
        local_qa.validate_connected_local_qa_database(
            database_name,
            database_user,
            server_address,
        )


def test_disable_cors_for_local_qa_restores_app_state():
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    original_middleware = list(app.user_middleware)
    original_stack = app.middleware_stack

    restore = local_qa.disable_cors_for_local_qa(app)
    assert all(item.cls is not CORSMiddleware for item in app.user_middleware)
    assert app.middleware_stack is None

    restore()
    assert app.user_middleware == original_middleware
    assert app.middleware_stack is original_stack


def test_local_qa_auth_maps_wechat_code_to_existing_user_and_restores():
    from app.user import service
    from app.user.models import User

    original_code_exchange = service.wx_code_to_openid
    original_get_or_create = service.get_or_create_user
    db = Mock()
    user = object()
    db.get.return_value = user

    restore = local_qa.install_local_qa_auth(293)
    try:
        openid = service.wx_code_to_openid("devtools-one-time-code")
        assert service.get_or_create_user(db, openid) == (user, False)
        db.get.assert_called_once_with(User, 293)
        with pytest.raises(ValueError, match="不能为空"):
            service.wx_code_to_openid("")
    finally:
        restore()

    assert service.wx_code_to_openid is original_code_exchange
    assert service.get_or_create_user is original_get_or_create


def test_main_restores_auth_cors_and_jwt_when_server_fails(monkeypatch):
    restore_auth = Mock()
    restore_cors = Mock()
    original_jwt_secret = local_qa.settings.JWT_SECRET

    monkeypatch.setattr(
        sys,
        "argv",
        ["run_local_wechat_qa.py", "--user-id", "2", "--port", "18001"],
    )
    monkeypatch.setattr(local_qa, "validate_local_qa_database", Mock())
    monkeypatch.setattr(local_qa, "verify_local_qa_database_and_user", Mock())
    monkeypatch.setattr(
        local_qa,
        "install_local_qa_auth",
        Mock(return_value=restore_auth),
    )
    monkeypatch.setattr(
        local_qa,
        "disable_cors_for_local_qa",
        Mock(return_value=restore_cors),
    )
    monkeypatch.setattr(
        local_qa.uvicorn,
        "run",
        Mock(side_effect=RuntimeError("port unavailable")),
    )

    with pytest.raises(RuntimeError, match="port unavailable"):
        local_qa.main()

    assert local_qa.settings.JWT_SECRET == original_jwt_secret
    restore_cors.assert_called_once_with()
    restore_auth.assert_called_once_with()
