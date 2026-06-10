# Spec v6.1 · Sprint 13+14 上线冲刺(熟人约骑闭环 + 路线百科上架)

> 上游:docs/prd/sprint-13-launch-prd.md(Tim 全 y,2026-06-11)+ 战略决策 D-004/D-005/D-006。
> 审判轨迹:v6.0 双审第一轮 Critical=5 / Important=12 → 本版全修 → 待第二轮复核,Critical=0 后进 Step 8 Tim y/n。

## §0.1 代码侧事实表(双审复核后修订版)

| 事实 | 证据 | 来源 |
|---|---|---|
| meetups.status ∈ DRAFT/OPEN/CANCELLED/COMPLETED,String(16),CHECK 约束 | app/meetup/models.py:36,70-71 | ✓ |
| meetups.start_time / estimated_end_time 均 DateTime(tz),NOT NULL | models.py:43-44 | ✓ |
| meetups.route_book_id FK→route_books,SET NULL | models.py:38 | ✓ |
| GPX/FIT 上传路径状态机 4 态:pending→processing→completed/failed;importing 是 Strava 导入专用中间态(import_scheduler.py:354),不在本 spec 范围 | activity/models.py:13,36-39 + 双审 B-C3 修订 | ✓ |
| activities.user_id FK→users;started_at 为骑行业务时间 | models.py:49 + CLAUDE.md 约定 | ✓ |
| meetup 行锁在 publish 流程(_load_and_authorize_meetup) | app/meetup/service.py:125(B-I3 修订,原误标 460-475) | ✓ |
| 后端上传白名单 {.gpx,.fit};worker FIT 分支(garmin_fit_sdk) | service.py:46 / worker.py:208,28 | ✓ |
| 前端 upload.js extension 仅 ['gpx'] | upload.js:45-48 | ✓ |
| meetup-create 有 onShareAppMessage;meetup-detail 无 | meetup-create.js:260-268 / meetup-detail.js | ✓ |
| meetup tick 节拍 = scheduler 15 秒 × 计数器 20 = 5 分钟;complete_tick 自建 SessionLocal、无参签名 | scheduler.py:37,55 / cron.py:35-44 | ✓ |
| 活动状态轻量端点 GET /api/activities/{id}/status(仅 status/error/duplicate_of)与详情端点分离 | activity/router.py:247,82 | ✓ |
| IntegrityError try/except 是项目冲突处理惯例;ON CONFLICT DO NOTHING 全库零先例 | meetup/service.py:191-196,505-511 / activity/service.py:247 | ✓ |
| Boolean server_default 项目主流写法 false()(meetup/models.py:108 等) | 双审 B-I1 | ✓ |
| 北京时区已在两处各自定义(_BJ_TZ):training/service.py:39 / notification/progress_detector.py:46,无共享函数 | 双审 B hot-1 | ✓ |
| migration 链末节点 = 20260603_meetup_create_fields | alembic/versions/ | ✓ |
| route_books 字段(无 description/is_official);route_book/models.py 未导入 func | route_book/models.py:24-35,12-13 | ✓ |
| meetup↔activity 现无任何关联 | 全库 grep 为空 | ✓ |
| 反向 hook 现有 2 处已登记;本 spec 新增 MeetupActivity 为 Meetup→Activity 正向,不新增反向 | 双审 B 架构层核验 | ✓ |
| TENCENT_MAP_KEY 生产配置状态 | 未知 | ⚠️ 运行时,T6 部署 SOP 第一步亲查 .env 并记录,缺失则按配置步骤补 |

## §1 决策记录

