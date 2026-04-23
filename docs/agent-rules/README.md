# velo agent 规则体系

> 本目录存放面向 AI agent(Claude Code、Cursor、产品内 agent、未来任何 AI 工具)的 velo 运行规则。
>
> 人类 PRD 放在 `docs/prd/`,给人读。这里的文档给 agent 读。
>
> 两套系统分开维护,服务于不同消费方式,不重复不冗余。

---

## 这套规则体系的设计哲学

velo 的文档体系服务三类读者:**人类、agent、混合**。

人类 PRD(`docs/prd/` 下的 vision / strategy / product-spec)写得像故事,有画像、类比、叙事、品牌气质——服务 VC、合伙人、工程师、设计师等人类读者。

agent 读 PRD 效率低。agent 需要的是**规则化结论**加**可执行的判断框架**,不需要叙事张力。强行让 agent 读 2580 行人类 PRD,既浪费 token,又会稀释真正重要的决策规则。

所以 agent-rules 独立维护,服务 agent 的消费方式。

---

## 两层结构:B+ 树式设计

本目录采用**索引 + 细节**两层结构,类似 B+ 树的内部节点和叶子节点。

### Layer 1: 规则执行层 — `product-decisions.md`

**常驻加载**。agent 进入 velo 仓库工作时,默认加载这份。

内容是**规则化结论**:
- 永不违反的不变式(INV-P01 到 INV-P06)
- 用户画像优先级(P1/P2/P3/NON-USER)
- 产品决策规则(D-P01 到 D-P10,每条有 ID)
- 活人感硬标准(RUBRIC-CONTENT)
- 当期 scope(v5 明确能做不能做)
- 禁止词清单(产品文案、UI 措辞)

**使用场景**:agent 遇到具体决策时快速查表。90% 的日常工作靠这份就够。

### Layer 2: 战略思考层 — `velo-mental-model.md`

**按需加载**。agent 遇到复杂决策、边界模糊、新场景时加载。

内容是**mental model 和判断框架**:
- velo 作为公司的思维模型(sustainable 小而美 vs 独角兽)
- 主画像的画面感描写(不只是属性,是真实生活场景)
- 五大对手的战略位置和弱点(帮助 agent 理解竞争格局)
- 五大失败模式(让 agent 知道 velo 在防什么)
- 三重护城河(让 agent 知道 velo 在守什么)
- **10 问功能必要性评估框架**(核心,教 agent 像 Tim 一样做 PM 判断)
- 活人感的深层心法(非规则化的品味内化)

**使用场景**:规则层没覆盖、需要创造性判断、要给出有深度的 reasoning 时,加载这份。

---

## Agent 工作流:何时读哪份

```
Agent 接到任务
    ↓
是否涉及产品判断 / 功能决策 / 战略方向?
    ├── 否(纯技术任务)→ 读 CLAUDE.md 的技术规则就够
    │
    └── 是 → 读 product-decisions.md(规则层)
              ↓
          规则能直接回答吗?
              ├── 能 → 按规则执行,引用 INV/D-P0N ID
              │
              └── 不能(新场景/边界模糊/需要 PM 判断)
                  → 加载 velo-mental-model.md
                  → 按 10 问框架思考
                  → 给出判断 + 引用哪个 mental model
                  → 有进一步疑问 → 读 docs/prd/ 原始 PRD
```

---

## ID 命名规范

和 CLAUDE.md 技术层规则对齐,采用统一命名:

| 前缀 | 含义 | 示例 | 出处 |
|---|---|---|---|
| `INV-P0N` | 产品层不变式(永不违反) | INV-P01 只做公路车垂直 | product-decisions.md |
| `INV-T0N` | 技术层不变式 | INV-T01 禁用 async def | CLAUDE.md(已有) |
| `D-P0N` | 产品层决策规则 | D-P01 新功能评估 | product-decisions.md |
| `D-T0N` | 技术层决策规则 | D-T01 纯函数不碰 DB | CLAUDE.md(已有) |
| `RUBRIC-X` | 评估框架 | RUBRIC-CONTENT 活人感标准 | 跨文档 |
| `MENTAL-X` | 思维模型 | MENTAL-COMPANY velo 公司定位 | velo-mental-model.md |

agent 在给出判断时**必须引用 ID**,让人类可追溯。不允许"我觉得"式的无根据判断。

---

## 和其他文档的关系

agent-rules 是**规则层和思考层**,不是全量知识库。完整的深度信息在别处:

- **人类战略全景**:`docs/prd/velo-vision.md` + `velo-strategy.md` + `velo-product-spec.md`(总 2580 行)
- **技术决策论证**:`docs/adr/` 下 10 份 ADR
- **技术工程规则**:`CLAUDE.md`(根目录)
- **竞品深度分析**:`docs/competitive-analysis/` 下 5 份文档
- **架构细节**:`docs/architecture-guide.md`
- **当期任务**:`docs/spec-v5.md`(及后续版本)
- **已知风险和债务**:`docs/tech-debt.md`

agent-rules 里的规则都有**引用指针**指向原文档。当规则需要深度论证时,agent 按指针去读原文。

---

## 维护机制

### 触发更新的条件

agent-rules 是活文档,随 velo 演化持续更新。触发更新的关键事件:

1. **PRD 战略调整**(vision/strategy 变了)→ 同步更新 product-decisions 和 mental-model
2. **新增 ADR 或重大 ADR 修订**→ 更新 product-decisions 里的引用
3. **进入新版本期**(如从 v5 过渡到 v6)→ 更新"当期 scope"部分
4. **发现 agent 在某个模糊地方反复犯错**→ 加规则或补 mental model
5. **outbase dogfood 完成 / Strava 政策重大变化 等竞争格局事件**→ 更新 mental-model §竞争格局
6. **定期刷新**:每 6 个月全量 review

### 谁来更新

- Tim 是最终决策者
- Claude(对话中)可以协助起草和修订
- 未来团队成员加入后,可以贡献修订意见,但最终合并由 Tim 决定

### 更新时的硬约束

- **规则冲突先解决,再 commit**:如果新规则和旧规则冲突,必须明确哪条 deprecated
- **ID 不重用**:废弃的 INV-P01 永远不被重用,只会标注"已废弃于 YYYY-MM-DD"
- **Mental model 变化必须解释**:如果公司定位从"小而美"改成别的,必须有战略文档支撑(不是轻率改写)

---

## 给 Agent 的使用建议

当你作为 agent 进入 velo 仓库工作:

1. **第一次**:完整读 CLAUDE.md + README(本文) + product-decisions.md,建立基础认知(~600 行)
2. **日常**:product-decisions.md 常驻 context,按需引用
3. **复杂决策**:加载 mental-model.md,按 10 问框架思考
4. **极端疑问**:读 docs/prd/ 原始 PRD 找深度论证
5. **遇到规则不覆盖的场景**:宁可停下询问 Tim,不要自行推进。说"我不确定"比说错更受尊重

---

## 当前状态

- **v1.0 创建日期**:2026-04-22
- **对应 velo 阶段**:v5(2026 Q2-Q3)
- **下次重大刷新触发条件**:v5 发布后首批用户数据 / outbase dogfood 完成 / 首次融资前后
- **创建者**:Tim + Claude 协作

---

**骑车路上见。**
