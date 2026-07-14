#!/usr/bin/env python3
"""只读核对目标环境的健康状态和 OpenAPI 方法/路径合同。"""

from __future__ import annotations

import argparse
import json
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

import httpx


EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_INPUT = 2
EXIT_UNAVAILABLE = 3
EXIT_MISMATCH = 4
ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


class InputError(ValueError):
    """CLI 输入不能安全、明确地表示待检查合同。"""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise InputError("命令行参数非法")


def parse_requirement(value: str) -> tuple[str, str]:
    """解析 `METHOD:/path`，不接受会改变 URL 语义的 query 或 fragment。"""
    method, separator, path = value.partition(":")
    method = method.strip().upper()
    path = path.strip()
    if not separator or method not in ALLOWED_METHODS:
        raise InputError("method/path 格式非法")
    if not path.startswith("/") or "?" in path or "#" in path:
        raise InputError("method/path 格式非法")
    return method, path


def normalize_base_url(value: str) -> str:
    """把目标规范为无凭据、无 query/fragment 的 HTTP(S) origin。"""
    try:
        parsed = urlsplit(value.strip())
        parsed.port
    except ValueError as exc:
        raise InputError("base URL 格式非法") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InputError("base URL 必须是完整的 http(s) 地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise InputError("base URL 不得包含凭据、query 或 fragment")
    if parsed.path not in {"", "/"}:
        raise InputError("base URL 只接受 origin，不接受额外路径")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _unavailable(base_url: str, reason: str, error_type: str | None = None) -> dict:
    result = {
        "status": "probe_unavailable",
        "base_url": base_url,
        "reason": reason,
        "required": [],
        "missing": [],
    }
    if error_type:
        result["error_type"] = error_type
    return result


def probe_live_api_contract(
    base_url: str,
    requirements: Iterable[tuple[str, str]],
    *,
    health_path: str = "/health",
    openapi_path: str = "/openapi.json",
    timeout_seconds: float = 5.0,
    transport: httpx.BaseTransport | None = None,
) -> dict:
    """只发两个 GET，返回可直接序列化的最小证据。"""
    normalized_base_url = normalize_base_url(base_url)
    normalized_requirements = list(requirements)
    if not normalized_requirements:
        raise InputError("至少需要一个 --require")
    for method, path in normalized_requirements:
        parse_requirement(f"{method}:{path}")
    if not health_path.startswith("/") or not openapi_path.startswith("/"):
        raise InputError("health/openapi 路径必须以 / 开头")
    if timeout_seconds <= 0:
        raise InputError("timeout 必须大于 0")

    try:
        with httpx.Client(
            base_url=normalized_base_url,
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=False,
        ) as client:
            health_response = client.get(health_path)
            if health_response.status_code != 200:
                return _unavailable(
                    normalized_base_url,
                    f"health_http_{health_response.status_code}",
                )
            try:
                health_body = health_response.json()
            except (json.JSONDecodeError, ValueError):
                return _unavailable(normalized_base_url, "health_invalid_json")
            health_status = health_body.get("status") if isinstance(health_body, dict) else None
            if health_status != "ok":
                return _unavailable(normalized_base_url, "health_status_not_ok")

            openapi_response = client.get(openapi_path)
            if openapi_response.status_code != 200:
                return _unavailable(
                    normalized_base_url,
                    f"openapi_http_{openapi_response.status_code}",
                )
            try:
                openapi = openapi_response.json()
            except (json.JSONDecodeError, ValueError):
                return _unavailable(normalized_base_url, "openapi_invalid_json")
    except httpx.HTTPError as exc:
        return _unavailable(
            normalized_base_url,
            "network_error",
            exc.__class__.__name__,
        )

    paths = openapi.get("paths") if isinstance(openapi, dict) else None
    if not isinstance(paths, dict):
        return _unavailable(normalized_base_url, "openapi_paths_invalid")
    openapi_version = openapi.get("openapi")
    if not isinstance(openapi_version, str) or not openapi_version.startswith("3."):
        return _unavailable(normalized_base_url, "openapi_version_invalid")

    required = []
    missing = []
    for method, path in normalized_requirements:
        operations = paths.get(path)
        operation = operations.get(method.lower()) if isinstance(operations, dict) else None
        if isinstance(operations, dict) and method.lower() in operations and not isinstance(
            operation, dict
        ):
            return _unavailable(normalized_base_url, "openapi_operation_invalid")
        present = isinstance(operation, dict)
        required.append({"method": method, "path": path, "present": present})
        if not present:
            missing.append(f"{method}:{path}")

    info = openapi.get("info") if isinstance(openapi.get("info"), dict) else {}
    return {
        "status": "contract_mismatch" if missing else "pass",
        "base_url": normalized_base_url,
        "health": {"http_status": 200, "body_status": health_status},
        "openapi": {
            "http_status": 200,
            "version": openapi_version,
            "title": info.get("title"),
            "path_count": len(paths),
        },
        "required": required,
        "missing": missing,
    }


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--require", action="append", default=[])
    parser.add_argument("--health-path", default="/health")
    parser.add_argument("--openapi-path", default="/openapi.json")
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        requirements = [parse_requirement(value) for value in args.require]
        result = probe_live_api_contract(
            args.base_url,
            requirements,
            health_path=args.health_path,
            openapi_path=args.openapi_path,
            timeout_seconds=args.timeout_seconds,
        )
        exit_code = {
            "pass": EXIT_OK,
            "probe_unavailable": EXIT_UNAVAILABLE,
            "contract_mismatch": EXIT_MISMATCH,
        }[result["status"]]
    except InputError as exc:
        result = {"status": "invalid_input", "reason": str(exc)}
        exit_code = EXIT_INPUT
    except Exception as exc:  # 最后一层：只暴露异常类型，不输出响应或潜在凭据。
        result = {"status": "unexpected_error", "error_type": exc.__class__.__name__}
        exit_code = EXIT_UNEXPECTED

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
