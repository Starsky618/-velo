# Persona Engine Task-3 — trigger_router + filters + cache + service api

> 所属：Persona Engine Sprint / 6 task 中的第 3 个 / 大脑层
> 上下文：宪法 § 6 用法说明 + § 7.2 四不规则
> **共用约束 / SOP / 双审**：详见 `persona-engine-handoff.md`

---

## ─────── 给 Tim 看 ───────

### 干啥用

给 NPC 装"大脑"——根据用户做的事判断该不该说话、说哪个场景、选哪条具体台词、跑防漂移检查、防 7 天内重复。

本 task 完成后 NPC 系统**内部决策完整可跑** —— 但还没接业务（task-4）/ 还没前端展示（task-5）。

### 用户故事

无直接用户故事（内部 service 层 / 被 task-4 调用）。

### 怎么算做对了

- ✓ 7 种 event 都能被正确路由到对应 scene_type + segment
- ✓ 文案含宪法 § 3 反例关键词（"恭喜你" / "棒棒哒"等）→ filter 直接 reject
- ✓ 文案 < 5 字 或 > 25 字 → filter 直接 reject
- ✓ 用户最近 7 天用过的模板不会再选（pool 耗尽兜底）
- ✓ persona service 任何子模块抛错 → 顶层 catch / 返 None / 不污染调用方事务
- ✗ persona service 抛 5xx / 让调用方崩 = 严重 bug（违反宪法 § 7.2"不传染失败"）

### 这次**不做**的事

- 业务接入（task-4：worker hook / endpoint）
- 前端展示（task-5）
- LLM 调用（v0.5+）
- 用户 A/B 分组（v1.0+）

### 估时

2 天

---

## ─────── 折叠：技术细节 ───────

<details>
<summary>展开</summary>

### 防火墙红线

参 handoff § 1。本 task 特别重点：
- § 1.1 ADR-009：service 接收**参数 dict** / 不查业务 service / 只读 ORM 模型
- § 1.4 失败隔离：**service 顶层必须 try/except 兜底返 None**（CRITICAL）

### `trigger_router.py` 接口

```python
from typing import Optional
from pydantic import BaseModel
from datetime import datetime

class PersonaEvent(BaseModel):
    # v0.2 修 / Claude A 抓 I-4 / 补全 7 种 event type
    type: str  # 'activity_uploaded' / 'consecutive_high_detected' / 'silence_detected' / 'milestone_reached' / 'empty_state' / 'error_state' / 'pr_detected'(deprecated - PR 是 activity_uploaded 内分支)
    activity_data: Optional[dict] = None  # 活动相关数据 dict
    user_data: dict  # 用户上下文（含 total_distance_m / last_activity_days / weekly_count）
    timestamp: datetime
    error_code: Optional[str] = None  # error_state event 用

class PersonaDecision(BaseModel):
    scene_type: str
    segment: Optional[str] = None
    context_dict: dict = {}  # 给前端展示用的附加上下文
    fallback_template_id: Optional[int] = None  # v0.2 修 / Claude A 抓 I-1 / 主 pool 查空时降级用

def route(event: PersonaEvent) -> Optional[PersonaDecision]:
    """7 种 event 路由 / 返 None 表示该 event 暂无文案。"""
```

### 7 种 event 路由判定（route 内部逻辑）

| event.type | 触发条件（用 event.activity_data + user_data） | 决策输出 |
|---|---|---|
| `activity_uploaded` + PR | activity 任一字段（distance / elevation_gain / duration / np）打破历史 max | `scene_type='pr'`, segment=None |
| `activity_uploaded` + 非 PR | else（普通活动）| `scene_type='segment_distance'`, segment=`{stage}_{bucket}` |
| `activity_uploaded` + 夜骑 | `started_at` 23-04 点 | `scene_type='extreme'`, segment='night'（**优先于段位**）|
| `activity_uploaded` + 极端 | 距离 < 5 / > 150 / 速度 > X / 速度 < Y / ...8 种 | `scene_type='extreme'`, segment=对应类型 |
| `consecutive_high_detected` | user_data.weekly_count ≥ 5 | `scene_type='consecutive_high'`, segment=None |
| `silence_detected` | user_data.last_activity_days ≥ 7 | `scene_type='silence'`, segment=None |
| `empty_state` / `error_state` | 前端透传 | `scene_type='empty_error'`, segment=error_code |
| `milestone_reached` | user_data 触发节气 / 周年 / 累计跨阈值 | `scene_type='surprise'`, segment=对应类型 |

**优先级**：极端 trigger 优先于段位 trigger（同一活动夜骑 80km → 走 'extreme/night' 不走 'segment_distance/...'）。

### `filters.py` 接口

