"""热图缓存写后失效回归：所有活动完成/删除入口都必须在 commit 后清缓存。"""

import inspect

from app.activity import service as activity_service
from app.activity import worker as activity_worker
from app.strava import import_scheduler, service_sync, worker_strava


def _assert_commit_before_heatmap_invalidation(function) -> None:
    source = inspect.getsource(function)
    invalidate_at = source.rfind("invalidate_heatmap_cache")
    assert invalidate_at >= 0, f"{function.__module__}.{function.__name__} 漏清 heatmap cache"
    commit_at = source.rfind("db.commit()", 0, invalidate_at)
    assert commit_at >= 0, f"{function.__module__}.{function.__name__} 必须提交后再清 heatmap cache"


def test_activity_write_paths_invalidate_heatmap_after_commit():
    _assert_commit_before_heatmap_invalidation(activity_worker._do_parse)
    _assert_commit_before_heatmap_invalidation(worker_strava.process_strava_webhook_update)
    _assert_commit_before_heatmap_invalidation(worker_strava._process_strava_main)
    _assert_commit_before_heatmap_invalidation(import_scheduler._run_tier2)


def test_activity_delete_paths_invalidate_heatmap_after_commit():
    _assert_commit_before_heatmap_invalidation(activity_service.delete_activity)
    _assert_commit_before_heatmap_invalidation(service_sync.handle_webhook_event)
