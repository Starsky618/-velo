#!/usr/bin/env python3
"""Run VELO with a fail-closed local-only WeChat login for DevTools QA.

This entrypoint exists because a WeChat ``wx.login`` code can only be exchanged by
the matching AppID/secret. Local heatmap worktrees intentionally do not contain
that production secret. Instead of pasting a JWT into the DevTools console, this
process maps any non-empty ``wx.login`` code to one existing QA user.

Safety boundaries are deliberately redundant:

- the database must be PostgreSQL on localhost;
- it must match the dedicated heatmap QA database port, name, and user;
- Uvicorn is always bound to ``127.0.0.1``;
- the QA user must already exist;
- the JWT signing key is random and process-local.

The normal ``app.main:app`` entrypoint never installs this login adapter.
"""

from __future__ import annotations

import argparse
import ipaddress
import secrets
import sys
from collections.abc import Callable
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import uvicorn
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.config import settings


_LOCAL_DATABASE_HOSTS = {"127.0.0.1", "localhost", "::1"}
_LOCAL_QA_DATABASE_PORT = 55435
_LOCAL_QA_DATABASE_NAME = "velo_heatmap_real_qa"
_LOCAL_QA_DATABASE_USER = "velo_heatmap_qa"
_LOCAL_QA_OPENID = "__velo_local_wechat_qa__"


class LocalQAConfigError(ValueError):
    """The requested server could escape the local disposable QA boundary."""


def validate_local_qa_database(database_url: str) -> None:
    """Reject remote, non-PostgreSQL, and non-QA databases before auth is patched."""
    try:
        parsed = make_url(database_url)
    except Exception as exc:
        raise LocalQAConfigError("DATABASE_URL 格式非法") from exc
    if not parsed.drivername.startswith("postgresql"):
        raise LocalQAConfigError("本地微信 QA 只允许 PostgreSQL")
    if parsed.query:
        raise LocalQAConfigError("本地微信 QA 禁止 DATABASE_URL query 参数")
    if parsed.host not in _LOCAL_DATABASE_HOSTS:
        raise LocalQAConfigError("本地微信 QA 只允许 localhost 数据库")
    if parsed.port != _LOCAL_QA_DATABASE_PORT:
        raise LocalQAConfigError("本地微信 QA 数据库端口不匹配")
    if parsed.database != _LOCAL_QA_DATABASE_NAME:
        raise LocalQAConfigError("本地微信 QA 数据库名称不匹配")
    if parsed.username != _LOCAL_QA_DATABASE_USER:
        raise LocalQAConfigError("本地微信 QA 数据库用户不匹配")


def validate_connected_local_qa_database(
    database_name: str | None,
    database_user: str | None,
    server_address: str | None,
) -> None:
    """Verify the real libpq connection target, not only the URL text."""
    if database_name != _LOCAL_QA_DATABASE_NAME:
        raise LocalQAConfigError("实际连接的数据库名称不匹配")
    if database_user != _LOCAL_QA_DATABASE_USER:
        raise LocalQAConfigError("实际连接的数据库用户不匹配")
    try:
        address = ipaddress.ip_interface(server_address or "").ip
    except ValueError as exc:
        raise LocalQAConfigError("无法确认实际数据库服务器地址") from exc
    if not (address.is_loopback or address.is_private):
        raise LocalQAConfigError("实际数据库服务器不是 loopback 或 Docker 私网")


def verify_local_qa_database_and_user(user_id: int) -> None:
    """Fail before installing the auth adapter if the real target is unsafe."""
    from app.database import SessionLocal
    from app.user.models import User

    if user_id <= 0:
        raise LocalQAConfigError("QA user id 必须为正整数")
    with SessionLocal() as db:
        database_name, database_user, server_address = db.execute(
            text(
                "SELECT current_database(), current_user, "
                "inet_server_addr()::text"
            )
        ).one()
        validate_connected_local_qa_database(
            database_name,
            database_user,
            server_address,
        )
        if db.get(User, user_id) is None:
            raise LocalQAConfigError("QA user 不存在")


def disable_cors_for_local_qa(app) -> Callable[[], None]:
    """Keep arbitrary browser origins from obtaining the local QA token."""
    original_middleware = list(app.user_middleware)
    original_stack = app.middleware_stack
    app.user_middleware = [
        middleware
        for middleware in app.user_middleware
        if middleware.cls is not CORSMiddleware
    ]
    app.middleware_stack = None

    def restore() -> None:
        app.user_middleware = original_middleware
        app.middleware_stack = original_stack

    return restore


def install_local_qa_auth(user_id: int) -> Callable[[], None]:
    """Patch only the service facade used by the login router in this process."""
    from app.user import service
    from app.user.models import User

    original_code_exchange = service.wx_code_to_openid
    original_get_or_create = service.get_or_create_user

    def local_code_exchange(code: str) -> str:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("wx.login code 不能为空")
        return _LOCAL_QA_OPENID

    def local_get_or_create_user(db, openid: str):
        if openid != _LOCAL_QA_OPENID:
            raise LocalQAConfigError("本地微信 QA openid 非法")
        user = db.get(User, user_id)
        if user is None:
            raise LocalQAConfigError("QA user 不存在")
        return user, False

    service.wx_code_to_openid = local_code_exchange
    service.get_or_create_user = local_get_or_create_user

    def restore() -> None:
        service.wx_code_to_openid = original_code_exchange
        service.get_or_create_user = original_get_or_create

    return restore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="启动仅供微信开发者工具使用的 VELO 本地 QA API",
    )
    parser.add_argument("--user-id", type=int, required=True, help="已有 QA 用户 ID")
    parser.add_argument("--port", type=int, default=18001)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not 1 <= args.port <= 65535:
        raise LocalQAConfigError("端口必须在 1..65535")
    validate_local_qa_database(settings.DATABASE_URL)
    verify_local_qa_database_and_user(args.user_id)

    from app.main import app

    original_jwt_secret = settings.JWT_SECRET
    restore_auth = install_local_qa_auth(args.user_id)
    restore_cors = disable_cors_for_local_qa(app)
    settings.JWT_SECRET = secrets.token_urlsafe(48)
    try:
        print(
            f"LOCAL WECHAT QA AUTH ENABLED: user_id={args.user_id} "
            f"http://127.0.0.1:{args.port}"
        )
        uvicorn.run(app, host="127.0.0.1", port=args.port)
    finally:
        settings.JWT_SECRET = original_jwt_secret
        restore_cors()
        restore_auth()


if __name__ == "__main__":
    main()
