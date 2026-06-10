# Spec v6 · Sprint 13+14 上线冲刺(熟人约骑闭环 + 路线百科上架)

> 上游:docs/prd/sprint-13-launch-prd.md(Tim 全 y,2026-06-11)+ 战略决策 D-004/D-005/D-006。
> 状态:待 Step 7 双审(spec 层 Agent A 内部一致性 + Agent B 代码兼容性)→ Critical=0 → Step 8 Tim y/n 清单。
> 本 spec 是差量 spec:约骑/路书后端已 ship(10 task,138 测试),本期只写新增与改造。

## §0.1 代码侧事实表(预读清单产物,审查者对照用)

| 事实 | 证据 | 来源 |
|---|---|---|
| meetups.status ∈ DRAFT/OPEN/CANCELLED/COMPLETED,String(16),CHECK 约束 | app/meetup/models.py:36,70-71 | ✓ grep 本轮 |
| meetups.start_time / estimated_end_time 均 DateTime(tz),NOT NULL | models.py:43-44 | ✓ grep 本轮 |
| meetups.route_book_id FK→route_books,SET NULL | models.py:38 | ✓ grep |
| meetups.share_token 字段存在 | models.py:54 | ✓ 扫描 |
| activities 状态机 pending→processing→completed/failed,另有 importing | app/activity/models.py:36-39 docstring | ✓ grep 本轮 |
| activities.user_id FK→users | models.py:49 | ✓ grep 本轮 |
| activities.started_at 为骑行业务时间(展示禁用 created_at) | CLAUDE.md 关键技术约定 + 判例 time_field | ✓ |
| meetup_participants 表存在,join 用 with_for_update 行锁 | app/meetup/service.py:460-475 | ✓ 集成审 |
| 后端上传白名单 {.gpx,.fit};worker 有 FIT 分支(garmin_fit_sdk) | app/activity/service.py:46 / worker.py:208,28 | ✓ 集成审 |
| 前端 upload.js chooseMessageFile extension 仅 ['gpx'] | miniprogram/pages/upload/upload.js:45-48 | ✓ grep |
| meetup-create 有 onShareAppMessage(带 token);meetup-detail 无 onShareAppMessage,onLoad 只读 id/token | meetup-create.js:260-268 / meetup-detail.js:46-63 | ✓ 集成审 |
| meetup cron 每 5 分钟 tick,过期 OPEN→COMPLETED | app/meetup/cron.py:20-30 | ✓ 集成审 |
| route_books 字段:id/creator_id/name/distance/climb/reference_line(LINESTRING,4326)/file_id/file_type/source/source_activity_id/city/created_at;无 description/is_official | app/route_book/models.py:24-35 | ✓ grep 本轮 |
| meetup↔activity 现无任何关联(无表/无FK/无查询) | 全库 grep MeetupActivity/meetup_activit* 为空 | ✓ 集成审 |
| notification.event_type 仅赛段类(pr/kom/...),不承载约骑事件 | app/notification/models.py:69-70 | ✓ 集成审 |
| 反向 hook 现有 2 处已登记(user/service:72 延迟 import;segment/router:31),新增反向依赖被 CLAUDE.md 明禁 | CLAUDE.md 开发原则 4 | ✓ |
| 路线预览逻辑存在于 meetup-create(restoreRoutePreview) | meetup-create.js | ✓ 集成审 |

## §1 决策记录

