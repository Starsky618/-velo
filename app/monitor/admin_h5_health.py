"""
admin H5 端到端监测探针（2026-05-06 事故防御 / Sprint 1+2+3 收尾后增量）。

干啥用：
- 在 monitor 容器里每 60 秒探一次 admin H5 反代链路
- 任何一项失败 → 飞书告警，让我们手机能立刻知道生产挂了
- 抓的就是本次（2026-05-06）踩的 502 类故障：admin-h5 容器挂 / nginx DNS 缓存 / 反代到 api 链路断

操作注意（关键设计）：
- **不查 DB**：本模块只走 HTTP / 与 processing_health.py 模块边界划清（DB 层 vs HTTP 层不混）
- **告警不阻断**：飞书 webhook 5xx / 网络异常 → catch 后 logger.error，仍返失败列表
- **未配 webhook 兜底**：dev / CI 没配 FEISHU_BOT_WEBHOOK → 跳过推送但仍返失败列表
- **单次失败即告警**：不去抖动（沿用 task-1.C.1 简化模式），噪音过多再加

数据流：
- 入：无（容器内独立探活，调用方只需启动）
- 中：在 docker network 内 GET admin-h5 服务的 2 条路径 → 比对预期状态码 → 失败列表
- 出：list[str] 失败探测项名（空 = 全绿）

部署：docker-compose monitor 容器主循环加 `python -m app.monitor.admin_h5_health`
"""

import logging

import httpx

from app.config import settings


logger = logging.getLogger(__name__)


# admin-h5 在同 docker network / docker compose service 名 = `admin-h5` / 内部端口 80
# 配成常量便于测试 monkeypatch（dev stack 改成 admin-h5-dev:80 也方便）
ADMIN_H5_BASE_URL = "http://admin-h5"

# 单次 HTTP 探测超时：3 秒。
# 探测窗口 60s / 2 项探测 → 单项不超 3s 已远低于窗口，不会让 monitor 容器堆积。
PROBE_TIMEOUT_SEC = 3

# 同一组失败 sig 的告警间隔：5 分钟（codex 异源审 I2 抓的告警风暴）
# 探测周期 60s / 真故障期间不去抖会发 60 条/h 重复消息 / Redis SETNX EX 速率限制
ALERT_DEDUP_TTL_SEC = 5 * 60


def _probe_static_site() -> str | None:
    """探 admin H5 静态站可达。

    GET http://admin-h5/ → 期望 200（nginx 返 index.html）。

    返回失败原因（短描述），全绿则返 None。
    """
    try:
        resp = httpx.get(f"{ADMIN_H5_BASE_URL}/", timeout=PROBE_TIMEOUT_SEC)
    except Exception as exc:
        return f"network: {exc.__class__.__name__}"

    if resp.status_code != 200:
        return f"status {resp.status_code}"

    return None


def _probe_api_proxy() -> str | None:
    """探 admin H5 反代到 api 容器的链路是否通。

    GET http://admin-h5/api/admin/whoami（无 token）→ 期望 401（backend decode_token 抛）。
    若反代挂 → 502 / 503 / 504 → 探测失败（精确捕获 2026-05-06 事故同类故障）。

    返回失败原因，全绿则返 None。
    """
    try:
        resp = httpx.get(
            f"{ADMIN_H5_BASE_URL}/api/admin/whoami",
            timeout=PROBE_TIMEOUT_SEC,
        )
    except Exception as exc:
        return f"network: {exc.__class__.__name__}"

    # 5xx：nginx 自己返（反代到 api 失败）
    if 500 <= resp.status_code < 600:
        return f"upstream {resp.status_code}（nginx 反代挂）"

    # 严格断言 4xx（codex 异源审抓的 I1）：
    # 200 不算通 —— nginx 配置坏 / location /api/ 失效时，请求会落到 location /
    # 被 try_files 兜底返 SPA index.html 200，反代实际挂但旧版宽松判定会漏报
    # 只接受 4xx（401 unauthorized / 422 validation 等）= 反代真生效到了 backend
    if 400 <= resp.status_code < 500:
        return None
    return f"unexpected {resp.status_code}（反代未生效 / 可能落到 SPA fallback）"


