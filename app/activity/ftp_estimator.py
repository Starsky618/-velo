"""Sprint 9 task-5：CP 3-param eFTP 估算器。

这个文件干什么？
-----------------
当用户没有功率计实测 FTP（功能阈值功率），或者 FTP 长时间没更新时，
我们需要"算"出来一个估计值。原理类似于：通过你跑 100 米、400 米、1500 米的
最好成绩，反推你的"长距离稳定速度"（耐力区间）。骑行里的 eFTP 同理：
用 3/5/10/20/60 分钟的最大功率，反推你"能稳定输出 1 小时的功率"——这就是 FTP。

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
- v0.1 不做心率加权（method='cp3_no_hr'）/ v0.2 真用回归后再决定加不加
- scipy.optimize.curve_fit 可能数值不稳 / 异常 / 不收敛 → 必须 try/except 兜底
- 滑动窗口找 best power 用 O(n²) 简单实现 / v0.2 若性能瓶颈再优化成 O(n) 单调队列
- 该模块"纯计算 + DB 查询"，不写库 / 调用方负责持久化结果

输入/输出数据流：
    入参：db Session + user_id
    出参：EstimationResult(ftp, confidence, method, r2)
    依赖：Activity.activity_type='cycling' / Activity.status='completed' / Trackpoint.power
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.activity.models import Activity, Trackpoint
from app.user.models import User  # noqa: F401 — standalone script 防 SQLAlchemy 找不到外键关联表


logger = logging.getLogger(__name__)


# Codex 异源审 Critical：3-4 个 best efforts = 自由度 ≤ 1 → R² 趋向 1.0 = 虚假置信度
# 必须 ≥ 5 个 best efforts 才允许真正的 high/medium 置信度 / 否则强制降级 low
_MIN_EFFORTS_FOR_RELIABLE = 5


@dataclass
class EstimationResult:
    """eFTP 估算结果。

    像一份"体检报告"——既给数字（ftp），也给可信度（confidence + r2），
    让调用方决定要不要采用（比如低可信度时不覆盖用户手填值）。
    """
    ftp: Optional[int]    # 估算的 FTP（W），insufficient 时为 None
    confidence: str       # 'insufficient' / 'low' / 'medium' / 'high'
    method: str           # 'cp3_no_hr'（v0.1）/ 'cp3_hr_weighted'（v0.2）
    r2: float             # 拟合质量决定系数 / insufficient 时 = 0.0


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
    """eFTP 估算主入口。

    步骤：
      1. 扫历史 cycling 活动找 best 3/5/10/20/60 分钟功率
      2. 心率加权（v0.1 不做 / v0.2 加）
      3. scipy curve_fit 拟合 CP 3-param → CP ≈ FTP

    返：EstimationResult / 调用方根据 confidence 决定是否采用
    """
    efforts = _extract_best_efforts(db, user_id)
    if len(efforts) < 3:
        logger.info(
            "estimate_ftp_for_user user_id=%s 数据不足 efforts_count=%s",
            user_id, len(efforts),
        )
        return EstimationResult(
            ftp=None, confidence="insufficient", method="cp3_no_hr", r2=0.0
        )

    result = fit_cp3_model(efforts)
    logger.info(
        "estimate_ftp_for_user user_id=%s ftp=%s confidence=%s r2=%s",
        user_id, result.ftp, result.confidence, result.r2,
    )
    return result
