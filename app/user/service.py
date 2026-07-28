"""
用户模块业务逻辑层主入口——"前台总台"。

本文件在 v5 task-user-split-001 中完成物理拆分（834 行红灯 → 4 文件）：
- 微信登录 / JWT 鉴权 / 用户 CRUD → service_auth.py
- 骑行统计 / 功率曲线 / cache → service_stats.py
- 热图 / 城市 / 看他人主页 / 探索骑友 → service_social.py
- 本文件保留共享 doc + 转导出（re-export）所有 public API，对外契约 0 改动

调用方按 `from app.user.service import xxx` 继续工作（含 app.dependencies.decode_token
+ app.activity.worker.invalidate_xxx + tests.test_user 的 mock patch path），
不必感知文件分拆细节。

整体职责分层（类比"小区物业"）：
- service_auth.py = 大门口的门卫 + 户籍登记处
- service_stats.py = 物业的"住户健康报表"（骑行 + 功率曲线）
- service_social.py = 物业的"住户名片簿 + 邻居通讯录"

注意事项：
- 所有数据库操作都在子文件完成，router 层不直接操作数据库
- 距离单位转换（米→公里）在 service 层做（API 返回的就是 km）
- 不要在子文件 import router 或 schemas（避免循环依赖）
- 跨子文件依赖严格单向：service_stats → service_auth.get_user_by_id（拿 weekly_goal）
- BEIJING_TZ + _get_redis_client 在 stats + social 各自独立复制（Q1 a 决策 / 不抽共享）
"""

# v5 task-user-split-001：service.py 834 行红灯 → 拆 4 文件，对外契约不变
# 调用方按 `from app.user.service import xxx` 继续工作，不必感知文件分拆细节
from app.user.service_auth import (  # noqa: F401 — 转导出
    create_token,
    decode_token,
    get_or_create_user,
    get_user_by_id,
    update_user_profile,
    wx_code_to_openid,
)
from app.user.service_stats import (  # noqa: F401 — 转导出
    get_user_power_curve,
    get_user_stats,
    invalidate_power_curve_cache,
)
from app.user.service_social import (  # noqa: F401 — 转导出
    InvalidHeatmapViewport,
    get_active_users,
    get_city_medals,  # Sprint 6 task-3：城市征服勋章聚合（自他对称入口）
    get_user_badges,  # Sprint 6 task-2：身份徽章计算（自他对称入口）
    get_user_heatmap,
    get_user_profile_for_others,
    invalidate_heatmap_cache,
    update_user_city,
)
from app.user.service_heatmap_tiles import (  # noqa: F401 — 转导出
    InvalidHeatmapTile,
    get_user_heatmap_tile,
)


