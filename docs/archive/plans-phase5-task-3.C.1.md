# 任务 3.C.1：候选池脚本 + cron 配

## 🎯 目标

新建 `scripts/generate_curation_pool.py`：定时（每周一次）跑全表 segments 算 pool_score（热度 + 难度区间分布平衡），UPSERT 进 segment_curation_pool 表 top 100。

## ⛓ 前置依赖

- task-0.6（segment_curation_pool 表已建）
- task-1.A.1（segments 三新字段已就绪）

## 📤 输出契约

| 文件 / 配置 | 用途 |
|---|---|
| `scripts/generate_curation_pool.py` | 算 pool_score + UPSERT top 100 候选 |
| docker-compose curation-pool-cron 容器 | `while true; sleep 604800; python -m scripts.generate_curation_pool` |

## 🧱 现状

- `scripts/` 现有 2 脚本（cleanup_zombies.py / gen_learning_notes.py），spec §0.1 已查实
- 沿用现有 cron 模式：docker-compose 容器包装 + while sleep

## 🛠 完整代码

抄 spec §3.7.1（行 1898-1990）实现 `generate_curation_pool` 函数。

```python
"""候选池脚本（5.D.1）：每周一次跑，UPSERT top 100 候选。

排序分（PRD Q5 拍）：
- 热度（segment_efforts COUNT）权重 0.6
- 难度区间分布平衡（每档 ~25 条）权重 0.4

UPSERT by segment_id UNIQUE：幂等，可重复跑。
"""
import logging
import sys
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.database import SessionLocal
from app.segment.models import Segment, SegmentCurationPool, SegmentEffort

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# 完整算法实现：抄 spec §3.7.1 行 1898-1990
# - 查 Segment + COUNT(SegmentEffort) → 计算 popularity_score
# - 按 difficulty 分组取 top（保证四档分布平衡）
# - 合并算 pool_score
# - UPSERT segment_curation_pool（INSERT ... ON CONFLICT DO UPDATE）


def main() -> int:
    db = SessionLocal()
    try:
        logger.info("=== 开始生成候选池 ===")
        added, updated = generate_curation_pool(db)
        logger.info(f"完成：新增 {added} 条 / 更新 {updated} 条")
        return 0
    except Exception as e:
        logger.exception(f"候选池生成失败: {e}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
```

### docker-compose.yml 加 cron 容器

```yaml
  curation-pool-cron:
    build: .
    command: sh -c "while true; do python -m scripts.generate_curation_pool || true; sleep 604800; done"
    depends_on:
      - db
    environment:
      DATABASE_URL: ${DATABASE_URL}
    restart: unless-stopped
```

> 周期 604800s = 7 天。沿用 cleanup_zombies / monitor 容器包装模式。

### 实施补充：清理未选旧候选

脚本写入 top N 后，删除"本轮未入选 + 非人工选中"的旧候选行，保证候选池不无限累积；`selected_for_v5=True` 的候选不动（人工决定优先）。测试 `test_generate_prunes_unselected_stale_rows_but_keeps_selected` 钉死契约。

## ✅ 测试

```python
# tests/test_curation_pool_script.py
def test_generate_creates_top_100():
    # 跑前 segment_curation_pool 空，跑后 ≤ 100 条
def test_generate_idempotent():
    # 跑两次结果一致（UPSERT by segment_id）
def test_generate_difficulty_distribution_balanced():
    # 4 档 difficulty 各 ~25 条（容差 ± 5）
def test_generate_popularity_weighted():
    # 高 effort 数的 segment pool_score 较高
def test_generate_handles_empty_segments_table():
    # 0 条 segments → 跑通无错（返 0 added）
```

```bash
sudo docker compose exec api python3 -m scripts.generate_curation_pool
```

预期：日志显示新增 / 更新数；segment_curation_pool 表有 ≤ 100 行。

## 📝 commit

```
feat(scripts): 任务 3.C.1 候选池脚本 + cron 配

- scripts/generate_curation_pool.py（每周一次，UPSERT top 100）
- pool_score = popularity * 0.6 + diversity * 0.4（PRD Q5 拍）
- UPSERT by segment_id UNIQUE 幂等
- docker-compose curation-pool-cron 容器（while sleep 604800 包装）
```

## 🔍 自检三问

1. **幂等性**：UPSERT 失败到一半 → 部分行更新 / 部分未更新，下次跑会自愈吗？  
   → 是。UPSERT 单条事务，失败回滚单条。下次跑全表重算覆盖。

2. **新赛段时延**：候选池每周跑一次 → 新建 segment 最长 7 天才进候选池。spec §7 已限定"接受"。  
   → 是。

3. **跑期 admin 改候选**：脚本跑期间 admin 在 H5 切换 selected_for_v5 字段 → 冲突吗？  
   → UPSERT 只更新 pool_score / pool_reason / segment 关联字段，**不动 selected_for_v5 / selected_by_user_id**（这两个字段由 admin 独占管理）。spec §6.2 已确认。
