from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
from threading import RLock
from time import monotonic
from typing import Iterable
from uuid import uuid4
import zlib

import jwt
from PIL import Image, ImageFilter
from rq import Retry

from app.config import settings


_TICKET_PREFIX = "heatmap:web-ticket:v1:"
_TICKET_TTL_SEC = 120
_SESSION_AUDIENCE = "velo-heatmap-web-v1"
_SESSION_TTL_SEC = 60 * 60
_SESSION_VERSION_PREFIX = "heatmap:web-version:v1:"
_SESSION_COVERAGE_PREFIX = "heatmap:web-coverage:v1:"
_SESSION_COVERAGE_CACHE: OrderedDict[
    tuple[str, str, str], tuple[float, frozenset[str]]
] = OrderedDict()
_SESSION_COVERAGE_CACHE_LOCK = RLock()
_SESSION_COVERAGE_CACHE_TTL_SEC = 60
_SESSION_COVERAGE_CACHE_MAX_ITEMS = 16
_PREWARM_MARKER_PREFIX = "heatmap:artifact-prewarm:v1:"
_PREWARM_MARKER_TTL_SEC = 300
_PREWARM_CHUNK_SIZE = 32
_ARTIFACT_VERSION = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ARTIFACT_GENERATION = re.compile(r"^g(?P<generation>\d+)-")
_USER_ARTIFACT_DIR = re.compile(r"^user_(?P<user_id>\d+)$")
_ORPHAN_ARTIFACT_DIR = re.compile(r"^\.orphan-user_\d+-[0-9a-f]{32}\.deleting$")
_AUDIENCES = {"owner", "public"}
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_logger = logging.getLogger(__name__)


class HeatmapWebUnavailable(RuntimeError):
    """Redis、地图 Key 或冷缓存不可用，正式页应明确失败而不是裸奔。"""


class HeatmapWebSessionError(ValueError):
    """一次性票据或短会话无效。"""


class HeatmapTileNotCovered(ValueError):
    """坐标不在服务端签发的稀疏清单中，绝不能触发渲染或落盘。"""


def _redis_client():
    from app.queue import heatmap_redis_conn

    return heatmap_redis_conn


def _ticket_key(ticket: str) -> str:
    return f"{_TICKET_PREFIX}{sha256(ticket.encode()).hexdigest()}"


def create_web_ticket(viewer_user_id: int, target_user_id: int) -> str:
    """创建 2 分钟一次性票据；长期登录 JWT 不进入 URL 或浏览器存储。"""
    ticket = secrets.token_urlsafe(32)
    payload = json.dumps(
        {
            "viewer_user_id": int(viewer_user_id),
            "target_user_id": int(target_user_id),
        },
        separators=(",", ":"),
    ).encode()
    try:
        stored = _redis_client().set(
            _ticket_key(ticket),
            payload,
            ex=_TICKET_TTL_SEC,
            nx=True,
        )
    except Exception as exc:
        raise HeatmapWebUnavailable("热图会话服务暂时不可用") from exc
    if not stored:
        raise HeatmapWebUnavailable("热图会话创建冲突，请重试")
    return ticket


