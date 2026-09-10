# 官网改版发布 — 2026-09-11

用户在完成白底、地图与 TYY7 社群预览后要求手机可正常显示即可部署，随后追加手绘、可选贴路、GLO-30 海拔及中文字体/密度调整；这些均纳入同一次发布。

## 发布对象

- 已批准的预览底稿 commit `5af70a3`，加上本次手绘与排版改动；不带入本地 VELO 脏工作区的小程序改动。
- `website-src/` 是可重建前端，`website/` 保存预渲染 HTML 和静态产物。Node 22 下在 website-src 执行 `npm ci && npm run build`。浏览器使用 hydration。
- 保留原公司介绍、中英文隐私页、英文首页、404、备案、favicon、微信验证文件和旧页面样式字体。
- 首页采用本地 Noto Sans SC Regular/Medium，OFL 授权文件随字体保存。说明字放大、区块间距收紧，维持白底与轻量导航。研究参考苹果中国官方样式、小米 MiSans 官方资料和 MUJI 中国官网；未使用/再分发苹果专有字体或 MiSans。
- 121 条公开来源赛段 / 55 条总览代表；全天路线为明确示意。尚缺清徐与汾河全线准确来源，未用旧 GPX 代替。
- TYY7 三段介绍按用户原文保留，七张原始照片不变，社群章节不添加注明。

## 手绘 / 贴路 / 海拔

产品同时支持保留原线和腾讯地图贴路；官网交互体验使用 Valhalla/FOSSGIS 的 OSM bicycle 路由，明确写出本页使用 OSM。只在点击贴路时发请求，不做批量查询。原线和贴路结果分别保存，可切换、撤销和清空；失败不伪造路线。

新增 `POST /api/website/elevation-preview`，由现有 `build_route_elevation_result` 和 Copernicus GLO-30 缓存计算。同一成品剖面产生图表、累计爬升、下降及逐输入点高度；GPX 带对应高度，不用第三方海拔混入。端点不写数据库或路书、不需要登录，输入仅接受 WGS84 太原周边 2–2000 点、10m–120km 路线，每 IP 12 次/300s，单进程最多两项同步计算，DEM 查询总时限 20s。范围和数量在请求校验时拒绝；缺数据/忙/限流返回错误而非零海拔。

前端每次改线/撤销/清空取消旧请求并用代次隔离，防止旧海拔覆盖新路线；路线与海拔未对齐时不写入 GPX。公共演示不保存访客轨迹。

## 运行配置与发布

Caddy 只允许同源脚本、blob WebGL workers 和内联运行时样式；外部地图连接仅 tiles.openfreemap.org、valhalla1.openstreetmap.de，海拔仅 api.weiluai.top。官网继续独立 file_server，不反代 API、不开放 uploads，未知地址真实 404。新 website-src 不进入后端镜像。

没有新增环境变量、数据库结构、迁移或响应缓存字段。API 新增接口，因此在正常 PR/pytest 通过后，服务器 fast-forward main，重建 api；Caddyfile 变更先无端口 preflight，通过再 recreate Caddy。迁移按部署 SOP 核对/upgrade head。无必要重建其他 worker 镜像；检查共享入口和 API 健康。

## 验收

本地：手机 390px/320px，图库/长文/联系、手绘/撤销/切换/导出、预渲染正文与 CSP 资源加载。官网静态合同保留支持页、字体、备案、隐私和上传隔离检查；新增公开海拔的参数/真实算法调用/失败/忙/限流测试。图表必须使用真实 GLO 结果，不把 mock 当作上线证据。

上线：根域、www、公司/中英文政策/英文首页、未知 404、uploads/编码穿越隔离、API health/OpenAPI；真实 POST 新接口取得 GLO-30 曲线；正式 HTTPS 页面操作一次贴路与海拔/导出。服务器独立 release-evidence 和当前任务最终回报记录实际结果。本文件是发布合同，不意味着上述步骤已完成。
