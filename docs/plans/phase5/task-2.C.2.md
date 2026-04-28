# 任务 2.C.2：user.service 5 个新增函数

## 🎯 目标

`app/user/service.py` 追加 5 个新增函数，覆盖 5.C.2（功率曲线）+ 5.A.1（热图）+ 5.A.2（看他人主页）+ city 更新。

## ⛓ 前置依赖

- task-2.C.1（User.city 字段就位）
- task-2.B.1（calculate_power_curve / _from_activities 实现）

## 📤 输出契约

| 函数 | 用途 | 调用方 |
|---|---|---|
| `get_user_power_curve(db, user_id, period) -> dict` | 6 个 period 枚举（this_month / last_month / this_year / last_year / all_time / 7_days）+ Redis 缓存 | router task-2.C.3 |
| `invalidate_power_curve_cache(user_id) -> None` | activity 完成后失效缓存 | worker hook（task-2.A.1） |
| `get_user_heatmap(db, user_id, city) -> list` | 按 city 筛 simplified_track 聚合点 | router task-2.C.3 |
| `update_user_city(db, user_id, city) -> User` | PATCH /api/users/me 更新 city | router task-2.C.3 |
| `get_user_profile_for_others(db, target_user_id, requester_user_id) -> dict` | 严格字段过滤（RESPONSE_KEYS 白名单） | router task-2.C.3 |

## 🧱 现状

- `app/user/service.py` 现有函数（profile / login 等），本 task 追加 5 个新函数
- `from app.queue import redis_conn as REDIS_CLIENT`（不是 strava.client._redis，第三轮 R3-C1 已修）
- `from app.common.geo import infer_city_from_coords`（第二轮 B2A-2 已修，避免 user→segment 反向依赖）

## 🛠 完整代码

抄 spec：

| 函数 | spec 引用 |
|---|---|
| `get_user_power_curve` | `docs/spec-v5.md §3.3.2`（行 1314-1430）—— **period 切片用 BJ_TZ 转换**（R3-C3 已修） |
| `invalidate_power_curve_cache` | `docs/spec-v5.md §3.3.2` 内（同模块）—— `redis_conn.scan_iter('power_curve:user_X:*')` 删全 period |
| `get_user_heatmap` | `docs/spec-v5.md §3.5`（行 1700-1820）—— **JSONB 端 Python 聚合**（不调 PostGIS，B2A-3 已修），缓存 1h |
| `update_user_city` | `docs/spec-v5.md §3.5` 末段 —— 失效该 user 所有 city 的 heatmap 缓存 |
| `get_user_profile_for_others` | `docs/spec-v5.md §3.6`（行 1820-1955）—— **RESPONSE_KEYS 白名单 return 前过滤**（R3-I3 已修） |

### 关键修订（前 3 轮已修，subagent 抄时检查到位）

- import 顺序：`from datetime import datetime, timedelta, timezone`（含 timedelta，B2A-1 修）
- Redis: `from app.queue import redis_conn as REDIS_CLIENT`（R3-C1 修）
- city 函数：`from app.common.geo import infer_city_from_coords`（B2A-2 修）
- "本月" / "本周"：用 BJ_TZ +8 转换（R3-C3 修）
- Profile RESPONSE_KEYS 实际生效：`{k: v for k, v in raw_response.items() if k in RESPONSE_KEYS}`（R3-I3 修）
- worker 自动推 city 加 SELECT FOR UPDATE 行锁防并发重复（R3-Minor 修）

## ✅ 测试（每函数 ≥ 5 case）

```python
# tests/test_user_service_v5.py

# get_user_power_curve
def test_power_curve_no_activities_returns_zeros(): ...
def test_power_curve_cached_returns_redis(): ...
def test_power_curve_invalidate_cache(): ...
def test_power_curve_period_this_month_uses_bj_tz():
    # 关键：UTC 看是月底 / BJ 看是次月初的 activity → period 切片应按 BJ 视角划

# get_user_heatmap
def test_heatmap_no_activities_returns_empty(): ...
def test_heatmap_filter_by_city(): ...
def test_heatmap_caches_and_invalidates_on_city_update(): ...
def test_heatmap_no_postgis_query_in_implementation():  # B2A-3 防回退
    # 用 mock SQLAlchemy event 抓 SQL 执行，断言不含 ST_Collect / ST_AsGeoJSON

# update_user_city
def test_update_user_city_invalidates_heatmap_cache(): ...

# get_user_profile_for_others
def test_profile_returns_only_response_keys(): 
    # 关键：raw_response 加一个不在 RESPONSE_KEYS 的字段 'strava_access_token'
    # 验证最终返回 dict 不包含此字段（R3-I3 防回退）
def test_profile_self_vs_others_same_fields():  # D-P08 红线
def test_profile_user_not_exist_raises():
def test_profile_current_month_uses_bj_tz(): ...
```

## 📝 commit

```
feat(user): 任务 2.C.2 user.service 5 个新增函数

- get_user_power_curve（period 切片 BJ_TZ + Redis 缓存）
- invalidate_power_curve_cache（worker hook 调）
- get_user_heatmap（JSONB Python 聚合 + 缓存 1h）
- update_user_city（失效热图缓存）
- get_user_profile_for_others（RESPONSE_KEYS 白名单生效）

import 修订（前 3 轮）：
- from app.queue import redis_conn as REDIS_CLIENT（R3-C1）
- from app.common.geo import infer_city_from_coords（B2A-2 反向依赖修复）
- 时区统一 BJ_TZ +8（R3-C3）
```

## 🔍 自检三问

1. **白名单生效**（R3-I3 防回退）：subagent 写完后 grep `RESPONSE_KEYS` 必须见 return 前的过滤逻辑 `{k: v for k, v in ...}`，**不能只定义不用**。  
   → grep 验证。

2. **反向依赖**（B2A-2 防回退）：grep `from app.segment` `app/user/service.py` 必须 0 hits。`infer_city_from_coords` import 路径必须是 `from app.common.geo import`。  
   → grep 验证。

3. **时区一致**（R3-C3 防回退）：所有 period / 本月 / 本周计算必须经过 BJ_TZ 转换，不直接 `now.replace(day=1, ...)` 用 UTC。  
   → grep `now.replace\(day=1` 检查每处都有 BJ_TZ astimezone 转换。
