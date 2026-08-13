# 横岭山区路线积木 research slice

## 结论

横岭已经用与地域无关的机械程序跑通为第二个山区积木：以 observation 2「横岭11km爬坡」完整 Strava 来源线作为只读参考里程轴，不使用 OSM；完整下坡及四条短赛段投影到同一轴，热度按方向和原子区间分账，重叠赛段不再被当成额外道路、额外爬升或可直接相加的独立骑手数。

这仍是 `research_shadow`，不是公开路线或正式推荐。当前证据能描述横岭主走廊内部；赛段终点只是观察边界，不代表公路到此结束。城市接驳、横岭与桃花沟之间的完整过境路径、o40/o82 支路接入和 access 仍需在路线组装层计算。

## 输入账

- census batch：`xishan-20260813-v1`
- GLO fact batch：`xishan-20260813-v1-glo30-v1-a1`
- 主走廊 exact observations：`[2, 16, 24, 25, 26, 115]`
- off-axis holdout：`[40, 82]`
- 横岭 XC：仍留在用户确认的 6 条 excluded set，不进入主走廊
- 生产只读回读：6/6 observation、Strava ID、完整来源线、geometry hash、完整 GLO snapshot/profile 与热度字段对齐；数据库写入 0
- 完整来源/GLO/热度 slice 的本机可重放证据副本：`~/.codex/evidence/velo/mountain-modules/hengling-v1/source-slice.json`；JSON 内 `slice_sha256=02c431…`，不是临时目录文件

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

程序不再凭空生成“横岭爬升往返候选”。横岭赛段依附在公路的一段上，骑手到达赛段终点后通常继续沿真实道路进入后续路线；不能把 Strava 赛段末端误判为道路断头点。只有像枣杜公路这类由道路/路由事实确认的断头路，且路线目标要求进入后返回，才启用 `forced_out_and_back` 和 typed turnaround 检查。

积木端口只表示“这段目的地走廊从哪里进入、从哪里离开”，不是端口之间天然存在直连边。

## 热度不是单分

同一轴的 forward 原子区间输出：

- reach union lower/upper bound；
- repeat proxy range；
- star/intent proxy range；
- projection quality；
- evidence coverage。

GPT Pro 最终手册已经给出完整排序架构：先删掉 hard-gate fail，再取 Pareto 非劣集，然后按版本化 rider intent 做 lexicographic 排序；最后才允许学习模型在 hard-feasible Pareto 候选内重排。学习层不是“学不出来”，而是尚未用同一次候选集的展示、位置概率、选择/拒绝与完成/放弃 episode 训练。固定 40/30/20/10 加权和本身被最终手册否决。

重叠赛段会提高对应 directed interval 的证据密度：人数下界取 `max`，上界取 `sum`，复骑/收藏作为独立代理；不会额外增加物理距离、爬升，也不会伪装成已经去重的唯一骑手数。过境道路没有赛段时记 `unobserved`，不是“不热门”。

## 横岭与桃花沟怎么组合

横岭和桃花沟都是骑行目的地积木，但**当前不声称二者直接相连**。完整候选应表示为：

```text
城市/入口 → 横岭目的地积木 → 若干过境道路 → 桃花沟目的地积木 → 返回
```

中间道路主要承担通行，不因连接两个热门目的地就继承两端热度。组装完整路线时，程序必须对过境路径单独累计距离、GLO 爬升/下降、access 和热度 evidence coverage；没有 Strava 赛段的部分保持 `unobserved`。

## 下一积木的合同

每个山区都必须产出同一结构：

```text
山区 manifest
→ 完整来源/GLO/热度 exact-set 回读
→ 参考轴 occurrence 与方向
→ 原子区间 evidence bounds
→ 可组合 Traversal
→ 总距离、整线总爬升/下降
→ research candidate 推荐理由
```

typed blocker 属于完整 TransitPath / FullRouteValidator 组装层，不能由单个 destination evidence module 凭文字声明。跨山区组合保存完整 transit path，而不是一条“横岭→桃花沟”的抽象直连边；不得把它写死进任一山区积木。
