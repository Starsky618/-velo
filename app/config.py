"""
应用配置管理

把所有环境变量集中在一个地方读取和管理，就像大楼的"总控制面板"——
各个系统（数据库、Redis、微信、JWT）的开关和参数都在这里统一设置，
其他模块要用配置时直接来这里拿，不用自己去翻环境变量。

pydantic-settings 会自动从 .env 文件或系统环境变量中读取值，
变量名不区分大小写，自动匹配。
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    所有配置项集中定义在这里。
    每个字段对应 .env 文件中的一个环境变量。
    如果环境变量没设置，就用这里写的默认值。
    """

    # 数据库连接地址
    # 格式：postgresql://用户名:密码@主机:端口/数据库名
    DATABASE_URL: str = "postgresql://velo:changeme@localhost:5432/velo"

    # Redis 连接地址（rq 任务队列用）
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT 签名密钥——用来给"通行证"盖章和验章
    # 生产环境必须换成随机长字符串，否则任何人都能伪造通行证
    JWT_SECRET: str = "change-me-to-a-random-secret"

    # 微信小程序凭证——调用微信接口换取用户信息时需要
    WX_APPID: str = ""
    WX_SECRET: str = ""

    # GPX 文件本地存储根目录
    UPLOAD_DIR: str = "./uploads"

    # Strava OAuth 凭证——调用 Strava API 时需要
    # 这三个值从 .env 文件读取，开发/生产环境各自配置
    STRAVA_CLIENT_ID: str = ""           # Strava API 应用 ID
    STRAVA_CLIENT_SECRET: str = ""       # Strava API 密钥
    STRAVA_REDIRECT_URI: str = ""        # OAuth 回调地址
    STRAVA_WEBHOOK_VERIFY_TOKEN: str = ""  # Webhook 订阅验证密钥
    # Webhook 订阅 ID——初次订阅 Strava Push Subscription 时 Strava 返回的 id
    # 用于 Webhook 事件真伪校验（payload 里带，不匹配则拒收）
    # 未配置时 POST /webhook 会返 503，防止裸奔
    STRAVA_WEBHOOK_SUBSCRIPTION_ID: str = ""

    class Config:
        # 告诉 pydantic-settings 从项目根目录的 .env 文件读取配置
        env_file = ".env"
        # 允许 .env 中有 Settings 未定义的变量（如 DB_PASSWORD），不报错
        extra = "ignore"


# 全局唯一的配置实例——整个应用都用这一个，不要重复创建
settings = Settings()
