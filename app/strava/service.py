"""
Strava OAuth 业务逻辑层主入口——"外交部签证处"的总台。

本文件在 v5 task-strava-split-001 中完成物理拆分（906 行红灯 → 4 文件）：
- OAuth 流程（生成授权链接 / 回调换 token / scope 双层校验）→ service_oauth.py
- Token 管理（查绑定状态 / 自动续签）→ service_token.py
- Webhook + 手动同步 + 导入进度 → service_sync.py
- 本文件保留共享 doc + 转导出（re-export）所有 public API，对外契约 0 改动

调用方按 `from app.strava.service import xxx` 继续工作，不必感知文件分拆细节。

整个 OAuth 流程可以类比为"办签证"：
1. build_authorize_url：填签证申请表（生成授权链接）
2. handle_callback：大使馆批准签证、贴到护照上（把 token 写入数据库）
3. ensure_valid_token：签证过期了自动续签（刷新 access_token）

注意事项：
- state 用 Redis nonce + GETDEL 一次性消费，防 CSRF + 重放
- scope 双层校验（query string + token response）防篡改（CLAUDE.md 陷阱 #20）
- token 刷新失败时会清空所有 Strava 字段，用户需要重新绑定
- IntegrityError 捕获：一个 Strava 账号只能绑一个系统用户
- generate_authorize_url 是 v0 时代旧版（JWT state / 无 Redis），保留作向后兼容；
  新代码请用 build_authorize_url（v4 重构 / Redis nonce 一次性消费）
"""

# v5 task-strava-split-001：service.py 906 行红灯 → 拆 4 文件，对外契约不变
# 调用方按 `from app.strava.service import xxx` 继续工作，不必感知文件分拆细节
# 异常类归宿在 app.strava.exceptions（caller 想 catch 异常时可直接 import exceptions
# 不必拉 OAuth 业务模块进 import 链 / codex round-1 review 的 I-1 修复）
from app.strava.exceptions import (  # noqa: F401 — 转导出
    BoundByOtherUserError,
    InvalidStateError,
)
from app.strava.service_oauth import (  # noqa: F401 — 转导出
    build_authorize_url,
    generate_authorize_url,
    handle_callback,
    verify_state_and_consume,
)
from app.strava.service_token import (  # noqa: F401 — 转导出
    ensure_valid_token,
    get_strava_status,
)
from app.strava.service_sync import (  # noqa: F401 — 转导出
    get_import_progress,
    handle_manual_sync,
    handle_webhook_event,
)
