"""
用户模块的业务逻辑层——真正干活的地方。

如果 router.py 是前台接待员（接收请求、返回结果），
那 service.py 就是后台办事员（处理业务、操作数据库）。

前台不直接碰数据库，所有脏活累活都交给这里。
这样做的好处：前台只管接客，后台只管办事，各司其职，方便测试和替换。

注意事项：
- 所有数据库操作都在这里完成，router 层不直接操作数据库
- 距离单位转换（米→公里）也在这里做，router 层拿到的就是最终数据
- 不要在这里 import router 或 schemas（避免循环依赖）
"""

from datetime import datetime, timedelta, timezone

import httpx
import jwt
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.config import settings
from app.user.models import User

# 北京时间偏移量（UTC+8）
# 统计"本周""本月"等时间范围时，要用用户所在时区的零点做分界，
# 而不是 UTC 零点。比如周一凌晨 0 点北京时间 = 周日下午 4 点 UTC。
BEIJING_TZ = timezone(timedelta(hours=8))

# JWT 配置
# HS256 是一种对称加密算法——用同一把钥匙签名和验证
# 对 MVP 阶段完全够用，简单可靠
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 7


def wx_code_to_openid(code: str) -> str:
    """
    拿微信授权 code 去微信服务器换取用户的 openid。

    流程就像：用户拿着一张"临时号码牌"（code）来前台，
    前台打电话给微信总部确认："这个号码牌是真的吗？对应哪个用户？"
    微信总部回复："是真的，这个人的身份编号是 xxx（openid）。"

    code 是一次性的，用过就作废，5分钟内有效。
    """
    # 调用微信 jscode2session 接口
    # 网络异常（超时、连接失败等）统一包装为 ValueError，
    # 让 router 层能用同一个 except ValueError 捕获所有错误
    try:
        resp = httpx.get(
            "https://api.weixin.qq.com/sns/jscode2session",
            params={
                "appid": settings.WX_APPID,
                "secret": settings.WX_SECRET,
                "js_code": code,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        data = resp.json()
    except httpx.HTTPError:
        raise ValueError("微信授权失败")

    # 微信返回 errcode 表示出错
    if "errcode" in data and data["errcode"] != 0:
        # errcode 40029 表示 code 过期或无效
        if data["errcode"] == 40029:
            raise ValueError("code已过期，请重新授权")
        raise ValueError("微信授权失败")

    openid = data.get("openid")
    if not openid:
        raise ValueError("微信授权失败")

    return openid


def get_or_create_user(db: Session, openid: str) -> tuple[User, bool]:
    """
    用 openid 查找用户，找到就返回，找不到就新建一个。

    返回值是一个元组：(用户对象, 是否是新用户)
    就像小区门卫查花名册：名字在册就放行，不在册就登记一个新住户。
    """
    user = db.query(User).filter_by(openid=openid).first()
    if user:
        return user, False

    # 新用户：只记录 openid，其他信息（昵称、头像等）后续通过编辑资料填写
    user = User(openid=openid)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, True


def create_token(user_id: int) -> str:
    """
    给用户签发一张 JWT "通行证"。

    JWT 就像一张带防伪标记的临时工牌：
    - 上面写着你的工号（user_id）和有效期（7天）
    - 盖了公司的章（用 JWT_SECRET 签名）
    - 任何人拿到这张工牌都能看到上面的信息，但没有公章就伪造不了
    """
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),  # sub 是 JWT 标准字段，表示"这张证属于谁"
        "exp": expire,        # 过期时间，到期后自动作废
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> int:
    """
    验证并解析 JWT，返回 user_id。

    就像门卫检查工牌：看防伪标记对不对、有没有过期。
    通过了就放行（返回工号），不通过就拦下（抛异常）。
    """
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[JWT_ALGORITHM])
    user_id_str = payload.get("sub")
    if user_id_str is None:
        raise ValueError("无效凭证")
    return int(user_id_str)


# ========== 任务 2.4：用户资料 ==========

def get_user_by_id(db: Session, user_id: int) -> User:
    """
    根据 user_id 查找用户。
    找不到说明数据异常（JWT 里的 id 在数据库里不存在），直接抛异常。
    """
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise ValueError("用户不存在")
    return user


def update_user_profile(db: Session, user_id: int, update_data: dict) -> User:
    """
    更新用户资料。

    只更新前端传过来的字段，没传的保持不变。
    就像修改住户档案：只改你说要改的栏目，其他栏目原样保留。
    """
    user = get_user_by_id(db, user_id)

    # 遍历要更新的字段，逐个修改
    for field, value in update_data.items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


# ========== 任务 2.5：骑行统计 ==========

