# 任务 2.C.3：user.router 4 个新 endpoint

## ⚠ 路径命名修订（2026-04-30 实施时 / Tim 拍 A）

原 task 卡声明 `/api/users/...`（复数）与 CLAUDE.md 命名规则"user/* 不复数"+ 现有 router prefix `/api/user`（单数）冲突。
**选 A：统一单数**——所有新 endpoint 用 `/api/user/me/...` `/api/user/{user_id}/profile`。spec §4.2 已同步。

## 🎯 目标

`app/user/router.py` 加 4 个新 endpoint，对接 task-2.C.2 的 service 函数。

## ⛓ 前置依赖

task-2.C.2（service 5 函数实现完）。

## 📤 输出契约（API 接口）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/users/me/power-curve?period=` | current_user | period 6 枚举 |
| GET | `/api/users/me/heatmap?city=` | current_user | city 6 枚举 |
| PATCH | `/api/users/me` | current_user | body 加 city 字段（**新增不替换现有 PUT /profile**，B2B-6 修） |
| GET | `/api/users/{user_id}/profile` | current_user | RESPONSE_KEYS 白名单返回 |

## 🧱 现状

- `app/user/router.py` 现有：`POST /login` / `GET /profile` / `PUT /profile` / `GET /stats`
- v5 新增 4 个 endpoint **不与现有冲突**（spec §0.1 已查实）

## 🛠 完整代码

抄 spec §4.2（行 2330-2370）的 endpoint 设计。

```python
# app/user/router.py 追加

from fastapi import HTTPException, Query
from app.user import service


@router.get("/me/power-curve", response_model=schemas.PowerCurveResponse)
def get_my_power_curve(
    period: str = Query(..., regex="^(this_month|last_month|this_year|last_year|all_time|7_days)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return service.get_user_power_curve(db, current_user.id, period)


@router.get("/me/heatmap", response_model=schemas.HeatmapResponse)
def get_my_heatmap(
    city: str = Query(..., regex="^(beijing|shanghai|hangzhou|shenzhen|chengdu|taiyuan|unknown)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return {"points": service.get_user_heatmap(db, current_user.id, city)}


@router.patch("/me", response_model=schemas.UserResponse)
def update_my_profile(
    body: schemas.UserPatchRequest,  # body 含 optional city 字段
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.city is not None:
        service.update_user_city(db, current_user.id, body.city)
    return current_user  # 沿用现有 schema


@router.get("/{user_id}/profile", response_model=schemas.UserProfileResponse)
def get_user_profile(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return service.get_user_profile_for_others(db, user_id, current_user.id)
    except ValueError:  # user 不存在
        raise HTTPException(404, detail="用户不存在")
```

### `app/user/schemas.py` 加

```python
class PowerCurveResponse(BaseModel):
    period: str
    curve: dict[int, float]  # window_sec → max_avg_power_W

class HeatmapResponse(BaseModel):
    points: list[list[float]]  # list of [lon, lat]

class UserPatchRequest(BaseModel):
    city: str | None = Field(None, regex="^(beijing|...|unknown)$")

class UserProfileResponse(BaseModel):
    id: int
    nickname: str
    avatar_url: str | None
    city: str | None
    ftp: int | None
    bike_type: str | None
    total_distance_km: float
    total_elevation_m: float
    activity_count: int
    current_month_summary: dict
```

## ✅ 测试

```python
# tests/test_user_router_v5.py
def test_power_curve_endpoint_invalid_period_422():
def test_power_curve_endpoint_returns_6_buckets():
def test_heatmap_endpoint_filter_by_city():
def test_heatmap_endpoint_invalid_city_422():
def test_patch_me_city_invalid_422():
def test_patch_me_city_valid_updates():
def test_get_user_profile_not_exist_404():
def test_get_user_profile_returns_only_whitelisted_fields():
    # 关键：验证响应 dict 严格只含 RESPONSE_KEYS 字段，不含 strava_access_token / openid 等
```

## 📝 commit

```
feat(user): 任务 2.C.3 user.router 4 个新 endpoint

- GET /api/users/me/power-curve（period Query 6 枚举校验）
- GET /api/users/me/heatmap（city 枚举校验）
- PATCH /api/users/me（body 加 city，新增不替换 PUT /profile）
- GET /api/users/{user_id}/profile（404 翻译 + RESPONSE_KEYS 白名单）

schemas 新增 4 个 response model
```

## 🔍 自检三问

1. **不冲突现有路由**：grep `@router.get\|@router.post\|@router.put\|@router.patch` `app/user/router.py` 确认 PATCH /me / GET /me/power-curve / GET /me/heatmap / GET /{user_id}/profile 都是新路径，无路径冲突。  
   → 现有 PUT /profile / GET /profile 在不同路径下，不冲突。

2. **白名单严格**：UserProfileResponse 字段集合必须严格匹配 service 返回的 RESPONSE_KEYS 字段集合——不多不少。  
   → 双重保险：service 已 RESPONSE_KEYS 过滤；schema 也只声明白名单字段，FastAPI 自动忽略多余键。

3. **PATCH 语义**：body 字段 optional —— 不传 city 时不动 user.city，不抹空。  
   → 是。`if body.city is not None` 保护，传 None 显式不更新。
