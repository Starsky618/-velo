# ADR-004: 为什么 PR/KOM 活在 notifications 表不在 segment_efforts

## 状态
accepted (2026-04-22)

## 上下文

velo 核心用户体验之一: 用户破了个人纪录(PR, Personal Record)或夺得赛段最速(KOM, King of Mountain)时,要立刻收到通知,而且活动详情页要显示醒目的 PR/KOM 徽章。

v3 期(2026-03 中,通知系统设计期)的关键问题:
- PR/KOM 是**数据属性**还是**业务事件**?
- 该把 `is_pr` / `is_kom` 字段加在 `segment_efforts` 表,还是独立建 notification 表?

自然直觉是加字段:每条 segment_effort 记录打标 `is_pr=True`,查询时直接 join 即可。

## 决策

PR / KOM / KOM_lost 作为**独立业务事件**,存入 `notifications` 表。

**严禁**在 `segment_efforts` 表加 `is_pr` / `is_kom` 字段。

数据表职责分工:
- `segment_efforts`: 存**状态**(某用户在某赛段的某次成绩 elapsed_time 等数值)
- `notifications`: 存**事件**(PR / KOM / KOM_lost 发生了什么、何时、已读否、60 天后过期)

前端展示 PR 徽章:
- 查询 `GET /api/activities/{id}/segments` 拿成绩
- 查询 `GET /api/notifications?activity_id={id}&event_type=pr` 拿事件
- 前端 join 两者

## 理由

1. **事件 vs 状态是不同抽象**。"PR"不是成绩的永久属性,是成绩**发生那一刻**对"此前所有同赛段成绩"的比较结果。如果用户半年后刷了更好成绩,那原来的 PR 就不再是 PR 了 —— 如果 `is_pr` 存在效绩表,需要回溯更新(破坏了"记录一次事件"的不变性)。

2. **事件有事件特有的属性**。通知有:发生时间、消息文案、是否已读、过期时间、关联对手(KOM_lost 时的新 KOM 所有者 `rival_user_id`)、排名快照(`rank`)、用时快照(`elapsed_time`)、已读标记(`is_read`)。这些属性塞进 segment_efforts 会污染成绩表,让成绩表字段从 10 个膨胀到 20+。

3. **notifications 表增长独立于 efforts 表**。PR/KOM 通知有 60 天过期机制(`expires_at` 字段 + 定时清理)。如果 PR 字段在 efforts,过期不能删(删了成绩记录就没了),但留着又是一堆"60 天前的破 PR 了"的冗余数据。分表后,过期通知直接删,成绩数据永久保留。

4. **事件触发机制清晰**。`notification/detector.py` 是纯函数,负责判定"这次成绩是不是 PR/KOM",输出 `['pr', 'kom']` 列表。这种纯函数测试极简,替换实现也简单(以后想改 "连续 3 次 PR 才通知" 逻辑,只改 detector 不动 efforts)。

5. **删除级联清晰**。用户删活动时:
   - segment_efforts `ON DELETE CASCADE` → 成绩自动删
   - notifications 外键 `ON DELETE SET NULL` → 通知保留但 activity_id 置空,显示"该记录已失效"
   
   这样用户历史事件记录不丢,但具体成绩数据可以按需删除。如果 is_pr 存 efforts,删成绩就丢事件。

## 后果

### 正面
- 两张表职责清晰,各自演化不相互掣肘
- notifications 表可以做全文搜索 / 分类 / 按日期分组 等扩展,不影响 efforts 性能
- 未来新增事件类型(如"10 公里以上长距离赛段完成")只需要 detector 加逻辑 + notifications 加 event_type 枚举值,不动 efforts 表

### 负面
- 前端展示 PR 徽章必须 join 两个 API(活动详情页因此多一次请求)。对首屏体验有微小影响(典型活动详情 p95 从 200ms 涨到 250ms)
- 新同事或 agent 第一次看到"我的赛段成绩为什么没有 is_pr 字段"会困惑,需要文档说明

### 触发重新评估的条件
- 如果 PR 徽章成为首页核心(如"动态流每条活动都要显示 PR"),前端 join 成为性能瓶颈
- 如果需要按 "PR 次数" 做用户排行榜,需要 SQL 能从一张表出结果

## 违反代价

如果未来 PR 给 `segment_efforts` 加 `is_pr` / `is_kom` 字段,会触发:

1. **数据一致性灾难**: 新 PR 产生时要更新旧记录(把旧 PR 的 is_pr 置 false),但这会改变"成绩"这个本应永久不变的事实。如果出 bug(忘记更新),数据库会有多条 `is_pr=true` 的记录 → 前端显示多个 PR → 用户投诉
2. **expires 语义混乱**: PR 字段没有过期概念,但 notification 有 expires_at。如果两处都有 PR 信号,哪个才是真的?
3. **反向污染**: 通知系统设计是独立的,给 efforts 加字段意味着通知逻辑要反向更新 efforts,破坏单向依赖(notification 依赖 segment,现在反过来写 segment 就违反了依赖方向)

**防御措施**: 
- CLAUDE.md 防火墙式扩展原则: "禁止修改核心表(如 `segment_efforts`)除非修 bug"
- 架构 guide v2 §4.2.5 明确标注 "**没有** `is_pr` / `is_kom` 字段(PR/KOM 是事件,在 notifications 表)"

## 相关文档

- 架构 guide v2 §4.2.5 segment_efforts 字段清单 / §6.3 前端 join 示例 / §7.2 防火墙扩展
- 数据流 guide 链路 1.4 通知检测子流程 / 链路 7 骑行详情页聚合(双请求 join 模式)
- ADR-008(防火墙式扩展)— 本决策是该原则的具体应用
- 数据模型: `app/notification/models.py`(event_type 枚举 / expires_at / is_read)