def _get_period_start(period: str) -> datetime | None:
    """
    根据统计范围，计算起始时间点（北京时间零点，转为 UTC）。

    比如 period="week"：找到本周一的北京时间 00:00:00，再转成 UTC 存储时间。
    period="all" 返回 None，表示不加时间条件。
    """
    # 先拿当前北京时间
    now_bj = datetime.now(BEIJING_TZ)

    if period == "week":
        # weekday() 返回 0=周一, 6=周日
        # 先把时分秒归零得到"今天零点"，再往前退 weekday 天得到本周一零点
        # 例：北京时间 2026-04-08 周三 → weekday()=2 → 退2天 → 2026-04-06 周一 00:00 UTC+8
        today_start = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
        monday = today_start - timedelta(days=now_bj.weekday())
        return monday.astimezone(timezone.utc)
    elif period == "month":
        first_day = now_bj.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return first_day.astimezone(timezone.utc)
    elif period == "year":
        first_day = now_bj.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return first_day.astimezone(timezone.utc)
    else:
        # period == "all"
        return None


def get_user_stats(db: Session, user_id: int, period: str) -> dict:
    """
    聚合用户的骑行统计数据。

    直接用 SQL 查 activities 表，不 import Activity 模块的任何代码。
    这样 User 模块保持独立，不依赖 Activity 模块的实现细节。

    好比物业管理处直接看门禁刷卡记录统计出入次数，
    不需要去问住户"你今天进出了几次"。
    """
    # 构建 SQL：从 activities 表聚合已完成的骑行记录
    period_start = _get_period_start(period)

    # activities 表在 Task 3.1 才会创建，在此之前查询会报 ProgrammingError。
    # 捕获这个异常，返回全零数据，避免 500 错误。
    try:
        if period_start is not None:
            sql = text("""
                SELECT
                    COALESCE(SUM(distance), 0)       AS distance,
                    COUNT(*)                         AS rides,
                    COALESCE(SUM(elevation_gain), 0) AS elevation_gain,
                    COALESCE(SUM(duration), 0)       AS duration
                FROM activities
                WHERE user_id = :user_id
                  AND status = 'completed'
                  AND started_at >= :period_start
            """)
            row = db.execute(sql, {"user_id": user_id, "period_start": period_start}).fetchone()
        else:
            # period == "all"：不加时间条件
            sql = text("""
                SELECT
                    COALESCE(SUM(distance), 0)       AS distance,
                    COUNT(*)                         AS rides,
                    COALESCE(SUM(elevation_gain), 0) AS elevation_gain,
                    COALESCE(SUM(duration), 0)       AS duration
                FROM activities
                WHERE user_id = :user_id
                  AND status = 'completed'
            """)
            row = db.execute(sql, {"user_id": user_id}).fetchone()

        distance_m = float(row.distance)
        rides = int(row.rides)
        elevation_gain = float(row.elevation_gain)
        duration = int(row.duration)
    except ProgrammingError:
        # activities 表尚未创建，回滚事务（ProgrammingError 会让当前事务失效），返回全零
        db.rollback()
        distance_m = 0.0
        rides = 0
        elevation_gain = 0.0
        duration = 0

    # 距离：米 → 公里，保留 1 位小数
    distance_km = round(distance_m / 1000.0, 1)

    # 获取用户的周目标
    # 防御性处理：server_default 在 ORM 创建后 refresh 才生效，极端情况可能为 None
    user = get_user_by_id(db, user_id)
    weekly_goal = float(user.weekly_goal) if user.weekly_goal is not None else 200.0

    # 完成百分比：distance_km / weekly_goal * 100，向下取整
    goal_percent = int(distance_km / weekly_goal * 100) if weekly_goal > 0 else 0

    return {
        "period": period,
        "distance": distance_km,
        "rides": rides,
        "elevation_gain": elevation_gain,  # 爬升单位是米，直接返回，不做转换
        "duration": duration,
        "weekly_goal": weekly_goal,
        "goal_percent": goal_percent,
    }


# ========== task-2.A.1 stub：power curve 缓存失效占位 ==========
# 真实现在 task-2.C.2（service 层 + Redis 缓存）/ 接进来后这个 stub 会被替换
# 现在只是占位让 worker 集成（status='completed' 后调）能正常 import + 调用不炸
# 不写真逻辑是因为 cache 还没建——还没建的 cache 没东西要 invalidate

def invalidate_power_curve_cache(user_id: int) -> None:
    """
    清除用户 power_curve 缓存——**task-2.A.1 stub / task-2.C.2 真实现**。

    用户上传新 activity → 上月最佳功率可能变化 → 下次查 power_curve 要重算。
    清缓存让下次查时 cache miss 走真实计算。

    现在是空 stub，因为 cache 系统在 task-2.C.2 才建（Redis 缓存 power_curve:user_{id}:period_{p}）。
    保留空函数让 worker 集成路径稳定（worker 在 status='completed' 后调本函数 +
    detect_5min_power_progress 是 spec §3.4 钦定的两步动作 / 现在先把第二步打通）。

    task-2.C.2 实现后此 stub 会被替换为：
        for period in ('this_month', 'last_month', 'this_year', 'last_year', 'all_time'):
            REDIS_CLIENT.delete(f'power_curve:user_{user_id}:period_{period}')
    """
    # 故意空实现 / 不抛错 / 不写日志（避免无意义的"清了空缓存"日志噪音）
    return None
