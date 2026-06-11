# Spec v6.4 · Sprint 13+14 上线冲刺(熟人约骑闭环 + 路线百科上架)

> 上游:docs/prd/sprint-13-launch-prd.md(Tim 全 y,2026-06-11)+ 战略决策 D-004/D-005/D-006。
> 审判轨迹:v6.0 5C/12I → v6.1 5C/13I → v6.2 2C/15I(集成侧归零)→ v6.3 终轮 2C/6I → v6.4(本版)全修,复核归零后进 Step 8。

## §0.1 代码侧事实表(双审复核后修订版)

| 事实 | 证据 | 来源 |
|---|---|---|
| meetups.status ∈ DRAFT/OPEN/CANCELLED/COMPLETED,String(16),CHECK 约束 | app/meetup/models.py:36,70-71 | ✓ |
| meetups.start_time / estimated_end_time 均 DateTime(tz),NOT NULL | models.py:43-44 | ✓ |
| meetups.route_book_id FK→route_books,SET NULL | models.py:38 | ✓ |
| GPX/FIT 上传路径状态机 4 态:pending→processing→completed/failed;importing 是 Strava 导入专用中间态(import_scheduler.py:354),不在本 spec 范围 | activity/models.py:13,36-39 + 双审 B-C3 修订 | ✓ |
| activities.user_id FK→users;started_at 为骑行业务时间 | models.py:49 + CLAUDE.md 约定 | ✓ |
| _load_and_authorize_meetup 定义于 service.py:107,行锁语句在 :125;invite_only 门禁函数 _assert_invite_only_access 在 service.py:386-401 | app/meetup/service.py | ✓ |
| 后端上传白名单 {.gpx,.fit};FIT 分支在 app/activity/worker.py:209(根目录 worker.py 仅 55 行,与此无关);garmin-fit-sdk 在 requirements.txt:19 | activity/service.py:46 / activity/worker.py:209 | ✓ |
| 前端 upload.js extension 仅 ['gpx'] | upload.js:45-48 | ✓ |
| meetup-create 有 onShareAppMessage;meetup-detail 无 | meetup-create.js:260-268 / meetup-detail.js | ✓ |
| meetup tick 节拍 = scheduler 15 秒 × 计数器 20 = 5 分钟;complete_tick 自建 SessionLocal、无参签名 | scheduler.py:37,55 / cron.py:35-44 | ✓ |
| 活动状态轻量端点 GET /api/activities/{id}/status(仅 status/error/duplicate_of)与详情端点分离 | activity/router.py:247,82 | ✓ |
| IntegrityError try/except 是项目冲突处理惯例;ON CONFLICT DO NOTHING 全库零先例 | meetup/service.py:191-196,505-511 / activity/service.py:247 | ✓ |
| Boolean server_default 项目主流写法 false()(meetup/models.py:108 等) | 双审 B-I1 | ✓ |
| 北京时区已在两处各自定义(_BJ_TZ):training/service.py:39 / notification/progress_detector.py:46,无共享函数(pre-T1 现状,T1 建共享模块) | 双审 B | ✓ |
| migration 链末节点 = 20260603_meetup_create_fields | alembic/versions/ | ✓ |
| route_books 字段(无 description/is_official);route_book/models.py 已导入 func(L14),未导入 Boolean/false | route_book/models.py:24-35,13-14 | ✓ |
| meetup↔activity 现无任何关联 | 全库 grep 为空 | ✓ |
| 反向 hook 现有 2 处已登记;本 spec 新增 MeetupActivity 为 Meetup→Activity 正向,不新增反向 | 双审 B 架构层核验 | ✓ |
| TENCENT_MAP_KEY 生产配置状态 | ✅ 存在（2026-06-11 T6 部署亲查 .env 销账；同 key 已填前端 map-theme subkey 启用个性化底图） | ✓ |

## §1 决策记录

