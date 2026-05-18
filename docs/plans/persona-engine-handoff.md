# Persona Engine Sprint Handoff —— 共用约束 / SOP / 双审顺序

> 所属：Persona Engine Sprint（NPC 文案系统 v0.1）
> 这是 6 个 task 卡的**共用文档** / 不重复写在每卡 / task 卡引用本文 §章节
> 上下文：2026-05-16 Tim 拍 / 防火墙隔离作为本 Sprint 顶层硬约束
> 状态：**plans v0.4 已 ship**（4 轮双审 / Critical=0 / 2026-05-16）/ 等实施

---

## § 0 新 claude 起手指南（实施 claude 进程必读 / 不要读 4 轮双审历史）

**起手 5 分钟做完这 5 件事 / 然后进 task-1**：

1. **读 Persona 宪法**：`docs/agent-rules/persona-constitution.md`（NPC 灵魂源 / ~558 行 / 全读 / 这是文案 ground truth）
2. **读 Sprint PRD**：`docs/prd/persona-engine-sprint-prd.md` § 0 north star + § 0.1 真实代码事实表 + § 1 共用规范引用（前 150 行）/ § 3 9 章节按 task 顺序进时再读
3. **读 handoff（本文）**：§ 1 防火墙红线 + § 2 SOP + § 3 拔出脚本 + § 4 依赖图 + § 5 工期
4. **读当前 task 卡**：按 task-1 → task-6 顺序 / 每张卡"给 Tim 看"层 + 技术细节折叠层
5. **起手 grep 防 stale**：
   ```bash
   ls migrations/versions/ | tail -3   # 确认真 head（防 Sprint 6 实施后 head 又前移）
   ls app/agent/                       # 确认现有 agent 模块
   cat app/agent/__init__.py           # 学边界声明样
   ```

**协作纪律（不写下来新 claude 不会知道）**：
- **副线 cycle 扩 112 条新文案**：和 task-2 工程实施**并行** / Claude 起 8-10 候选 → Tim 拍 5 条金标尺 → 整组入库 → 下一场景 cycle。**不一次性丢 100 条给 Tim**（按"每场景 ≥ 5 条"硬约束扩到 ~158 条 / 7 个场景 × 5 cycle ≈ 7 轮 Tim 投入）
- **代码层三重审判**：每 task ship 前 Claude A 忠 spec + Claude B 集成 + Codex 异源（按 `docs/agent-rules/agent-collaboration.md §4 场景 B`）
- **真用回归 final gate**：task-6 必须真用 7 场景 + 拔出测试 / 不能 mock-only ship

**已知残留 Important（实施时代码层双审会再次抓 / 不慌）**：
- activity_upload 退化逻辑应严格 activity_id 过滤（Codex 第三轮 I2）
- `_detect_pr` 加 `(user_id, activity_type)` 索引建议（Codex 第三轮 I3）
- PersonaOutputResponse 字段名注释明确"手工映射不是 ORM 自动"（Claude A+B 第四轮 I1）
- persona-scanner 删多余 REDIS_URL（Claude B 第四轮 I2）
- router.py 实施时补 imports（Claude A 第四轮 I2）

---

## § 1 防火墙 / 隔离红线（六卡共用 / 必读 / 宪法 § 7 落地）

所有 6 个 task 必须**同时**守住下列硬约束。违反任一 → REJECT / 重做：

### 1.1 ADR-009 边界（每模块顶部必含声明）

- `app/agent/persona/` 内任何文件**不允许** `from app.user.service import ...` / `from app.activity.service import ...` / `from app.segment.service import ...` 等业务 service
- 允许：`from app.user.models import User` / `from app.activity.models import Activity`（只读 ORM 模型 / 不调业务逻辑）
- 允许：参数 dict 由调用方喂进来（worker / endpoint 主动调 persona service 时把数据打包传入）

### 1.2 命名前缀约定（宪法 § 7.5.1 / 让"哪些是 persona 资产"可 grep）

