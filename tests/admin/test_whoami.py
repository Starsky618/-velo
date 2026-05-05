"""admin whoami endpoint 测试。"""


def test_whoami_admin_returns_200_with_is_admin_true(client, admin_header):
    """管理员 token 应能读取自己的 admin 身份。"""
    res = client.get("/api/admin/whoami", headers=admin_header)

    assert res.status_code == 200
    data = res.json()
    assert data["is_admin"] is True
    assert "user_id" in data
    assert "nickname" in data
    assert "created_at" in data


def test_whoami_normal_user_403(client, auth_header):
    """普通用户应被 require_admin 拦截。"""
    res = client.get("/api/admin/whoami", headers=auth_header)

    assert res.status_code == 403


def test_whoami_no_token_401(client):
    """没有 token 时应先由登录依赖返回 401。"""
    res = client.get("/api/admin/whoami")

    assert res.status_code == 401
