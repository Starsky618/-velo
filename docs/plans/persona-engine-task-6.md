# Persona Engine Task-6 — 真用回归 + 拔出测试

> 所属：Persona Engine Sprint / 6 task 中的第 6 个 / final gate
> 上下文：memory `feedback_real_usage_vs_mock_blindspot.md` 真用回归 5 类盲区 + 宪法 § 7.5.3 拔出测试
> **共用约束 / SOP / 双审**：详见 `persona-engine-handoff.md`

---

## ─────── 给 Tim 看 ───────

### 干啥用

NPC 系统上线前 final gate / 真注册一个账号 / 上传几条不同类型活动 / 模拟一些场景 / 验证 NPC **7 个场景都能触发** / 模板覆盖率 ≥ 80%（v0.2 扩 ~158 条 / 至少 ~126 条被实际触发过）/ 拔出测试全绿（删 NPC 整块后核心业务不炸）。

### 防火墙红线（v0.2 修 / Codex 抓 I-11 / 独立段补 / 不只 reference handoff）

本 task 重点验证（参 handoff § 1 五条硬约束在真用回归中验收）：
- **§ 1.1 ADR-009**：拔出测试时 / 删 persona 模块后 / 业务模块无 import error（自动验证）
- **§ 1.2 命名前缀**：`find . -name "*persona*"` 列全部资产 / 对照 MANIFEST.md
- **§ 1.3 数据隔离**：拔出后核心表（users / activities / segments）无残留 persona_* FK 引用
- **§ 1.4 失败隔离**：故意让 persona 抛错 → activity 上传仍正常 completed
- **§ 1.5 MANIFEST 同步**：拔出测试输出资产清单 = MANIFEST.md 列表

### 用户故事

无（这是测试任务 / 但要走真用户视角的完整流程）。

### 怎么算做对了

- ✓ 注册新用户走完整流程 / **7 个场景全部触发文案**（v0.2 修 / Claude A 抓 I-5 / 不再是"至少 5 个"）
- ✓ 上传 PR 活动 → 看到 PR 场景文案
- ✓ 上传普通 80km → 看到段位文案
- ✓ 连骑 5 天 mock → 看到 consecutive_high 文案
- ✓ 沉寂 8 天 mock + 跑 scanner → 看到 silence 文案
- ✓ 上传短距 / 长距 / 夜骑 / 雨天 → 看到对应 extreme 文案
- ✓ 断网 / 上传失败 → 看到 empty_error 文案
- ✓ 拔出测试全绿（删 persona 全部资产 + 核心业务 pytest 全过）
- ✓ 模板覆盖率 ≥ 80%（动态分母（实施时按真值 × 80% / v0.3 修 / Claude A 抓 I-new-3 + Codex 抓 I3）被实际触发过）
- ✓ deployment-diary 记录"NPC Engine 真用激活时间"
- ✗ 拔出测试不绿 = 必修才能上线（红线）

### 这次**不做**的事

- 自动化端到端测试框架（手测 OK / 100 用户量级不值得投资）
- 模板覆盖率监控仪表盘 → v1.0+
- A/B 实验框架 → v1.0+

### 估时

1 天

---

## ─────── 折叠：技术细节 ───────

<details>
<summary>展开</summary>

### 拔出测试脚本

参 handoff § 3 完整 `scripts/persona_pluck_dryrun.sh`。本 task 实施 + 跑一次验证。

### 真用回归 8 个场景手动跑

按 memory `feedback_real_usage_vs_mock_blindspot.md` 5 类盲区（mock 断言 / 进程独立 import / SQLite vs PG / 单线程 vs 容器集群 / 第三方依赖激活状态）—— 真用是 final gate / 不能跳。

#### 场景 1：注册 + profile 开场

1. 用新微信号扫码注册 velo
2. 打开"我的"页
3. 期望：profile 头像下方看到至少 1 条 NPC 文案（可能是 profile_open empty 或段位起步文案）