```python
ANTI_PATTERN_KEYWORDS = [
    # v0.2 修 / Codex 异源审 + Claude A 抓 / 补全宪法 § 3 全部 9 类
    # § 3.1 开场禁区
    "恭喜你", "您", "亲", "亲爱的", "哥哥", "小可爱", "小老弟",  # v0.2 补哥哥/小可爱
    # § 3.2 套娃数学
    "相当于", "等于", "等同于", "绕地球", "次珠峰", "根香蕉",
    # § 3.3 表演式鼓励
    "棒棒哒", "真厉害", "太牛了", "加油",
    "突破自我", "创造奇迹", "永不放弃",
    "Keep going", "Stay strong",
    # § 3.4 客服腔
    "您还没有", "请检查", "感谢您", "建议您", "适度休息",
    # § 3.5 emoji 与"哈哈哈"笑场（v0.2 补）
    "哈哈哈",  # 字面笑场 / emoji 由独立 unicode 检查（见 check_no_emoji helper）
    # § 3.6 结构化表达（v0.2 补）
    "首先", "其次", "最后",
    # § 3.7 破圈梗
    "yyds", "绝绝子", "蚌埠住了", "泰裤辣",
    "不是吧不是吧", "我直接好家伙",
    "doge", "狗头保命",
    # § 3.8 中年油腻
    "哎呦不错哦", "牛批",
    # § 3.9 拙劣模仿英式（v0.2 补）
    "我觉得", "我严重怀疑",
]

# v0.2 补 / § 3.5 emoji 单独检查（关键词无法穷举 emoji unicode 范围）
def _contains_emoji(text: str) -> bool:
    """检测文本含 emoji / 颜文字 / 装饰符。"""
    import re
    # emoji unicode 范围 + 常见颜文字 + 波浪号 + 中括号装饰
    emoji_pattern = re.compile(
        r"[\U0001F300-\U0001F9FF\U0001F600-\U0001F64F☀-➿]|"
        r"~~|【|】|"
        # v0.3 修 / Codex 抓 I2 / ASCII 颜文字
        r":\)|:\(|:D|:P|;\)|\^_\^|\^\.\^|T_T|TT|>_<|orz|=口="
    )
    return bool(emoji_pattern.search(text))

def check_anti_pattern(text: str) -> bool:
    """命中宪法 § 3 任一关键词 → True（reject）/ 安全 → False。"""

def check_length(text: str) -> bool:
    """5 ≤ len(text) ≤ 25 (Unicode codepoint) → True (合格) / 否则 False (reject)。"""

def is_safe(text: str) -> bool:
    """组合检查：通过所有 filter → True。"""
```

### `cache.py` 接口

```python
from datetime import datetime, timedelta, timezone

def get_recent_outputs(
    db: Session,
    user_id: int,
    scene_type: str,
    days: int = 7,
) -> list[int]:
    """查最近 N 天该 scene_type 用过的 template_id。"""

def record_output(
    db: Session,
    user_id: int,
    scene_type: str,
    template_id: int,
    text_snapshot: str,  # v0.4 修 / Claude A+B 共识 C1 / 文案快照
    activity_id: Optional[int] = None,
) -> None:
    """写 persona_outputs（含 text_snapshot 文案快照 / 避免未来 endpoint JOIN）。失败 fire-and-forget / 不抛错。"""
```

### `service.py` 主入口（v0.3 修 / Claude A + B 共识 C2 / 补全 3 个公开函数）

