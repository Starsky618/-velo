"""
数据库连接与 session 管理

这是整个后端的"总配电箱"——所有需要读写数据库的模块都从这里获取连接。
自己不处理业务逻辑，只负责：
1. 创建数据库连接（engine）
2. 提供 session 工厂（SessionLocal）——每次需要操作数据库时"借一把钥匙"
3. 提供 Base 基类——所有数据表模型的"祖先"，后续 models.py 都继承它

全同步设计：API 路由和 rq Worker 共用同一套 session 逻辑，
不用维护两套（同步+异步），代码复杂度减半。
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

# 创建数据库引擎——相当于打通了程序到数据库的"管道"
# pool_pre_ping=True：每次从连接池借连接前先"敲一下门"，
# 确认连接还活着，避免用到已断开的死连接
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

# session 工厂——每次调用 SessionLocal() 就会生产一个新的数据库会话
# 可以理解为"钥匙复制机"，需要操作数据库时复制一把钥匙，用完归还
# autocommit=False：不自动提交，需要手动 commit，防止写到一半的数据被提交
# autoflush=False：不自动刷新，避免在查询时意外触发未提交的写入
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# 所有数据表模型的"祖先类"
# 后续每个模块的 models.py 都会写 class User(Base)、class Activity(Base) 等
# 这样 SQLAlchemy 就知道这些类对应数据库里的哪张表
Base = declarative_base()


def get_db():
    """
    FastAPI 的依赖注入函数——"借钥匙"机制。

    工作流程就像图书馆借书：
    1. 进门时自动借一把钥匙（创建 session）
    2. 用钥匙开柜子读写数据（在路由函数中使用）
    3. 离开时自动还钥匙（关闭 session）

    用法：在路由函数参数里写 db: Session = Depends(get_db)
    rq Worker 不走这个机制，直接用 SessionLocal() 创建 session。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
