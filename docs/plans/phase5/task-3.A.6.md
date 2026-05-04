# 任务 3.A.6：admin from-gpx endpoint + 老 endpoint 平滑迁移

> **brainstorming v2 / 2026-05-05 决策落地**：决策 a "仅 admin 可创赛段"——已实证 service 层有守卫，但 v5 admin endpoint 应统一在 `/api/admin/*` 前缀下，老 `POST /api/segments` 路径破坏一致性。

## 🎯 目标

`app/admin/router.py` 追加 `POST /api/admin/segments/from-gpx`：从 admin 上传的 GPX 解析后坐标点创建赛段。**复用** `segment.service.create_segment()`（service 层已有 admin 守卫，无需重写）。**老 `POST /api/segments` 标 deprecated**，task-3.B.2 切完 segment-creator.html 后再删。

## ⛓ 前置依赖

- task-3.A.5 ✅（admin 框架 + from-activity / commit `8be37e3`）
- task-1.A.2 ✅（service 层 `create_segment` 已实现 + WGS-84 转换 + 距离/爬升计算）

## 📤 输出契约

| 接口 | 用途 | 状态 |
|---|---|---|
| `POST /api/admin/segments/from-gpx` | admin 提交 reference_points → 创建赛段 | 新增 |
| `POST /api/segments` | 老路径，segment-creator.html 临时仍调 | deprecated（task-3.B.2 切完后删） |

## 🧱 现状（grep 已验证 2026-05-05）

- `app/segment/service.py:49 create_segment()` 函数已存在
- service 层守卫：第 70-72 行 `if not user or not user.is_admin: raise PermissionError("需要管理员权限")` ✅
- `app/segment/router.py:34 POST /api/segments` 现存（segment-creator.html 调）
- v5 admin 路径前缀：`/api/admin/*`（task-3.A.1 ~ 3.A.5 全部遵守，老 `/api/segments` 破坏一致性）

## 🛠 完整代码

### 1. admin schemas 加 FromGpxRequest（`app/admin/schemas.py`）

```python
class FromGpxRequest(BaseModel):
    """admin 从 GPX 解析后的坐标点创建赛段。
    
    与 segment.schemas.SegmentCreateRequest 字段集**等价**——意图：admin 端直接复用同样的 service.create_segment 函数，避免逻辑分叉。
    """
    name: str = Field(..., min_length=2, max_length=128)
    description: str | None = Field(None, max_length=2000)
    reference_points: list[dict] = Field(..., min_length=2)  # [{"lat": x, "lon": y}, ...]
    match_tolerance: float | None = Field(None, gt=0, le=200)
    min_match_ratio: float | None = Field(None, ge=0, le=1)
    coordinate_system: str = Field("gcj02", pattern="^(gcj02|wgs84)$")
    
    model_config = ConfigDict(extra="forbid")  # admin schema 默认严格（陷阱沉淀）
    
    @field_validator('reference_points')
    @classmethod
    def validate_points(cls, v):
        for p in v:
            if 'lat' not in p or 'lon' not in p:
                raise ValueError("每个点必须含 lat/lon")
            if not (-90 <= p['lat'] <= 90):
                raise ValueError(f"lat 越界: {p['lat']}")
            if not (-180 <= p['lon'] <= 180):
                raise ValueError(f"lon 越界: {p['lon']}")
        return v
```

### 2. admin router 加 endpoint（`app/admin/router.py`）

```python
@router.post(
    "/segments/from-gpx",
    response_model=schemas.AdminSegmentResponse,
    status_code=201,
)
def create_segment_from_gpx_admin(
    body: schemas.FromGpxRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """从 admin 上传的 GPX 解析后坐标点创建赛段。
    
    复用 segment.service.create_segment（service 层已有 is_admin 守卫 + WGS-84 转换 +
    距离/爬升计算 + Hausdorff 重复检测）—— admin endpoint 仅做权限层 + 异常翻译。
    
    双层守卫：
    - router 层：require_admin（提前 403，防止 service 被无意义调用）
    - service 层：is_admin 兜底（防止 router 配置漏 require_admin）
    """
    try:
        segment = segment_service.create_segment(
            db=db,
            user_id=admin.id,
            name=body.name,
            reference_points=body.reference_points,
            description=body.description,
            match_tolerance=body.match_tolerance,
            min_match_ratio=body.min_match_ratio,
            coordinate_system=body.coordinate_system,
        )
        db.commit()
        db.refresh(segment)
        return admin_service.admin_segment_response(segment)
    except PermissionError as e:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except SegmentOverlapError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(e))
```

### 3. 老 POST /api/segments 平滑 deprecated（`app/segment/router.py`）

不立即删除（segment-creator.html 还在调）。加：
- response header `Sunset: <date>`（HTTP RFC 8594）
- response header `Deprecation: true`
- log warning：标记调用源
- 注释 # DEPRECATED

