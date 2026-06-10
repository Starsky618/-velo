# Sprint 13 Task-5 — 五环节埋点（SENSOR 行 + source 参数 + 数据回看查询）

> 所属：Sprint 13 闭环主链 / 第 5 个 task / 给 D-004/D-005 复检装传感器。
> 上游：`docs/spec-v6.md` §3.5 / D8；PRD §4 数据回看表（①②④⑤传感器当前均不存在，本 task 就是去装）。
> 前置门：T1 已 commit。与 T2/T3 并行。

---

## ─────── 给 Tim 看 ───────

### 干啥用

上线后第 4 周要回答"五环节到底死在哪一格"——这个 task 给看不见的两环（①看到卡进来、②自主进入）装日志传感器，并把 5 条回看查询写成可以直接复制执行的命令。没有它，上线等于没装仪表盘。

### 用户故事

上线 4 周后的周一，你想知道："分享卡发出去到底有没有人点？"跑一条 grep 命令，数字出来：share_card 来源访问 37 次，其中非参与者 21 次。第②格活着，接着看第③格报名数。每一格都有一条现成命令，不用现场想 SQL。

### 怎么算做对了

- ✓ 访问约骑详情会留一行日志：谁（参与者/游客/未登录）、从哪来（share_card/report_card/direct）、看的哪场。
- ✓ 5 条回看查询 + 1 条复检哨兵命令能直接复制执行出数字。
- ✓ 不建任何新表（百用户级 grep 日志足够，D8）。

### 这次不做

- 不建事件表 / 不接任何分析平台。
- 不做管理后台报表页。

### 估时

0.5 天。

---

## ─────── 执行 subagent 技术细节 ───────

<details>
<summary>展开</summary>

## 1. 起手必跑

```bash
nl -ba docs/spec-v6.md | sed -n '171,179p'               # §3.5 全文
sed -n '160,182p' app/meetup/router.py                    # get_meetup 现状签名
rg -n "get_optional_user" app/meetup/router.py | head -3
rg -n "SENSOR" app/ -r                                    # 现有 SENSOR 行（T1 已加 attach 行）
```

已验证事实（2026-06-11 主 agent grep）：
- `get_meetup` 在 router.py:169，签名 = `meetup_id` + `token: str | None = Query(None)` + `current_user_id: int | None = Depends(get_optional_user)` + db，**无 source 参数** [✓ Read router.py:168-177]
- viewer 判定原料齐备：current_user_id（None=anon）+ MeetupParticipant 表查询（participant/guest 分流）

## 2. 文件改动清单

- Modify `app/meetup/router.py`：get_meetup 加 `source: str = Query("direct")` + viewer 判定 + SENSOR 行
- Modify `docs/prd/sprint-13-launch-prd.md` §4：把 5 条回看查询从 spec §3.5 抄进 PRD 数据回看表的"从哪查"列（spec 是真相源，PRD 是 Tim 周一直接照着跑的地方）
- Create `tests/test_meetup_sensor_log.py`（或并入既有 meetup router 测试文件，按现有测试组织习惯）
- **Do not** 建表 / **Do not** 改 service 层（埋点留在 router，service 保持纯业务）

## 3. 完整代码

```python
@router.get("/{meetup_id}", response_model=schemas.MeetupResponse)
def get_meetup(
    meetup_id: int,
    token: str | None = Query(None),
    source: str = Query("direct"),     # 仅日志用：share_card / report_card / direct
    current_user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    meetup = service.get_meetup_detail(db, meetup_id, current_user_id=current_user_id, token=token)
    # 五环节传感器（D8）：固定前缀 SENSOR，grep 可数。viewer 三态——
    # anon=未登录 / participant=已报名 / guest=登录了但没报名（②自主进入就数 guest+anon）
    if current_user_id is None:
        viewer = "anon"
    else:
        # 复用现有 service.is_participant [✓ grep service.py:434]——_live_response 链路已用它，
        # 不新写第二份 participants 存在性查询（共享逻辑识别）
        viewer = "participant" if service.is_participant(db, meetup_id, current_user_id) else "guest"
    logger.info(
        "SENSOR view meetup_id=%s viewer=%s token=%s source=%s",
        meetup_id, viewer, token, source,
    )
    return _live_response(db, meetup, current_user_id=current_user_id)
```

注意：
- SENSOR 行放在 `get_meetup_detail` 之后——invite_only 无权访问会先 404，不记一条"看到了"的假数据。
- token 直接按 spec 字面记原值：它本就出现在 uvicorn 访问日志的 query string 里，这里不新增暴露面；日志仅服务器 sudo 可读。
- router 文件若无 logger，按项目惯例补 `logger = logging.getLogger(__name__)`。

## 4. 数据回看查询（spec §3.5 原文，写进 PRD §4）

```bash
# ① 触达（看到分享卡进来）
docker compose logs api | grep "SENSOR view" | grep "source=share_card" | wc -l
# ② 自主进入（非参与者）
docker compose logs api | grep "SENSOR view" | grep "source=share_card" | grep -E "viewer=(guest|anon)" | wc -l
```

```sql
-- ③ 报名
SELECT count(*) FROM meetup_participants WHERE meetup_id=X;
-- ④⑤ 交卷率 = ④ ÷ ③
SELECT count(*) FROM meetup_activities WHERE meetup_id=X;
-- 复检哨兵（D-004 直读：非创始团队参与者数）
SELECT count(DISTINCT user_id) FROM meetup_participants WHERE meetup_id=X AND user_id NOT IN (:创始三人);
```

## 5. 测试用例

| # | 用例 | 断言（caplog） |
|---|---|---|
| 1 | 未登录访问 public 约骑 | SENSOR 行含 viewer=anon source=direct |
| 2 | 已报名用户带 ?source=share_card | viewer=participant source=share_card |
| 3 | 登录未报名用户 | viewer=guest |
| 4 | invite_only 无 token 游客 | 404 且**无** SENSOR 行（不记假触达） |
| 5 | 不传 source | 默认 direct（向后兼容，现有前端调用不改也不炸） |

## 6. 自检（commit 前）

- [ ] `rg -n "SENSOR view" app/meetup/router.py` 恰一处
- [ ] 5 条回看命令在本地 dev 环境真跑一遍（哪怕结果是 0），截输出进交付报告
- [ ] PRD §4 已同步（spec→PRD 抄录无漂移）
- [ ] 自检三问：做了卡外的事吗 / 验收命令都真跑了吗 / 与 spec §3.5 逐条对照过吗

## 7. commit 指令

```
feat(meetup): S13-T5 五环节埋点（SENSOR view 行 + source 参数 + 回看查询入 PRD）
```

</details>
