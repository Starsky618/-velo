# 任务 2.A.1：notification.progress_detector + payload 字段

## ✅ 完成状态（2026-04-30）

- commit `7611042` / 10 测试全过真 PG / 0.78s
- 实施时**主动捕获 spec §3.4 SAVEPOINT 隐患**：detector 内部 `db.commit()/db.rollback()` 会回退 worker 在同 session 改的 `activity.status='completed'` → 升级为 `db.begin_nested()` SAVEPOINT 隔离 + 同步 spec
- codex 异源审网络层连续 2 次流断 → **3 层兜底成熟**：知识层验证 + 主线程自审 + 实证测试（`test_savepoint_isolates_failure_from_outer_transaction`）
- 沉淀：CLAUDE.md 陷阱清单 #13 / memory `feedback_savepoint_isolation_for_inner_modules.md`

## 🎯 目标

新建 `app/notification/progress_detector.py`：
- `detect_5min_power_progress(db, user_id, activity_id)` 检测 5 分钟功率进步 ≥ 5W → 写 notification
- 同步 worker 集成 hook（在 status='completed' 切换点调用）

`Notification` model 加 `payload JSONB` 字段（task 0.6 已迁，本 task 加 ORM 声明）。

## ⛓ 前置依赖

- **task-2.B.1（硬依赖）**——spec §3.4 第 1552 行 import `calculate_power_curve` + `calculate_power_curve_from_activities`，在 2.B.1 实现。**2.A.1 必须等 2.B.1 完成**（2026-04-30 grep 实证 / Tim 拍）
- task-2.C.2（软依赖）—— `invalidate_power_curve_cache` 在 2.C.2 实现；本 task worker 集成 hook 调用此函数，可先 stub / 等 2.C.2 真实现后无缝替换
- task-0.6（notifications.payload 字段 + event_type CHECK 扩展）—— **已完成**，model 已同步（models.py:114-118 + 138-142）

## ⚠ task 卡 stale 标记（2026-04-30 grep 验证）

- ❌ "前置依赖只列 task-1.A.1" 错——1.A.1 是 segment 算法，与 power_curve 无关
- ❌ "本 task 加 ORM 声明（payload）" 错——payload 已在 task-0.6 加 ORM 声明（models.py:114-118）
- ❌ "event_type CHECK 扩展" 错——已扩展（models.py:138-142 含 6 值）
- ✅ 真正本 task 要做的：**只新建 progress_detector.py + worker hook 集成**（model 全已就绪）

## 📤 输出契约

| 函数 | 用途 |
|---|---|
| `detect_5min_power_progress(db, user_id, activity_id) -> Notification \| None` | worker hook 调，命中阈值写 notification |

## 🧱 现状

- `app/notification/detector.py` 现有 PR / KOM 检测器（沿用，本 task 不动）
- `app/notification/progress_detector.py` **不存在**，本 task 新建
- `app/notification/models.py:85-86` 加 payload 字段

## 🛠 完整代码

抄 `docs/spec-v5.md §3.4`（行 1505-1675）—— 含完整 `detect_5min_power_progress` 实现。

**关键修订（前 3 轮已修）**：
- `from datetime import datetime, timedelta, timezone`（含 timedelta）
- "上月" 用 BJ_TZ 转换（CLAUDE.md 时区约定，第三轮 R3-C3 修）
- `if baseline_5min <= 0: return None` 守卫（codex E1 漏抓 + R3-I1 修）
- `mute_notifications` 静音用户跳过
- 调 `calculate_power_curve_from_activities`（task-2.B.1 实现）按 activity 分组算 baseline

### Notification model 加字段

```python
# app/notification/models.py
payload = Column(JSONB, nullable=True)  # v5 新增（progress detector 写入）
```

CheckConstraint 扩展（task 0.6 已迁，model 同步）：

```python
__table_args__ = (
    # ... 沿用现有
    CheckConstraint(
        "event_type IN ('pr','kom','kom_lost','progress_segment_pb','progress_5min_power')",
        name='ck_notifications_event_type',
    ),
)
```

### worker 集成

修 `app/activity/worker.py` 在 status='completed' 赋值后、commit 前加：

```python
from app.notification.progress_detector import detect_5min_power_progress
from app.user.service import invalidate_power_curve_cache  # task-2.C.2 实现

# activity.status = 'completed' 之后立即触发
detect_5min_power_progress(db, activity.user_id, activity.id)
invalidate_power_curve_cache(activity.user_id)
# 然后 db.commit()
```

> ⚠ 实施前 grep 找 status='completed' 赋值点：
> `grep -n "status\s*=\s*['\"]completed" app/activity/worker.py`

## ✅ 测试

```python
# tests/test_progress_detector.py
def test_no_baseline_last_month_returns_none(): ...
def test_baseline_zero_returns_none():  # codex E1 漏抓项
    # 上月 activity 全无功率 → baseline=0 → 不推送（不假阳性）
def test_current_5min_zero_returns_none(): ...
def test_delta_4w_returns_none():  # < 5W 阈值
def test_delta_5w_creates_notification(): ...
def test_delta_negative_returns_none():  # 退步
def test_mute_user_returns_none(): ...
def test_uses_bj_timezone_for_month_boundary():
    # 关键：构造一个"BJ 1 号 0 点 8 分钟前的 activity"，UTC 看是上月、BJ 看是本月
    # 确认按 BJ 划月，不被 UTC 错归
def test_payload_contains_activity_id_and_baseline(): ...
```

## 📝 commit

```
feat(notification): 任务 2.A.1 progress_detector + payload 字段

- 新建 app/notification/progress_detector.py（5 分钟功率进步检测）
  - baseline_5min <= 0 守卫（codex E1 漏抓 + R3-I1）
  - "本月" 按 BJ_TZ +8 划分（CLAUDE.md 时区约定）
  - mute_notifications 静音用户跳过
  - 调 calculate_power_curve_from_activities（task-2.B.1）按 activity 分组
- Notification model 加 payload JSONB 字段（task-0.6 已迁，ORM 同步）
- event_type CHECK 扩展加 progress_5min_power / progress_segment_pb
- worker 集成 hook：status='completed' 切换点调用 detector + invalidate cache
```

## 🔍 自检三问

1. **baseline=0 守卫**：上月所有活动无功率（如全用单车架训练台无功率计） → baseline=0 → 守卫拦截 → 返 None。覆盖了吗？  
   → 是，第三轮 R3-I1 已修。test_baseline_zero_returns_none 验证。

2. **时区一致性**：本月划分用 BJ_TZ，与 §3.6 看他人主页 / §3.3 power_curve 划分逻辑一致吗？  
   → 是。spec 第三轮 R3-C3 已统一三处都用 BJ_TZ。

3. **worker hook 时序**：detect_5min_power_progress 调用必须在 activity.status='completed' 已赋值后、db.commit 前——避免读到旧状态的 activity？  
   → 是。spec §3.4 已写明 hook 位置。subagent grep status='completed' 赋值点确认。
