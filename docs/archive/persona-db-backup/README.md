# persona-db-backup

> 2026-05-21 Persona Engine 整模块清理时的 DB 数据备份归档。

## 这是啥

Persona Engine（"骑车老登"NPC 嘴贱便利贴功能）在 2026-05-20 战略 reset 中被砍掉——属于"装饰展示"层（用户看一眼不改变行为），不该上 sprint 主线。详战略复盘：

- `~/.claude/CLAUDE.md` §2.1 "装饰展示 vs 主动指导"
- memory `feedback_decoration_vs_guidance_velo_persona_lesson.md`
- `docs/changelog.md` 2026-05-20 段 "战略 reset"

2026-05-21 Tim 拍彻底清理（C 方案：前端 + 后端 + DB 表）。drop 表前先 pg_dump 这 3 张表做归档备份——万一未来想回头看用户真实反应数据有路可查。

## 包含数据（2026-05-21 拍快照）

| 表名 | 行数 | 内容 |
|---|---|---|
| persona_outputs | 193 | Tim 测试期 NPC 真实输出（生成的便利贴文案 + 触发上下文）|
| persona_templates | 168 | 模板库（大部分系统 seed / 含 Tim 手工调过的几条）|
| persona_feedback | 0 | 用户反馈 ← **0 条实证"装饰展示无人理"决策正确** |

## 备份方式

```bash
ssh ubuntu@114.132.190.245 "sudo docker compose exec -T db pg_dump -U velo -d velo \
  -t persona_outputs -t persona_templates -t persona_feedback \
  --no-owner --no-acl --inserts" > 2026-05-21-persona-tables.sql
```

参数选择：
- `--inserts`: SQL INSERT 格式（人类可读 / 跨版本兼容好 / 不用 COPY 二进制）
- `--no-owner --no-acl`: 剥离环境耦合（owner / 权限 / 可在任意 PG 实例 restore）
- 含 schema CREATE TABLE + 数据 + FK 约束（FK: persona_outputs.user_id → users.id）

## 恢复方式（未来万一）

```bash
# 在测试 / 本地 PG 上 restore（生产已 drop 表 / 不会直接灌生产）
psql -U velo -d velo < 2026-05-21-persona-tables.sql
```

注意：
- 若 `users` 表不存在或 user_id 不匹配 → FK 约束会失败 / 需先建 users 或临时去 FK
- 若想看数据不恢复表 / 直接 grep / 文件人类可读

## 关联清理动作

| stage | commit | 内容 |
|---|---|---|
| 1（本备份）| 待 commit | pg_dump 3 张表归档 |
| 2 | 待 commit | 后端代码清（app/agent/persona/ + 5 处跨模块引用 + docker-compose persona-scanner service） |
| 3 | 待 commit | Alembic reverse migration drop 3 张表 |
| 4 | 待 commit | 前端代码清（miniprogram 14 文件） |
| 5 | 待 commit | 生产部署 SOP |
