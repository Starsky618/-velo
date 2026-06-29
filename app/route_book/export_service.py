"""路线导出门禁——判断谁能把哪一版路线变成下载文件。

这个文件像下载室门口的保安：它不生成 GPX/TCX 文件，只检查来的人有没有资格。
操作注意事项：`file_id` 是仓库内部钥匙，任何下载接口都应该先走这里，再由后端读取文件。
输入输出：传入 route/job/artifact 这类对象，返回布尔值或抛出 `PermissionError`。
"""

from datetime import datetime, timezone
from typing import Any


def can_export_route(
    route: Any,
    *,
    current_user_id: int | None,
    is_admin: bool = False,
    share_link: Any | None = None,
    now: datetime | None = None,
) -> bool:
    """
    判断当前用户能不能发起路线导出。

    规则按 Batch 3 边界收紧：主人和管理员能导出；公开且已发布的路线能导出；
    未列出路线必须等未来分享链接带 `can_export=True`，本轮没有链接就默认关门。
    """
    if route is None:
        return False
    if is_admin:
        return True

    route_owner_id = getattr(route, "creator_id", None)
    if current_user_id is not None and route_owner_id == current_user_id:
        return True
    if current_user_id is None:
        return False

    visibility = getattr(route, "visibility", None)
    publish_status = getattr(route, "publish_status", None)
    if visibility == "public" and publish_status == "published":
        return True

    if visibility == "unlisted" and publish_status == "published":
        return _share_link_can_export(share_link, route_id=getattr(route, "id", None), now=now)

    return False


def assert_can_export_route(
    route: Any,
    *,
    current_user_id: int | None,
    is_admin: bool = False,
    share_link: Any | None = None,
) -> None:
    """给未来导出接口用的硬门禁：没资格就直接挡住。"""
    if not can_export_route(
        route,
        current_user_id=current_user_id,
        is_admin=is_admin,
        share_link=share_link,
    ):
        raise PermissionError("route export not allowed")


def can_download_export_artifact(
    artifact: Any,
    *,
    current_user_id: int | None,
    job: Any | None = None,
    route: Any | None = None,
    is_admin: bool = False,
) -> bool:
    """
    判断当前用户能不能下载某个导出产物。

    默认只放行两类人：管理员、当时发起这次导出的用户。这样公开路线也不会把
    别人的 `file_id` 变成公共链接；路线主人要下载，也应创建自己的导出任务。
    """
    if artifact is None:
        return False
    if not _artifact_matches_route(artifact, route):
        return False
    if is_admin:
        return True
    if current_user_id is None:
        return False

    requester_id = getattr(job, "requester_id", None)
    if requester_id is not None and requester_id == current_user_id:
        return True

    return False


def _artifact_matches_route(artifact: Any, route: Any | None) -> bool:
    if route is None:
        return True
    artifact_route_id = getattr(artifact, "route_book_id", None)
    route_id = getattr(route, "id", None)
    if artifact_route_id is None or route_id is None:
        return True
    return artifact_route_id == route_id


def assert_can_download_export_artifact(
    artifact: Any,
    *,
    current_user_id: int | None,
    job: Any | None = None,
    route: Any | None = None,
    is_admin: bool = False,
) -> None:
    """给未来下载接口用的硬门禁：没资格就不让摸到内部文件钥匙。"""
    if not can_download_export_artifact(
        artifact,
        current_user_id=current_user_id,
        job=job,
        route=route,
        is_admin=is_admin,
    ):
        raise PermissionError("route export artifact download not allowed")


def _share_link_can_export(share_link: Any | None, *, route_id: int | None, now: datetime | None) -> bool:
    if share_link is None or route_id is None:
        return False
    if getattr(share_link, "route_book_id", None) != route_id:
        return False
    if getattr(share_link, "status", None) != "active":
        return False
    if getattr(share_link, "can_export", None) is not True:
        return False
    return not _is_expired(getattr(share_link, "expires_at", None), now=now)


def _is_expired(expires_at: datetime | None, *, now: datetime | None) -> bool:
    if expires_at is None:
        return False
    current = now or datetime.now(timezone.utc)
    if expires_at.tzinfo is None or expires_at.tzinfo.utcoffset(expires_at) is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if current.tzinfo is None or current.tzinfo.utcoffset(current) is None:
        current = current.replace(tzinfo=timezone.utc)
    return expires_at <= current
