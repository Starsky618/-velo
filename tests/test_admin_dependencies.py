"""admin 权限依赖测试。"""

import pytest
from fastapi import HTTPException

from app.admin.dependencies import require_admin
from app.user.models import User


def test_require_admin_grants_admin_user(db):
    """管理员像拿到后台门禁卡的人，能通过 require_admin 检查。"""
    admin = User(openid="admin_dep_openid", is_admin=True)
    db.add(admin)
    db.commit()
    db.refresh(admin)

    result = require_admin(user_id=admin.id, db=db)

    assert result.id == admin.id
    assert result.is_admin is True


def test_require_admin_rejects_normal_user_403(db, test_user):
    """普通用户没有后台门禁卡，访问 admin 依赖时应被 403 拦下。"""
    with pytest.raises(HTTPException) as exc_info:
        require_admin(user_id=test_user.id, db=db)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "需要管理员权限"


def test_require_admin_rejects_missing_user_403(db):
    """JWT 里的用户如果库里不存在，也不能被当成管理员放行。"""
    with pytest.raises(HTTPException) as exc_info:
        require_admin(user_id=999999, db=db)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "需要管理员权限"
