# heatmap-card / icons

热力图 marker 图标（4 张密度梯度 / 32×32px PNG / placeholder 版本）。

## 当前状态

由 `task-4.2.B subagent`（2026-05-08）用 PIL 生成的**纯色实心圆 placeholder**——
所有图标都是 32×32 透明底 + 28px 实心圆，仅颜色不同。视觉风格朴素，仅满足"能渲染、不报错"的最低要求。

## 4 张图标用途（密度梯度）

| 文件 | 颜色 RGBA | 寓意 |
|---|---|---|
| `grey.png` | `(158, 158, 158, 255)` | 最低密度 / 中性 / 当前所有 marker 默认用这张 |
| `blue.png` | `(33, 150, 243, 255)` | 低中密度 / 偶尔骑过 |
| `orange.png` | `(255, 152, 0, 255)` | 中高密度 / 经常骑过 |
| `red.png` | `(244, 67, 54, 255)` | 最高密度 / 主战场区域 |

## 当前实际使用情况

**只用 `grey.png`**——其他 3 张暂时闲置。

原因：当前后端 `GET /api/user/me/heatmap` 返回的 `multipoint.coordinates`
是纯坐标列表，**没有 count 字段**。"按 count 上色"是未来后端升级 grid 聚合时的事，
本期不伪造数据。详见 `heatmap-card.js / _convertToMarkers` 注释。

未来后端如返回 `[{lon, lat, count}, ...]` 结构，组件内部按 count 分桶映射到 4 个颜色即可，
icon 文件已就位无需新增。

## designer 替换指南

替换时保持以下硬约束：

1. **尺寸 32×32px**（component js 写死 width/height = 16，DPR 2x 实际 32px）
2. **PNG 格式**（小程序 `markers[i].iconPath` 不支持 SVG）
3. **透明底**（避免方框边缘破坏地图视觉）
4. **文件名不变**（component js hardcode 这 4 个名字）

如需更高 DPR 适配，可改成 64×64 / 96×96，js 端 width/height 不动即可。
