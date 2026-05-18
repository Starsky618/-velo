# Persona Engine Task-2 — 46 条模板入库 + 段位算法 + template_lib

> 所属：Persona Engine Sprint / 6 task 中的第 2 个 / 素材层
> 上下文：宪法 § 2 50 条精选（本 task 实施 46 条 / 跳过 § 2.7 跨时间镜像 4 条 / 留 v0.5）
> **共用约束 / SOP / 双审**：详见 `persona-engine-handoff.md`

---

## ─────── 给 Tim 看 ───────

### 干啥用

把宪法 § 2 那 46 条金标尺台词全部"录"进数据库 / 让 NPC 系统知道哪个场景该说哪句。

同时写一个"段位识别"小算法 —— 用户累计骑了多少 km 就归到哪个段位（萌新 / 入门 / 进阶 / 老登）/ 让同样 80km 的活动对不同段位用户说不同的话。

本 task 完成后系统**有了素材但还不会主动说话** —— task-3 才是大脑。

### 用户故事

无直接用户故事（内部任务 / 但为后续 task 提供 NPC 的"剧本库"）。

### 怎么算做对了

- ✓ `persona_templates` 表恰有 46 条 active 模板
- ✓ 每条 template_text **和宪法 § 2 字面 byte-by-byte 一致**（防文案漂移）
- ✓ 累计 8500km 用户被识别为"老登"段位
- ✓ 80km 距离被识别为 "normal" 桶
- ✓ pytest 跑通段位算法 / 距离桶算法 / pick 防 7 天重复
- ✗ 模板文本有任何错字 / 改动 / 命中宪法 § 3 反例关键词 = 是 bug

### 这次**不做**的事

- 触发判断（task-3 trigger_router）
- LLM 调用（v0.5+）
- 模板变量替换（本 Sprint 模板都是固定文案 / 不需要 user 名字 / 距离填入）

### 估时（v0.2 扩 / Tim 拍每场景 ≥ 5 条）

**2.5 天**（v0.1 = 1.5 天 / +1 天写新文案副线 cycle）

- v0.1 起步 46 条入库（已草拟 / 在 task 卡 data migration TEMPLATES list）
- v0.2 副线 cycle：Claude 起 8-10 候选 / Tim 拍 5 条金标尺 / 整组入库 / 总 7 cycle × 5 分钟 Tim 投入 ≈ 35 分钟（不阻塞工程实施 / 平行进行）
- 实施时 data migration TEMPLATES list 按 cycle 进度同步扩展（46 → ~158）

---

## ─────── 折叠：技术细节 ───────

<details>
<summary>展开</summary>

### 防火墙红线

参 handoff § 1。本 task 重点：
- § 1.1 ADR-009：template_lib 只读 `persona_templates` 表 / 不查任何业务表
- § 1.2 命名前缀：迁移文件 `persona_engine_seed_46.py` / 测试 `test_persona_template_lib.py`
- **额外红线**：模板文案 ground truth = 宪法 § 2 / pytest 字面比对防漂移（任何字符改动 fail）/ **v0.2 修 / Codex 抓 / 只比"文案内容。"部分**（不含 `【...】` 标签 / 不含 `（...）` 触发说明 / 见宪法 § 2 ground truth 注释）
- **v0.2 新红线**：每个 (scene_type, segment) ≥ 5 条（Tim 拍 / 防 broken record / 副线 cycle 扩到 ~158 条）

### template_lib.py 公开接口

```python
from typing import Optional
from sqlalchemy.orm import Session
from app.agent.persona.models import PersonaTemplate

def compute_user_stage(total_distance_m: int) -> str:
    """累计距离（米）→ 段位（纯函数 / 不查 DB）。

    阈值（宪法 § 2.2 实证）：
    - < 500_000 → 'rookie'   （萌新）
    - 500_000 - 3_000_000 → 'entry'  （入门）
    - 3_000_000 - 8_000_000 → 'mid'  （进阶）
    - > 8_000_000 → 'veteran'（老登）
    """

def compute_distance_bucket(distance_m: int) -> str:
    """单次活动距离（米）→ 桶（纯函数）。

    v0.2 cycle 1 修（2026-05-17 Tim 拍）：normal 中位从 80km 下调 40km
    （velo 用户群周末甜区 30-60km / 80km 已属 long 桶 / 不是日常）。

    - < 5_000 → 'tiny'
    - 5_000 - 30_000 → 'short'
    - 30_000 - 60_000 → 'normal'    （中位 ~45km）
    - 60_000 - 150_000 → 'long'     （中位 ~100km）
    - > 150_000 → 'extreme'
    """

def get_templates_for_scene(
    db: Session,
    scene_type: str,
    segment: Optional[str] = None,
) -> list[PersonaTemplate]:
    """查匹配模板。segment=None 时查该 scene_type 下所有 segment=NULL 的通用模板。"""

def pick_template(
    templates: list[PersonaTemplate],
    user_id: int,
    recent_template_ids: list[int],
) -> Optional[PersonaTemplate]:
    """从 pool 选一条 / 优先避开 recent_template_ids / pool 耗尽返第一条。"""
```

### 46 条模板 data migration

文件：`migrations/versions/persona_engine_seed_46.py`

