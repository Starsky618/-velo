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
"""

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, func

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

    # 创建时间和更新时间
    # server_default 让数据库自动填入当前时间，不依赖 Python 端的时钟
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
