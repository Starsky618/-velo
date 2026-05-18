# Persona Engine 资产清单 v0.1

> 强制规则：每加一处 persona 资产 → 必须更新本清单（PR review 红线 / 不更新不让 merge）
>
> 用途：让"想拔时知道拔哪些"——`find . -name "*persona*" -o -name "persona_*"` 一条命令列全。
>
> 维护：Sprint 内每个 task 完工 PR 必扫本文件 / Tim review 第一眼看的就是这里。

---

## 后端代码

- `app/agent/persona/` —— 整目录（task-1 建）
  - `__init__.py` —— ADR-009 边界声明 + 宪法 reference
  - `trigger_router.py` —— 场景路由（task-3 实施完 / PersonaEvent + route 7 种 event / PR > 极端 > 段位优先级）
  - `template_lib.py` —— 模板池 + 渲染（task-2 实施完 / 4 函数 compute_user_stage / compute_distance_bucket / get_templates_for_scene / pick_template）
  - `filters.py` —— 反 pattern 后置过滤（task-3 实施完 / ANTI_PATTERN_KEYWORDS 覆盖宪法 §3 全 9 类 + emoji + 长度 5-25）
  - `cache.py` —— 去重 + 缓存（task-3 实施完 / get_recent_outputs 7 天 + record_output SAVEPOINT 隔离）
  - `service.py` —— 顶层入口（task-3 实施完 / generate_persona_output 6 步流水线 + get_latest_output_for_scene + get_recent_outputs / 顶层 try/except 不传染）
  - `router.py` —— FastAPI endpoint（task-4 加 / GET /api/persona/output + /recent）
- `app/activity/worker.py` —— task-4 加 NPC hook（SAVEPOINT 隔离 / activity_uploaded + consecutive_high event）+ 3 helper（_query_weekly_count / _detect_pr / _query_total_distance）
- `app/main.py` —— task-4 挂载 persona_router
  - `models.py` —— 3 个 ORM（task-1 加）
  - `MANIFEST.md` —— 本清单
- `app/agent/__init__.py` —— 子工程 reference 段（task-1 追加）

## 数据库

- `migrations/versions/persona_engine_init.py` —— task-1 建（down_revision = sprint6_activity_city）
- `migrations/versions/persona_engine_seed.py` —— task-2 建（down_revision = sprint6_user_city_widen / 168 条 NPC 文案 batch insert）
- 表：
  - `persona_outputs`（文案发送台账）
  - `persona_templates`（模板池 / task-2 已 seed 168 条）
  - `persona_feedback`（用户反馈占位 / v1.0+ 才用）
- 索引：
  - `ix_persona_outputs_user_scene_shown` (user_id, scene_type, shown_at)
  - `ix_persona_templates_scene_active` (scene_type, active)

## 文档

- `docs/agent-rules/persona-constitution.md` —— Persona 宪法 v0.1（NPC 文案灵魂源）
- `docs/prd/persona-engine-sprint-prd.md` —— Sprint PRD（9 章节）
- `docs/plans/persona-engine-handoff.md` —— 共用约束 / SOP / 双审顺序
- `docs/plans/persona-engine-task-1.md` ~ `task-6.md` —— 6 个 task 卡

## 前端

（task-5 实施时追加 PERSONA_START / PERSONA_END 标记位 + 前端 utils 模块）

## 配置

- env: 暂无 `PERSONA_*` 配置（v0.5+ 接 LLM 时加）
- `docker-compose.yml` 加 `persona-scanner` 容器（task-4 / sleep 86400 循环跑 2 个 scanner）

## 测试

- `tests/test_persona_module_init.py` —— task-1 加（4 条 / import + docstring + 迁移 upgrade/downgrade）
- `tests/test_persona_template_lib.py` —— task-2 加（11+ 条 / 段位算法边界 / 距离桶 / 字面漂移 / pick 防重复）
- `tests/test_persona_task3.py` —— task-3 加（25+ 条 / router 7 event + 夜骑边界 / filters 反例 + 长度边界 / cache 7 天 / service 端到端 + 失败兜底 + 不传染）
- `tests/test_persona_task4.py` —— task-4 加（9 条 / worker hook helper + endpoint /output 真+null + /recent + scanner silence + milestone）
- （task-5 ~ task-6 加各自的 `test_persona_*.py`）

## 脚本

- `scripts/persona_silence_scanner.py` —— task-4 加（≥ 7 天没骑 → silence event / persona-scanner 容器调用）
- `scripts/persona_milestone_scanner.py` —— task-4 加（累计里程碑 + 周年 + 节气 → surprise event / 含同日幂等 guard）
- `scripts/persona_pluck_dryrun.sh` —— task-6 实施（拔出测试 / clean tree gate）

---

*命名前缀守则（宪法 § 7.5.1）：persona_* 表 / persona_engine_*.py 迁移 / test_persona_*.py 测试 / scripts/persona_*.py 脚本 / `app/agent/persona/` 后端目录 / `<!-- PERSONA_START -->` 前端块标记 / `PERSONA_*` env 配置*
