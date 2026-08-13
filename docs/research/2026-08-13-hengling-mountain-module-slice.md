# 横岭山区路线积木 research slice

## 结论

横岭已经用与地域无关的机械程序跑通为第二个山区积木：以 observation 2「横岭11km爬坡」完整 Strava 来源线作为只读参考里程轴，不使用 OSM；完整下坡及四条短赛段投影到同一轴，热度按方向和原子区间分账，重叠赛段不再被当成额外道路、额外爬升或可直接相加的独立骑手数。

这仍是 `research_shadow`，不是公开路线或正式推荐。当前证据能描述横岭主走廊内部，不能证明山顶掉头、城市接驳、o40/o82 支路接入或 access。

## 输入账

- census batch：`xishan-20260813-v1`
- GLO fact batch：`xishan-20260813-v1-glo30-v1-a1`
- 主走廊 exact observations：`[2, 16, 24, 25, 26, 115]`
- off-axis holdout：`[40, 82]`
- 横岭 XC：仍留在用户确认的 6 条 excluded set，不进入主走廊
- 生产只读回读：6/6 observation、Strava ID、完整来源线、geometry hash、完整 GLO snapshot/profile 与热度字段对齐；数据库写入 0

区域规则只在 [`hengling_v1.json`](../../data/research/mountain_modules/hengling_v1.json)；[薄 SOP](../../data/research/mountain_modules/README.md) 给出新山区的导出、重放和回读命令；算法在 `app/route_cognition/mountain_modules.py`，离线 runner 在 `scripts/analyze_mountain_module.py`。通用 runner 已用结构不同、方向语义不同的单向山区 fixture 验证；不得复制区域算法或创建区域专属 skill。

## 机械结果

参考轴长度为 10.931789 km：

| observation | 方向 | 来源覆盖 | 轴上 occurrence |
|---|---|---:|---:|
| o2 横岭11km爬坡 | forward | 100% | 0–10.932 km |
| o16 横岭下坡 | reverse | 99.8% | 0–10.932 km |
| o24 大留村到铁道桥 | forward | 100% | 0–0.540 km |
| o25 二库岔口到陡坡前 | forward | 100% | 5.600–8.231 km |
| o115 横岭最陡坡 | forward | 100% | 8.049–8.583 km |
| o26 陡坡后到横岭村 | forward | 99.6% | 8.472–10.932 km |

这说明 o115 横跨 o25 尾部与 o26 开头，是重叠热度证据，不是应额外拼接的一段距离。5.600 km 以前以及各短段空隙仍由 o2 完整来源线覆盖；程序不把短赛段集合冒充完整道路。

## 当前积木组合

### 横岭完整爬坡

- 距离：10.932 km
- GLO-30 meaningful ascent：622.2 m
- 下降：3.4 m
- 热度：全程存在方向化证据；区间 reach 下界取 active facts 的 `max(athlete_count)`，上界取 `sum`，不伪造唯一人数
- 推荐理由：完整来源线与整线 GLO 事实一次计账；四条短段只提高相应区间的热度证据密度，不增加距离和爬升

### 横岭完整下坡

- 距离：10.948 km
- 爬升：0 m
- 下降：620.1 m
- 热度：只使用 reverse 方向事实，不借用上坡证据抬高下坡

### 横岭爬升往返候选

- 账面两条完整来源线：21.880 km、爬升 622.2 m、下降 623.5 m
- 状态：`blocked_unknown_connection`
- 阻塞原因：山顶掉头连接和完整城市出发—返回路线尚未由当前事实证明

积木端口已经机械写出为参考轴里程和方向。当前两条可能的拼接边都明确拒绝晋级：上坡→下坡的山顶掉头、下坡→上坡的山脚掉头均为 `blocked_unknown_connection`。这比“看起来首尾相接”更诚实，也让以后获得真实连接事实时只新增边，不必改写山区内部距离、爬升和热度账。

## 热度不是单分

同一轴的 forward 原子区间输出：

- reach union lower/upper bound；
- repeat proxy range；
- star/intent proxy range；
- projection quality；
- evidence coverage。

这些维度先并列展示。当前没有 rider choice/rejection gold，不能凭感觉写一个 40/30/20/10 权重并宣称“综合热度”。以后只有在 hard-feasible 路线候选通过后，才允许用真实选择和拒绝 episode 学习排序 utility。

## 下一积木的合同

每个山区都必须产出同一结构：

```text
山区 manifest
→ 完整来源/GLO/热度 exact-set 回读
→ 参考轴 occurrence 与方向
→ 原子区间 evidence bounds
→ 可组合 Traversal
→ 总距离、整线总爬升/下降
→ 推荐理由 / typed blocker
```

跨山区组合单独保存 transition evidence；不得把「桃花沟→横岭」连接写死进任一山区积木。
