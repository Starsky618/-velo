"""
Strava 集成模块——"外交部"。

负责和 Strava 平台打交道：用户授权绑定、拉取骑行数据、接收实时通知。
好比国际贸易中的海关部门：管理通行证（OAuth token）、翻译文件格式、处理进出口。

本模块的职责边界：
- OAuth 授权流程（绑定/解绑 Strava 账号）
- API 请求封装（限流、重试、错误处理）
- Webhook 接收（新活动通知）
- 历史导入调度

不做的事：
- 不解析轨迹数据（交给 parsing/strava_adapter.py）
- 不写 trackpoints 到数据库（交给 activity/worker.py 的共享函数）
"""
