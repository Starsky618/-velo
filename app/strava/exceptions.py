"""
Strava 模块自定义异常——把"未绑定 / 限流 / 失效"等业务态翻译成清晰的异常类型。

为什么要单独建文件：
- 异常类是模块对外的"语义契约"，调用方靠 catch 这些类来分流逻辑
- 跟 service.py 解耦——避免 caller 为了 catch 一个异常被迫 import 整个 service 模块
- 未来加新异常（如 StravaQuotaExhausted）时有明确的归宿

类比：医院给病人贴的"诊断标签"——心梗 / 骨折 / 感冒，不同的标签触发不同的治疗流程。
异常类就是代码世界的诊断标签，让调用方"按病分诊"。
"""


class UnboundStravaError(Exception):
    """用户未绑定 Strava（strava_refresh_token IS NULL）。

    触发场景：
    - 用户从未点过"绑定 Strava"按钮，直接调需要 Strava 数据的接口（如手动同步）
    - 用户曾绑定过但 refresh_token 失效后被清空（见 service.py:ensure_valid_token 的 401 分支）

    调用方行为：
    - router 层 catch 后转 HTTP 400，提示用户去设置页绑定 Strava
      （注意：caller 应使用固定 detail，不要 `str(e)` / `e.args[0]` 透传 message——
      message 含 user_id 是给日志用的，不该暴露给前端）
    - scheduler 层 catch 后把对应 StravaImport 置 paused，避免反复捞同一条卡住
      其他用户的导入轮转（v5 task-0.3 已在 import_scheduler._do_tick 实施）
    """
    pass


class InsufficientScopeError(Exception):
    """用户在 Strava 授权页未授予必需的 `activity:read_all` scope。

    触发场景：
    - 用户在 Strava 授权页**手动取消勾选** "View data about your private activities"
    - velo 收到 callback 带 granted_scope 缺少 activity:read_all
    - 没有此 scope 私密活动（visibility=Only You）永远拉不到，OAuth 升级形同虚设
      （详 CLAUDE.md 陷阱清单 #20 / 2026-05-11 私密活动同步事故）

    调用方行为：
    - router 层 catch 后返 403 HTML 错误页 + 提示用户重新点击"绑定 Strava"并不要取消任何权限勾选
    - **绑定状态不持久化**（在校验失败前不写 user.strava_*），用户可立即重试
    """
    pass