所有 Persona Engine 相关资产必须以下列前缀命名：

| 资产 | 命名 |
|---|---|
| 数据库表 | `persona_*` |
| 迁移文件 | `migrations/versions/persona_engine_*.py` |
| 测试文件 | `tests/test_persona_*.py` |
| 后端代码 | `app/agent/persona/` 整目录 |
| 前端工具 | `miniprogram/utils/persona_*.js`（如有） |
| 前端 wxml 块 | `<!-- PERSONA_START -->` / `<!-- PERSONA_END -->` 标记 |
| 配置 env | `PERSONA_*`（如未来加） |
| Scheduler 脚本 | `scripts/persona_*.py` |

**收益**：一条命令列全部资产 → `find . -name "*persona*" -o -name "persona_*"`

### 1.3 数据隔离（宪法 § 7.3）

- 3 张表（`persona_outputs` / `persona_templates` / `persona_feedback`）独立
- 允许 FK：`user_id → users.id` / `activity_id → activities.id`（只 reference / 不写入）
- 禁止：修改 `users` / `activities` / `segments` / `notifications` 等核心表的任何字段

### 1.4 失败隔离（宪法 § 7.2 "不传染失败"）

- worker hook 调 persona service **必须**用 `db.begin_nested()` SAVEPOINT 隔离（CLAUDE.md 陷阱 #13）
- persona service 顶层 catch 任何 Exception → 返 `None` / 不抛
- endpoint 调 service 抛错 → 返 200 + `template_text: null` / 不返 5xx

### 1.5 MANIFEST 强制更新

每 task 加新资产 → 必须更新 `app/agent/persona/MANIFEST.md`（PR review 红线 / 不更新不让 merge）

---

## § 2 共用 SOP

### 2.1 起手必跑 grep（每 task 实施前先重新 grep / 防 PRD § 0.1 stale）

```bash
# 当前 migration head
ls migrations/versions/ | tail -5

# agent 模块边界声明现状（学样）
cat app/agent/__init__.py

# 检查命名前缀已建
find . -name "*persona*" -o -name "persona_*"
```

### 2.2 部署 SOP（每 task commit 后必跑）

按 memory `feedback_deploy_must_curl_verify_not_just_docker_ps.md` **5 步**：

1. 本地 `git push origin main`
2. 远端 `git pull`
3. **改 schema → 清 Redis 相关 cache**（防 ResponseValidationError 500）
4. `docker compose up -d --build`（不是 restart）
5. curl verify（具体 endpoint 见每 task 卡）

### 2.3 双审顺序（每 task commit 前必跑 / CLAUDE.md "三重审判"硬性）

1. **Claude A 忠 PRD + 宪法**：对照 `docs/prd/persona-engine-sprint-prd.md` § 3.X task 验收标准 + `docs/agent-rules/persona-constitution.md` § 1-2.5 字段对照
2. **Claude B 集成审**：跨模块影响（不反向 import / 命名前缀 / MANIFEST 更新 / failure isolation）
3. **Codex 异源审**：调 `codex:codex-rescue` / focus 列在每 task 卡尾部

详细派 reviewer prompt 见 `docs/agent-rules/agent-collaboration.md §4 场景 B` 模板。

### 2.4 通用 reviewer prompt focus（每轮强调）

> 把这份 git diff 当作 fresh PR / 不要相信 author 任何"已修复 / Tim 拍过"声明 / 自由探索 / 重点扫：
> - ADR-009 反向 import 违反
> - 命名前缀漏守
> - MANIFEST 漏更新
> - SAVEPOINT 失败传染
> - persona service 抛错未被顶层 catch

---

## § 3 拔出测试脚本（task-6 实施 / v0.2 加 clean tree 前置 / Codex 抓 I-12）

`scripts/persona_pluck_dryrun.sh`：