| # | 决策 | 理由 |
|---|---|---|
| D1 | 关联走 meetup 侧 cron 轮询(attach tick),不在 activity worker 触发 | 方案 B 零反向依赖;竞态消解;崩溃自愈;格子点亮延迟 ≤5 分钟可接受 |
| D2 | 关联窗口 = 约骑当天北京时区自然日 + started_at ≥ start_time−30min;不用 estimated_end_time | +3h 估算脆弱性不进匹配;骑 6 小时不掉窗 |
| D3 | 每人每场只挂 1 条(UNIQUE meetup_id+user_id),取窗口内 started_at 最早一条 | 战报一人一格;约骑出发后最先开始的误挂概率最低 |
| D4 | 补传截止 = start_time 时刻 + 168 小时(命名常量 ATTACH_WINDOW_DAYS=7,代码中可调,复检时一并审)。显式偏离 PRD 必答 #2 的「completed_at+N 天」并论证:completed_at 由 cron 节拍对 estimated_end 的判定产生,继承 +3h 估算脆弱性(与 D2 弃用它同一理由);start_time 时刻锚与 tick 查询 interval 同粒度,无日切歧义 | 边界 C;防陈年文件;二轮 A-C1 定案 |
| D5 | 介绍富文本入新表 route_guides,不给 route_books 加列(D11 细化:guide 为主实体,route_book_id 可空) | 防火墙;半衰期分离;未来实况层挂同侧 |
| D6 | route_books 加 is_official(Boolean, server_default=false(),与 meetup 模块写法一致);查询一律 .is_(True) 防 truthiness | 官方/用户路线筛选;陷阱 #1 |
| D7 | 5 秒预算两段式:先实测(T6 脚本),p90>5s 才开小文件同步快路径 | 不为未测量的问题预建复杂度 |
| D8 | 五环节埋点 = logger.info 行,固定前缀字符串 "SENSOR "(沿用项目日志惯例,不建事件表) | 百用户级 grep 足够 |
| D9 | 战报格子按交卷先后排序(meetup_activities.created_at ASC),未交卷灰格(无 created_at)排末尾(NULLS LAST 语义,两步查询时 Python 合并同义)。与 D-006 的关系:D-006 押后的是骑行表现排名,交卷顺序是行为顺序不是表现排名,不违反 | v6.0 误引 D-006 修正;终轮 I4 补灰格位次 |
| D10 | 同一活动允许挂到多场约骑(用户真报名了两场窗口重叠的约骑时):uq_meetup_activity 只防同场重复,不做跨场互斥 | 极罕见场景,数据保真实;边界表新增行 |
| D11 | route_guides 为官方路线的主实体:guide 可先于轨迹存在(route_book_id 可空 = track_pending 态),海拔曲线在灌库时预计算存列。官方路书无 source_activity_id,Trackpoint 链路不存在(二轮实证),海拔必须由灌库脚本从 track.gpx 算好落库 | 治 track_pending 无落点 + elevation_profile 无来源两个二轮 finding;列表页数据源=route_guides 全集,「发起约骑」按钮仅 route_book_id 非空时显示 |

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

迁移拆两个文件(任务并行回滚隔离,二轮 B-N2 定案):T1 → 20260611_meetup_activities.py(`down_revision = "20260603_meetup_create_fields"`,链末实证,只建本表);T7 → 20260612_route_guides.py(`down_revision = "20260611_meetup_activities"`,建 route_guides + route_books.is_official 列)。

### 2.2 新表 route_guides + route_books 加列(S14-T7,归属 app/route_book/models.py)

```python
# models.py 顶部补两行(实证现状:func 已导入,Boolean/false 均缺):
# from sqlalchemy import Boolean(加入现有 import 行)
# from sqlalchemy.sql 行追加 false

class RouteGuide(Base):                        # 官方路线主实体(D11)
    __tablename__ = "route_guides"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, unique=True)     # 路线名,灌库幂等键
    city = Column(String(32), nullable=False, server_default="太原")
    route_book_id = Column(Integer, ForeignKey("route_books.id", ondelete="SET NULL"),
                           nullable=True, unique=True)          # 可空 = track_pending 态(D11)
    content_md = Column(Text, nullable=False)
    cover_url = Column(String(512), nullable=True)
    highlights = Column(Text, nullable=True)                    # JSON 数组文本
    elevation_profile = Column(Text, nullable=True)             # JSON [[累计km, 海拔m],...] ~100 点,
                                                                # 灌库时从 track.gpx 降采样预计算(D11);
                                                                # 无轨迹时 NULL,前端 wx:if 整块隐藏(no-dash 判例)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

# RouteBook 加列:
is_official = Column(Boolean, nullable=False, server_default=false())
```

