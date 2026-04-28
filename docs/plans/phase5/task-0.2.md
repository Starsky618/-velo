# 任务 0.2：ensure_valid_token 签名改造

## 🎯 目标

把 `ensure_valid_token` 的入参从 `User` 对象改为 `user_id: int`，返回值从单 token 改为 `(User, token)` 元组——让函数内部完整封装"行锁 user 行 + 刷 token + 返回锁后 user 实例"，调用方不必自己 query user。

## ⛓ 前置依赖

无。可与 Sprint 0 其他任务并行。

## 📤 输出契约

| 产出 | 用途 |
|------|------|
| `ensure_valid_token(db, user_id, force=False) -> tuple[User, str]` | Strava 客户端 / scheduler 等所有调用方统一入口 |

## 🧱 现状（grep 已验证）

| 位置 | 现状 |
|------|------|
| `app/strava/service.py:388` | `def ensure_valid_token(db: Session, user: User, force: bool = False) -> str:` |
| `app/strava/service.py:415-419` | 函数体内已用 SELECT FOR UPDATE 重新 query user 行锁，遮蔽入参 user |
| `app/strava/client.py:154` | `token = ensure_valid_token(self.db, self.user)` |
| `app/strava/client.py:208` | `token = ensure_valid_token(self.db, self.user, force=True)` |

合计 **2 callers** 需同步改。

## 🛠 完整代码

### `app/strava/service.py`

```diff
- def ensure_valid_token(db: Session, user: User, force: bool = False) -> str:
+ def ensure_valid_token(db: Session, user_id: int, force: bool = False) -> tuple[User, str]:
      """
      确保用户的 Strava access_token 有效，过期则自动刷新。
      
+     v5 task-0.2 签名改造：
+     - 入参 user_id 替代 user 对象 → 函数内部 query + 行锁，调用方不必先 query
+     - 返回 (User, token) 元组 → 调用方用锁后 user 实例做后续操作（如读 athlete_id），
+       避免在外部用过时 user 对象触发并发数据 drift
      """
      user = (
          db.query(User)
-         .filter(User.id == user.id)
+         .filter(User.id == user_id)
          .with_for_update()
          .first()
      )
+     if user is None:
+         raise ValueError(f"user_id={user_id} 不存在")
+     
      # ... 其余逻辑不变（refresh / 写新 token / 401 pause imports）...
      
-     return token
+     return user, token
```

### `app/strava/client.py`

```diff
  # 行 154
- token = ensure_valid_token(self.db, self.user)
+ self.user, token = ensure_valid_token(self.db, self.user.id)

  # 行 208
- token = ensure_valid_token(self.db, self.user, force=True)
+ self.user, token = ensure_valid_token(self.db, self.user.id, force=True)
```

> **替换 self.user**：行锁后的 user 对象数据更新，赋回 self.user 让后续 client 方法用最新值。

## ✅ 测试

跑现有 strava 相关测试，确认无回归：

```bash
python3 -m pytest tests/test_strava*.py tests/test_oauth*.py -x -q
```

预期：全 passed（签名改造对外行为不变，只是调用风格更安全）。

新增 case：`tests/test_strava_token.py` 加 `test_ensure_valid_token_returns_locked_user_instance` ——验证返回的 user 是行锁后的实例（refresh 完写回新 token 字段）。

## 📝 commit

```
refactor(strava): 任务 0.2 ensure_valid_token 签名改造

签名 (db, user, force) → str  改为  (db, user_id, force) → tuple[User, str]
- 内部封装行锁 + query，调用方传 id 即可
- 返回锁后 user 实例，避免外部用过时对象触发数据 drift

callers: app/strava/client.py:154 / :208 同步改
```

## 🔍 自检三问

1. **崩溃恢复**：函数中途异常（refresh API 5xx）→ 行锁怎么释放？  
   → with_for_update 锁随事务结束自动释放（commit / rollback 都释放）。caller 在 client.py 隐式事务内，异常会触发 rollback 解锁。

2. **陷阱核查**：入参从 user 改 user_id 后，未先 query 的 caller 拿不到 user 对象——会有遗漏 caller 吗？  
   → grep 确认仅 2 callers，已全改。无第三方反向依赖。

3. **下游波及**：返回值从 str 改 tuple，所有 caller 解构正确吗？  
   → client.py:154 / 208 都改成 `self.user, token = ...`，self.user 替换后续行为一致（属性读取相同）。
