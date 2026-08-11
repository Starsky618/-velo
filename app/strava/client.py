"""
Strava API 客户端——"外交官"。

所有和 Strava 服务器的对话都通过这个类进行，它负责：
1. 自动带上有效的通行证（access_token），过期就续签
2. 控制请求频率（限流），防止被 Strava 封禁
3. 处理各种异常（网络错误、Strava 宕机、用户撤销授权等）

好比驻外大使馆的外交官：
- 出门前检查签证（ensure_valid_token）
- 遵守当地法律限速驾驶（限流）
- 遇到路障走备用路线（重试），实在不行打道回府（跳过）

生命周期约束：
- 短命对象，绑定单个 db session，用完即弃
- 调度器中应为每个用户创建新实例，不要跨任务复用
- 这样避免 db session 过期、ORM 对象脱离等长连接陷阱

注意事项：
- 限流是全 App 共享的（不是 per-user），用 Redis 计数器实现
- 401 错误最多尝试刷新 1 次 token，防止死循环
- 所有日志包含 user_id 和 activity_id，方便排查
"""

import logging
import time
from datetime import date

import httpx
from sqlalchemy.orm import Session

from app.queue import redis_conn as _redis
from app.strava.service import ensure_valid_token
from app.user.models import User

logger = logging.getLogger(__name__)

# Strava API 基地址
_API_BASE = "https://www.strava.com/api/v3"

# 限流阈值（全 App 共享，不是 per-user）
# Strava 官方限制：每天 1000 次读取、每 15 分钟 200 次
_DAILY_LIMIT = 1000
_WINDOW_15MIN_LIMIT = 200

# Redis 键名前缀（与 rq 的 rq: 前缀隔离）
_RATE_KEY_DAILY = "strava:rate:daily:{date}"
_RATE_KEY_15MIN = "strava:rate:15m:{window}"

# get_activity_streams 请求的数据类型列表
# 这 8 种是 from_streams() 适配器需要的全部字段，硬编码因为项目里不会变
_STREAM_KEYS = "time,distance,latlng,altitude,velocity_smooth,heartrate,cadence,watts"

# HTTP 请求超时（秒）
_TIMEOUT = 15

# v5 task-0.8：_redis 别名沿用，连接源从 app.queue 单一获取
# （键名前缀 "strava:rate:..." 与 rq 的 "rq:..." 隔离不冲突）


class StravaRateLimitError(Exception):
    """API 额度用完时抛出，调用方应停止当前批次等下一个窗口。"""
    pass


