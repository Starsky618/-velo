# Sprint 13 Task-4 — 战报页（report API + pages/meetup-report + 详情入口）

> 所属：Sprint 13 闭环主链 / 第 4 个 task / S13 前端收口。
> 上游：`docs/spec-v6.md` §3.4 / §4（MeetupReportOut 全字段定义）/ D9 / 终轮 C2（两步查询防灰格消失）。
> 前置门：T1（数据来源）、T2/T3（已 ship，本 task 上线后它们的降级路径自动恢复）。

---

## ─────── 给 Tim 看 ───────

### 干啥用

一场约骑的"成绩册"：集体合计（总里程、总爬升）+ 照片墙 + 每人一格。交了卷的格子亮着显示数据，没交的是灰格 + 一个「交卷」按钮。**灰格是战报的命**——它制造"我的卷子还空着"的社交压力，又不写一句催语。

### 用户故事

老张在群里点开成绩卡，落在战报页：第一行集体合计往上跳，照片墙是早上拍的合影，下面 6 个格子——交卷的 1 个亮着 42.3km，他自己那格是灰的，写着「交卷」。他点进去传完文件，5 分钟内格子点亮。他顺手把战报转回群里：「天龙山西线战报 · 已交卷 2/6」。

### 怎么算做对了

- ✓ 战报页**不在任何 tab 和首页导航里**（PRD 验收=检查导航配置）——只能从分享卡和约骑详情两条路进来。
- ✓ 没交卷的人永远显示灰格（哪怕一个人都没交，格子也全员列出）。
- ✓ 格子按交卷先后排，灰格排末尾；没有名次、没有催语，文案只有「交卷」。
- ✓ 集体合计 = 已交卷数据求和（km 为单位）。
- ✓ 私圈约骑无口令访问战报 → 404（和详情页同一套门禁，不另写一份）。
- ✓ 战报页自己也能转发，标题带「已交卷 m/n」。

### 这次不做

- 不做名次 / 排序按表现（D-006 押后；交卷先后是行为顺序不是表现排名）。
- 不做催缴推送 / 通知。
- 不进 tab、不进首页导航（反向验收项）。

### 估时

1.5 天（后端 0.5 + 前端 1）。

---

## ─────── 执行 subagent 技术细节 ───────

<details>
<summary>展开</summary>

## 1. 起手必跑

```bash
nl -ba docs/spec-v6.md | sed -n '167,170p;205,216p'      # §3.4 + §4 响应模型全文
sed -n '404,500p' app/meetup/service.py                   # get_meetup_detail + list_participants（JOIN 惯例）
rg -n "media" app/meetup/service.py app/meetup/router.py | head   # 照片墙现有取数函数（复用）
rg -n "class MeetupMediaOut|class InviteeSummary" app/meetup/schemas.py
rg -n '"pages/' miniprogram/app.json                      # 确认导航现状
```

已验证事实（2026-06-11 主 agent grep）：
- 门禁整链函数 `get_meetup_detail(db, meetup_id, current_user_id, token)` 在 service.py:404，内含查询 + `_assert_invite_only_access`（:386）[✓ Read]——**report 必须先调它再聚合，禁止另写查询或门禁（spec §4 防漂移）**
- participants JOIN users 惯例 [✓ Read service.py:467-483]：`db.query(MeetupParticipant, User).join(User, User.id == MeetupParticipant.user_id)`，输出用 `nickname=user.nickname or None` / `avatar_url=user.avatar_url`
- **avatar 字段定案 = `avatar_url`**（users 表实际字段，[✓ grep app/user/models.py:45]；spec §4 写的 `avatar` 以预读为准条款落定为 `avatar_url`）
- 已交卷数据字段在 Activity 上：`distance`（米）/ `avg_speed`（km/h）/ `elevation_gain`（米）[✓ grep app/activity/models.py:74-78]
- meetup schemas 全部 `model_config = ConfigDict(extra="forbid")` [✓ grep schemas.py 多处]
- app.json pages 列表现状无 meetup-report [✓ Read]

## 2. 文件改动清单

