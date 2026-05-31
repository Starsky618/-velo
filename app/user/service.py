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
    get_active_users,
    get_city_medals,  # Sprint 6 task-3：城市征服勋章聚合（自他对称入口）
    get_user_badges,  # Sprint 6 task-2：身份徽章计算（自他对称入口）
    get_user_heatmap,
    get_user_profile_for_others,
    invalidate_heatmap_cache,
    update_user_city,
)


def delete_user(db, user_id: int) -> None:
    """删除用户前先收拾约骑生态：OPEN 取消，DRAFT 硬删，然后删用户本体。"""
    from datetime import datetime, timezone

    from app.meetup.models import Meetup
    from app.meetup.service import _cleanup_meetup_storage, _delete_meetup_row_and_collect_files
    from app.user.models import User

    # 三步在同一事务内做完后一次性 commit 保证原子（cancel OPEN → 硬删 DRAFT → 删 user）。
    # 不用 with db.begin()：真实注销端点注入的 session 已因身份查询触发 autobegin，
    # 再 with db.begin() 二次开启事务会抛 InvalidRequestError 500；和项目其他 service 统一用末尾单次 db.commit()。
    file_ids = []
    open_meetups = db.query(Meetup).filter(Meetup.creator_id == user_id, Meetup.status == "OPEN").all()
    for meetup in open_meetups:
        meetup.status = "CANCELLED"
        meetup.cancelled_at = datetime.now(timezone.utc)

    draft_ids = [
        row.id
        for row in db.query(Meetup.id).filter(Meetup.creator_id == user_id, Meetup.status == "DRAFT").all()
    ]
    for meetup_id in draft_ids:
        file_ids.extend(_delete_meetup_row_and_collect_files(db, meetup_id))

    user = db.query(User).filter(User.id == user_id).first()
    if user is not None:
        db.delete(user)

    db.commit()
    # commit 后再删物理文件（DB 是 source of truth）：删失败只记日志，不回滚已删的账号数据。
    _cleanup_meetup_storage(file_ids)
