"""
解析器入口 activity_type 分流测试（第 4 期 task-7.7 种子 3）。

这个文件验证 `parse_activity` 的入口分流逻辑：
- 拿到任务后先看 activity.activity_type 字段
- 只有 'cycling' 走完整解析流程（下载文件 / 翻译 / 写 DB）
- 其他类型（running / 未知类型）直接置 failed，连文件都不下载

为什么分三个用例：
1. cycling 正常放行——证明岔路口不影响现有流程
2. running 明确拒绝——证明分流生效，且省掉了文件 I/O
3. 未知类型（skydiving）兜底拒绝——证明用"!= cycling"判断而不是枚举黑名单
   （== 'cycling' 的白名单思路更稳：未来冒出陌生值也会被拦住）

类比：这是机场安检在登机口前的"目的地检查"——牌子写着"飞北京"的才放行，
其他牌子（飞上海、无牌）一律拒登机。本期只开通了北京航线。

测试基础设施说明：
parse_activity 内部调 SessionLocal() 自建 session（真 PostgreSQL 配置），
而测试环境是 SQLite。所以必须 patch SessionLocal，让它返回 conftest 的 db fixture，
并让 db.close() 空操作（避免测试 session 被提前关闭）。
"""

from unittest.mock import patch, MagicMock

from app.activity.models import Activity
from app.activity.worker import parse_activity


def _make_session_factory(db):
    """构造一个"伪 SessionLocal"：调用时返回 db，close() 被吞掉。

    真的 SessionLocal 每次调用都返回新 session，这里我们固定返回测试 db。
    同时劫持 close——测试结束前不能真的关，否则 conftest 的清理逻辑会失败。
    """
    wrapped = MagicMock(wraps=db)
    wrapped.close = MagicMock()  # 吞掉 close，保持测试 session 存活
    return MagicMock(return_value=wrapped)


# ==================== cycling 正常放行 ====================

def test_cycling_activity_goes_full_path(db, test_user):
    """activity_type='cycling' 应走完整解析流程，不会在分流点被拦下。

    策略：不验证完整的解析结果（那是 worker 本身的测试范畴），
    只验证"分流没拦住它"——也就是文件下载被触发了、save_parse_result 被调用了。
    把 save_parse_result 整体 mock 掉，避开 JSONB/Trackpoint 写入在 SQLite 下的兼容问题。
    """
    activity = Activity(
        user_id=test_user.id,
        title="Test Ride",
        status="pending",
        file_url="test.gpx",
        activity_type="cycling",
    )
    db.add(activity)
    db.commit()
    activity_id = activity.id

    with patch("app.activity.worker.SessionLocal", _make_session_factory(db)), \
         patch("app.activity.worker._storage") as mock_storage, \
         patch("app.activity.worker.GPXParser") as MockParser, \
         patch("app.activity.worker.normalize", side_effect=lambda x: x), \
         patch("app.activity.worker.save_parse_result") as mock_save:

        mock_storage.download.return_value = b"<gpx></gpx>"
        # parser.parse() 返回一个假的 result，只需有 .trackpoints（安全网用）
        fake_result = type("R", (), {"trackpoints": []})()
        MockParser.return_value.parse.return_value = fake_result

        parse_activity(activity_id)

        # 关键断言 1：文件下载被触发 → 证明流程穿过了分流点
        mock_storage.download.assert_called_once_with("test.gpx")
        # 关键断言 2：save_parse_result 被调用 → 证明走到了写 DB 步骤
        mock_save.assert_called_once()

    # 关键断言 3：cycling 活动最终状态是 completed
    db.refresh(activity)
    assert activity.status == "completed"


# ==================== 非 cycling 直接置 failed ====================

def test_non_cycling_activity_marked_failed(db, test_user):
    """activity_type='running' 应直接置 failed，且不触发文件下载（省 I/O）。"""
    activity = Activity(
        user_id=test_user.id,
        title="Test Run",
        status="pending",
        file_url="test.gpx",
        activity_type="running",
    )
    db.add(activity)
    db.commit()
    activity_id = activity.id

    with patch("app.activity.worker.SessionLocal", _make_session_factory(db)), \
         patch("app.activity.worker._storage") as mock_storage:
        parse_activity(activity_id)

        # 关键：文件 I/O 不应被触发——分流点在下载之前
        mock_storage.download.assert_not_called()

    db.refresh(activity)
    assert activity.status == "failed"
    assert activity.error_message is not None
    assert "running" in activity.error_message
    assert "不支持" in activity.error_message


def test_unknown_activity_type_marked_failed(db, test_user):
    """未知运动类型（未来扩展前的"乱写值"）也应兜底置 failed。

    这条用例守护"白名单思路"——只有明确是 cycling 才放行，
    其他一律拒绝，包括未来可能出现的陌生值。
    """
    activity = Activity(
        user_id=test_user.id,
        title="Test",
        status="pending",
        file_url="test.gpx",
        activity_type="skydiving",  # 故意乱写
    )
    db.add(activity)
    db.commit()
    activity_id = activity.id

    with patch("app.activity.worker.SessionLocal", _make_session_factory(db)), \
         patch("app.activity.worker._storage") as mock_storage:
        parse_activity(activity_id)
        mock_storage.download.assert_not_called()

    db.refresh(activity)
    assert activity.status == "failed"
    assert "skydiving" in activity.error_message
