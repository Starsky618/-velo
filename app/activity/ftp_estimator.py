"""Sprint 10：HR-gated FTP 估算器。

这个文件干什么？
-----------------
当用户没有功率计实测 FTP（功能阈值功率），或者 FTP 长时间没更新时，
我们需要"算"出来一个估计值。当前口径不是历史 PB，而是"当前训练 FTP"：
先找最近 90 天里同一连续窗口同时有功率和心率、且心率强度够高的 20 分钟努力，
用 `20min_power * 0.95` 做主锚点；CP3 只拿已经通过心率门控的窗口做一致性校验。

公式（Morton 1996 / PMID 8854981 标准 CP 3-param 模型）：
    P(t) = CP + W' * (P_max - CP) / (W' + t * (P_max - CP))

（注：原 spec 写 `t = W'/(P-CP) + W'/(P_max-CP)` 是 typo / 这里以反解
形式为单一真相源，跟 cp3_func 实现一致）

三个参数的物理含义：
    CP    渐近线功率（≈ FTP）—— 你能"无限期"维持的功率
    W'    无氧储备能量（焦耳）—— 像一个"电池"，超过 CP 的部分吃这个电池
    P_max 瞬间最大功率（W）—— 你能爆发出来的最大功率

confidence 4 档判断（拟合质量 + 自由度）：
    insufficient < 3 best efforts / 拟合失败 / R² < 0.75 / 数据非单调 / 物理参数不合理
    low         R² ≥ 0.75（n < 5 时最高只能 low / 防自由度欺骗）
    medium      0.85 ≤ R² < 0.95 且 n ≥ 5
    high        R² ≥ 0.95 且 n ≥ 5

自由度修正（Codex 异源审 Critical）：
    3 个 best efforts 拟合 3 参数 = 自由度 0 → R² 必然 1.0 = 虚假高置信度
    所以 n < 5 时强制降级最高 low / 否则会欺骗用户"我们很确定"

操作注意事项：
- estimate_ftp_for_user 对外 method='p20_hr_gated_cp3_check'
- fit_cp3_model 保留 method='cp3_no_hr'，表示底层数学函数不直接看心率
- scipy.optimize.curve_fit 可能数值不稳 / 异常 / 不收敛 → 必须 try/except 兜底
- 滑动窗口找 best power 用 O(n) 双指针，避免长活动上 O(n²) 扫描
- 该模块"纯计算 + DB 查询"，不写库 / 调用方负责持久化结果

输入/输出数据流：
    入参：db Session + user_id
    出参：EstimationResult(ftp, confidence, method, r2)
    依赖：Activity.activity_type='cycling' / Activity.status='completed'
         / Trackpoint.power / Trackpoint.heart_rate / User.max_hr 或 User.birth_year
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.activity.models import Activity, Trackpoint
from app.user.models import User


logger = logging.getLogger(__name__)


# Codex 异源审 Critical：3-4 个 best efforts = 自由度 ≤ 1 → R² 趋向 1.0 = 虚假置信度
# 必须 ≥ 5 个 best efforts 才允许真正的 high/medium 置信度 / 否则强制降级 low
_MIN_EFFORTS_FOR_RELIABLE = 5

_HR_GATED_METHOD = "p20_hr_gated_cp3_check"
_FTP_PRODUCT_BIAS_W = 5
_HISTORY_DAYS = 90
_MAX_VALID_ACTIVITIES = 10
_POWER_COVERAGE_MIN = 0.90
_HR_COVERAGE_MIN = 0.80
_P20_AVG_HR_RATIO = 0.85
_SHORT_MAX_HR_RATIO = 0.90
_CP3_DIFF_RATIO_MAX = 0.12
_P20_WINDOW_SECONDS = 1200
_AUX_WINDOWS_SECONDS = (180, 300, 600, 1200, 3600)


@dataclass
class EstimationResult:
    """eFTP 估算结果。

    像一份"体检报告"——既给数字（ftp），也给可信度（confidence + r2），
    让调用方决定要不要采用（比如低可信度时不覆盖用户手填值）。
    """
    ftp: Optional[int]    # 估算的 FTP（W），insufficient 时为 None
    confidence: str       # 'insufficient' / 'low' / 'medium' / 'high'
    method: str           # 对外 'p20_hr_gated_cp3_check' / 底层 CP3 保留 'cp3_no_hr'
    r2: float             # 拟合质量决定系数 / insufficient 时 = 0.0
    raw_ftp: Optional[float] = None  # 内部原始 FTP；普通前端响应 schema 不暴露


@dataclass
class QualifiedEffort:
    """通过心率门控的连续窗口。

    类比：不是整张试卷都算数，而是只把“监考老师确认认真答题”的那几道题
    交给 CP3 数学模型，防止模型拿通勤/恢复骑当全力证据。
    """
    duration_seconds: int
    avg_power: float
    avg_hr: float
    max_hr: int
    power_coverage: float
    hr_coverage: float
    activity_id: int


def fit_cp3_model(efforts: list[tuple[int, float]]) -> EstimationResult:
    """用 scipy.optimize.curve_fit 拟合 CP 3-param。

    入参：efforts = [(duration_seconds, power_w), ...]
        至少 3 个点 / 时长可以乱序（curve_fit 不关心顺序）

    返：EstimationResult / CP 即 FTP（渐近线）

    数学思路：
        给定 5 个 (t, P) 数据点，找一组 (W', CP, P_max) 使 P(t) 反解公式
        最贴近这些点（最小二乘）。scipy.curve_fit 是非线性最小二乘求解器，
        类似 Excel 里的"添加趋势线"功能，但是用我们指定的公式而不是多项式。
    """
    # 数据不足：至少要 3 个点才能定 3 参数（再少欠定 = 无数解）
    if len(efforts) < 3:
        return EstimationResult(
            ftp=None, confidence="insufficient", method="cp3_no_hr", r2=0.0
        )

    # Codex 异源审 Important：非单调（短时长 power < 长时长）= 物理不可能 / R² 兜底不够
    # 想象百米跑得比一公里慢——身体物理不允许；CP 模型假设 P(t) 严格单调递减
    # 数据非单调 → curve_fit 仍能给出"拟合"但物理无意义 / 直接 insufficient
    sorted_efforts = sorted(efforts, key=lambda x: x[0])
    for i in range(1, len(sorted_efforts)):
        if sorted_efforts[i][1] > sorted_efforts[i - 1][1]:
            logger.warning(
                "non-monotonic best efforts %s / 跳过拟合", sorted_efforts
            )
            return EstimationResult(
                ftp=None, confidence="insufficient", method="cp3_no_hr", r2=0.0
            )

    try:
        # 延迟 import：避免 scipy 启动开销影响其他模块加载
        from scipy.optimize import curve_fit
        import numpy as np

        durations = np.array([e[0] for e in efforts], dtype=float)
        powers = np.array([e[1] for e in efforts], dtype=float)

        def cp3_func(t, w_prime, cp, p_max):
            """CP 3-param 反解公式 P(t) = CP + W' * (P_max - CP) / (W' + t * (P_max - CP))。

            重要：第二项分母是 P_max - CP，不是 CP - P_max——三轮 reviewer 抓的真重点。
            """
            return cp + w_prime * (p_max - cp) / (w_prime + t * (p_max - cp))

        # 初值（p0）选普通业余骑手范围：W'=15kJ / CP=200W / Pmax=800W
        # curve_fit 对初值敏感，离真值太远可能不收敛
        # Codex 异源审 Important：加 bounds 防优化器发散到无意义参数空间
        #   W' 5-50 kJ（业余 10-20kJ / 精英 30kJ+）
        #   CP 50-500W（业余 150-250W / ITT 世界级 500W）
        #   Pmax 600-1200W（爆发力区间 / 顶级冲刺手 1500W+ 但 CP 模型用不到那么高）
        popt, _ = curve_fit(
            cp3_func,
            durations,
            powers,
            p0=[15000.0, 200.0, 800.0],
            bounds=([5000.0, 50.0, 600.0], [50000.0, 500.0, 1200.0]),
            maxfev=5000,  # 最多 5000 次迭代，给数值噪声留余地
        )
        w_prime, cp, p_max = popt

        # 计算 R²（决定系数）：1 - 残差平方和/总平方和
        # R²=1 完美拟合 / R²=0 等同于"猜平均值" / R²<0 比"猜平均值"还差
        predicted = cp3_func(durations, *popt)
        ss_res = float(np.sum((powers - predicted) ** 2))
        ss_tot = float(np.sum((powers - np.mean(powers)) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

        # 物理合理性检查（Codex 收紧）：CP 上限从 800 改 500
        # 500W 已是 ITT 世界级 / 业余 350+ 极少 / 800 太宽容易放过病态拟合
        if not (50 <= cp <= 500 and w_prime > 0 and p_max > cp):
            logger.warning(
                "CP3 fit gave nonsensical params: cp=%.1f w_prime=%.1f p_max=%.1f",
                cp, w_prime, p_max,
            )
            return EstimationResult(
                ftp=None, confidence="insufficient", method="cp3_no_hr",
                r2=round(r2, 3),
            )

        # Codex 异源审 Critical：自由度修正
        # n=3 → 自由度 0 → 必 R²=1.0 / n=4 → 自由度 1 → R² 极易 ≈1.0
        # 这种"数学必完美"的高 R² 不代表 FTP 估算可靠 → 强制降级
        n_efforts = len(efforts)
        if n_efforts < _MIN_EFFORTS_FOR_RELIABLE:
            # < 5 efforts：最高只能 low；R² 不够阈值直接 insufficient
            if r2 >= 0.75:
                conf = "low"
            else:
                return EstimationResult(
                    ftp=None, confidence="insufficient", method="cp3_no_hr",
                    r2=round(r2, 3),
                )
        else:
            # n ≥ 5 才允许真正的 confidence 分级
            if r2 >= 0.95:
                conf = "high"
            elif r2 >= 0.85:
                conf = "medium"
            elif r2 >= 0.75:
                conf = "low"
            else:
                # R² 太低 = 拟合质量不可信 / 视为数据不足
                return EstimationResult(
                    ftp=None, confidence="insufficient", method="cp3_no_hr",
                    r2=round(r2, 3),
                )

        return EstimationResult(
            ftp=int(round(cp)),
            confidence=conf,
            method="cp3_no_hr",
            r2=round(r2, 3),
        )

    except Exception:
        # curve_fit 可能抛 RuntimeError（不收敛）/ OptimizeWarning / ValueError 等
        # 数学错绝不能炸掉调用方（worker / endpoint）—— 一律降级 insufficient
        logger.exception("CP3 fit failed unexpectedly")
        return EstimationResult(
            ftp=None, confidence="insufficient", method="cp3_no_hr", r2=0.0
        )


def _sliding_window_best_power(
    tps: list[tuple[float, datetime]],
    window_seconds: int,
) -> float:
    """滑动窗口：找该活动里"连续 window_seconds 秒内最大平均功率"。

    入参：tps = [(power_w, timestamp), ...] 按时间正序
    返：该窗口长度下的最大平均功率（W）/ 数据不够时返 0.0

    **v0.2 修 bug**（Tim 2026-05-21 真用回归实证 / 修 task-5 quality reviewer Important 2 +
    Codex 异源审 Important 3 / 单条活动内 7 条 300s > 180s 物理矛盾的根因）：

    旧实现 2 个 bug 叠加：
    1. **90% 容差**：180s 窗口允许 162s 段 / 短段平均功率 ≠ 真 180s 段
    2. **index 计数平均**：sum(power) / n 在采样不均匀时（Garmin 4Hz vs 1Hz）失真
       —— 实际是 index 算术平均 / 不是时间加权平均

    新实现（严格 + 时间加权 + O(n) prefix sum）：
    - 严格要求 span ≥ window_seconds（不再 90% 容差）
    - 用 `power[i] × dt[i]` 累计 prefix sum / 时间加权平均
    - O(n) 双指针 / left 单向推进

    物理保证：单条活动内 best 180s ≥ best 300s（短窗 ≥ 长窗 / 因 180s 是 300s 子集）。
    """
    if not tps or len(tps) < 2:
        return 0.0

    n = len(tps)

    # cumulative_time[i] = tps[0] 到 tps[i] 累计秒数
    times = [0.0]
    for i in range(1, n):
        dt = (tps[i][1] - tps[i - 1][1]).total_seconds()
        times.append(times[-1] + max(dt, 0))  # 防 timestamp 倒序（数据脏） / 当 0

    # cumulative_energy[i] = tps[0] 到 tps[i] 累计 power*dt
    # 用 tps[i-1] 的 power 代表 [i-1, i] 这段（Coggan 标准约定）
    energy = [0.0]
    for i in range(1, n):
        dt = times[i] - times[i - 1]
        energy.append(energy[-1] + tps[i - 1][0] * dt)

    best = 0.0
    left = 0
    for right in range(1, n):
        # 推进 left：让 [left, right] 时间跨度尽量贴近 window_seconds（但 ≥）
        while left + 1 < right and (times[right] - times[left + 1]) >= window_seconds:
            left += 1
        span = times[right] - times[left]
        if span < window_seconds:
            continue  # 当前窗口不够长（活动开头 / 暂停后 / 跳过）
        # 时间加权平均：(累计能量差) / (时间跨度)
        avg_power = (energy[right] - energy[left]) / span
        if avg_power > best:
            best = avg_power
    return best


def _clamp_ftp(ftp: int) -> int:
    """把建议 FTP 卡在产品允许范围 50-500W。"""
    return max(50, min(500, ftp))


def _effective_max_hr(user: User) -> tuple[int | None, bool]:
    """返回 (有效最大心率, 是否用年龄公式兜底)。

    优先级：
    1. 用户自填 max_hr：最接近个人真实值
    2. birth_year 推 Tanaka 公式：208 - 0.7 * age，只做低置信度兜底
    3. 都没有：不能估，避免心率门槛凭空造标准
    """
    if user.max_hr is not None:
        return int(user.max_hr), False

    if user.birth_year is None:
        return None, False

    current_year = datetime.now(timezone.utc).year
    age = current_year - int(user.birth_year)
    if age <= 0 or age > 100:
        return None, False
    return int(round(208 - 0.7 * age)), True


def _best_qualified_window(
    tps: list[tuple[int | None, int | None, datetime]],
    window_seconds: int,
    effective_max_hr: int,
    require_avg_hr_gate: bool,
) -> QualifiedEffort | None:
    """找单条活动里某个时长的最佳合格窗口。

    合格 = 同一时间窗口内功率覆盖 ≥90%、心率覆盖 ≥80%，再看心率强度。
    20/60min 用平均心率门槛；3/5/10min 用峰值心率门槛作辅助证据。
    """
    if len(tps) < 2:
        return None

    n = len(tps)
    times = [0.0]
    for i in range(1, n):
        dt = (tps[i][2] - tps[i - 1][2]).total_seconds()
        times.append(times[-1] + max(dt, 0.0))

    power_energy = [0.0]
    power_time = [0.0]
    hr_energy = [0.0]
    hr_time = [0.0]
    for i in range(1, n):
        dt = times[i] - times[i - 1]
        power = tps[i - 1][0]
        hr = tps[i - 1][1]
        power_energy.append(
            power_energy[-1] + (float(power) * dt if power is not None else 0.0)
        )
        power_time.append(power_time[-1] + (dt if power is not None else 0.0))
        hr_energy.append(
            hr_energy[-1] + (float(hr) * dt if hr is not None else 0.0)
        )
        hr_time.append(hr_time[-1] + (dt if hr is not None else 0.0))

    best: QualifiedEffort | None = None
    left = 0
    hr_deque: deque[int] = deque()

    for right in range(1, n):
        hr_index = right - 1
        hr_value = tps[hr_index][1]
        if hr_value is not None:
            while hr_deque and (tps[hr_deque[-1]][1] or 0) <= hr_value:
                hr_deque.pop()
            hr_deque.append(hr_index)

        while left + 1 < right and (times[right] - times[left + 1]) >= window_seconds:
            left += 1
        while hr_deque and hr_deque[0] < left:
            hr_deque.popleft()

        span = times[right] - times[left]
        if span < window_seconds:
            continue

        measured_power_time = power_time[right] - power_time[left]
        measured_hr_time = hr_time[right] - hr_time[left]
        power_coverage = measured_power_time / span if span > 0 else 0.0
        hr_coverage = measured_hr_time / span if span > 0 else 0.0
        if power_coverage < _POWER_COVERAGE_MIN or hr_coverage < _HR_COVERAGE_MIN:
            continue

        avg_power = (power_energy[right] - power_energy[left]) / span
        avg_hr = (
            (hr_energy[right] - hr_energy[left]) / measured_hr_time
            if measured_hr_time > 0 else 0.0
        )
        max_hr = int(tps[hr_deque[0]][1]) if hr_deque else 0

        if require_avg_hr_gate:
            if avg_hr < effective_max_hr * _P20_AVG_HR_RATIO:
                continue
        elif max_hr < effective_max_hr * _SHORT_MAX_HR_RATIO:
            continue

        if best is None or avg_power > best.avg_power:
            best = QualifiedEffort(
                duration_seconds=window_seconds,
                avg_power=avg_power,
                avg_hr=avg_hr,
                max_hr=max_hr,
                power_coverage=round(power_coverage, 3),
                hr_coverage=round(hr_coverage, 3),
                activity_id=-1,
            )

    return best


def _extract_hr_gated_efforts(
    db: Session,
    user_id: int,
    effective_max_hr: int,
) -> tuple[list[tuple[int, float]], int]:
    """扫最近 90 天，最多采纳最近 10 条有合格窗口的活动。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=_HISTORY_DAYS)
    activity_ids = (
        db.query(Activity.id)
        .filter(
            Activity.user_id == user_id,
            Activity.status == "completed",
            Activity.activity_type == "cycling",
            Activity.duplicate_of.is_(None),
            Activity.started_at >= cutoff,
        )
        .order_by(Activity.started_at.desc())
        .all()
    )

    best_per_window: dict[int, QualifiedEffort] = {}
    valid_activity_count = 0

    for (aid,) in activity_ids:
        if valid_activity_count >= _MAX_VALID_ACTIVITIES:
            break

        rows = (
            db.query(Trackpoint.power, Trackpoint.heart_rate, Trackpoint.timestamp)
            .filter(
                Trackpoint.activity_id == aid,
                Trackpoint.timestamp.isnot(None),
            )
            .order_by(Trackpoint.seq)
            .all()
        )
        if len(rows) < 10:
            continue

        tps = [(p, h, t) for p, h, t in rows]
        found_in_activity = False
        for window_sec in _AUX_WINDOWS_SECONDS:
            effort = _best_qualified_window(
                tps,
                window_sec,
                effective_max_hr,
                require_avg_hr_gate=(
                    window_sec in (_P20_WINDOW_SECONDS, 3600)
                ),
            )
            if effort is None:
                continue
            effort.activity_id = aid
            found_in_activity = True
            prev = best_per_window.get(window_sec)
            if prev is None or effort.avg_power > prev.avg_power:
                best_per_window[window_sec] = effort

        if found_in_activity:
            valid_activity_count += 1

    efforts = [
        (duration, effort.avg_power)
        for duration, effort in sorted(best_per_window.items())
    ]
    return efforts, valid_activity_count