- Modify `app/meetup/schemas.py`：新增 MeetupReportTotals / MeetupReportCell / MeetupReportOut（datetime/Field import 按需补）
- Modify `app/meetup/service.py`：新增 `get_meetup_report(db, meetup_id, current_user_id, token=None)`；**import 必补两行**——`MeetupActivity` 并入现有 `from app.meetup.models import ...` 行（现状只有 Meetup, MeetupMedia, MeetupParticipant [✓ grep service.py:17]）+ `from app.activity.models import Activity`（正向依赖，Meetup→Activity 合规）
- Modify `app/meetup/media_service.py` + `router.py`：把 `_media_response`（现在 router.py:63 [✓ grep]）挪到 media_service 层供"媒体列表端点 + 战报"两处复用，router 原调用点改 import——**禁止在 service 里复制第二份字段映射**（共享逻辑识别，CLAUDE.md spec 自审 #2）
- Modify `app/meetup/router.py`：新增 `GET /{meetup_id}/report`（**注册在 `GET /{meetup_id}` 之前**，路由顺序敏感惯例同 route_book）
- Create `miniprogram/pages/meetup-report/`（js/wxml/wxss/json 四件）
- Modify `miniprogram/app.json`：注册页面（只进 pages 数组，**不进 tabBar**）
- Modify `miniprogram/pages/meetup-detail/`：「看战报」按钮（条件显示）
- Create `tests/test_meetup_report.py`
- **Do not** 给 meetup_activities 加列 / **Do not** 写单条 INNER JOIN 出 cells / **Do not** 加通知逻辑

## 3. 完整代码（后端核心）

### 3.1 schemas（spec §4 字段闭集，extra="forbid"）

```python
class MeetupReportTotals(BaseModel):
    distance_km: float
    climb_m: float
    rider_count: int
    submitted_count: int
    model_config = ConfigDict(extra="forbid")


class MeetupReportCell(BaseModel):
    """战报里的一格。未交卷格：submitted=False，四个数据字段全 null（前端整块条件渲染）。"""
    user_id: int
    nickname: str | None = None
    avatar_url: str | None = None
    submitted: bool
    distance_km: float | None = None
    avg_speed: float | None = None
    # climb_m / submitted_at 是序列化别名（spec §4 定案，禁止加数据库列）：
    # Python 侧字段名沿用 ORM 来源（elevation_gain / created_at），JSON 输出名是别名。
    elevation_gain: float | None = Field(default=None, serialization_alias="climb_m")
    created_at: datetime | None = Field(default=None, serialization_alias="submitted_at")
    model_config = ConfigDict(extra="forbid")


class MeetupReportOut(BaseModel):
    meetup_id: int
    totals: MeetupReportTotals
    cells: list[MeetupReportCell]
    media: list[MeetupMediaResponse]   # 真实类名 [✓ grep schemas.py:162]；spec 原文 MeetupMediaOut 是幻觉类名，已修 spec
    model_config = ConfigDict(extra="forbid")
```

注：FastAPI 对 response_model 默认按 serialization_alias 输出，前端拿到的就是 `climb_m` / `submitted_at`。前端代码**只允许引用别名后的字段名**。

### 3.2 service（两步查询——终轮 C2：禁止单条 INNER JOIN，它会把未交卷者滤掉，灰格永不出现）

```python
def get_meetup_report(db: Session, meetup_id: int, current_user_id: int | None, token: str | None = None) -> MeetupReportOut:
    """聚合一场约骑的战报：合计 + 每人一格 + 照片墙。

    门禁复用整链（spec §4）：先走 get_meetup_detail（内含 404 与 invite_only 校验），
    本函数不另写查询、不另写门禁——两套门禁必然漂移。
    """
    meetup = get_meetup_detail(db, meetup_id, current_user_id=current_user_id, token=token)

    # 第一步：participants JOIN users 取全集骨架——灰格是战报的命，
    # 必须先拿到"所有报名的人"，再往骨架上贴数据。
    skeleton_rows = (
        db.query(MeetupParticipant, User)
        .join(User, User.id == MeetupParticipant.user_id)
        .filter(MeetupParticipant.meetup_id == meetup_id)
        .all()
    )

    # 第二步：已交卷数据（MeetupActivity JOIN Activity），Python 按 user_id 合并进骨架
    submitted_rows = (
        db.query(MeetupActivity, Activity)
        .join(Activity, Activity.id == MeetupActivity.activity_id)
        .filter(MeetupActivity.meetup_id == meetup_id)
        .all()
    )
    by_user = {ma.user_id: (ma, act) for ma, act in submitted_rows}

    cells, total_distance_m, total_climb_m = [], 0.0, 0.0
    for participant, user in skeleton_rows:
        hit = by_user.get(participant.user_id)
        if hit is None:
            cells.append(MeetupReportCell(
                user_id=user.id, nickname=user.nickname or None,
                avatar_url=user.avatar_url, submitted=False,
            ))
            continue
        ma, act = hit
        total_distance_m += act.distance or 0.0
        total_climb_m += act.elevation_gain or 0.0
        cells.append(MeetupReportCell(
            user_id=user.id, nickname=user.nickname or None,
            avatar_url=user.avatar_url, submitted=True,
            distance_km=round((act.distance or 0.0) / 1000, 1),   # DB 米 → API km（项目约定）
            avg_speed=act.avg_speed,
            elevation_gain=act.elevation_gain,
            created_at=ma.created_at,
        ))

    # D9 排序：已交卷按交卷先后（created_at asc），灰格（无 created_at）排末尾——
    # NULLS LAST 语义在 Python 合并时等价实现。
    cells.sort(key=lambda c: (c.created_at is None, c.created_at or datetime.max.replace(tzinfo=timezone.utc)))

    return MeetupReportOut(
        meetup_id=meetup_id,
        totals=MeetupReportTotals(
            distance_km=round(total_distance_m / 1000, 1),
            climb_m=round(total_climb_m),
            rider_count=len(skeleton_rows),
            submitted_count=len(submitted_rows),
        ),
        cells=cells,
        # 取数 = media_service.list_meetup_media(db, meetup_id) [✓ grep media_service.py:119，返回 ORM 行]；
        # ORM→schema 映射用挪到 media_service 的 _media_response（见文件改动清单），禁止直接把 ORM 行塞进 schema
        media=[_media_response(m) for m in list_meetup_media(db, meetup_id)],
    )
```

