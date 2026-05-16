"""
用户数据模型——大楼的"住户登记簿"。

每个注册用户在数据库里就是这张表的一行记录，
记着他的微信身份（openid）、昵称、头像、骑行能力（FTP）等信息。

好比小区物业的住户档案：每户一张卡片，
写着门牌号（id）、身份证号（openid，微信的唯一标识）、联系方式等。

注意事项：
- openid 是微信给每个用户的唯一编号，不能重复
- ftp 和 weight 可以为空（用户可能还没填）
- is_admin 只能手动在数据库里改，不开放给普通接口
- 这个模型会被骑行模块（Activity）引用，建立"这条记录属于谁"的关系
- city 字段（v5）允许 NULL：未填写状态等价于"不参与按城市筛选/热图"，
  填值必须是 6 城枚举之一（防止脏数据混入热图聚合）
"""

from sqlalchemy import (
    Column, Integer, BigInteger, String, Float, Boolean, DateTime, Text,
    CheckConstraint, func,
)

from app.database import Base


class User(Base):
    """
    用户表——对应数据库中的 users 表。
    每个字段对应表里的一列。
    """

    # 表名：复数小写，符合项目命名规范
    __tablename__ = "users"

    # 主键：每个用户的唯一门牌号，数据库自动递增
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 微信 openid：用户在微信里的"身份证号"，全局唯一，不可重复
    # 用户登录时靠它来识别"你是谁"
    openid = Column(String(64), unique=True, nullable=False)

    # 昵称和头像：用户的公开信息
    nickname = Column(String(64), nullable=True)
    avatar_url = Column(Text, nullable=True)

    # FTP（Functional Threshold Power，功能阈值功率）
    # 骑行者的核心能力指标，单位是瓦（W）
    # 用来计算功率区间（Z1-Z6），判断骑行强度
    # 可以为空——新用户可能还不知道自己的 FTP
    ftp = Column(Integer, nullable=True)

    # 体重，单位公斤（kg），用于计算功率体重比等指标
    weight = Column(Float, nullable=True)

    # 车型：road（公路车）/ gravel（砾石车）/ mtb（山地车）
    bike_type = Column(String(20), nullable=True)

    # 每周骑行目标（公里），默认 200km
    # 前端首页会显示"本周进度 xx/200 km"
    # server_default 确保即使直接用 SQL 插入数据，也能拿到默认值
    weekly_goal = Column(Float, server_default="200.0")

    # 管理员标记：只有管理员才能创建赛段
    # v1 阶段不开放注册管理员，需要手动在数据库里把这个字段改成 True
    # server_default 确保非 ORM 路径插入时也默认为 False
    is_admin = Column(Boolean, server_default="false")

    # ===== Strava 绑定信息 =====
    # 用户绑定 Strava 后，这四个字段存储 OAuth 令牌信息
    # 好比你在一个翻译平台上绑定了谷歌账号：
    #   - athlete_id 是你在 Strava 那边的"门牌号"
    #   - access_token 是进门的"临时通行证"（有效期短，过期要换）
    #   - refresh_token 是"换通行证的凭据"（用它去 Strava 换新的 access_token）
    #   - token_expires_at 记着通行证什么时候过期
    # 未绑定 Strava 的用户这些字段全部为 NULL
    # strava_athlete_id 加 UNIQUE：一个 Strava 账号只能绑定一个系统用户，
    # 防止两个微信号绑同一个 Strava 造成数据混乱
    strava_athlete_id = Column(BigInteger, unique=True, nullable=True)
    strava_access_token = Column(String(255), nullable=True)
    strava_refresh_token = Column(String(255), nullable=True)
    # 用 DateTime(timezone=True) 让 PostgreSQL 使用 TIMESTAMP WITH TIME ZONE，
    # 这样存入和读出的都是带时区的 datetime，避免 naive vs aware 比较报 TypeError
    strava_token_expires_at = Column(DateTime(timezone=True), nullable=True)

    # ===== 免打扰开关（第 4 期种子字段）=====
    # NULL 表示"未设置"，False 表示"已设置为不静音"，True 表示"静音"
    # 本期前端不读写这字段，仅作为未来跨设备同步留位
    mute_notifications = Column(
        Boolean,
        nullable=True,
        comment="免打扰开关预留字段。本期仅字段存在，实际开关存前端本地",
    )

    # ===== 城市（第 5 期 task-0.6 + 2.C.1 完整启用）=====
    # 6 主城枚举 + 'unknown' 兜底，NULL 表示用户未填写
    # 用于：5.A.1 个人页热图按城市筛选 + admin 列表按城市分组
    # 防止脏数据混入：CHECK 约束要么 NULL 要么 7 个允许值之一
    # 注意 truthiness 陷阱（CLAUDE.md 陷阱 #1）：判"是否填写"用 `is not None`，
    # 不要用 `if user.city:`——'unknown' 也会是 truthy（已选了"我不在这 6 城"也算填了）
    city = Column(
        String(32),
        nullable=True,
        comment="所属城市：beijing/shanghai/hangzhou/shenzhen/chengdu/taiyuan/unknown 或 NULL",
    )

    # ===== 骑手签名 bio（Sprint 6 task-1）=====
    # 个性签名 / 一行短描述，"我的"页骑手名片展示。
    # 类比：微信"个性签名"——一行字让别人秒懂你是哪种骑手
    # （如"成都老登 / 公路党 / FTP 220W"）。
    # 长度：30 个字符上限（PostgreSQL varchar 按 Unicode codepoint 计 / 与 schema
    # max_length=30 完全对齐，防止绕过 API 走脚本直写超长 bio 污染数据层）。
    # nullable=True：用户可不填；空字符串("") 或 纯空格 "  " 在 service 层
    # 等价转 NULL，避免"看似填了实际空"的脏数据。
    bio = Column(String(30), nullable=True)

    # 创建时间和更新时间
    # server_default 让数据库自动填入当前时间，不依赖 Python 端的时钟
    # tz-aware（第 5 期 task-0.1）：统一时区元数据，避免 naive vs aware TypeError
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # city 必须 NULL 或 7 个枚举值之一（防脏数据进热图聚合）
        CheckConstraint(
            "city IS NULL OR city IN ('beijing', 'shanghai', 'hangzhou', "
            "'shenzhen', 'chengdu', 'taiyuan', 'unknown')",
            name="ck_users_city",
        ),
    )