def _extract_best_efforts(
    db: Session,
    user_id: int,
    windows_seconds: tuple[int, ...] = (180, 300, 600, 1200, 3600),
    history_days: int = 180,
) -> list[tuple[int, float]]:
    """扫该用户最近 6 个月 cycling 活动 / 滑窗找各时长 best power。

    返：[(window_seconds, best_power_w), ...] 只含有效窗口（power > 0）

    设计思路：
        我们要的不是"某一次骑行的 best"，而是"近半年最强的一次表现"——
        所以对每个时长窗口（3min / 5min / 10min / 20min / 60min），
        遍历所有历史活动，取各活动该窗口的 max，再在所有活动间取 max。

    性能注意：
        每条活动单独查 trackpoints（功率非空）/ 内存里跑滑窗。
        100 用户量级 / 单用户 295 活动 / 单活动 ≤ 5 万点（worker 上限） → 可接受。
        v0.2 若慢可改为预计算缓存（new 表 user_best_efforts）。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=history_days)
    activity_ids = (
        db.query(Activity.id)
        .filter(
            Activity.user_id == user_id,
            Activity.status == "completed",
            Activity.activity_type == "cycling",
            Activity.started_at >= cutoff,
            Activity.avg_power.isnot(None),  # 没功率的活动直接跳过
        )
        .all()
    )

    if not activity_ids:
        return []

    # 用 dict 累积每个窗口长度的全局最佳
    best_per_window: dict[int, float] = {w: 0.0 for w in windows_seconds}

    for (aid,) in activity_ids:
        tps = (
            db.query(Trackpoint.power, Trackpoint.timestamp)
            .filter(
                Trackpoint.activity_id == aid,
                Trackpoint.power.isnot(None),
                Trackpoint.timestamp.isnot(None),  # 没时间戳算不了滑窗
            )
            .order_by(Trackpoint.seq)
            .all()
        )
        if len(tps) < 10:
            continue

        # 转 list[tuple[float, datetime]] for sliding window
        tps_list = [(float(p), t) for p, t in tps]

        for window_sec in windows_seconds:
            best = _sliding_window_best_power(tps_list, window_sec)
            if best > best_per_window[window_sec]:
                best_per_window[window_sec] = best

    # 过滤 0 值（该窗口压根没有数据）/ 返回 (duration, power) 对
    return [(w, p) for w, p in best_per_window.items() if p > 0]


def estimate_ftp_for_user(db: Session, user_id: int) -> EstimationResult:
    """FTP 估算主入口：20min HR gate 主锚点 + CP3 一致性检查。

    关键原则：CP3 不能再盲扫所有功率活动。只有同一窗口内同时有功率和心率，
    且心率强度像阈值努力，才会进入 `qualified_efforts`。
    """
    user = db.query(User).filter_by(id=user_id).first()
    if user is None:
        return EstimationResult(
            ftp=None, confidence="insufficient", method=_HR_GATED_METHOD, r2=0.0
        )

    effective_max_hr, max_hr_from_age = _effective_max_hr(user)
    if effective_max_hr is None:
        logger.info("estimate_ftp_for_user user_id=%s 缺 max_hr/birth_year", user_id)
        return EstimationResult(
            ftp=None, confidence="insufficient", method=_HR_GATED_METHOD, r2=0.0
        )

    efforts, valid_activity_count = _extract_hr_gated_efforts(
        db, user_id, effective_max_hr
    )
    p20 = next(
        (power for duration, power in efforts if duration == _P20_WINDOW_SECONDS),
        None,
    )
    if p20 is None:
        logger.info(
            "estimate_ftp_for_user user_id=%s 无合格 20min 窗口 efforts=%s",
            user_id, efforts,
        )
        return EstimationResult(
            ftp=None, confidence="insufficient", method=_HR_GATED_METHOD, r2=0.0
        )

    raw_ftp = p20 * 0.95
    suggested_ftp = _clamp_ftp(int(round(raw_ftp)) + _FTP_PRODUCT_BIAS_W)
    cp3_result = fit_cp3_model(efforts) if len(efforts) >= 3 else EstimationResult(
        ftp=None, confidence="insufficient", method="cp3_no_hr", r2=0.0
    )

    confidence = "low"
    if cp3_result.ftp is not None and raw_ftp > 0:
        diff_ratio = abs(cp3_result.ftp - raw_ftp) / raw_ftp
        powers = [power for _, power in efforts]
        power_spread = (max(powers) - min(powers)) / p20 if p20 > 0 else 0.0
        if (
            len(efforts) >= _MIN_EFFORTS_FOR_RELIABLE
            and diff_ratio <= _CP3_DIFF_RATIO_MAX
            and power_spread >= 0.08
        ):
            confidence = "medium"
    if max_hr_from_age:
        confidence = "low"

    logger.info(
        "estimate_ftp_for_user user_id=%s raw_ftp=%.1f suggested=%s confidence=%s "
        "r2=%s efforts=%s valid_activities=%s max_hr_source=%s",
        user_id, raw_ftp, suggested_ftp, confidence, cp3_result.r2, efforts,
        valid_activity_count, "age" if max_hr_from_age else "user",
    )
    return EstimationResult(
        ftp=suggested_ftp,
        confidence=confidence,
        method=_HR_GATED_METHOD,
        r2=cp3_result.r2,
        raw_ftp=raw_ftp,
    )