| # | 决策 | 理由 |
|---|---|---|
| D1 | 关联实现走「meetup 侧 cron 轮询」:复用现有 5 分钟 tick,扫描近 7 天约骑的参与者活动做关联。不在 activity worker 里触发 | 满足 spec 必答 #1(方案 B,零新增反向依赖);必答 #3 竞态消解(关联与约骑状态解耦,COMPLETED 后照样关联);崩溃自愈(下个 tick 重扫);代价=格子点亮延迟 ≤5 分钟,用户故事是「晚上看战报」,可接受 |
| D2 | 关联窗口按「约骑当天(北京时区自然日)+ started_at ≥ start_time−30min」判定,完全不用 estimated_end_time | 必答 #4 消解:+3h 估算的脆弱性不进入匹配逻辑;骑 6 小时也不掉窗;PRD 原文就是「约骑当天」 |
| D3 | 每人每场只挂 1 条活动:UNIQUE(meetup_id, user_id),取窗口内 started_at 最早的一条;后续命中忽略 | 战报每人一格的语义;边界 A(当天两骑)取约骑出发后最先开始的那条,误挂概率最低 |
| D4 | 补传截止:活动入库时间 ≤ 约骑日 +7 天仍自动关联 | 边界 C;7 天后停止防陈年文件乱挂;7 天为 [🟡 初始值] |
| D5 | 介绍富文本入新表 route_guides(1:1 挂 route_books),不加列 | 必答 #5:防火墙(介绍是慢变内容资产,路书是轨迹数据,半衰期不同物理分离);未来实况层(D-002 第二层)也挂这一侧,route_books 保持纯轨迹 |
| D6 | route_books 加 is_official Boolean 列(server_default false) | 官方/用户路线区分,列表页与向导筛选依赖;route_books 非核心四表,防火墙允许 |
| D7 | 5 秒解析预算:先实测后定路径(task 6 含延迟实测脚本);p90>5s 才开小文件同步快路径 | 必答 #7;不为未测量的问题预建复杂度(20% 复杂度原则) |
| D8 | 五环节埋点用结构化日志行(logger,固定前缀 SENSOR),不建事件表 | 100 用户量级 grep 日志足够;表是过度设计;格式见 §5 |

## §2 数据模型(新增/变更)

### 2.1 新表 meetup_activities(S13-T1)

```python
class MeetupActivity(Base):
    __tablename__ = "meetup_activities"
    id = Column(Integer, primary_key=True, autoincrement=True)
    meetup_id = Column(Integer, ForeignKey("meetups.id", ondelete="CASCADE"), nullable=False)
    activity_id = Column(Integer, ForeignKey("activities.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("meetup_id", "activity_id", name="uq_meetup_activity"),
        UniqueConstraint("meetup_id", "user_id", name="uq_meetup_user_one_cell"),
        Index("idx_meetup_activities_meetup", "meetup_id"),
    )
```

归属:app/meetup/models.py(meetup 模块拥有关联,方向=meetup 依赖 activity,合法)。迁移:新文件 alembic/versions/20260611_meetup_activities.py。级联:删活动/删约骑/删用户 → 连带删关联行(边界 E 之外的级联维)。

### 2.2 新表 route_guides + route_books 加列(S14-T7)

```python
class RouteGuide(Base):
    __tablename__ = "route_guides"
    id = Column(Integer, primary_key=True, autoincrement=True)
    route_book_id = Column(Integer, ForeignKey("route_books.id", ondelete="CASCADE"), nullable=False, unique=True)
    content_md = Column(Text, nullable=False)          # 介绍正文(markdown,来自 13 张卡)
    cover_url = Column(String(512), nullable=True)
    highlights = Column(Text, nullable=True)           # 亮点短句 JSON 数组文本(进路线列表卡)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

route_books 变更:`is_official = Column(Boolean, nullable=False, server_default=text("false"))`。同一迁移文件内完成。
归属:app/route_book/models.py。

## §3 核心逻辑

### 3.1 关联 tick(S13-T1,meetup/cron.py 扩展)

```
run_meetup_attach_tick(db):
  meetups = 近 7 天内 start_time 的约骑(状态 OPEN 或 COMPLETED),JOIN participants
  for 每个 (meetup, participant):
    若 meetup_activities 已有 (meetup_id, user_id) → skip          # D3 幂等
    candidate = 该 user 的 activities 中:
        status == 'completed'
        且 started_at ∈ [meetup.start_time − 30min, 约骑日北京时 23:59]   # D2
        取 started_at 最早一条                                       # D3
    若有 → INSERT,冲突(uq_*)则忽略(ON CONFLICT DO NOTHING)         # 边界 E 幂等
    日志:SENSOR attach meetup_id=X user_id=Y activity_id=Z
