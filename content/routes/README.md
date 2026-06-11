# 路线百科内容目录——Tim 手动改文字的唯一入口

> **文案真相源就是这里的 `guide.md`**（2026-06-11 拍）：VS Code 直接打开改字，像之前改 HTML 一样，
> LLM 不经手、投影器不覆盖（`render_route_guides_md.py` 遇到已存在的 guide.md 自动跳过，除非 `--force`）。
> route.json（route skill 工作区）只继续管结构化数据：轨迹坐标、数据指标、证据链。

## 改文字三步（全程不碰容器、不碰数据库迁移）

1. 在下表找到路线目录，VS Code 打开 `guide.md` 改字保存（注意保持 `## 模块名` 行不动——前端按它切折叠模块）
2. 跑 `./scripts/publish_routes.sh`（或告诉 Claude"发布路线"）
3. 约一分钟后小程序下拉刷新即见

## 目录对照表

| 目录 | 路线 | 备注 |
|---|---|---|
| `tianlongshan/` | 天龙山盘山公路 | v11 定本手工转写（不在 route skill 工作区） |
| `hengling/` | 横岭 | |
| `huanfenhe/` | 环太原汾河自行车道 | Tim 拍的最新定本 |
| `jueweishan/` | 崛围山 | |
| `wanmu/` | 启春阁 | |
| `qingxu/` | 清徐夜骑 | |
| `langpo/` | 狼坡 | |
| `aoshen/` | 奥申 | |
| `miaoqianshan/` | 庙前山 | |
| `xixigou/` | 小西沟 | |
| `yuquanshan/` | 玉泉山 | |

## 每个目录里有什么

- `guide.md` —— 正文（**你改这个**）。`## 模块名` 是折叠模块协议：这是一条什么路 / 给真要去的骑友 / 核心数据 / 怎么骑 / 骑友怎么说 / 安全
- `meta.json` —— 卡片元信息（路线名 / 一句话简介 / 封面图 URL）。改一句话简介改这里的 highlights
- `track.gpx`（可选）—— 轨迹文件。有它路线就"就绪"：详情页出红色轨迹地图 + 海拔曲线，约骑可直接选这条路线