def scan_admin_h5_health() -> list[str]:
    """
    探活 admin H5 端到端链路 → 任何探测项失败 → 飞书告警。

    设计思路：
    - 容器内探活（同 docker network / 用 service 名），不依赖公网 IP / 端口映射
    - 模块边界：本探针不查 DB / 不调外部业务 API / 只走 HTTP / 失败时唯一副作用 = 飞书消息
    - 类比锅炉房的水流警报 —— 任意管道堵了响铃，至于堵在哪段管道由消息内容透出来

    返回：
        list[str] 失败探测项名（空 = 全绿）

    异常路径（全部内部消化）：
        - 飞书 webhook 抛异常 → logger.error + 仍返失败列表
        - FEISHU_BOT_WEBHOOK 未配 → logger.warning + 跳过推送但仍返失败列表
    """
    failures: dict[str, str] = {}

    # 第 1 步：跑两个独立探测项 / 互不影响
    # 用 dict 而不是 list 是为了在告警消息里同时给出"哪项 + 为啥"
    static_err = _probe_static_site()
    if static_err is not None:
        failures["static_site"] = static_err

    proxy_err = _probe_api_proxy()
    if proxy_err is not None:
        failures["api_proxy"] = proxy_err

    # 第 2 步：全绿直接返空，省一次 webhook 调用
    if not failures:
        return []

    failed_names = list(failures.keys())

    # 第 3 步：渲染告警文本
    # 不带敏感信息（无 token / 无 IP / 无 user_id）→ 群里安全
    lines = [f"  - {name}: {reason}" for name, reason in failures.items()]
    msg = (
        "🚨 admin H5 探活告警\n"
        "失败项：\n"
        + "\n".join(lines)
        + "\n建议：sudo docker compose ps / docker compose logs admin-h5"
    )

    # 第 4 步：推飞书（无 webhook 则跳过 / 异常 catch 不抛）
    if not settings.FEISHU_BOT_WEBHOOK:
        logger.warning(
            f"FEISHU_BOT_WEBHOOK 未配置，admin H5 探活失败 {failed_names} 但跳过推送"
        )
        return failed_names

    # 速率限制：同 sig 5 分钟内只发一次（codex 异源审 I2）
    # sig = 失败项名按字典序拼接 / 同样的失败组合 = 同一条告警，不重复刷屏
    # Redis SETNX EX 一次原子操作搞定：成功 set = 第一次发 / 已存在 = 静默
    # Redis 不可达时（容器没起 / 网络分区）→ catch 后退化为"不去抖"，至少不丢告警
    sig = "|".join(sorted(failures.keys()))
    dedup_key = f"monitor:admin_h5:last_alert:{sig}"
    should_send = True
    try:
        from app.queue import redis_conn

        # set with NX (only if not exists) + EX (auto expire) 原子组合
        # 返回 True = 设置成功（第一次见这个 sig）→ 应该发
        # 返回 None / False = key 已存在还在 TTL 内 → 应该静默
        should_send = bool(redis_conn.set(dedup_key, "1", ex=ALERT_DEDUP_TTL_SEC, nx=True))
    except Exception as exc:
        # Redis 挂了不阻断告警发送（宁可重复也不漏）
        logger.warning(f"admin_h5 alert dedup redis check failed: {exc} / will send anyway")

    if not should_send:
        logger.info(f"admin_h5 alert deduplicated within {ALERT_DEDUP_TTL_SEC}s: sig={sig}")
        return failed_names

    try:
        # raise_for_status() 让 4xx/5xx 抛 HTTPStatusError 显式记 error
        # 沿用 task-1.C.1 的姿势（codex 异源审 2026-04-30 抓的 Important）
        response = httpx.post(
            settings.FEISHU_BOT_WEBHOOK,
            json={"msg_type": "text", "content": {"text": msg}},
            timeout=5,
        )
        response.raise_for_status()
    except Exception as exc:
        # 飞书挂了不阻断 —— 业务正常跑，告警这条路断就断
        logger.error(f"feishu webhook failed: {exc}")

    return failed_names


def main() -> int:
    """命令行入口（docker-compose monitor 容器主循环调用）。

    返回退码：0 = 全绿 / 1 = 至少一项失败（cron 监控可用退码识别）
    """
    failed = scan_admin_h5_health()
    return 0 if not failed else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
