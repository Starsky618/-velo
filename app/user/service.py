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
from jose import jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.user.models import User

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