### 2.3 共享时区工具(S13-T1 顺带,治三处重复定义)

新建 app/common/bj_time.py:`BJ_TZ = timezone(timedelta(hours=8))` + `def to_bj_date(dt_aware) -> date`。attach tick 用它;training/service.py:39 与 notification/progress_detector.py:46 两处存量定义的迁移记入 docs/tech-debt.md(不在本期强改已 ship 模块,共享逻辑规则的存量豁免登记)。

## §3 核心逻辑

### 3.1 attach tick(S13-T1,app/meetup/cron.py)

函数签名与 session 管理(双审 B-C2 定案):`run_meetup_attach_tick()` 无参,自建 `SessionLocal()`,finally 关闭——与 run_meetup_complete_tick 完全同模式(cron.py:35-44 实证)。scheduler.py 集成位置(精确到行,防 15 秒全量扫描事故):

```python
if _meetup_tick_counter >= 20:          # scheduler.py:55 现有块
    run_meetup_complete_tick()
    run_meetup_attach_tick()            # ← 唯一合法插入点:if 块内,complete 之后
    _meetup_tick_counter = 0
```

部署须 `docker compose up -d --build`(scheduler 容器加载新模块,restart 不够)。

cron.py 新增 import 块(三轮 B-C1 定案,漏一个 = scheduler 启动即崩):
`from sqlalchemy.exc import IntegrityError` / `from app.activity.models import Activity` / `from app.meetup.models import MeetupActivity, MeetupParticipant` / `from app.common.bj_time import to_bj_date`(bj_time.py 必须先于本文件创建——T1 卡内排序 blocking)。scheduler.py 顶部同步加 `run_meetup_attach_tick` 到现有 import 行(scheduler.py:22)。常量:`ATTACH_WINDOW_DAYS = 7` 定义在 cron.py 顶部。