| # | 决策 | 理由 |
|---|---|---|
| D1 | 关联走 meetup 侧 cron 轮询(attach tick),不在 activity worker 触发 | 方案 B 零反向依赖;竞态消解;崩溃自愈;格子点亮延迟 ≤5 分钟可接受 |
| D2 | 关联窗口 = 约骑当天北京时区自然日 + started_at ≥ start_time−30min;不用 estimated_end_time | +3h 估算脆弱性不进匹配;骑 6 小时不掉窗 |
| D3 | 每人每场只挂 1 条(UNIQUE meetup_id+user_id),取窗口内 started_at 最早一条 | 战报一人一格;约骑出发后最先开始的误挂概率最低 |
| D4 | 补传截止 = 约骑日(start_time 北京自然日)+7 天 [🟡 初始值]。显式偏离 PRD 必答 #2 的「completed_at+N 天」并论证:completed_at 由 cron 节拍对 estimated_end 的判定产生,继承了 +3h 估算的脆弱性(与 D2 弃用它同一理由);约骑日是业务锚,稳定且用户可理解 | 边界 C;防陈年文件 |
| D5 | 介绍富文本入新表 route_guides(1:1),不给 route_books 加列 | 防火墙;半衰期分离;未来实况层挂同侧 |
| D6 | route_books 加 is_official(Boolean, server_default=false(),与 meetup 模块写法一致);查询一律 .is_(True) 防 truthiness | 官方/用户路线筛选;陷阱 #1 |
| D7 | 5 秒预算两段式:先实测(T6 脚本),p90>5s 才开小文件同步快路径 | 不为未测量的问题预建复杂度 |
| D8 | 五环节埋点 = logger.info 行,固定前缀字符串 "SENSOR "(沿用项目日志惯例,不建事件表) | 百用户级 grep 足够 |
| D9 | 战报格子按 meetup_activities.created_at ASC 排序(交卷先后)。与 D-006 的关系:D-006 押后的是骑行表现排名,交卷顺序是行为顺序不是表现排名,不违反 | v6.0 误引 D-006 作排序依据,本版立独立决策(双审 A-C1) |
| D10 | 同一活动允许挂到多场约骑(用户真报名了两场窗口重叠的约骑时):uq_meetup_activity 只防同场重复,不做跨场互斥 | 极罕见场景,数据保真实;边界表新增行 |

## §2 数据模型

### 2.1 新表 meetup_activities(S13-T1,归属 app/meetup/models.py)

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

迁移:alembic/versions/20260611_meetup_activities.py,`down_revision = "20260603_meetup_create_fields"`(链末实证)。本迁移同时含 §2.2 两项变更,一个文件三件事。

### 2.2 新表 route_guides + route_books 加列(S14-T7,归属 app/route_book/models.py)

```python
# models.py 顶部补:from sqlalchemy.sql import func, false   # 现文件未导入 func(实证)

class RouteGuide(Base):
    __tablename__ = "route_guides"
    id = Column(Integer, primary_key=True, autoincrement=True)
    route_book_id = Column(Integer, ForeignKey("route_books.id", ondelete="CASCADE"), nullable=False, unique=True)
    content_md = Column(Text, nullable=False)
    cover_url = Column(String(512), nullable=True)
    highlights = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

# RouteBook 加列:
is_official = Column(Boolean, nullable=False, server_default=false())
```

### 2.3 共享时区工具(S13-T1 顺带,治三处重复定义)

新建 app/common/bj_time.py:`BJ_TZ = timezone(timedelta(hours=8))` + `def to_bj_date(dt_aware) -> date`。attach tick 用它;training/service.py:39 与 notification/progress_detector.py:46 两处存量定义的迁移记入 docs/tech-debt.md(不在本期强改已 ship 模块,共享逻辑规则的存量豁免登记)。

## §3 核心逻辑

### 3.1 attach tick(S13-T1,app/meetup/cron.py)

函数签名与 session 管理(双审 B-C2 定案):`run_meetup_attach_tick()` 无参,自建 `SessionLocal()`,finally 关闭——与 run_meetup_complete_tick 完全同模式(cron.py:35-44 实证)。scheduler.py 集成:在现有 meetup 5 分钟计数器块内、complete_tick 之后追加调用;部署须 `docker compose up -d --build`(scheduler 容器加载新模块,restart 不够)。

```
run_meetup_attach_tick():
  db = SessionLocal()
  try:
    meetups = status IN ('OPEN','COMPLETED') AND start_time >= now() - interval '7 days'   # 精确定义
    for meetup in meetups, for participant in meetup.participants:
      若已存在 (meetup_id, user_id) 关联 → continue                       # D3 幂等快路径
      candidate = participant 的 activities:
          status == 'completed'
          AND to_bj_date(started_at) == to_bj_date(meetup.start_time)      # D2,用 §2.3 共享函数
          AND started_at >= meetup.start_time - 30min
          ORDER BY started_at ASC LIMIT 1                                  # D3
      若有:
        db.add(MeetupActivity(...)); 
        try: db.commit()
        except IntegrityError: db.rollback(); continue    # 项目惯例写法(B-C1 定案,零新 import);
                                                          # 同时吞 uq_meetup_activity 与 uq_meetup_user_one_cell 两个约束名,
                                                          # 不解析异常串区分——两种冲突的正确动作都是跳过
        logger.info("SENSOR attach meetup_id=%s user_id=%s activity_id=%s", ...)
  finally: db.close()
```