```python
"""persona_engine_seed_46

Revision ID: persona_engine_seed_46
Revises: persona_engine_init
"""

TEMPLATES = [
    # § 2.1 PR (6)
    ("pr", None, "今天嗑药了？"),
    ("pr", None, "今天你最猛。"),
    ("pr", None, "数据有点过分。"),
    ("pr", None, "前 1% 的一天。"),
    ("pr", None, "把自己拉爆了。"),
    ("pr", None, "8500km 里这一天。"),

    # § 2.2 段位 × 距离 (8 / v0.2 cycle 1 修 / normal 锚 80→40 / 让 40km 真落 normal 桶)
    ("segment_distance", "rookie_normal",  "今天 40km。挺猛。"),
    ("segment_distance", "entry_normal",   "今天 40km。可以的吧。"),
    ("segment_distance", "mid_normal",     "今天 40km。日常水平了。"),
    ("segment_distance", "veteran_normal", "40km。蹬两脚意思意思。"),
    ("segment_distance", "rookie_short",   "30km。开了个头。"),
    ("segment_distance", "entry_long",     "100km。稳得很。"),
    ("segment_distance", "mid_long",       "150km。说明状态在。"),
    ("segment_distance", "veteran_extreme","200km。膝盖呢。"),

    # § 2.3 连骑高频 (6)
    ("consecutive_high", None, "把膝盖磨成粉了？"),
    ("consecutive_high", None, "锁鞋焊脚上了？"),
    ("consecutive_high", None, "屁股还活着吗？"),
    ("consecutive_high", None, "车架冒烟没？"),
    ("consecutive_high", None, "本周第 5 次了。"),
    ("consecutive_high", None, "今天又上车。停不下来了。"),

    # § 2.4 沉寂 (6)
    ("silence", None, "最近去哪儿了。"),
    ("silence", None, "充电桩等你好久了。"),
    ("silence", None, "上次骑车 12 天前。"),
    ("silence", None, "膝盖恢复完了？"),
    ("silence", None, "车蹭灰了吧。"),
    ("silence", None, "胎压还在吗。"),

    # § 2.5 极端数据 (8)
    ("extreme", "night",          "又是夜骑党。"),
    ("extreme", "tiny",           "5 公里？撒尿都不够。"),
    ("extreme", "long_dist",      "150km 了。洗澡去吧。"),
    ("extreme", "high_speed",     "这平均速度，摩托吧？"),
    ("extreme", "late_collapse",  "前快后慢，老剧本了。"),
    ("extreme", "rain",           "雨里也出去？禧玛诺交响曲好听吗。"),
    ("extreme", "early",          "这点出门？老登。"),
    ("extreme", "low_speed",      "今天电助力坏了吗？"),

    # § 2.6 空状态 / 错误 / 加载 (8)
    ("empty_error", "empty",          "还没数据。先去蹬两圈。"),
    ("empty_error", "upload_failed",  "今天轨迹丢了。下次记得开 GPS。"),
    ("empty_error", "network_down",   "连不上。WiFi 切流量试试。"),
    ("empty_error", "server_5xx",     "服务器在打盹儿。"),
    ("empty_error", "loading",        "算你的高光中…"),
    ("empty_error", "unauth_401",     "要重新登录一下了。"),
    ("empty_error", "uploading",      "正在抢救你今天的轨迹。"),
    ("empty_error", "delete_confirm", "这条骑行要丢了哦。"),

    # § 2.8 错峰惊喜 (4)
    ("surprise", "solar_term",  "立秋了，凉快下来了。"),
    ("surprise", "anniversary", "上车一周年。8500km。"),
    ("surprise", "milestone",   "1 万了。老登正式入会。"),
    ("surprise", "new_year",    "新年第一蹬。"),
]
# 总计 46 条

def upgrade():
    # batch insert 46 条
    ...

def downgrade():
    op.execute("DELETE FROM persona_templates")
```

### 测试要求（`tests/test_persona_template_lib.py`）

最少 8 条 pytest：

1. **模板总数**：`SELECT count(*) FROM persona_templates WHERE active = true` **>= 46**（v0.3 修 / Claude A 抓 I-new-2 / 副线 cycle 扩到 ~158 进度变化 / 用 >= 而不是 ==）
2. **字面漂移检测**：每条 template_text 和 hardcoded list（从宪法 § 2 复制）byte-by-byte 一致
3. **段位算法边界**：
   - `compute_user_stage(0)` == "rookie"
   - `compute_user_stage(500_000)` == "entry"（边界值归右）
   - `compute_user_stage(8_500_000)` == "veteran"
4. **距离桶算法**：
   - `compute_distance_bucket(80_000)` == "normal"
   - `compute_distance_bucket(4_999)` == "tiny"
   - `compute_distance_bucket(200_000)` == "extreme"
5. **场景查询**：`get_templates_for_scene("pr")` 返 6 条
6. **段位过滤**：`get_templates_for_scene("segment_distance", "veteran_normal")` 返 1 条 = "80km。蹬两脚意思意思。"
7. **pick 防重复**：用户最近用过 id=1 / pool=[1,2,3] → pick 返 id=2 or 3
8. **pool 耗尽兜底**：用户用过 [1,2,3] / pool=[1,2,3] → pick 仍返 list[0]（不返 None）

### 双审 focus

参 handoff § 2.3 + § 2.4。本 task **重点扫**：
- 46 条文案宪法字面一致（漂移 = Critical / 直接 fail）
- 段位 / 距离桶边界值正确
- `pick_template` 防重复逻辑 + pool 耗尽兜底
- ADR-009 不反向 import（不查 activities / users 业务表）

### 依赖

- 依赖：task-1（表存在）
- 阻塞：task-3（trigger_router 调 template_lib）

### 部署 verify

```bash
docker compose exec db psql -c "SELECT count(*) FROM persona_templates WHERE active = true"  # 46
docker compose exec db psql -c "SELECT template_text FROM persona_templates WHERE scene_type='pr'"  # 6 条对照宪法 § 2.1
```

</details>