注意（执行时核对）：SQLite fixture 下 `ma.created_at` 可能 naive（陷阱 #2）——排序 key 里 datetime.max 的 tzinfo 处理要跟取出值一致，测试里两种都跑。

### 3.3 router

```python
@router.get("/{meetup_id}/report", response_model=schemas.MeetupReportOut)
def get_meetup_report(
    meetup_id: int,
    token: str | None = Query(None),
    current_user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    return service.get_meetup_report(db, meetup_id, current_user_id=current_user_id, token=token)
```

（鉴权依赖用 `get_optional_user` 与 get_meetup 详情一致——分享卡落地的人可能未登录态；invite_only 的保护由 service 内门禁整链负责。执行时 re-grep get_meetup 现状抄齐。）

## 4. 前端（pages/meetup-report）

- 布局自上而下（spec §3.4）：集体合计 → 照片墙（复用 meetup-detail 照片墙渲染模式）→ 每人一格。
- 格子：已交卷 = 昵称/头像 + distance_km / avg_speed / climb_m；未交卷 = 灰格 + 「交卷」按钮 → `navigateTo /pages/upload/upload?meetup_id={id}&token={token}`（跨任务契约，T2 消费）。**格子无催语，文案只有「交卷」**（spec 风险 7）。
- 入口按钮（Modify meetup-detail）：`status === 'COMPLETED' || (status === 'OPEN' && reportStats && reportStats.submitted_count >= 1)` 时显示「看战报」→ navigateTo 战报页（带 token）。reportStats 来自 T3 的预拉，本 task 只加按钮。
- 战报页自身分享（spec 终轮定案）：`onShareAppMessage` 同步读 onLoad 已加载数据，title=「{约骑名} 战报 · 已交卷 m/n」，path=`/pages/meetup-report/meetup-report?id=X&token=Y&source=report_card`（落地回战报页自身）。
- 字段渲染遵守 no-dash 判例：null 字段整块 wx:if 隐藏。

## 5. 测试用例

| # | 用例 | 断言 |
|---|---|---|
| 1 | 3 人报名 1 人交卷 | cells 长度 3；1 亮 2 灰；灰格四数据字段全 null |
| 2 | 合计求和 | distance_km/climb_m = 已交卷求和（米→km 换算对） |
| 3 | D9 排序 | 先交卷在前；灰格全在末尾 |
| 4 | 0 人交卷 | cells 全灰，totals 全 0，不炸 |
| 5 | invite_only 无 token 非参与者 | 404（门禁整链生效） |
| 6 | invite_only 带对 token | 200 |
| 7 | 响应字段名 | JSON 输出含 `climb_m`/`submitted_at`（别名生效），无 `elevation_gain`/`created_at` |
| 8 | extra="forbid" | 多余字段构造报错 |
| 9 | 导航不可达 | app.json tabBar 不含 meetup-report（grep 断言写进测试或自检） |

前端协议三层自校验逐条 grep 贴报告；两个正向入口（分享路径 / 详情按钮）开发者工具各走一遍。

## 6. 自检（commit 前）

- [ ] `rg -n "JOIN|join" app/meetup/service.py` 内 report 函数无单条 participants×activities INNER JOIN（终轮 C2）
- [ ] `rg -n "meetup-report" miniprogram/app.json` → 只在 pages 数组，不在 tabBar
- [ ] `rg -n "_assert_invite_only_access" app/meetup/service.py` → report 路径没有第二份门禁实现
- [ ] pytest 全套绿
- [ ] 自检三问：做了卡外的事吗 / 验收命令都真跑了吗 / 与 spec §3.4+§4 逐条对照过吗

## 7. commit 指令

```
feat(meetup): S13-T4 战报页（report API 两步查询 + meetup-report 页 + 详情入口）
```

</details>
