# 输入合同

输入描述“从公开页面观察到了什么”，不包含 Strava polyline 或 GPX。

## 最小结构

```json
{
  "schema_version": 1,
  "target_definition": {
    "physical_role": "要收录的现实道路范围，必须在搜索候选前写清",
    "expected_direction": "从山脚到山顶",
    "expected_distance_range_m": {"min": 9500, "max": 10500},
    "expected_start_wgs84": {"lat": 37.0, "lon": 112.0, "name": "已知起点"},
    "expected_end_wgs84": {"lat": 37.1, "lon": 112.1, "name": "已知终点"},
    "endpoint_tolerance_m": 100,
    "required_shape_features": ["检查站走左路", "半山岔口走右路", "经过螺旋高架"],
    "acceptance_sources": [
      {
        "type": "user_acceptance_anchor",
        "reference": "当前任务确认的路线边界",
        "note": "这些锚点早于候选选择，防止拿搜索结果反向定义目标"
      }
    ]
  },
  "segment": {
    "name": "赛段名称",
    "city": "taiyuan",
    "direction": "从起点向终点爬升"
  },
  "reconstruction": {
    "tencent_routing_profile": "bicycling",
    "profile_selection_reason": "普通地面道路先用骑行算路；若存在立交层级错误则实测对比 driving"
  },
  "selection": {
    "source_segment_name": "公开页面显示的赛段名",
    "identity_check": {
      "boundary_match": "yes",
      "direction_match": "yes",
      "distance_match": "yes",
      "shape_match": "yes",
      "checked_against": "与 target_definition 和已知道路锚点逐项对照",
      "selection_basis": "说明为什么它是目标，而不只是名字相似"
    },
    "rejected_candidates": [
      {
        "name": "同区域但边界不同的候选",
        "source_url": "https://www.strava.com/segments/456",
        "rejection_reason": "起点、终点或路形不符合 target_definition"
      }
    ]
  },
  "discovery": {
    "source_type": "strava_public_page",
    "source_url": "https://www.strava.com/segments/123",
    "observed_at": "2026-08-09T17:30:00+08:00",
    "coordinate_observation": {
      "acquisition_mode": "strava_visible_markers_aligned_to_tencent_map",
      "strava_start_marker_seen": true,
      "strava_end_marker_seen": true,
      "alignment_method": "把公开页面起终点标记与腾讯同一道路位置对齐，再转成 WGS-84",
      "estimated_accuracy_m": 20,
      "legacy_geometry_used": false,
      "note": "说明使用了哪些地标、路形和地图标记"
    },
    "start_wgs84": {"lat": 37.0, "lon": 112.0, "name": "起点"},
    "end_wgs84": {"lat": 37.1, "lon": 112.1, "name": "终点"},
    "anchors_wgs84": [
      {"lat": 37.04, "lon": 112.03, "name": "决定走向的岔口"}
    ],
    "route_shape_notes": "公开页面可见的发卡弯和道路分支；只写观察，不写脑补。",
    "observed_metrics": {
      "distance_m": 10000,
      "elevation_gain_m": 536,
      "average_gradient_pct": 5.2,
      "minimum_elevation_m": 830,
      "maximum_elevation_m": 1356
    },
    "popularity": {
      "athlete_count": 500,
      "effort_count": 1200,
      "star_count": 173
    },
    "comparison_scope": "天龙山及其两侧可见骑行赛段",
    "nearby_comparisons": [
      {
        "name": "同区域局部反爬",
        "source_url": "https://www.strava.com/segments/456",
        "relation": "同一山体的反向局部爬坡，不是本次全程",
        "popularity": {"athlete_count": 700, "effort_count": 2300, "star_count": 91}
      }
    ]
  }
}
```

## 字段规则

- `schema_version`：当前固定为 `1`。
- `target_definition`：必须在选择候选前冻结。`physical_role` 说清现实道路范围；`expected_distance_range_m` 必填；已知起终点时成对提供并填写允许偏差；`required_shape_features` 至少一项；`acceptance_sources` 说明这些预期从哪里来。
- `segment.name`：页面看到的赛段名或 VELO 预定名称，不能为空。
- `segment.city`：使用项目现有城市枚举；暂不清楚时写 `unknown`。
- `segment.direction`：说明哪边到哪边，不用“正向”这种脱离上下文的词。
- `reconstruction.tencent_routing_profile`：只支持 `bicycling` 或 `driving`，必须显式选择。它只控制道路几何重建，不证明道路允许骑行。
- `reconstruction.profile_selection_reason`：说明为何选择该模式。立交、盘桥或密集发卡弯必须依据实际返回的距离和路形选择，不能永远写死一种模式。
- `selection.source_segment_name`：公开页面的原名，与 VELO 内部命名分开。
- `selection.identity_check`：边界、方向、距离、路形必须全部为 `yes`；任一项不通过，脚本在调用腾讯前停止。
- `selection.rejected_candidates`：记录同区域但未入选的页面及确切拒绝理由。它们只帮助复盘选择，不进入主候选数据。
- `source_type`：固定为 `strava_public_page`，强调人工观察公开页面。
- `source_url`：必须是 `strava.com` 的 HTTP(S) 页面，不是 API 地址。
- `observed_at`：必须带时区。热度数字没有观察时间就无法判断新旧。
- `coordinate_observation`：必须确认公开页面的起点和终点 marker 都实际可见，并记录对齐方法和预计精度。新数据用 `acquisition_mode=strava_visible_markers_aligned_to_tencent_map` 且 `legacy_geometry_used=false`；看不清 marker 或无法对齐时停止，不猜坐标。
- `acquisition_mode=legacy_verified_geometry_regression` 只允许旧赛段回归，并必须写 `legacy_geometry_used=true`。这类 bundle 最多成为 `verified_regression`，不能发布为新硬数据。
- `start_wgs84` / `end_wgs84`：经纬度必须是 WGS-84，纬度在 `lat`，经度在 `lon`。
- `anchors_wgs84`：只放能消除腾讯选路歧义的关键点，按骑行顺序排列。它不是轨迹点串。
- `route_shape_notes`：记录可见路形、岔口、隧道或方向线索，供人工对照。
- `observed_metrics`：页面可见的赛段统计。`distance_m` 必填且必须落在预期范围内；其余可为 `null`。这些是外部观测，不是 VELO 硬知识。
- `popularity`：三个字段都可为 `null`，有值时必须是非负整数。数字只作观测证据。
- `comparison_scope`：说明“热门”比较覆盖哪里、哪些候选；存在邻近比较项时必填。
- `nearby_comparisons`：同次观察的候选赛段，只保存名称、页面、关系说明和热度数字，不放进硬知识。最多 50 条。

起点和终点不能相同。锚点不能与相邻点重合；重复点会让腾讯返回无意义短路线。若 `target_definition` 提供已知起终点，公开页面坐标超出允许偏差也会立即拒绝。

腾讯重建后的 WGS-84 点串距离必须落在 `expected_distance_range_m` 内。超出范围时脚本在调用海拔前停止；先检查 profile，再检查锚点。密集立交上不要默认堆锚点，因为不同高程的道路在二维坐标上接近，可能让分段算路倒退或重复。

## 版本与更新

热度变化时创建新的 discovery 输入或新观察快照，不修改旧 bundle。几何边界发生变化时视为新的候选版本，重新跑腾讯、海拔和人工复核。只有主候选与 `nearby_comparisons` 处于同一 `observed_at`、同一 `comparison_scope`，才能提出“此范围内最热门”的派生判断。