```python
@router.post("", response_model=schemas.SegmentResponse)
def create_segment(
    req: schemas.SegmentCreateRequest,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
    response: Response = None,
):
    """[DEPRECATED 2026-05-05] 创建赛段——v5 后迁到 POST /api/admin/segments/from-gpx。
    
    sunset：task-3.B.2 切完 segment-creator.html 后删除（预计 v5 收尾）。
    """
    import logging
    logging.getLogger(__name__).warning(
        "DEPRECATED endpoint POST /api/segments called by user_id=%s. Migrate to /api/admin/segments/from-gpx.",
        user_id,
    )
    response.headers["Sunset"] = "Wed, 30 Jun 2026 00:00:00 GMT"
    response.headers["Deprecation"] = "true"
    
    # 原逻辑保持不变（service 层已有 admin 守卫）
    points = [p.model_dump() for p in req.reference_points]
    try:
        segment = service.create_segment(...)
    # ...rest unchanged
```

## ✅ 测试（`tests/test_admin_from_gpx.py`）

```python
def test_from_gpx_basic_create_201(admin_user, client):
    resp = client.post('/api/admin/segments/from-gpx', json={
        'name': 'test seg',
        'reference_points': [{'lat': 39.9, 'lon': 116.4}, {'lat': 39.91, 'lon': 116.41}],
        'coordinate_system': 'wgs84',
    }, headers=admin_auth(admin_user))
    assert resp.status_code == 201
    assert resp.json()['name'] == 'test seg'

def test_from_gpx_normal_user_403(normal_user, client):
    """service 层 PermissionError → 403（非双重 require_admin 即使漏配也兜底）"""
    resp = client.post('/api/admin/segments/from-gpx', json={...}, headers=auth(normal_user))
    assert resp.status_code == 403

def test_from_gpx_invalid_coords_422():
    """schema 层 lat/lon 越界校验"""
    resp = client.post('/api/admin/segments/from-gpx', json={
        'reference_points': [{'lat': 999, 'lon': 0}],
    })
    assert resp.status_code == 422

def test_from_gpx_too_short_400(admin_user, client):
    """两个点距离 < 1m → ValueError → 400"""
    resp = client.post('/api/admin/segments/from-gpx', json={
        'reference_points': [{'lat': 39.9, 'lon': 116.4}, {'lat': 39.9, 'lon': 116.4}],
    }, headers=admin_auth(admin_user))
    assert resp.status_code == 400

def test_from_gpx_gcj02_to_wgs84_conversion(admin_user, client):
    """coordinate_system='gcj02' 时 service 自动转 wgs84"""
    # 高德/腾讯地图坐标传入，DB 存 wgs84
    ...

def test_old_endpoint_returns_deprecation_header(admin_user, client):
    """老 POST /api/segments 仍工作 + 带 Deprecation: true header"""
    resp = client.post('/api/segments', json={...}, headers=admin_auth(admin_user))
    assert resp.status_code == 200  # 老接口正常返回
    assert resp.headers.get('Deprecation') == 'true'
    assert 'Sunset' in resp.headers

def test_admin_endpoint_extra_forbid_422(admin_user, client):
    """schema extra='forbid' 防 admin 误传未定义字段"""
    resp = client.post('/api/admin/segments/from-gpx', json={
        'name': 'x',
        'reference_points': [...],
        'unknown_field': 'foo',
    }, headers=admin_auth(admin_user))
    assert resp.status_code == 422
```

## 📝 commit

```
feat(admin): 任务 3.A.6 admin from-gpx endpoint (5.D.6)

- POST /api/admin/segments/from-gpx（201/400/403/409/422）
- 复用 segment.service.create_segment（service 层已有 is_admin guard，双层守卫）
- schemas.FromGpxRequest（含 reference_points / coordinate_system 等，extra=forbid）
- 老 POST /api/segments 加 Deprecation + Sunset header（log warning）

异常翻译：
- PermissionError → 403（service 层兜底）
- ValueError → 400（距离不足等）
- SegmentOverlapError → 409
- schema 层越界 → 422

迁移路径：
- task-3.B.2 切 segment-creator.html 调用路径
- v5 收尾时删老 endpoint
```

## 🔍 自检三问

1. **为什么不直接删老 POST /api/segments，强制 segment-creator.html 一次切完？**
   → 平滑迁移降风险。Sunset header + log warning 给观测期，确认无遗漏调用方再删。直接删万一漏切某客户端 = 创赛段功能完全瘫痪。

2. **service 层已有 is_admin 守卫，router 层 `require_admin` 是不是冗余？**
   → 不是，是双层防护：
   - router 层 `require_admin`：提前 403，避免 service 被无效调用 / log 污染
   - service 层 `is_admin`：兜底，防 router 配置漏依赖
   - 两层语义不同（authorization layer），都不能省

3. **`SegmentOverlapError` 出现在 from-gpx 场景吗？**
   → 是。`segment.service.create_segment` 内部走 Hausdorff 重复检测（task-1.A.2 实现）。admin 上传一个和已有赛段几乎重合的轨迹 → 409，避免赛段污染。