class StravaClient:
    """
    Strava API 客户端。

    每个请求自动带 token、检查限流、处理错误。
    好比一个规矩的外交官：每次出门前检查签证、数好今天还剩几次出访配额、
    遇到闭门羹知道该重试还是该放弃。
    """

    def __init__(self, db: Session, user: User):
        """
        创建客户端实例。

        参数：
            db: 数据库 session（用于 token 刷新时写入新 token）
            user: 用户 ORM 对象（必须有 strava_access_token 等字段）

        注意：这是短命对象，db session 关闭后这个实例就不能再用了。
        """
        self.db = db
        self.user = user

    # ===== 公开接口 =====

    def get_athlete_activities(
        self, before: int | None = None, per_page: int = 30
    ) -> list[dict]:
        """
        获取用户的活动列表（第一层：骨架信息）。

        用时间戳游标分页：每次传上一批最早活动的 start_date 作为 before，
        Strava 返回该时间之前的活动。比 page= 分页靠谱——中间新增活动不会打乱进度。

        参数：
            before: Unix 时间戳，返回此时间之前的活动。None 表示从最新开始
            per_page: 每页条数，Strava 上限 200，默认 30

        返回：
            活动列表（骨架字段：id, name, type, distance, start_date 等）
        """
        params = {"per_page": per_page}
        if before is not None:
            params["before"] = before

        return self._request("GET", "/athlete/activities", params=params)

    def get_activity_detail(self, activity_id: int) -> dict:
        """
        获取单条活动的详情（完整统计数据）。

        返回的 JSON 包含 Strava 服务端计算好的摘要：
        distance, moving_time, average_speed, max_speed,
        average_watts, average_heartrate, calories, total_elevation_gain 等。
        """
        return self._request("GET", f"/activities/{activity_id}")

    def get_activity_streams(self, activity_id: int) -> dict:
        """
        获取单条活动的轨迹流（逐点数据）。

        轨迹流是"并行数组"结构——每种数据类型一个等长数组，按索引对齐。
        好比 Excel 表格：每列是一种数据（时间、距离、经纬度...），每行是一个采样点。

        Strava 对轨迹点做了降采样，上限约 10000 点，不需要我们额外处理。
        """
        params = {
            "keys": _STREAM_KEYS,
            "key_by_type": "true",  # 返回 {type: {data: [...]}} 而非 [{type, data}]
        }
        return self._request(
            "GET", f"/activities/{activity_id}/streams", params=params
        )

    def get_segment_detail(self, segment_id: int) -> dict:
        """读取公开 Strava 赛段详情，供受控的标准几何复核使用。"""
        if isinstance(segment_id, bool) or not isinstance(segment_id, int) or segment_id <= 0:
            raise ValueError("Strava segment_id 必须是正整数")
        result = self._request("GET", f"/segments/{segment_id}")
        if not isinstance(result, dict):
            raise ValueError("Strava 赛段详情格式异常")
        return result

    # ===== 内部方法 =====

    def _request(self, method: str, path: str, params: dict | None = None) -> dict | list:
        """
        统一请求入口——所有 Strava API 调用都走这里。

        职责链：检查限流 → 获取 token → 发请求 → 记录限流 → 处理错误。
        好比出门办事的标准流程：
        查配额 → 拿通行证 → 去办事 → 打卡记录 → 处理结果。
        """
        # 第 1 步：检查限流——还有配额吗？
        self._check_rate_limit()

        # 第 2 步：确保 token 有效
        # v5 task-0.2：函数返回 (锁后 user, token) 元组——回写 self.user
        # 让后续 client 方法读到刷新后的最新字段（access_token / expires_at）
        self.user, token = ensure_valid_token(self.db, self.user.id)

        # 第 3 步：发请求
        url = f"{_API_BASE}{path}"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            resp = httpx.request(
                method, url, headers=headers, params=params, timeout=_TIMEOUT
            )
        except httpx.HTTPError as e:
            logger.error(
                "Strava API 网络错误 user_id=%d path=%s error=%s",
                self.user.id, path, str(e),
            )
            raise

        # 第 4 步：记录限流计数（无论成功失败，Strava 都会计入配额）
        self._increment_rate_counter()

        # 第 5 步：处理响应
        return self._handle_response(resp, method, path, params)

    def _handle_response(
        self, resp: httpx.Response, method: str, path: str, params: dict | None
    ) -> dict | list:
        """
        根据 HTTP 状态码分发处理逻辑。

        每种状态码的处理策略写在 spec 6.2 的错误处理表中，
        这里是那张表的代码实现。
        """
        status = resp.status_code

        # 200：成功
        if status == 200:
            try:
                return resp.json()
            except Exception:
                logger.error(
                    "Strava 返回非 JSON 响应 user_id=%d path=%s body=%s",
                    self.user.id, path, resp.text[:200],
                )
                raise ValueError("Strava 返回格式异常")

        # 401：Token 失效——强制刷新 1 次后重试
        # 用 force=True 绕过 expires_at 检查，因为 Strava 可以在 expires_at 之前
        # 作废 token（如用户撤销授权），此时本地的 expires_at 还没到期但 token 已失效
        if status == 401:
            logger.warning(
                "Strava 返回 401 user_id=%d path=%s，强制刷新 token",
                self.user.id, path,
            )
            try:
                # v5 task-0.2：force=True 路径同步回写 self.user
                self.user, token = ensure_valid_token(
                    self.db, self.user.id, force=True
                )
            except ValueError:
                # refresh_token 失效，用户需要重新绑定
                logger.error("Strava token 刷新失败 user_id=%d，需重新授权", self.user.id)
                raise

            # 用新 token 重试一次（不再递归，最多刷新 1 次）
            headers = {"Authorization": f"Bearer {token}"}
            try:
                resp = httpx.request(
                    method, f"{_API_BASE}{path}", headers=headers,
                    params=params, timeout=_TIMEOUT,
                )
            except httpx.HTTPError as e:
                logger.error(
                    "Strava API 重试网络错误 user_id=%d path=%s error=%s",
                    self.user.id, path, str(e),
                )
                raise

            self._increment_rate_counter()

            if resp.status_code == 200:
                try:
                    return resp.json()
                except Exception:
                    raise ValueError("Strava 返回格式异常")

            # 重试后仍非 200，放弃
            logger.error(
                "Strava 刷新 token 后仍失败 user_id=%d path=%s status=%d",
                self.user.id, path, resp.status_code,
            )
            raise ValueError("Strava 授权已失效，请重新绑定")

        # 403：权限不足
        if status == 403:
            logger.warning(
                "Strava 返回 403 权限不足 user_id=%d path=%s", self.user.id, path
            )
            raise ValueError("Strava 权限不足")

        # 404：活动不存在（用户可能在 Strava 上删了）
        if status == 404:
            logger.info(
                "Strava 活动不存在 user_id=%d path=%s", self.user.id, path
            )
            raise ValueError("Strava 活动不存在")

        # 429：被 Strava 限流（我们的客户端限流应该提前拦截，走到这说明计数有偏差）
        if status == 429:
            logger.warning(
                "被 Strava 限流 user_id=%d path=%s", self.user.id, path
            )
            raise StravaRateLimitError("Strava API 限流")

        # 500+：Strava 服务端错误——重试 1 次
        # 500+：Strava 服务端错误——和 token 无关，直接用现有 token 重试 1 次
        if status >= 500:
            logger.warning(
                "Strava 服务端错误 user_id=%d path=%s status=%d，重试 1 次",
                self.user.id, path, status,
            )
            try:
                resp = httpx.request(
                    method, f"{_API_BASE}{path}",
                    headers={"Authorization": f"Bearer {self.user.strava_access_token}"},
                    params=params, timeout=_TIMEOUT,
                )
            except httpx.HTTPError:
                raise ValueError("Strava 服务端错误（重试失败）")

            self._increment_rate_counter()

            if resp.status_code == 200:
                try:
                    return resp.json()
                except Exception:
                    raise ValueError("Strava 返回格式异常")

            raise ValueError(f"Strava 服务端错误 status={resp.status_code}")

        # 其他未知状态码
        logger.error(
            "Strava 未知状态码 user_id=%d path=%s status=%d body=%s",
            self.user.id, path, status, resp.text[:200],
        )
        raise ValueError(f"Strava API 错误 status={status}")

    # ===== 限流管理 =====

    def _check_rate_limit(self) -> None:
        """
        请求前检查限流——还有配额吗？

        用 Redis 计数器实现两级限流：
        - 每天 1000 次（全 App 共享）
        - 每 15 分钟 200 次（全 App 共享）

        超限时不发请求，直接抛 StravaRateLimitError，
        调用方（调度器）捕获后停止当前批次，等下一个窗口再继续。

        为什么主动限流而不是等 Strava 返回 429？
        因为 429 时 Strava 可能已经开始计入"违规次数"，
        累积多了可能被临时封禁。主动限流是"守法公民"的做法。
        """
        # Redis 降级策略：如果 Redis 不可用，限流检查跳过（放行），记录 warning。
        # 限流是保护性措施，Redis 短暂宕机时不应阻断所有 Strava 请求。
        try:
            # 检查日限额
            today = date.today().isoformat()
            daily_key = _RATE_KEY_DAILY.format(date=today)
            daily_count = _redis.get(daily_key)
            if daily_count is not None and int(daily_count) >= _DAILY_LIMIT:
                logger.warning("Strava 日限额已满 count=%s", daily_count)
                raise StravaRateLimitError("Strava API 日限额已满")

            # 检查 15 分钟窗口限额
            # window_id = 当前时间戳 / 900（每 900 秒一个窗口），自动轮转
            window_id = int(time.time() / 900)
            window_key = _RATE_KEY_15MIN.format(window=window_id)
            window_count = _redis.get(window_key)
            if window_count is not None and int(window_count) >= _WINDOW_15MIN_LIMIT:
                logger.warning("Strava 15 分钟限额已满 count=%s", window_count)
                raise StravaRateLimitError("Strava API 15 分钟限额已满")
        except StravaRateLimitError:
            raise  # 限额满是正常的业务逻辑，不吞掉
        except Exception:
            logger.warning("Redis 不可用，限流检查跳过（降级放行）")

    def _increment_rate_counter(self) -> None:
        """
        请求后递增限流计数器。

        无论请求成功还是失败，Strava 服务端都会计入配额，
        所以我们也必须无条件递增。

        用 Redis 的 INCR + EXPIRE 实现：
        - INCR 是原子操作，多个 Worker 并发递增也不会计数错乱
        - EXPIRE 让键自动过期，不需要手动清理
        """
        today = date.today().isoformat()
        daily_key = _RATE_KEY_DAILY.format(date=today)
        window_id = int(time.time() / 900)
        window_key = _RATE_KEY_15MIN.format(window=window_id)

        # 用 pipeline 批量执行，减少网络往返
        # Redis 不可用时静默跳过（降级：不计数但不阻断请求）
        try:
            pipe = _redis.pipeline()
            pipe.incr(daily_key)
            pipe.expire(daily_key, 86400)       # 24 小时后自动清理
            pipe.incr(window_key)
            pipe.expire(window_key, 900)        # 15 分钟后自动清理
            pipe.execute()
        except Exception:
            logger.warning("Redis 不可用，限流计数跳过")