逐行 add+commit 在自建 session 顶层进行,无外层事务,SAVEPOINT 纪律(陷阱 #8/#13)不适用——它管的是「内层模块污染外层事务」,本函数自己就是最外层(B-C2 定案)。

边界情况表(v6.1 补全):

| 边界 | 行为 |
|---|---|
| A 当天两骑 | 取出发后最早一条(D3) |
| B 两场约骑窗口重叠(不同人) | 只扫本人报名的约骑,不串场 |
| B2 同一人真报了两场重叠约骑 | 同一活动允许挂两场(D10) |
| C 骑完第 3 天才传 | 7 天内 tick 自动补挂;COMPLETED 态照常关联(D4) |
| C2 约骑被取消(CANCELLED)后上传 | tick 只扫 OPEN/COMPLETED,CANCELLED 不关联(明文保证,A-I5) |
| D 补传昨天的文件 | 匹配用 started_at,与上传时间无关 |
| E worker 重试/并发 tick | 双 UNIQUE + except IntegrityError 跳过,幂等 |
| 崩在循环中途 | 已 commit 的保留,下个 tick 续扫 |
| 参与者退出后才上传 | JOIN 当前 participants,不挂;已挂后退出 → 行保留,战报随 participants 渲染自然消失 |
| 北京时区日切 | 比较一律经 to_bj_date(aware),禁止比较 UTC 日期;T1 必含测试:约骑北京 20:00 开始、活动 started_at=UTC 12:00 同日命中 |

### 3.2 开奖与 5 秒预算(S13-T2)

前端按 demo 重做(docs/prototypes/upload-reveal-first-rider.html 为交互蓝本)。轮询协议(B-I4 定案):上传成功 → 800ms 间隔轮询轻量端点 GET /api/activities/{id}/status;status=completed → 再 fetch 一次 GET /api/activities/{id} 拿完整开奖数据(避免轮询拖全量轨迹 JSONB)。>5s 显示阶段文案,>30s 转后台提示。upload.js:48 extension 改 ['gpx','fit'],wxml 文案同步。延迟实测脚本与快路径触发条件同 D7。

### 3.3 分享卡双发起点(S13-T3)

meetup-detail.js:onLoad 阶段预拉战报统计(已交卷 m/报名 n)存入 data;onShareAppMessage 为同步钩子只读 data,禁止在钩子内异步 fetch(B hot-3,微信平台约束,异步结果不会等到分享弹窗)。路径 =/pages/meetup-detail/meetup-detail?id=X&token=Y&source=share_card。meetup-create 现有分享路径追加 &source=share_card;成绩卡页分享 source=report_card。

### 3.4 战报页(S13-T4)

新页 pages/meetup-report,不注册 tab/不进首页导航。正向入口两个(A-I1 补):① 分享卡路径直达 ② meetup-detail 在 status∈{OPEN(已有≥1 条关联),COMPLETED} 时显示「看战报」按钮。数据源 GET /api/meetups/{id}/report。布局:集体合计 → 照片墙(meetup_media)→ 每人一格(participants 全列,已交卷显示 distance/avg_speed/climb,未交卷灰格+「交卷」按钮跳 upload;格子无催语,文案只有「交卷」)。排序按 D9。

### 3.5 五环节埋点(S13-T5)

get_meetup router 加 source query 参数(缺省 direct)+ 一行 `logger.info("SENSOR view meetup_id=%s viewer=%s token=%s source=%s", ...)`,viewer ∈ participant/guest/anon(由 get_optional_user + participants 判定)。数据回看查询照 v6.0 §3.5(grep SENSOR 行 + 两条 SQL),作为交付物写进 T5 task 卡。

### 3.6 灌库管线(S14-T7)

scripts/import_route_guides.py 读 content/routes/<路线名>/:guide.md + track.gpx[可选] + meta.json{name, city, is_official: true, highlights, cover_url 可选}。cover_url 缺省 null,前端列表空态显示占位图(A-I2 定案:首批允许无封面,不阻塞)。无轨迹路线标 track_pending 只建 guide;补 GPX 后按 name 幂等重跑。内容转换(13 张 HTML 卡 → guide.md)走 route skill 全部铁律,主 agent 亲自逐条做,天龙山以 v11 为定本(Tim 拍)。

### 3.7 路线页与双入口(S14-T8/T9)

- GET /api/route-books 加 official 过滤参数(T8 交付,与列表页同任务——A-I3 修正归属);service 层 `RouteBook.is_official.is_(True)`;前端分两次调用分组渲染:?official=1 官方组 + ?mine=true 我的组,无需后端合并(B-I7 定案)
- GET /api/route-books/{id}/guide(T8):guide 内容 + preview_points + 海拔曲线数据
- pages/route-list / route-detail(T8);详情底部「发起约骑」→ meetup-create?route_book_id=X 预填(T9)
- meetup-create 路线步加官方路线组(T9);meetup-detail 嵌路书预览,移植 restoreRoutePreview(T9)

## §4 API 变更清单

| 方法 | 路径 | 变更 | 任务 |
|---|---|---|---|
| GET | /api/meetups/{id} | 加 source 参数(仅日志)+ SENSOR 行 | T5 |
| GET | /api/meetups/{id}/report | 新增。token 门禁同 get_meetup_detail 语义:invite_only + 无 token + 非参与者 → 404(B-I5 明示) | T4 |
| GET | /api/route-books | 加 official 过滤 | T8 |
| GET | /api/route-books/{id}/guide | 新增 | T8 |

响应模型字段(A 审 Nice-1 补):MeetupReportOut{ meetup_id, totals{distance_km, climb_m, rider_count, submitted_count}, cells[{user_id, nickname, avatar, submitted, distance_km, avg_speed, climb_m, submitted_at}], media[…现有 MeetupMediaOut] };RouteGuideOut{ route_book_id, name, distance, climb, city, content_md, cover_url, highlights, preview_points, elevation_profile }。均 extra="forbid"。

## §5 风险表

| # | 风险 | 严重度 | 对策 |
|---|---|---|---|
| 1 | attach tick 扫描放大 | 低 | 7 天窗 + 现有索引;T1 自检查询计划 |
| 2 | 5 秒预算实测超标 | 中 | D7 两段式 |
| 3 | FIT 链路从未真跑 + garmin_fit_sdk 镜像确认 + scheduler 新模块 → 部署必须 --build 不是 restart | 中 | T6 硬项(B 跨进程陷阱定案) |
| 4 | share_token 端到端未真用 | 中 | T6 半生人剧本真演 |
| 5 | 灌库内容幻觉/侵权 | 高 | route skill 铁律,主 agent 亲自,来源标注 |
| 6 | TENCENT_MAP_KEY 生产状态未知 | 低 | T6 SOP 第一步亲查 .env;缺失按步骤配;前端降级不白屏 |
| 7 | 战报催缴感 | 低 | 格子无催语 |
| 8 | onShareAppMessage 异步陷阱 | 中 | §3.3 onLoad 预拉定案;T3 测试含「分享标题 m/n 非 0/0」断言 |

## §6 已知限制

格子点亮延迟 ≤5 分钟;一人多骑只记最早一条(其余仍在个人记录);实况层/评论层/赛段排行/手绘路书不在本期(启动信号见 PRD)。

## §7 任务拆分与测试策略

| 任务 | 核心交付 | 测试要点 |
|---|---|---|
| T1 关联 | 表+迁移(down_revision 明写)+attach tick+bj_time 共享模块 | 边界表 11 行各一测;幂等双跑;北京时区 20:00 案例;查询计划 |
| T2 开奖 | upload 重做+fit 后缀+双端点轮询 | 前端协议三层自校验(wxml↔js 函数名/js↔api 参数/setData↔wxml 字段,判例 frontend_protocol);真机 5 文件计时 |
| T3 分享 | detail 预拉+onShare 同步读 data+source 参数 | 分享标题 m/n 非 0/0;非参与者可转发 |
| T4 战报 | report API+页面+detail 入口按钮 | 合计求和;灰格;导航不可达+两个正向入口可达 |
| T5 埋点 | SENSOR 行+source 参数 | 三种 viewer 态断言 |
| T6 部署 | SOP(--build)+三喇叭位+延迟实测+TENCENT_MAP_KEY 亲查 | 线上 curl;FIT 端到端;p90 落 PRD |
| T7 灌库 | 双表迁移+脚本+13 条内容 | 幂等重跑;track_pending;is_official 查询 .is_(True) |
| T8 路线页 | 列表+详情+官方过滤+guide API | preview_points 渲染;无封面空态 |
| T9 双入口 | 预填+向导官方组+详情路书预览 | route_book_id 透传链 |

执行顺序:T1→(T2,T3,T5 并行)→T4→T6 ‖ T7→(T8,T9)→上线。代码层每批产出后信条 5 双审+Codex 异源,commit 过门禁。
