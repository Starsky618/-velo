# velo PRD 文档目录

> 这里是 velo 完整产品需求文档(PRD)的三份核心文档。**主要给人类读者**——Tim、合伙人、VC、潜在工程师/设计师/运营候选、合作伙伴。
>
> agent 读这里有"深度论证"需求时按 §3 检索,日常产品决策优先读 `docs/agent-rules/`。

---

## 1. 本目录三份核心文档

| 文件 | 行数 | 性质 | 阅读时间 |
|---|---|---|---|
| `velo-vision.md` | 460 | 宏观入门 / 立国宣言 | 15-20 分钟 |
| `velo-strategy.md` | 852 | 深度战略分析 | 45-60 分钟 |
| `velo-product-spec.md` | 1268 | 产品细节与执行 | 60-90 分钟精读,按需跳读 |

三份文档严格**上下游关系**:

- vision 定基调和定位(讲"是什么")
- strategy 做深度论证(讲"为什么")
- product-spec 定执行细节(讲"怎么做")

任何一份的战略结论必须和前一份一致,不冲突。

## 1.1 专题战略文档(单条主战略线的深展 / 和三件套并列、不重复)

| 文件 | 性质 | 阅读时间 |
|---|---|---|
| `velo-route-flywheel-strategy.md` | **路线百科与数据飞轮战略**(2026-06-08 立)——从"做路线内容"升维到"造有判断力的内容生产系统 + 数据飞轮";含 4 个核心战略判断(认知对象当地基 / 两阶段飞轮破冷启动 / 先调熟再放量 / 护城河=判断系统而非卡)+ Strava 数据边界 + 已知未解决问题 | 20-30 分钟 |

> 专题战略 = 某一条主战略线需要单独深展、撑得起独立成文时建(需 Tim 拍板)。它服从三件套的总战略,不冲突;它讲的是三件套里某条线的"为什么+怎么演化",比三件套更聚焦、更具体。

---

## 2. 读者路线图

### 如果你是 Tim 本人
从头读 vision,然后随时返查 strategy / product-spec 的具体章节。这是 velo 5 年战略的 north star,每 6 个月重大更新一次,每 2 周微调一次。

### 如果你是 VC 或投资人
先读 **vision(15 分钟)** → 感兴趣再读 **strategy §1 市场 + §2 竞争 + §8 投资人 Q&A**(30-45 分钟)→ 要看产品细节再读 **product-spec §2 产品价值 + §3 演化路径**。不用读 ADR 和架构 guide。

### 如果你是合伙人或核心团队候选
读 **vision + strategy 全部**(90 分钟)+ **product-spec §8 团队**(15 分钟)。这是你和 velo 长期绑定前需要对齐的全部战略信息。

### 如果你是潜在工程师
读 **vision** (20 分钟)+ **`docs/architecture-guide.md` + ADR + `docs/data-flow-guide.md`**(2-3 小时深度读)。product-spec 按需跳读。

### 如果你是潜在设计师
读 **vision + product-spec §2 产品价值 + §7 品牌气质 + §4 UGC 内容体系**(45-60 分钟)+ `docs/competitive-analysis/letterboxd-对标.md`(可选)。

### 如果你是运营候选
读 **vision + product-spec §9 增长路径 + §8 团队与运营**(45 分钟)+ `docs/competitive-analysis/` 失败模式(作为警示)。

### 如果你是骑行 club 领队或车店老板
只读 **vision**。如果你愿意和 velo 深度合作,Tim 会直接和你对话,不需要先读完整文档。

---

## 3. agent 使用指南

agent **不应该默认加载本目录任何文档**。产品决策规则在 `docs/agent-rules/`,那是 agent 的运行时规则。

agent 只在以下情况检索本目录:

**检索 velo-vision.md**:
- 需要一句话给外人讲 velo → 抄 §1.1 或 §0.4 thesis
- 要写 velo 对外宣传文案 → 读 §7 品牌气质
- 对 velo 整体定位有模糊 → 读全文

**检索 velo-strategy.md**:
- 需要回答"velo 的市场天花板"、"融资立场"等战略问题 → 对应章节
- 理解某个竞品的深度分析 → §2.X
- 回答投资人的具体问题 → §8 的 12 题 Q&A

**检索 velo-product-spec.md**:
- 需要某个用户画像的完整场景故事 → §1.2-1.6(王哲/张红/李明/老周/小美)
- 需要某个功能的产品化细节 → §2
- 要设计 UGC 治理机制 → §4
- 要设计信任/反骚扰机制 → §5
- 要规划路线图的具体做什么 → §3

> **核心原则**:agent 不重复加载 2580 行 PRD。日常决策去 `docs/agent-rules/product-decisions.md`(规则层 378 行)。复杂场景叠加 `docs/agent-rules/velo-mental-model.md`(思考层 756 行)。只有需要深度论证时才检索 PRD 的**具体章节**,不全文加载。

---

## 4. 这些文档之外的配套材料

| 需求 | 去哪看 |
|---|---|
| 技术架构全景 | `docs/architecture-guide.md` |
| 技术决策记录 | `docs/adr/`(看 `adr/README.md` 索引) |
| 竞品深度分析 | `docs/competitive-analysis/`(看对应 README) |
| 产品/战略 agent 规则 | `docs/agent-rules/product-decisions.md` |
| 产品/战略 agent 思考框架 | `docs/agent-rules/velo-mental-model.md` |
| 代码/工程 agent 规则 | `CLAUDE.md`(根目录) |
| 当期任务拆分 | `docs/spec-v5.md` |
| 数据流全景 | `docs/data-flow-guide.md` |
| 已知风险和债务 | `docs/tech-debt.md` |

---

## 5. 维护

- **版本**:v1.0(2026-04-22)
- **下次重大更新触发**:
  - v5 发布后首批用户数据出来(画像修正)
  - outbase dogfood 完成后(竞争格局校准)
  - 首次融资前后(战略细化)
  - 每 6 个月定期刷新
- **维护者**:Tim + Claude 协作
- **原则**:三份 PRD 的战略结论互相一致。任何一份修订后,其他两份对应章节必须同步检查。
