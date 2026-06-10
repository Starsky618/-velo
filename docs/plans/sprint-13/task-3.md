# Sprint 13 Task-3 — 分享卡双发起点（详情页补 onShare + source 参数）

> 所属：Sprint 13 闭环主链 / 第 3 个 task / 五环节第一环的修复。
> 上游：`docs/spec-v6.md` §3.3 / 风险 8；PRD 验收"分享卡可从两处发出"。
> 前置门：T1 已 commit。与 T2/T5 并行。**T4 未就绪时以 reportStats=null 降级（spec 已授权）。**

---

## ─────── 给 Tim 看 ───────

### 干啥用

现在只有发起人（创建完成页）能发约骑分享卡，参与者在详情页发不出去——五环节"看到分享卡"的第一环对参与者是断的。这个 task 给详情页装上转发能力，并且卡片标题带钩子：「天龙山西线约骑 · 已交卷 2/6」。

### 用户故事

老张报名了周六的约骑。周四晚上他想拉同事入伙，打开约骑详情页点右上角转发——卡片落到同事微信里，标题写着报名人数和交卷进度。同事点开直接进详情页（带口令，私圈约骑也进得来）。

### 怎么算做对了

- ✓ 约骑详情页可以微信原生转发（之前没有 onShareAppMessage，发不出）。
- ✓ 分享标题带「已交卷 m/n」，且不会出现「0/0」或「undefined/undefined」。
- ✓ 战报数据还拉不到时，标题退化为纯约骑名（不是出错）。
- ✓ 非参与者（游客视角）也能转发。
- ✓ 所有分享路径都带 source 参数，T5 的埋点才数得出"有多少人是从卡进来的"。

### 这次不做

- 不做战报页（T4）/ 不做成绩卡分享（T2 的事）。
- 不在分享钩子里发异步请求（微信平台约束：onShareAppMessage 是同步钩子，异步结果等不到弹窗）。

### 估时

0.5 天。

---

## ─────── 执行 subagent 技术细节 ───────

<details>
<summary>展开</summary>

## 1. 起手必跑

```bash
nl -ba docs/spec-v6.md | sed -n '163,166p'                          # §3.3 全文
sed -n '30,60p' miniprogram/pages/meetup-detail/meetup-detail.js     # data 块 + onLoad
sed -n '255,275p' miniprogram/pages/meetup-create/meetup-create.js   # 现有 onShareAppMessage（抄模式）
rg -n "onShareAppMessage" miniprogram/pages/meetup-detail/meetup-detail.js   # 预期为空
```

已验证事实（2026-06-11 主 agent grep）：
- meetup-detail.js **无** onShareAppMessage；meetup-create.js:260-268 有（含 invite_only 带 share_token 的模式，照抄）[✓ grep]
- meetup-detail.js data 初始化块在 :36-43，已有 `meetupId` / `shareToken`（onLoad 从 ?token= 取）/ `meetup` 字段，无 report 相关字段 [✓ Read]
- 预拉端点 = `GET /api/meetups/{id}/report`（T4 新增），取 `totals.submitted_count` / `totals.rider_count`——百用户量级 cells 最多几十行纯数字，无轨迹 JSONB，预拉不违反轻量化（spec 论证留档）

## 2. 文件改动清单

- Modify `miniprogram/pages/meetup-detail/meetup-detail.js`：data 加 `reportStats: null`；onLoad 预拉；新增 onShareAppMessage
- Modify `miniprogram/pages/meetup-create/meetup-create.js`：现有分享路径追加 `&source=share_card`（:264 path 拼接处）
- **Do not** 建战报页 / **Do not** 改后端 / **Do not** 在 onShareAppMessage 里 fetch

## 3. 行为契约（完整逻辑）

```javascript
// data 块新增
reportStats: null, // 战报统计预拉结果 {submitted_count, rider_count}；拉不到保持 null（降级）

// onLoad 里追加（在拿到 meetupId/token 之后，与详情请求并行）
fetchReportStats: function () {
  var that = this
  var url = '/api/meetups/' + this.data.meetupId + '/report'
  if (this.data.shareToken) url += '?token=' + encodeURIComponent(this.data.shareToken)
  api.get(url)
    .then(function (data) {
      // 只挑分享标题要用的两个数，别把整个战报塞进 data
      that.setData({ reportStats: {
        submitted_count: data.totals.submitted_count,
        rider_count: data.totals.rider_count,
      } })
    })
    .catch(function () {
      // T4 未上线（404）或网络失败：保持 null，分享标题降级为纯约骑名。
      // 这是 spec 授权的降级路径，不是错误——不弹 toast 不打扰用户。
    })
},

// 微信原生转发：同步钩子只读 data，禁止钩子内异步请求（异步结果不会等到分享弹窗）
onShareAppMessage: function () {
  var meetup = this.data.meetup || {}
  var title = meetup.snapshot_route_name || 'VELO 约骑'
  var stats = this.data.reportStats
  // 防 undefined/undefined：reportStats 为 null 时标题退化为纯约骑名
  if (stats && stats.rider_count > 0) {
    title += ' · 已交卷 ' + stats.submitted_count + '/' + stats.rider_count
  }
  var path = '/pages/meetup-detail/meetup-detail?id=' + this.data.meetupId + '&source=share_card'
  if (this.data.shareToken) {
    path += '&token=' + encodeURIComponent(this.data.shareToken)
  }
  return { title: title, path: path }
},
```

标题字段名已核实：`snapshot_route_name` [✓ grep app/meetup/models.py:39 + schemas，双审复核一致]；执行时仍按惯例 re-grep detail 页 setData 后的实际字段路径（meetup 对象是接口原样还是页面加工过）。

meetup-create.js 改动：现有 onShareAppMessage 的 path 拼接追加 `&source=share_card`（一行）。

## 4. 测试 / 自校验

| # | 用例 | 断言 |
|---|---|---|
| 1 | reportStats 有值（2/6） | 分享标题含「已交卷 2/6」，**非 0/0**（spec 风险 8 点名断言） |
| 2 | reportStats=null（预拉 404） | 标题 = 纯约骑名，无 undefined |
| 3 | 游客视角（未报名 + public 约骑） | onShareAppMessage 正常返回（非参与者可转发） |
| 4 | invite_only + 有 token | path 含 token + source=share_card |
| 5 | meetup-create 分享 | path 含 source=share_card |

前端协议三层自校验（wxml↔js / js↔api / setData↔wxml）逐条 grep 贴报告。

## 5. 自检（commit 前）

- [ ] `rg -n "source=share_card" miniprogram/pages/` → meetup-detail + meetup-create 两处都有
- [ ] `rg -n "api.get" miniprogram/pages/meetup-detail/meetup-detail.js` → onShareAppMessage 函数体内没有任何请求调用
- [ ] 自检三问：做了卡外的事吗 / 验收命令都真跑了吗 / 与 spec §3.3 逐条对照过吗

## 6. commit 指令

```
feat(miniprogram): S13-T3 约骑分享卡双发起点（详情页 onShare 预拉 + source 参数）
```

</details>