def delete_user(db, user_id: int) -> None:
    """注销用户：删除账号及关联私有数据，创建的全部路书和已开放约骑去标识保留。

    骑行、赛段成绩、功率突破、Strava 记录和约骑草稿物理删除；所有路线定义保留为无主，
    已开放约骑取消后保留给参与者查看，创建者关联由外键 SET NULL 清除。

    删除顺序很关键：users.id 有一批"挡路"的外键引用——activities / segment_efforts /
    breakthrough_events / strava_imports 的 user_id 都是 RESTRICT（没有 ON DELETE CASCADE），
    不先把这些子行删掉，最后 db.delete(user) 会被外键约束挡住抛 500（旧版只删约骑就踩这个坑）。
    breakthrough_events.activity_id 也是 RESTRICT，会挡住删 activities，所以它要在 activities 之前删。
    路书（route_books.creator_id）是 SET NULL：作为可被别人约骑引用的共享路线定义保留为"无主"，
    符合 spec"路书保留"原则，不随注销物理删。

    全程单事务、末尾一次提交保证原子（注销端点注入的 session 已 autobegin，
    禁止二次开启事务——见技术栈陷阱 #21，否则抛 InvalidRequestError）。"""
    from datetime import datetime, timezone

    from sqlalchemy import or_

    from app.activity.models import Activity, BreakthroughEvent
    from app.meetup.models import Meetup, MeetupActivity
    from app.meetup.service import _cleanup_meetup_storage, _delete_meetup_row_and_collect_files
    from app.route_book.models import RouteBookSaveRequest
    from app.segment.models import SegmentEffort
    from app.strava.models import StravaImport
    from app.user.models import User

    # commit 成功后再物理删的文件：约骑照片 + 活动 GPX 同在 uploads 存储后端，统一收集一次清理。
    storage_files = []

    # 1) 约骑：OPEN 取消（保留给已报名的人看到"已取消"）、DRAFT 硬删并收集照片文件。
    #    creator_id 在删 user 时由外键 SET NULL 置空——已取消的约骑作为"无主记录"留给参与者。
    open_meetups = db.query(Meetup).filter(Meetup.creator_id == user_id, Meetup.status == "OPEN").all()
    for meetup in open_meetups:
        meetup.status = "CANCELLED"
        meetup.cancelled_at = datetime.now(timezone.utc)
    draft_ids = [
        row.id
        for row in db.query(Meetup.id).filter(Meetup.creator_id == user_id, Meetup.status == "DRAFT").all()
    ]
    for meetup_id in draft_ids:
        storage_files.extend(_delete_meetup_row_and_collect_files(db, meetup_id))

    # 2) 先拿到该用户所有活动的 id + GPX 文件路径（删行后就查不到了，breakthrough 兜底和文件清理都要用）。
    activity_rows = db.query(Activity.id, Activity.file_url).filter(Activity.user_id == user_id).all()
    activity_ids = [r.id for r in activity_rows]
    storage_files.extend(r.file_url for r in activity_rows if r.file_url)

    # 3) 显式删 RESTRICT 阻塞子行（不靠 DB 级联，SQLite 测试也能验、行为确定）。
    db.query(SegmentEffort).filter(SegmentEffort.user_id == user_id).delete(synchronize_session=False)
    # breakthrough_events 被 user_id 和 activity_id 两个 RESTRICT 外键约束：正常数据二者一致（突破事件
    # 属于活动 owner），但为防脏数据（user_id 与活动 owner 不一致）删活动时被 activity_id RESTRICT 挡住抛 500，
    # 两个方向都兜底删（Codex 异源审 I1）。
    bt_filter = BreakthroughEvent.user_id == user_id
    if activity_ids:
        bt_filter = or_(bt_filter, BreakthroughEvent.activity_id.in_(activity_ids))
    db.query(BreakthroughEvent).filter(bt_filter).delete(synchronize_session=False)
    db.query(StravaImport).filter(StravaImport.user_id == user_id).delete(synchronize_session=False)
    # 手画路线保存账本含用户幂等凭据；路书本身保留为无主定义，但个人账本随账号注销清除。
    # PG 的 ON DELETE CASCADE 是兜底，这里显式删让 SQLite 测试与生产语义一致。
    db.query(RouteBookSaveRequest).filter(
        RouteBookSaveRequest.creator_id == user_id
    ).delete(synchronize_session=False)
    # meetup_activities（约骑交卷格子）在 PG 由 user_id/activity_id 双 CASCADE 自动清，这里仍显式删：
    # 注销是隐私关键路径，显式删让 PG/SQLite 两方言行为一致、测试可断言（Sprint 13 T1 双审 I2）。
    db.query(MeetupActivity).filter(MeetupActivity.user_id == user_id).delete(synchronize_session=False)

    # 4) 删骑行活动行（trackpoints / activity_privacy / segment_efforts 由 activity_id 的
    #    ON DELETE CASCADE 在 PG 自动级联清理）。
    db.query(Activity).filter(Activity.user_id == user_id).delete(synchronize_session=False)

    # 5) 删 user 本体：daily_training_load / meetup_participants / notifications(recipient) 由
    #    user_id 的 ON DELETE CASCADE 自动级联（meetup_activities 已在第 3 步显式删）；
    #    meetups / route_books 的 creator_id 等 SET NULL。
    user = db.query(User).filter(User.id == user_id).first()
    if user is not None:
        db.delete(user)

    db.commit()
    # commit 后再删物理文件（DB 是 source of truth）：删失败只记日志，不回滚已删的账号数据。
    _cleanup_meetup_storage(storage_files)