```python
import logging
from typing import Optional
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.agent.persona import trigger_router, template_lib, filters, cache
from app.agent.models import PersonaOutput

logger = logging.getLogger(__name__)

# 前端语义 scene_type 集合（v0.3 / Claude A 抓 C1 / endpoint 退化用）
FRONTEND_SEMANTIC_SCENES = {"profile_open", "user_page_open", "activity_upload"}


def get_latest_output_for_scene(
    db: Session,
    user_id: int,
    scene_type: str,
    activity_id: Optional[int] = None,
) -> Optional[PersonaOutput]:
    """endpoint 查询函数（v0.3 修 / Claude A + B 共识 C2）。

    - scene_type ∈ FRONTEND_SEMANTIC_SCENES（profile_open 等前端语义）
      → 退化为查最近 24h 该用户**任意宪法场景**最新一条
      → 让 profile 一打开就有文案（不限定特定场景）
    - scene_type ∈ 7 种宪法场景 → 按 scene_type 过滤
    - activity_id != None → 加 `WHERE activity_id IN (X, NULL)` 过滤
    - 返最近 24h 内最新一条 / 24h 外返 None
    """
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    query = db.query(PersonaOutput).filter(
        PersonaOutput.user_id == user_id,
        PersonaOutput.shown_at >= since,
    )
    if scene_type not in FRONTEND_SEMANTIC_SCENES:
        query = query.filter(PersonaOutput.scene_type == scene_type)
    if activity_id is not None:
        query = query.filter(
            (PersonaOutput.activity_id == activity_id) | (PersonaOutput.activity_id.is_(None))
        )
    return query.order_by(PersonaOutput.shown_at.desc()).first()


def get_recent_outputs(
    db: Session,
    user_id: int,
    limit: int = 10,
) -> list[PersonaOutput]:
    """拿用户最近 N 条 NPC 输出历史（v0.3 修 / Claude A + B 共识 C2）。"""
    return (
        db.query(PersonaOutput)
        .filter(PersonaOutput.user_id == user_id)
        .order_by(PersonaOutput.shown_at.desc())
        .limit(limit)
        .all()
    )


def generate_persona_output(
    event: trigger_router.PersonaEvent,
    db: Session,
) -> Optional[str]:
    """NPC 文案生成主入口 / 一站式流水线。

    流水线：route → template_lib → filters → cache。
    任何一步失败 / 返 None / **顶层 catch Exception 防传染**。
    """
    try:
        # 1. 路由决策
        decision = trigger_router.route(event)
        if decision is None:
            return None

        # 2. 查模板池
        templates = template_lib.get_templates_for_scene(
            db, decision.scene_type, decision.segment
        )
        if not templates:
            return None

        # 3. 查最近用过的
        user_id = event.user_data.get("user_id")
        recent_ids = cache.get_recent_outputs(
            db, user_id, decision.scene_type, days=7
        )

        # 4. 选一条
        picked = template_lib.pick_template(templates, user_id, recent_ids)
        if picked is None:
            return None

        # 5. 防漂移 filter
        if not filters.is_safe(picked.template_text):
            logger.warning(
                f"persona filter reject: scene={decision.scene_type} "
                f"template_id={picked.id} text={picked.template_text!r}"
            )
            return None

        # 6. 写历史 cache（fire-and-forget / v0.4 修 / 加 text_snapshot 文案快照）
        try:
            cache.record_output(
                db, user_id, decision.scene_type, picked.id,
                text_snapshot=picked.template_text,  # v0.4 修 / Claude A+B C1 / 文案快照防 endpoint JOIN
                activity_id=event.activity_data.get("id") if event.activity_data else None,
            )
        except Exception as e:
            logger.warning(f"persona cache write failed (ignored): {e}")

        return picked.template_text

    except Exception as e:
        # 宪法 § 7.2 "不传染失败" 顶层兜底
        logger.exception(f"persona service unexpected error (returned None): {e}")
        return None
```

### 测试要求（`tests/test_persona_service.py` + `test_persona_filters.py` + `test_persona_router.py`）

最少 12 条 pytest：

1. **route 7 种 event**：每种 event 各模拟一次 / 验证 scene_type 正确
2. **PR 优先**：activity 既是 PR 又是夜骑 → 走 'pr' 优先（设计取舍 / 实施时确认 PR 优先级最高）
3. **极端优先段位**：夜骑普通 80km → 走 'extreme/night' 不走 'segment_distance'
4. **filter 反例命中**：`check_anti_pattern("恭喜你完成 PR")` == True
5. **filter 长度卡极简**：`check_length("稳。")` == False（< 5 字）
6. **filter 长度卡过长**：`check_length("x" * 26)` == False（> 25 字）
7. **filter 长度合格**：`check_length("今天嗑药了？")` == True
8. **cache 防 7 天重复**：插一条 persona_outputs / `get_recent_outputs` 返该 id
9. **cache 8 天前不算最近**：插 8 天前的 / `get_recent_outputs(days=7)` 不返
10. **service 端到端**：mock PR event → 返 6 条 PR 模板之一
11. **service 失败兜底**：故意让 template_lib 抛 Exception → service 返 None / 不抛
12. **service 不传染**：故意让 cache.record_output 抛 Exception → service 仍返合法文案（fire-and-forget）

### 双审 focus

参 handoff § 2.3 + § 2.4。本 task **重点扫**：
- service 顶层 try/except 是否真兜底（**绝对 critical**）
- filter ANTI_PATTERN_KEYWORDS 列表是否覆盖宪法 § 3 全部 9 类
- cache.record_output 失败是否真 fire-and-forget（不影响主返）
- ADR-009 不反向 import（trigger_router / filters / cache / service 都只 from app.agent.persona / app.agent.models）

### 依赖

- 依赖：task-1 + task-2（service 调 template_lib）
- 阻塞：task-4（业务接入）+ task-5（前端展示）

### 部署 verify

```bash
docker compose exec api python -c "
from app.agent.persona.service import generate_persona_output
from app.agent.persona.trigger_router import PersonaEvent
from datetime import datetime, timezone
event = PersonaEvent(
    type='activity_uploaded',
    activity_data={'distance': 80000, 'elevation_gain': 600, 'started_at': '2026-05-16T10:00:00Z'},
    user_data={'user_id': 1, 'total_distance_m': 8500000, 'weekly_count': 2, 'last_activity_days': 1},
    timestamp=datetime.now(timezone.utc),
)
# 需要 DB session / 这里只测 import 通
print('OK')
"
```

</details>