```
run_meetup_attach_tick():
  db = SessionLocal()
  try:
    meetups = status IN ('OPEN','COMPLETED') AND start_time >= now() - ATTACH_WINDOW_DAYS 天   # 时刻粒度,与 D4 同锚
    for meetup in meetups:
      participants = db.query(MeetupParticipant).filter_by(meetup_id=meetup.id).all()
      # Meetup 模型零 relationship(实证),禁止写 meetup.participants —— 显式 query(service.py:427 惯例)
      for participant in participants:
      若已存在关联(WHERE meetup_id=本场.id AND user_id=本人.id,两条件缺一不可,防跨场误跳 D10)→ continue   # D3 幂等快路径
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
| F 同一人真报了两场重叠约骑(独立用例,非 B 子集) | 同一活动允许挂两场(D10) |
| C 骑完第 3 天才传 | 7 天内 tick 自动补挂;COMPLETED 态照常关联(D4) |
| C2 约骑被取消(CANCELLED)后上传 | tick 只扫 OPEN/COMPLETED,CANCELLED 不关联(明文保证,A-I5) |
| D 补传昨天的文件 | 匹配用 started_at,与上传时间无关 |
| E worker 重试/并发 tick | 双 UNIQUE + except IntegrityError 跳过,幂等 |
| 崩在循环中途 | 已 commit 的保留,下个 tick 续扫 |
| 参与者退出后才上传 | JOIN 当前 participants,不挂;已挂后退出 → 行保留,战报随 participants 渲染自然消失 |
| 北京时区日切 | 比较一律经 to_bj_date(aware),禁止比较 UTC 日期;T1 必含测试:约骑北京 20:00 开始、活动 started_at=UTC 12:00 同日命中 |
| 未来约骑(还没到约骑日) | 扫描窗含未来约骑,但 D2 日期相等条件天然不匹配今天的活动(明文保证+测试) |
| 同人同场二次上传 | 第一条已挂,第二条被 uq_meetup_user_one_cell 拒,except 跳过(与 E 同机制,单列防漏测) |

### 3.2 开奖与 5 秒预算(S13-T2)

前端按 demo 重做(docs/prototypes/upload-reveal-first-rider.html 为交互蓝本)。轮询协议(B-I4 定案):上传成功 → 800ms 间隔轮询轻量端点 GET /api/activities/{id}/status;status=completed → 再 fetch 一次 GET /api/activities/{id} 拿完整开奖数据(避免轮询拖全量轨迹 JSONB)。>5s 显示阶段文案,>30s 转后台提示。改造点三处明写:upload.js:48 extension 改 ['gpx','fit'];upload.js:177 轮询间隔 2000 改 800;wxml 文案同步(B-I2 二轮)。延迟实测脚本与快路径触发条件同 D7。

### 3.3 分享卡双发起点(S13-T3)

meetup-detail.js:data 初始化块(现 L36-43)新增 reportStats: null;onLoad 阶段预拉战报统计(已交卷 m/报名 n)写入;onShareAppMessage 为同步钩子只读 data,禁止钩子内异步 fetch(微信平台约束,异步结果不会等到分享弹窗)。reportStats 预拉端点 = GET /api/meetups/{id}/report,取 totals.submitted_count/rider_count(百用户量级 cells 最多几十行纯数字,无轨迹 JSONB,体量与轻量化原则不冲突——论证留档);T3 与 T4 协同实现,T4 未就绪时 T3 以 reportStats=null 降级。reportStats 仍为 null 时分享标题退化为纯约骑名,不显示 m/n(防 undefined/undefined)。路径 =/pages/meetup-detail/meetup-detail?id=X&token=Y&source=share_card。meetup-create 现有分享路径追加 &source=share_card;成绩卡页分享 source=report_card。

### 3.4 战报页(S13-T4)

新页 pages/meetup-report,不注册 tab/不进首页导航。正向入口两个(A-I1 补):① 分享卡路径直达 ② meetup-detail 在 status∈{OPEN(已有≥1 条关联),COMPLETED} 时显示「看战报」按钮。战报页自身可分享:onShareAppMessage(同步钩子,读 onLoad 已加载的本页数据),标题「{约骑名} 战报 · 已交卷 m/n」,路径 /pages/meetup-report/meetup-report?id=X&token=Y&source=report_card(落地回战报页自身)。数据源 GET /api/meetups/{id}/report。布局:集体合计 → 照片墙(meetup_media)→ 每人一格(participants 全列,已交卷显示 distance/avg_speed/climb,未交卷灰格+「交卷」按钮跳 upload;格子无催语,文案只有「交卷」)。排序按 D9。

### 3.5 五环节埋点(S13-T5)

get_meetup router 函数签名加 `source: str = Query("direct")`(现 router.py:168-177 无此参数,实证)+ 一行 `logger.info("SENSOR view meetup_id=%s viewer=%s token=%s source=%s", ...)`,viewer ∈ participant/guest/anon(由 get_optional_user + participants 判定)。数据回看查询(T5 交付物,inline 定义,治二轮 A-C2 悬空引用):
- ①触达:`docker compose logs api | grep "SENSOR view" | grep "source=share_card" | wc -l`
- ②自主进入:同上加 `grep -E "viewer=(guest|anon)"`
- ③报名:`SELECT count(*) FROM meetup_participants WHERE meetup_id=X;`
- ④⑤交卷率:`SELECT count(*) FROM meetup_activities WHERE meetup_id=X;` ÷ ③
- 复检哨兵:`SELECT count(DISTINCT user_id) FROM meetup_participants WHERE meetup_id=X AND user_id NOT IN (:创始三人);`

### 3.6 灌库管线(S14-T7)

scripts/import_route_guides.py 读 content/routes/<路线名>/:guide.md + track.gpx[可选] + meta.json{name, city, highlights, cover_url 可选}。按 D11:有 track.gpx → 建 route_book(is_official=true, source='file_upload', file_type='gpx', file_id=GPX 存储路径——三者联动满足 ck_route_books_file_type_source 联合 CHECK[实证 models.py:40-55],缺 file_id 则 INSERT 被 DB 拒)+ 算 elevation_profile + 建 guide(挂 book);幂等重跑已有轨迹的路线 → 更新旧 book 的 reference_line/distance/climb,不新建(防孤儿 book,三轮 B-I3 选项二);无轨迹 → 只建 guide(route_book_id=NULL=track_pending);脚本前置校验:guide.md 缺失立即报错退出,不进 DB 层撞 IntegrityError;meta.json 字段约定:必填=name,可选=city(默认太原)/highlights/cover_url,补 GPX 后按 name(unique 键)幂等重跑升级。cover_url 缺省 null,前端空态占位图。内容转换(13 条路线,原始 HTML 17 个,多版路线选定本后一线一份 guide.md)走 route skill 全部铁律,主 agent 亲自逐条做。定本:天龙山 v11(Tim 已拍);汾河 3 版定本为 Step 8 待拍项(推荐最新的「环太原汾河自行车道」版),拍板前 T7 不得灌汾河这条——未决决策不进实施。

### 3.7 路线页与双入口(S14-T8/T9)

- 路线推荐列表页数据源 = GET /api/route-guides(新,T8):返回 route_guides 全集(含 track_pending,标 ready 布尔),官方列表与 route_books 解耦(D11)
- 约骑向导官方组数据源 = GET /api/route-books?official=1(T9):service 层 `RouteBook.is_official.is_(True)`;前端两次调用分组渲染(官方组+我的组),无需后端合并
- GET /api/route-guides/{id}(T8):content_md + cover_url + highlights + elevation_profile(本表列,D11)+ preview_points(route_book_id 非空时经现有 route_book 预览机制取,reference_line 出)
- 路由注册顺序:route_guides 用独立子前缀 /api/route-guides,完全避开 route_book/router.py:104 的 /{route_book_id} 通配冲突(实证该文件 L6-7 已注明顺序敏感)
- pages/route-list / route-detail(T8);详情底部「发起约骑」→ meetup-create?route_book_id=X 预填(T9)
- meetup-create 路线步加官方路线组(T9);meetup-detail 嵌路书预览,移植 restoreRoutePreview(T9)

### 3.8 PRD 必答清单的论证留档(7/7 全覆盖索引)

- 必答 #1(关联方向)→ D1。 必答 #2(故障五维+UNIQUE+截止)→ D3/D4 + §3.1 边界表 12 行。 必答 #4(estimated_end 余量)→ D2(整体弃用该字段,余量问题消解)。 必答 #6(TENCENT_MAP_KEY)→ §0.1 末行 ⚠️ + §5 风险 6 + T6 SOP 亲查步骤。

- 必答 #3 竞态明文论证:complete_tick 把约骑置 COMPLETED 与用户上传是两个独立事件,attach tick 的扫描条件含 COMPLETED 态且与状态变更解耦——先 COMPLETED 后上传的活动最多等一个 5 分钟节拍即被关联,不存在丢失窗口。
- 必答 #5 三件套对比:方案 A(route_books 加 description 列)= 1 migration + 模型 1 行 + schema 1 行,最便宜但把慢变内容焊进轨迹表,违反防火墙与半衰期分离,且 track_pending 无落点;方案 B(新表 route_guides 主实体)= 1 migration + 新模型 + 新 schema + JOIN,贵一档但内容资产独立、可先于轨迹存在、未来实况层同侧扩展;方案 C(内容存对象存储/文件)= 零 migration 但失去 SQL 可查与事务一致性。取 B(D5/D11)。
- 必答 #7 备选否决:worker 并发调优——队列等待是否是瓶颈未实测,先调优是盲调;解析分级先出核心数据——改动解析器内部结构,复杂度最高,留作快路径也不够时的末手。故取「实测 → 必要时小文件同步快路径」最小路径(D7)。

### 3.9 顺带登记的历史债(本期不修,防加深)

segment/router.py ↔ meetup/service.py 存在历史双向 import(三轮 B 实证,反向侧已登记)。T1 实现禁令:meetup/cron.py 不得 import segment,防循环加深。登记进 docs/tech-debt.md。

## §4 API 变更清单

| 方法 | 路径 | 变更 | 任务 |
|---|---|---|---|
| GET | /api/meetups/{id} | 加 source 参数(仅日志)+ SENSOR 行 | T5 |
| GET | /api/meetups/{id}/report | 新增。token 门禁复用整链:report endpoint 先调 service.get_meetup_detail(db, meetup_id, current_user_id, token)(service.py:404-413,内含查询+_assert_invite_only_access 门禁)再做报告聚合,禁止另写查询或门禁(防漂移):invite_only + 无 token + 非参与者 → 404 | T4 |
| GET | /api/route-books | 加 official 过滤 | T9 |
| GET | /api/route-guides | 新增(官方路线列表,含 track_pending) | T8 |
| GET | /api/route-guides/{id} | 新增(详情) | T8 |

响应模型字段:MeetupReportOut{ meetup_id, totals{distance_km, climb_m, rider_count, submitted_count}, cells[{user_id, nickname, avatar_url, submitted, distance_km, avg_speed, climb_m, submitted_at}], media[现有 MeetupMediaResponse,schemas.py:162——plans 双审实证原写法 MeetupMediaOut 是幻觉类名,全库零命中] }——submitted_at 是 MeetupActivity.created_at 的序列化别名,不加新列(二轮 A-I1 定案);cells 构造必须保证 participants 全列(灰格是战报的命):两步查询——① query meetup_participants JOIN users 取全集骨架(nickname/avatar_url 来自 users 表[预读定案:users.avatar_url,app/user/models.py:45,沿用 InviteeSummary 惯例],JOIN 写法复用 list_participants 现有惯例 service.py:456-483)② query MeetupActivity JOIN Activity(distance/avg_speed/elevation_gain 在 Activity 上,实证 models.py:74-78)取已交卷数据,Python 按 user_id 合并进骨架。禁止用单条 INNER JOIN 实现(会把未交卷者过滤掉,灰格永不出现——终轮 C2)。未交卷格:submitted=false,distance_km/avg_speed/climb_m/submitted_at 均为 null(前端按 no-dash 判例整块条件渲染)。climb_m = Activity.elevation_gain 的序列化别名,Field(serialization_alias) 同 submitted_at 模式。RouteGuideOut{ id, name, city, ready, content_md, cover_url, highlights, elevation_profile, route_book_id, distance, climb, preview_points }。ready = (route_book_id IS NOT NULL);distance/climb/preview_points 仅 ready=true 时有值,经 JOIN route_books 取(distance/climb 是 route_books 现有列,models.py:27-28 实证),不在 route_guides 加列。submitted_at 用 Pydantic Field(serialization_alias="submitted_at") 映射 created_at,禁止加数据库列。均 extra="forbid"。

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
| T1 关联 | 表+独立迁移+attach tick+bj_time 共享模块(建模块先于 cron 改动,blocking 顺序) | 边界表 12 行各一测;幂等双跑;北京时区 20:00 案例;查询计划 |
| T2 开奖 | upload 重做+fit 后缀+双端点轮询 | 前端协议三层自校验(wxml↔js 函数名/js↔api 参数/setData↔wxml 字段,判例 frontend_protocol);真机 5 文件计时 |
| T3 分享 | detail 预拉+onShare 同步读 data+source 参数 | 分享标题 m/n 非 0/0;非参与者可转发 |
| T4 战报 | report API+页面+detail 入口按钮 | 合计求和;灰格;导航不可达+两个正向入口可达 |
| T5 埋点 | SENSOR 行+source 参数 | 三种 viewer 态断言 |
| T6 部署 | SOP 本体=docs/agent-rules/deploy-sop.md(单一真相源,本期增量三项:--build 要求/三喇叭位/延迟实测)+TENCENT_MAP_KEY 亲查 | 线上 curl;FIT 端到端;半生人剧本真演;p90 落 PRD |
| T7 灌库 | 独立迁移(route_guides+is_official)+脚本+13 条内容(汾河定本待 Tim) | 幂等重跑;track_pending 升级路径;elevation_profile 降采样正确性 |
| T8 路线页 | route-guides 双端点+列表+详情页 | track_pending 态渲染(无曲线/无发起按钮);无封面空态 |
| T9 双入口 | 预填+向导官方组+详情路书预览 | route_book_id 透传链 |

执行顺序:T1→(T2,T3,T5 并行)→T4→T6 ‖ T7→(T8,T9)→上线。代码层每批产出后信条 5 双审+Codex 异源,commit 过门禁。

## 附:二轮双审增补的事实
- Meetup 模型零 relationship 定义,查参与者一律显式 query(service.py:427-428 惯例)[✓]
- app/common/ 现仅 geo.py + __init__.py,bj_time.py 待建 [✓ ls]
- upload.js:177 现有轮询间隔 2000ms [✓]
- route_book/router.py:104 有 /{route_book_id} 通配路由,新增 /{id}/guide 需注意注册顺序(router.py:6-7 已有顺序敏感注释)[✓]
- meetup-detail.js data 初始化块(L36-43)无 report 相关字段 [✓]
- scheduler.py:22 顶层 import cron 函数,新增函数需同步加 import 行 [✓]