```bash
#!/bin/bash
# 模拟拔掉 Persona Engine 全部资产 / 跑核心业务 pytest / 验证可拔性

set -e

# 0. 前置：clean working tree 检查（v0.2 修 / 防 git add -A 污染无关改动）
if [ -n "$(git status --short)" ]; then
  echo "❌ Working tree not clean / 先 commit / stash 现有改动再跑拔出测试"
  git status --short
  exit 1
fi

# 1. 切临时 branch
git checkout -b persona-pluck-dryrun

# 2. 列资产（按命名前缀 / 排除 .git）
echo "=== Persona 资产清单 ==="
find . -path ./.git -prune -o \( -name "*persona*" -o -name "persona_*" \) -print | tee /tmp/persona_assets.txt

# 3. 干跑删除（只删 persona 资产 / 不 git add -A）
xargs -a /tmp/persona_assets.txt rm -rf
git add /tmp/persona_assets.txt $(cat /tmp/persona_assets.txt) 2>/dev/null || true
git commit -am "[dryrun] pluck persona"

# 4. 跑核心业务 pytest
pytest tests/test_user.py tests/test_activity.py tests/test_segment.py -v

# 5. 清理
git checkout main
git branch -D persona-pluck-dryrun

# 6. 全绿则证明 NPC 真的是可拔的码表
echo "✅ Pluck dryrun pass / NPC is removable"
```

---

## § 4 任务依赖图 + Alembic 链（v0.2 修 / Claude B 抓 C4）

```
task-1 (脚手架 / persona_engine_init.py)
  ↑ down_revision = "sprint6_activity_city" (当前真 head / grep 实证)
  │
  ├──→ task-2 (模板入库 / persona_engine_seed.py)
  │      ↑ down_revision = "persona_engine_init"
  │      └──→ task-3 (大脑)
  │              ├──→ task-4 (业务接入)
  │              └──→ task-5 (前端展示)
  │                      └──→ task-6 (真用回归 / 拔出测试)
```

- **task-1** 可和 Sprint 6 并跑（Tim 2026-05-16 拍）/ **但 Alembic head 链必须实施前重新 grep**：
  - 若 Sprint 6 还在跑 / head 可能持续前移
  - persona_engine_init 的 `down_revision` 在实施时**必须**重新 `ls migrations/versions/ | tail -3` 确定真 head
  - 当前（2026-05-16 起草时）真 head = `sprint6_activity_city`
- task-4 / task-5 都依赖 task-3 完成 / 可部分并行
- task-6 等全部完

---

## § 5 工期总览（v0.2 扩 / Tim 拍每场景 ≥ 5 条 / +1 天）

| task | 工期 v0.1 | 工期 v0.2 | 累计 v0.2 |
|---|---|---|---|
| task-1 | 0.5 天 | 0.5 天 | 0.5 |
| task-2 | 1.5 天 | **2.5 天**（扩 46 → ~158 条 / 副线 cycle 同时跑） | 3.0 |
| task-3 | 2 天 | 2 天 | 5.0 |
| task-4 | 1.5 天 | 1.5 天 | 6.5 |
| task-5 | 2-3 天 | 2-3 天 | 8.5-9.5 |
| task-6 | 1 天 | 1 天 | 9.5-10.5 |

**v0.2 合计 9.5-10.5 天**（单人）/ **5.5-6 天**（三人协作）。

---

## § 6 单一真相源 reference

- **Persona 宪法**：`docs/agent-rules/persona-constitution.md`（NPC 文案灵魂源 / 所有文案对照它）
- **Sprint PRD**：`docs/prd/persona-engine-sprint-prd.md`（任务详情 / 9 章节）
- **ADR-009**：`docs/adr/009-为什么-agent-层独立.md`（架构基础）
- **CLAUDE.md 陷阱 #13**：SAVEPOINT 隔离 pattern
- **memory `feedback_real_usage_vs_mock_blindspot.md`**：真用回归 5 类盲区
- **memory `feedback_deploy_must_curl_verify_not_just_docker_ps.md`**：部署 5 步 SOP

---

*本 handoff 由 Claude 起 / 2026-05-16 / 6 个 task 卡 reference 本文不重复*