```

边界情况表:

| 边界 | 行为 |
|---|---|
| A 当天两骑 | 取出发后最早一条;另一条不挂(D3) |
| B 两场约骑窗口重叠 | 只扫该用户报名的约骑(JOIN participants),互不串场 |
| C 骑完第 3 天才传 | 7 天内 tick 自动补挂(D4);约骑已 COMPLETED 不影响 |
| D 补传昨天的文件 | 匹配用 started_at(骑行时间),与上传时间无关 |
| E worker 重试/并发 tick | 双 UNIQUE + ON CONFLICT,天然幂等 |
| 进程崩在 tick 中途 | 无中间态:逐行 INSERT 各自提交语义,下个 tick 续扫 |
| 参与者退出约骑后才上传 | 不挂(JOIN 的是当前 participants);已挂后退出 → 关联行保留,战报格子随 participants 列表渲染,自然消失 |

### 3.2 开奖与 5 秒预算(S13-T2)

前端:upload 页按 demo 重做(docs/prototypes/upload-reveal-first-rider.html 为交互蓝本)。上传成功后以 800ms 间隔轮询 activity 详情,status=completed 即逐项开奖;>5s 未完成显示阶段文案(「正在读取轨迹点…」),>30s 转后台提示。
upload.js:48 extension 改 ['gpx','fit'],wxml 文案同步。
后端:task 6 先跑延迟实测(脚本 scripts/measure_parse_latency.py:本地连传 5 个真实文件,记录 enqueue→completed 分布);p90≤5s 则不动;超标按 D7 开快路径(≤2MB 同步解析,超时 3s 回退入队)——快路径实现仅在实测超标后启用,本 spec 不预写。

### 3.3 分享卡双发起点(S13-T3)

meetup-detail.js 新增 onShareAppMessage:path=/pages/meetup-detail/meetup-detail?id=X&token=Y&source=share_card;标题模板「{约骑名} · 已交卷 m/n」(m/n 来自战报统计接口)。meetup-create 现有分享路径追加 &source=share_card。成绩卡页(开奖终态)同样可分享,source=report_card。

### 3.4 战报页(S13-T4)

新页 pages/meetup-report,不注册 tab/不进首页导航(验收对照 app.json)。
数据源:GET /api/meetups/{id}/report(新 endpoint,见 §4)。
布局:头部集体合计(总里程/总爬升,由关联活动求和)→ 照片墙(现有 meetup_media 列表)→ 每人一格(participants 全列:已交卷的显示 distance/avg_speed/climb,未交卷显示灰格+「交卷」按钮跳 upload)。无名次列,格子按关联 created_at 排序(交卷顺序,D-006)。

### 3.5 五环节埋点(S13-T5,D8)

约骑详情 router(get_meetup)入口加一行结构化日志:
`SENSOR view meetup_id=X viewer={participant|guest|anon} token={1|0} source={share_card|report_card|direct}`
source 来自新增 query 参数(前端透传,缺省 direct)。关联 tick 已带 SENSOR attach 行。报名行为 participants 表本身可查,不加日志。
数据回看查询(写进本 spec 即交付物):
- ①触达:`grep "SENSOR view" | grep "source=share_card"` 计数
- ②自主进入:同上过滤 viewer=guest/anon
- ③报名:`SELECT count(*) FROM meetup_participants WHERE meetup_id=X`
- ④⑤交卷率:`SELECT count(*) FROM meetup_activities WHERE meetup_id=X` ÷ ③
- 复检哨兵:participants JOIN users 排除创始三人 user_id 清单(部署时配置)

### 3.6 灌库管线(S14-T7)

scripts/import_route_guides.py:读 content/routes/ 目录(每路线一个子目录:guide.md + track.gpx[可选] + meta.json{name,city,is_official:true,highlights}),走现有 route_book service 创建(轨迹经现有 GPX 解析路径)+ 写 route_guides。无轨迹的路线:meta 标 track_pending,只建 guide 不建 route_book,前端列表显示「路书制作中」;补 GPX 后重跑脚本幂等更新(按 name 匹配)。
内容转换(HTML 卡 → guide.md):velo 路线内容铁律全部适用(论断双闸/禁 AI 腔/judgment 层主 agent 亲自做,详 route skill content-rules)——13 条卡的转换是内容工作不是脚本工作,逐条人工(我)过。

### 3.7 路线页与双入口(S14-T8/T9)

- GET /api/route-books?official=1 → 列表(name/distance/climb/city/highlights/cover_url)
- GET /api/route-books/{id}/guide → 详情(guide 内容 + preview_points 轨迹 + 海拔曲线数据)
- 页面:pages/route-list(官方推荐列表)/ pages/route-detail(介绍+地图 polyline+海拔曲线;底部「发起约骑」按钮 → meetup-create?route_book_id=X 预填)
- meetup-create 路线步:loadRoutes 增加官方路线组(official=1),列表分组「官方路线 / 我的路书 / 我的活动」
- meetup-detail 嵌路书预览:移植 restoreRoutePreview 渲染逻辑(route_book_id 非空时显示轨迹缩略+入口)

## §4 API 变更清单

| 方法 | 路径 | 变更 | 任务 |
|---|---|---|---|
| GET | /api/meetups/{id} | 加 source query 参数(仅日志用)+ SENSOR 日志行 | T5 |
| GET | /api/meetups/{id}/report | 新增:集体合计+格子列表+media,token 门禁同详情 | T4 |
| GET | /api/route-books | 加 official 过滤参数 | T9 |
| GET | /api/route-books/{id}/guide | 新增:guide 内容+preview_points | T8 |

全部向后兼容(只增不改)。schema 层:新增响应模型 MeetupReportOut / RouteGuideOut(extra="forbid" 惯例同项目)。

## §5 风险表(故障五维 + 专项)

| # | 风险 | 严重度 | 对策 |
|---|---|---|---|
| 1 | 关联 tick 扫描放大(约骑×参与者×活动) | 低(百用户级) | 范围限近 7 天 + idx_meetups_status_start;查询计划在 task 卡自检 |
| 2 | 5 秒预算实测超标 | 中 | D7 两段式:先实测,超标才开快路径;不预建 |
| 3 | FIT 真链路从未跑通(前端历史阻断) | 中 | task 6 真用回归硬项:真 FIT 文件端到端 + worker 镜像 garmin_fit_sdk 确认 |
| 4 | share_token 端到端未真用 | 中 | task 6:半生人剧本真演一遍(他人微信点卡→报名) |
| 5 | 灌库内容幻觉/侵权 | 高 | 转换走 route skill 铁律,逐条人工过;来源标注保留 |
| 6 | TENCENT_MAP_KEY 生产未配 | 低 | task 6 部署清单项;缺失时路线预览降级显示静态数据不白屏 |
| 7 | 战报页对未交卷者的催缴感引发反感 | 低 | 文案只说「交卷」不说「就差你」;灰格无姓名公示压力(格子有名,无催语) |

## §6 已知限制

- 格子点亮延迟最长 5 分钟(cron 节拍),开奖即时性不受影响
- 同一约骑一人多骑只记最早一条,其余活动仍在个人记录中,不丢数据
- 实况层/评论层(D-002 二三层)、赛段排行(D-006)、手绘路书均不在本期,启动信号见 PRD §3

## §7 任务拆分与测试策略(骨架,Step 9 细化成 task 卡)

| 任务 | 核心交付 | 测试要点 |
|---|---|---|
| T1 关联 | 表+迁移+attach tick | 边界 A-E 各一测;幂等双跑;7 天截止 |
| T2 开奖 | upload 重做+fit 后缀+轮询 | 静态协议三层自校验;真机 5 文件计时 |
| T3 分享 | detail onShare+source 参数 | 分享路径含 token+source;非参与者可转发 |
| T4 战报 | report API+页面 | 合计求和正确;灰格渲染;导航不可达验证 |
| T5 埋点 | SENSOR 日志 | 三种 viewer 态日志断言 |
| T6 部署 | SOP+三喇叭位+延迟实测 | 线上 curl;FIT 端到端;p90 数据落 PRD 回看节 |
| T7 灌库 | 双表迁移+脚本+13 条内容 | 脚本幂等重跑;track_pending 态 |
| T8 路线页 | 列表+详情+guide API | preview_points 渲染;空态 |
| T9 双入口 | 预填+向导分组+详情预览 | route_book_id 透传链;官方组排序 |

执行顺序:T1→(T2,T3,T5 并行)→T4→T6 ‖ T7→(T8,T9)→上线。代码层每批产出后按信条 5 双审+Codex 异源,commit 前过门禁。