def consume_web_ticket(ticket: str) -> dict[str, int]:
    if not ticket or len(ticket) > 128:
        raise HeatmapWebSessionError("热图链接无效")
    try:
        raw = _redis_client().getdel(_ticket_key(ticket))
    except Exception as exc:
        raise HeatmapWebUnavailable("热图会话服务暂时不可用") from exc
    if not isinstance(raw, bytes):
        raise HeatmapWebSessionError("热图链接已过期或已使用")
    try:
        payload = json.loads(raw.decode())
        viewer_user_id = int(payload["viewer_user_id"])
        target_user_id = int(payload["target_user_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HeatmapWebSessionError("热图链接无效") from exc
    if viewer_user_id <= 0 or target_user_id <= 0:
        raise HeatmapWebSessionError("热图链接无效")
    return {
        "viewer_user_id": viewer_user_id,
        "target_user_id": target_user_id,
    }


def create_session_token(viewer_user_id: int, target_user_id: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(int(viewer_user_id)),
            "target": int(target_user_id),
            "aud": _SESSION_AUDIENCE,
            "iat": now,
            "exp": now + timedelta(seconds=_SESSION_TTL_SEC),
            "jti": uuid4().hex,
        },
        settings.JWT_SECRET,
        algorithm="HS256",
    )


def decode_session_token(token: str | None) -> dict[str, int | str]:
    if not token:
        raise HeatmapWebSessionError("热图会话已过期")
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=["HS256"],
            audience=_SESSION_AUDIENCE,
        )
        viewer_user_id = int(payload["sub"])
        target_user_id = int(payload["target"])
        session_id = str(payload["jti"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise HeatmapWebSessionError("热图会话已过期") from exc
    if (
        viewer_user_id <= 0
        or target_user_id <= 0
        or re.fullmatch(r"[0-9a-f]{32}", session_id) is None
    ):
        raise HeatmapWebSessionError("热图会话已过期")
    return {
        "viewer_user_id": viewer_user_id,
        "target_user_id": target_user_id,
        "session_id": session_id,
    }


def session_ttl_seconds() -> int:
    return _SESSION_TTL_SEC


def _session_version_key(session_id: str, year: int | None) -> str:
    year_part = str(int(year)) if year is not None else "all"
    return f"{_SESSION_VERSION_PREFIX}{session_id}:year_{year_part}"


def _session_coverage_key(
    session_id: str,
    year: int | None,
    version: str,
) -> str:
    year_part = str(int(year)) if year is not None else "all"
    return (
        f"{_SESSION_COVERAGE_PREFIX}{session_id}:"
        f"year_{year_part}:version_{version}"
    )


def _coverage_items(tiles: dict[str, list[list[int]]]) -> frozenset[str]:
    return frozenset(
        f"{int(zoom)}/{int(x)}/{int(y)}"
        for zoom, coordinates in tiles.items()
        for x, y in coordinates
    )


def _cache_session_coverage(
    cache_key: tuple[str, str, str],
    coverage: frozenset[str],
) -> None:
    with _SESSION_COVERAGE_CACHE_LOCK:
        _SESSION_COVERAGE_CACHE[cache_key] = (
            monotonic() + _SESSION_COVERAGE_CACHE_TTL_SEC,
            coverage,
        )
        _SESSION_COVERAGE_CACHE.move_to_end(cache_key)
        while len(_SESSION_COVERAGE_CACHE) > _SESSION_COVERAGE_CACHE_MAX_ITEMS:
            _SESSION_COVERAGE_CACHE.popitem(last=False)


def remember_session_coverage(
    session_id: str,
    year: int | None,
    version: str,
    tiles: dict[str, list[list[int]]],
) -> None:
    if re.fullmatch(r"[0-9a-f]{32}", session_id) is None:
        raise HeatmapWebSessionError("热图会话已过期")
    if _ARTIFACT_VERSION.fullmatch(version) is None:
        raise ValueError("invalid heatmap artifact version")
    coverage = _coverage_items(tiles)
    payload = zlib.compress("\n".join(sorted(coverage)).encode(), level=6)
    try:
        _redis_client().setex(
            _session_coverage_key(session_id, year, version),
            _SESSION_TTL_SEC,
            payload,
        )
    except Exception as exc:
        raise HeatmapWebUnavailable("热图会话服务暂时不可用") from exc
    _cache_session_coverage((session_id, str(year), version), coverage)


def validate_session_tile(
    session_id: str,
    year: int | None,
    version: str,
    zoom: int,
    x: int,
    y: int,
) -> None:
    _validate_artifact_identity("owner", version, zoom, x, y)
    cache_key = (session_id, str(year), version)
    coverage = None
    with _SESSION_COVERAGE_CACHE_LOCK:
        cached = _SESSION_COVERAGE_CACHE.get(cache_key)
        if cached is not None and cached[0] > monotonic():
            coverage = cached[1]
            _SESSION_COVERAGE_CACHE.move_to_end(cache_key)
        elif cached is not None:
            _SESSION_COVERAGE_CACHE.pop(cache_key, None)
    if coverage is None:
        try:
            raw = _redis_client().get(
                _session_coverage_key(session_id, year, version)
            )
            if not isinstance(raw, bytes):
                raise HeatmapWebSessionError("热图会话已过期")
            decoded = zlib.decompress(raw).decode()
            coverage = frozenset(decoded.splitlines()) if decoded else frozenset()
        except HeatmapWebSessionError:
            raise
        except Exception as exc:
            raise HeatmapWebUnavailable("热图会话服务暂时不可用") from exc
        _cache_session_coverage(cache_key, coverage)
    if f"{int(zoom)}/{int(x)}/{int(y)}" not in coverage:
        raise HeatmapTileNotCovered("heatmap tile outside manifest")


def remember_session_version(session_id: str, year: int | None, version: str) -> None:
    if re.fullmatch(r"[0-9a-f]{32}", session_id) is None:
        raise HeatmapWebSessionError("热图会话已过期")
    if _ARTIFACT_VERSION.fullmatch(version) is None:
        raise ValueError("invalid heatmap artifact version")
    try:
        _redis_client().setex(
            _session_version_key(session_id, year),
            _SESSION_TTL_SEC,
            version.encode(),
        )
    except Exception as exc:
        raise HeatmapWebUnavailable("热图会话服务暂时不可用") from exc


def validate_session_version(session_id: str, year: int | None, version: str) -> None:
    try:
        allowed = _redis_client().get(_session_version_key(session_id, year))
    except Exception as exc:
        raise HeatmapWebUnavailable("热图会话服务暂时不可用") from exc
    if allowed != version.encode():
        raise HeatmapWebSessionError("热图版本已更新，请刷新页面")


def validate_current_generation(user_id: int, version: str) -> None:
    """旧 web-view 会话不能在隐私或活动变更后继续读取上一代 PNG。"""
    match = _ARTIFACT_GENERATION.match(version)
    if match is None:
        raise HeatmapWebSessionError("热图版本已更新，请刷新页面")
    try:
        raw = _redis_client().get(f"heatmap:generation:user_{int(user_id)}")
        current_generation = int(raw or 0)
    except Exception as exc:
        raise HeatmapWebUnavailable("热图会话服务暂时不可用") from exc
    if int(match.group("generation")) != current_generation:
        raise HeatmapWebSessionError("热图版本已更新，请刷新页面")


def validate_current_artifact_version(
    db,
    user_id: int,
    audience: str,
    version: str,
) -> None:
    """完整校验 Redis generation + DB 活动/隐私指纹，Redis 失效失败也 fail closed。"""
    if audience not in _AUDIENCES:
        raise HeatmapWebSessionError("热图版本已更新，请刷新页面")
    try:
        from app.user.service_heatmap_tiles import get_current_heatmap_tile_version

        current = get_current_heatmap_tile_version(
            db,
            int(user_id),
            include_private=audience == "owner",
        )
    except Exception as exc:
        raise HeatmapWebUnavailable("热图版本校验暂时不可用") from exc
    if current != version:
        raise HeatmapWebSessionError("热图版本已更新，请刷新页面")


def _validate_artifact_identity(
    audience: str,
    version: str,
    zoom: int,
    x: int,
    y: int,
) -> None:
    if audience not in _AUDIENCES or _ARTIFACT_VERSION.fullmatch(version) is None:
        raise ValueError("invalid heatmap artifact identity")
    if not 0 <= zoom <= 22:
        raise ValueError("invalid heatmap artifact zoom")
    count = 1 << zoom
    if not (0 <= x < count and 0 <= y < count):
        raise ValueError("invalid heatmap artifact coordinate")


def _artifact_root() -> Path:
    return Path(settings.HEATMAP_TILE_DIR).expanduser().resolve()


@contextmanager
def _artifact_mutation_lock(user_id: int):
    """跨 API/worker 串行化同一用户的 PNG 写入与注销清盘。"""
    try:
        lock = _redis_client().lock(
            f"heatmap:artifact-mutation:v1:user_{int(user_id)}",
            timeout=60,
            blocking_timeout=10,
        )
        acquired = lock.acquire()
    except Exception as exc:
        raise HeatmapWebUnavailable("热图瓦片写入锁暂时不可用") from exc
    if not acquired:
        raise HeatmapWebUnavailable("热图瓦片正在更新，请稍后重试")
    try:
        yield
    finally:
        try:
            lock.release()
        except Exception:
            pass


def tile_artifact_path(
    user_id: int,
    audience: str,
    version: str,
    year: int | None,
    zoom: int,
    x: int,
    y: int,
    *,
    fallback: bool = False,
) -> Path:
    _validate_artifact_identity(audience, version, zoom, x, y)
    year_part = f"year_{int(year)}" if year is not None else "year_all"
    layer = "fallback" if fallback else "live"
    return (
        _artifact_root()
        / f"user_{int(user_id)}"
        / audience
        / year_part
        / version
        / layer
        / str(zoom)
        / str(x)
        / f"{y}.png"
    )


def _read_png(path: Path) -> bytes | None:
    try:
        payload = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise HeatmapWebUnavailable("热图瓦片缓存暂时不可用") from exc
    return payload if payload.startswith(_PNG_SIGNATURE) else None


def _write_png(path: Path, payload: bytes) -> None:
    if not payload.startswith(_PNG_SIGNATURE):
        raise HeatmapWebUnavailable("热图瓦片生成结果无效")
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    except OSError as exc:
        raise HeatmapWebUnavailable("热图瓦片缓存暂时不可用") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def purge_user_tile_artifacts(user_id: int) -> int:
    """删除一个用户全部可重建 PNG；账号注销后由业务层同步调用。"""
    if int(user_id) <= 0:
        raise ValueError("invalid heatmap artifact user")
    target = _artifact_root() / f"user_{int(user_id)}"
    try:
        with _artifact_mutation_lock(user_id):
            if target.is_symlink():
                target.unlink()
                return 1
            if not target.exists():
                return 0
            shutil.rmtree(target)
            return 1
    except OSError as exc:
        raise HeatmapWebUnavailable("热图瓦片缓存暂时不可清理") from exc


def _remove_artifact_tree(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def sweep_orphan_user_artifacts(db) -> int:
    """清理 DB 中已无用户对应的瓦片目录，不依赖 Redis。

    与注销后的实时清理构成持久补偿：Redis 宕机时 API/worker
    写入也会因拿不到锁而 fail closed；旧 writer 若在扫描期间重建目录，
    下一个 5 分钟周期仍会根据 DB 真相再次清除。
    """
    from app.user.models import User

    root = _artifact_root()
    if not root.exists():
        return 0
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        raise HeatmapWebUnavailable("热图瓦片缓存暂时不可扫描") from exc

    candidates: list[tuple[int, Path]] = []
    cleaned = 0
    for entry in entries:
        match = _USER_ARTIFACT_DIR.fullmatch(entry.name)
        if match is not None:
            candidates.append((int(match.group("user_id")), entry))
            continue
        if _ORPHAN_ARTIFACT_DIR.fullmatch(entry.name) is None:
            continue
        try:
            _remove_artifact_tree(entry)
            cleaned += 1
        except OSError:
            _logger.exception(
                "failed to remove quarantined heatmap artifacts",
                extra={"path": str(entry)},
            )

    if not candidates:
        return cleaned
    candidate_ids = {user_id for user_id, _ in candidates}
    existing_ids = {
        int(user_id)
        for (user_id,) in db.query(User.id).filter(User.id.in_(candidate_ids)).all()
    }
    for user_id, entry in candidates:
        if user_id in existing_ids:
            continue
        quarantine = root / f".orphan-user_{user_id}-{uuid4().hex}.deleting"
        try:
            os.replace(entry, quarantine)
            _remove_artifact_tree(quarantine)
            cleaned += 1
        except FileNotFoundError:
            continue
        except OSError:
            _logger.exception(
                "failed to sweep orphan heatmap artifacts",
                extra={"user_id": user_id},
            )
    return cleaned


def prune_stale_tile_artifacts_task(
    user_id: int,
    audience: str,
    current_version: str,
) -> dict[str, int | str]:
    """RQ 低优先级任务：按 audience 清掉当前 generation 之前的落盘版本。"""
    try:
        validate_current_generation(user_id, current_version)
    except HeatmapWebSessionError:
        return {"status": "stale", "deleted": 0}
    _validate_artifact_identity(audience, current_version, 0, 0, 0)
    expected_match = _ARTIFACT_GENERATION.match(current_version)
    if expected_match is None:
        return {"status": "stale", "deleted": 0}
    expected_generation = int(expected_match.group("generation"))
    audience_root = _artifact_root() / f"user_{int(user_id)}" / audience
    deleted = 0
    if not audience_root.exists():
        return {"status": "pruned", "deleted": 0}
    try:
        for year_root in audience_root.iterdir():
            if not year_root.is_dir():
                continue
            for version_root in year_root.iterdir():
                if version_root.name == current_version:
                    continue
                candidate = _ARTIFACT_GENERATION.match(version_root.name)
                # 只删严格更老的 generation。同代不同 fingerprint 留待下一代回收，
                # 避免隐私切换或并发 manifest 在本任务运行中写出新版本后被误删。
                if (
                    candidate is None
                    or int(candidate.group("generation")) >= expected_generation
                ):
                    continue
                if version_root.is_symlink():
                    version_root.unlink()
                elif version_root.is_dir():
                    shutil.rmtree(version_root)
                else:
                    version_root.unlink()
                deleted += 1
    except OSError as exc:
        raise HeatmapWebUnavailable("热图瓦片缓存暂时不可清理") from exc
    return {"status": "pruned", "deleted": deleted}


def enqueue_user_artifact_purge(user_id: int) -> bool:
    """注销后的磁盘清理失败时进入独立热图 worker 重试。"""
    job_id = f"heatmap-user-purge-v1-user-{int(user_id)}"
    try:
        from app.queue import heatmap_tiles_queue

        if heatmap_tiles_queue.fetch_job(job_id) is not None:
            return False
        heatmap_tiles_queue.enqueue(
            "app.heatmap_web.service.purge_user_tile_artifacts",
            int(user_id),
            job_id=job_id,
            job_timeout=300,
            result_ttl=86400,
            failure_ttl=7 * 86400,
            retry=Retry(max=5, interval=[10, 60, 300, 1800, 3600]),
        )
        return True
    except Exception:
        return False


def enqueue_stale_artifact_prune(
    user_id: int,
    audience: str,
    current_version: str,
) -> bool:
    """幂等入队旧版本清理，不让目录扫描阻塞用户打开地图。"""
    _validate_artifact_identity(audience, current_version, 0, 0, 0)
    job_id = (
        f"heatmap-prune-v1-user-{int(user_id)}-"
        f"audience-{audience}-v-{current_version}"
    )
    try:
        from app.queue import heatmap_tiles_queue

        if heatmap_tiles_queue.fetch_job(job_id) is not None:
            return False
        heatmap_tiles_queue.enqueue(
            "app.heatmap_web.service.prune_stale_tile_artifacts_task",
            int(user_id),
            audience,
            current_version,
            job_id=job_id,
            job_timeout=300,
            result_ttl=86400,
            failure_ttl=3600,
            retry=Retry(max=2, interval=[10, 60]),
        )
        return True
    except Exception:
        return False


def get_live_tile_artifact(
    db,
    user_id: int,
    audience: str,
    version: str,
    year: int | None,
    zoom: int,
    x: int,
    y: int,
    *,
    observation: dict[str, object] | None = None,
) -> bytes:
    path = tile_artifact_path(user_id, audience, version, year, zoom, x, y)
    payload = _read_png(path)
    if payload is not None:
        if observation is not None:
            observation.update(
                cache_status="artifact_hit",
                source="disk",
                source_point_count=None,
                output_bytes=len(payload),
            )
        return payload

    from app.user.service_heatmap_tiles import get_user_heatmap_tile

    tile_observation: dict[str, object] = {}
    payload = get_user_heatmap_tile(
        db,
        user_id,
        zoom,
        x,
        y,
        year=year,
        color="red",
        include_private=audience == "owner",
        observation=tile_observation,
    )
    # generation 可能在渲染期间推进；旧请求不得在清理任务后重新落盘旧私有数据。
    with _artifact_mutation_lock(user_id):
        validate_current_artifact_version(db, user_id, audience, version)
        _write_png(path, payload)
    if observation is not None:
        observation.update(
            cache_status=f"artifact_miss_{tile_observation.get('cache_status', 'unknown')}",
            source=tile_observation.get("source", "unknown"),
            source_point_count=tile_observation.get("source_point_count"),
            output_bytes=len(payload),
            source_duration_ms=tile_observation.get("duration_ms"),
        )
    return payload


def _crop_parent_tile(payload: bytes, delta: int, relative_x: int, relative_y: int) -> bytes:
    with Image.open(BytesIO(payload)) as source:
        rgba = source.convert("RGBA")
        width, height = rgba.size
        scale = 1 << delta
        left = relative_x * width / scale
        upper = relative_y * height / scale
        right = (relative_x + 1) * width / scale
        lower = (relative_y + 1) * height / scale
        cropped = rgba.crop((left, upper, right, lower)).resize(
            (width, height),
            Image.Resampling.BILINEAR,
        )
        erosion_size = 4 * (scale - 1) + 1
        if erosion_size % 2 == 0:
            erosion_size += 1
        if erosion_size > 1:
            cropped.putalpha(
                cropped.getchannel("A").filter(ImageFilter.MinFilter(erosion_size))
            )
        output = BytesIO()
        cropped.save(output, format="PNG", optimize=True)
        return output.getvalue()


def get_fallback_tile_artifact(
    db,
    user_id: int,
    audience: str,
    version: str,
    year: int | None,
    zoom: int,
    x: int,
    y: int,
    *,
    base_max_zoom: int = 15,
    observation: dict[str, object] | None = None,
) -> bytes:
    if zoom <= base_max_zoom:
        return get_live_tile_artifact(
            db, user_id, audience, version, year, zoom, x, y,
            observation=observation,
        )
    path = tile_artifact_path(
        user_id, audience, version, year, zoom, x, y, fallback=True
    )
    payload = _read_png(path)
    if payload is not None:
        if observation is not None:
            observation.update(
                cache_status="fallback_artifact_hit",
                source="disk",
                source_point_count=None,
                output_bytes=len(payload),
            )
        return payload

    parent_zoom = base_max_zoom
    delta = zoom - parent_zoom
    scale = 1 << delta
    parent_x = x // scale
    parent_y = y // scale
    parent_observation: dict[str, object] = {}
    parent = get_live_tile_artifact(
        db, user_id, audience, version, year, parent_zoom, parent_x, parent_y,
        observation=parent_observation,
    )
    payload = _crop_parent_tile(
        parent,
        delta,
        x - parent_x * scale,
        y - parent_y * scale,
    )
    with _artifact_mutation_lock(user_id):
        validate_current_artifact_version(db, user_id, audience, version)
        _write_png(path, payload)
    if observation is not None:
        observation.update(
            cache_status=(
                "fallback_artifact_miss_"
                f"{parent_observation.get('cache_status', 'unknown')}"
            ),
            source=f"parent_{parent_observation.get('source', 'unknown')}",
            source_point_count=parent_observation.get("source_point_count"),
            output_bytes=len(payload),
            source_duration_ms=parent_observation.get("source_duration_ms"),
        )
    return payload


def enqueue_base_tile_prewarm(
    user_id: int,
    generation: int,
    version: str,
    year: int | None,
    coordinates: Iterable[tuple[int, int, int]],
) -> int:
    """幂等地把 z3-z15 分块放入低优先级队列；请求线程不做全量渲染。"""
    year_part = str(year) if year is not None else "all"
    marker = (
        f"{_PREWARM_MARKER_PREFIX}user_{user_id}:g{generation}:"
        f"year_{year_part}:v_{version}"
    )
    redis_client = _redis_client()
    try:
        claimed = redis_client.set(
            marker,
            b"1",
            ex=_PREWARM_MARKER_TTL_SEC,
            nx=True,
        )
    except Exception:
        return 0
    if not claimed:
        return 0

    jobs = [tuple(map(int, item)) for item in coordinates]
    chunks = [
        jobs[index:index + _PREWARM_CHUNK_SIZE]
        for index in range(0, len(jobs), _PREWARM_CHUNK_SIZE)
    ]
    try:
        from app.queue import heatmap_tiles_queue

        for index, chunk in enumerate(chunks):
            job_id = (
                f"heatmap-artifact-v1-user-{user_id}-g{generation}-"
                f"year-{year_part}-v-{version}-part-{index}"
            )
            existing = heatmap_tiles_queue.fetch_job(job_id)
            if existing is not None:
                status = existing.get_status(refresh=True)
                status_value = getattr(status, "value", str(status))
                if status_value not in {"failed", "stopped", "canceled"}:
                    continue
                existing.delete()
            heatmap_tiles_queue.enqueue(
                "app.heatmap_web.service.prewarm_tile_chunk_task",
                int(user_id),
                int(generation),
                version,
                year,
                chunk,
                job_id=job_id,
                job_timeout=300,
                result_ttl=86400,
                failure_ttl=3600,
                retry=Retry(max=2, interval=[10, 60]),
            )
    except Exception:
        try:
            redis_client.delete(marker)
        except Exception:
            pass
        return 0
    return len(chunks)


def prewarm_tile_chunk_task(
    user_id: int,
    expected_generation: int,
    expected_version: str,
    year: int | None,
    coordinates: list[tuple[int, int, int]],
) -> dict:
    """RQ 子任务：只写可重建的 owner/red PNG，不修改业务数据。"""
    from app.database import SessionLocal
    from app.user.service_heatmap_tiles import get_user_heatmap_tile_manifest

    redis_client = _redis_client()
    try:
        generation = int(
            redis_client.get(f"heatmap:generation:user_{int(user_id)}") or 0
        )
    except Exception:
        return {"status": "redis-unavailable", "generated": 0}
    if generation != int(expected_generation):
        return {"status": "stale", "generated": 0}

    db = SessionLocal()
    try:
        manifest = get_user_heatmap_tile_manifest(
            db,
            int(user_id),
            year=year,
            include_private=True,
            min_zoom=3,
            max_zoom=15,
        )
        if manifest["cache_version"] != expected_version:
            return {"status": "stale", "generated": 0}
        generated = 0
        for zoom, x, y in coordinates:
            get_live_tile_artifact(
                db,
                int(user_id),
                "owner",
                expected_version,
                year,
                int(zoom),
                int(x),
                int(y),
            )
            generated += 1
        return {"status": "warmed", "generated": generated}
    finally:
        db.close()
