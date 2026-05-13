# 任务 0.3：ensure_valid_token 未绑定路径

## 🎯 目标

`ensure_valid_token` 入口加未绑定 Strava 校验：`if user.strava_refresh_token is None: raise UnboundStravaError`——避免内部去 refresh 一个 NULL token 触发底层 API 报错。

## ⛓ 前置依赖

task-0.2（签名改造完成后再加新分支，避免 merge 冲突）。

## 📤 输出契约

| 产出 | 用途 |
|------|------|
| 新异常 `UnboundStravaError` | client.py / scheduler 等调用方 catch 后转 4xx |
| 入口校验：refresh_token NULL → raise | 防底层 API 误报 |

## 🧱 现状（grep 已验证）

- `app/user/models.py:73-79` `strava_refresh_token = Column(String(256), nullable=True)`
- `app/strava/service.py:388 ensure_valid_token` 当前**无未绑定校验**——若 user.strava_refresh_token 为 NULL，函数会直接走到 refresh API 调用，报"NULL refresh_token"或 401，错误信息混淆
- 现有调用栈：未绑定用户调 `/api/strava/import-progress` 等接口时，client.py 会先调 ensure_valid_token，没校验直接进 refresh 失败

## 🛠 完整代码

### `app/strava/exceptions.py`（新建或追加现有）

```python
class UnboundStravaError(Exception):
    """用户未绑定 Strava（strava_refresh_token IS NULL）→ 调用方应转 400 提示用户去绑定。"""
    pass
```

### `app/strava/service.py`

```diff
+ from app.strava.exceptions import UnboundStravaError
  
  def ensure_valid_token(db: Session, user_id: int, force: bool = False) -> tuple[User, str]:
      user = (
          db.query(User)
          .filter(User.id == user_id)
          .with_for_update()
          .first()
      )
      if user is None:
          raise ValueError(f"user_id={user_id} 不存在")
+     
+     # task-0.3：未绑定路径明确化，避免底层 API 误报
+     if user.strava_refresh_token is None:
+         raise UnboundStravaError(f"user_id={user_id} 未绑定 Strava")
      
      # ... 其余 refresh 逻辑不变
```

### `app/strava/router.py`（caller 转 400）

凡是调用 ensure_valid_token / StravaClient 的 endpoint，加 except 翻译：

```diff
+ from app.strava.exceptions import UnboundStravaError
  
  @router.get("/import-progress")
  def import_progress(...):
      try:
          # ... 原逻辑
+     except UnboundStravaError:
+         raise HTTPException(400, detail="未绑定 Strava 账号，请先去设置页绑定")
```

类似处理 `/api/strava/manual-sync` / `/api/strava/disconnect` 等所有进 client 的 endpoint。

## ✅ 测试

```python
# tests/test_strava_unbound.py 新增
def test_ensure_valid_token_unbound_raises(db_session, user_factory):
    user = user_factory(strava_refresh_token=None)
    with pytest.raises(UnboundStravaError):
        ensure_valid_token(db_session, user.id)


def test_import_progress_unbound_returns_400(client, user_factory, auth_headers):
    user = user_factory(strava_refresh_token=None)
    res = client.get("/api/strava/import-progress", headers=auth_headers(user))
    assert res.status_code == 400
    assert "未绑定" in res.json()["detail"]
```

## 📝 commit

```
feat(strava): 任务 0.3 ensure_valid_token 未绑定路径

入口加 if user.strava_refresh_token is None: raise UnboundStravaError
新建 app/strava/exceptions.py UnboundStravaError 类
router 层 catch 转 400 友好提示，不再让底层 API 误报混淆
```

## 🔍 自检三问

1. **边界**：refresh_token = ""（空串而不是 NULL）会被当未绑定吗？  
   → `is None` 不捕空串。但项目约定空串视为已绑定（不是常态）；若需更严，改 `if not user.strava_refresh_token`（陷阱 #1 truthiness 例外：空字符串等价于未绑定语义合法）。本 task 保守用 `is None`。

2. **下游波及**：所有 endpoint 都加 except 翻译了吗？  
   → grep `ensure_valid_token\|StravaClient(` 找出所有 router 入口，每处加 except UnboundStravaError → 400。

3. **scheduler 中如何处理**：scheduler.py 跑批量导入碰到未绑定怎么办？  
   → scheduler 应跳过未绑定 user（改成 logger.info 跳过 + 不重试）。task 0.5 同步处理。