#### 场景 2：上传 PR

1. 准备一个长距离 GPX（80-120km / PR 候选）
2. 上传
3. 等 worker 完成（5-10s）
4. 期望：toast 显示 PR 场景文案（6 条之一）/ persona_outputs 表写入

#### 场景 3：上传普通 80km

1. 上传第 2 条 80km GPX（非 PR）
2. 期望：toast 显示段位文案（按用户当前段位）

#### 场景 4：上传极端数据

依次上传 4 条测试 GPX：
- < 5km（tiny）
- > 150km（long_dist）
- 起点 23 点后（night）
- 平均速度 > 35 km/h（high_speed / mock 数据）

期望：toast 各显示对应 extreme 文案。

#### 场景 5：连骑高频

mock 用户当前周 activity_count = 5（直改 DB 插测试数据）→ 上传第 6 条 → 期望 toast 显示 consecutive_high 文案。

#### 场景 6：沉寂

mock 用户上次骑车 8 天前（改 last activity started_at）→ 跑 silence scanner（`docker compose exec api python scripts/persona_silence_scanner.py`）→ 打开 velo profile 看到 silence 文案。

#### 场景 7：错峰惊喜

mock 用户累计跨 10000km → 跑 milestone scanner → 看到 surprise/milestone 文案 "1 万了。老登正式入会。"

#### 场景 8：错误 / 断网

- 关 WiFi 打开 velo → 错误页显示 "连不上。WiFi 切流量试试。"
- 故意上传一个损坏 GPX → toast 显示 "今天轨迹丢了。下次记得开 GPS。"

### 模板覆盖率统计

跑完 8 场景后：

```sql
SELECT COUNT(DISTINCT template_id) AS unique_used
FROM persona_outputs
WHERE shown_at > NOW() - INTERVAL '24 hours';
-- 期望 ≥ 37（真值 * 80% / v0.3 修）
```

如果 < 37 / 排查没触发的 scene_type → 手动 trigger 一遍补足。

### 拔出测试跑一遍

```bash
bash scripts/persona_pluck_dryrun.sh
```

期望输出：
```
=== Persona 资产清单 ===
./app/agent/persona/
./app/agent/persona/__init__.py
...
./migrations/versions/persona_engine_init.py
./tests/test_persona_*.py
...

# 跑核心 pytest
tests/test_user.py: PASSED
tests/test_activity.py: PASSED
tests/test_segment.py: PASSED

✅ Pluck dryrun pass / NPC is removable
```

### deployment-diary 记录

按 memory `feedback_real_usage_vs_mock_blindspot.md` 第三方依赖激活回归：

```markdown
## 2026-MM-DD：Persona Engine v0.1 真用激活

- 8 个场景全部触发 ✓
- 模板覆盖率：XX/46（XX%）
- 拔出测试：✓ 全绿
- 已知问题：（如有）
- 第三方依赖激活状态：DeepSeek 暂不调（v0.5+）/ 后端 endpoint 100% 真用通路
```

### 双审 focus

参 handoff § 2.3 + § 2.4。本 task **重点扫**：
- 真用 8 场景实际跑过 / 不只看 pytest（mock 盲区）
- 拔出测试输出真有"All 全绿"
- 模板覆盖率 ≥ 80% 真达到 / 不是预估
- deployment-diary 真写入

### 依赖

- 依赖：task-1 ~ task-5 全部完成
- 阻塞：无（final gate）

### 部署后 24h 验证

按 memory `feedback_real_usage_vs_mock_blindspot.md` "第三方依赖激活状态"盲区：

- 部署后 24h 内 Tim 亲自再走一遍场景 1-3（注册 / PR / 段位）/ 确认线上 NPC 真说话
- 部署后第 7 天 / 第 8 天验证 silence scanner 跑通（让真用户体验沉寂场景）

</details>
