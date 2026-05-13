# 任务 0.7：老数据回填脚本

## 🎯 目标

写 + 跑 `scripts/backfill_phase5.py`：给所有现有 segments 算 max_gradient / difficulty / city，给所有现有 users 推断 city。

## ⛓ 前置依赖

**task-0.6（v5 主迁移完成）+ task-1.A.1（算法函数 calculate_max_gradient / calculate_difficulty / infer_city_from_coords 实现完）**。

> ⚠ Sprint 顺序：0.6 跑完后段 segments 三新字段为 server_default 占位；1.A.1 算法函数实现后再回填精确值。**0.7 实际跑在 Sprint 1.A.1 完成之后**——但定义在 Sprint 0 是为了 closure 时一并 verify。

## 📤 输出契约

| 产出 | 用途 |
|------|------|
| scripts/backfill_phase5.py | 一次性回填脚本，幂等 |
| 220 条 segments 三新字段精确值 | Sprint 1.A.3 router 列表筛选准确 |
| 500 用户的 city（首次推断）| Sprint 2.A.1 / 2.C.2 热图筛选准确 |

## 🧱 现状

完整脚本见 `docs/spec-v5.md §2.6`（行 462-628）—— 含两段：
- `backfill_segments(db)` 单条 try/except 隔离 + SAVEPOINT + ST_DWithin geography cast
- `backfill_users_city(db)` 三段 fallback 链（30 天 / 全部 / NULL）

本 task 把 spec §2.6 抄成独立脚本，并写主入口 + 命令行调用。

## 🛠 完整代码

### `scripts/backfill_phase5.py`

```python
"""第 5 期老数据回填脚本（一次性，幂等）。

跑这个的前置：
1. alembic upgrade phase5_v5_db_changes（task 0.6 已跑）
2. 算法函数 calculate_max_gradient / calculate_difficulty / infer_city_from_coords 已实现（task 1.A.1 完成）

跑法：
    sudo docker compose exec api python3 -m scripts.backfill_phase5

幂等：再跑一次会重新算覆盖现有值，不会重复加新行。
"""
import logging
import sys
from app.database import SessionLocal

# 完整实现：抄 docs/spec-v5.md §2.6 行 462-628
# - backfill_segments(db)
# - backfill_users_city(db)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    db = SessionLocal()
    try:
        logger.info("=== 阶段 1：回填 segments ===")
        seg_failed = backfill_segments(db)
        
        logger.info("=== 阶段 2：回填 users.city ===")
        user_stats = backfill_users_city(db)
        
        logger.info(f"完成：seg_failed={len(seg_failed)} / user_unknown_pct={user_stats}")
        return 0 if not seg_failed else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
```

> **subagent 实施步骤**：
> 1. Read `docs/spec-v5.md` 行 462-628（§2.6 两段实现）
> 2. 把 backfill_segments + backfill_users_city 函数完整抄进 scripts/backfill_phase5.py
> 3. 在 docker container 内跑（需要 PG / PostGIS / 算法模块齐全）

### docker-compose 一次性容器（可选）

也可以加一个一次性 service 跑完即退：

```yaml
  backfill_v5:
    build: .
    command: python -m scripts.backfill_phase5
    depends_on:
      - db
    environment:
      DATABASE_URL: ${DATABASE_URL}
    restart: "no"  # 一次性跑完不重启
```

## ✅ 测试

### dry-run 验证（先 SELECT 不改）

```sql
-- 跑前看现状
SELECT difficulty, COUNT(*) FROM segments GROUP BY difficulty;
SELECT city, COUNT(*) FROM segments GROUP BY city;
SELECT city, COUNT(*) FROM users GROUP BY city;
```

### 跑脚本

```bash
sudo docker compose exec api python3 -m scripts.backfill_phase5
```

期望日志：
```
backfill segments: success=220, failed=0
backfill users.city: bj=120, sh=80, ..., unknown=15
```

### 跑后验证

```sql
SELECT difficulty, COUNT(*) FROM segments GROUP BY difficulty;
-- 期望：值分布合理（不再全是 'medium' default）
SELECT MAX(max_gradient), MIN(max_gradient), COUNT(*) FILTER (WHERE max_gradient IS NULL) FROM segments;
-- 期望：max_gradient 范围合理 / NULL 占比低（< 5%）
SELECT city, COUNT(*) FROM users GROUP BY city;
-- 期望：unknown 占比 < 30%（PRD 验收标准）
```

### 幂等验证

```bash
# 跑两次确认结果一致
sudo docker compose exec api python3 -m scripts.backfill_phase5
sudo docker compose exec api python3 -m scripts.backfill_phase5
```

## 📝 commit

```
feat(scripts): 任务 0.7 老数据回填脚本

scripts/backfill_phase5.py：
- backfill_segments：220 条 segments 算 max_gradient + difficulty + city
- backfill_users_city：500 用户三段 fallback 链推 city
- 单条 SAVEPOINT 隔离 + 失败记 logger 不阻断整体
- 幂等：可重复跑

预期跑后：
- segments difficulty 分布合理 / max_gradient NULL < 5%
- users.city unknown 占比 < 30%（PRD D-P10 验收）
```

## 🔍 自检三问

1. **崩溃恢复**：跑到第 100 条崩了 → 前 99 条已 commit 还是回滚？  
   → 单条 try/except + db.begin_nested() SAVEPOINT 隔离，单条失败回滚不影响其他；外层 db.commit() 在循环外，崩在循环内不写入。改为循环每条 commit 更安全（spec §2.6 选了批量 commit，可以接受重新跑幂等）。

2. **陷阱核查**：ST_DWithin 缺 `Trackpoint.geom.isnot(None)` 过滤 → spec 第二轮已修，subagent 抄时确认带这个过滤。

3. **下游波及**：跑期间 segments 被 admin 改了字段（5.D.3 批量管理）会冲突吗？  
   → v5 admin 模块 Sprint 3 才上线，0.7 跑在 Sprint 0/1 期，admin 还没启动——无并发冲突。
