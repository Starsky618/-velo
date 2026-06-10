# Sprint 13 Task-2 — 上传开奖 + 个人成绩卡（upload 页按 demo 重做）

> 所属：Sprint 13 闭环主链 / 第 2 个 task / 前端重做 + 轮询协议改造。
> 上游：`docs/spec-v6.md` §3.2 / D7；交互蓝本 = `docs/prototypes/upload-reveal-first-rider.html`（Tim 已过审：UX 吸引人，视觉留实装期打磨）。
> 前置门：T1 已 commit（成绩卡的"已交卷 m/n"数据靠 T1 的关联表点亮）。与 T3/T5 并行。

---

## ─────── 给 Tim 看 ───────

### 干啥用

把"传文件等转圈"改成"开奖"：选完文件后距离、均速、爬升逐项浮现，海拔曲线画出来，最后弹出一张比码表截图体面的成绩卡，一键发回群里。

类比：以前是把卷子塞进邮筒等通知；现在是当面阅卷——分数一项项亮出来，最后还发你一张可以晒的奖状。

### 用户故事

老张从微信聊天记录里选了码表导出的 .fit 文件（以前只能选 .gpx，现在两种都行）。5 秒内：轨迹点数往上跳 → 距离 42.3km 浮现 → 均速、爬升、最高时速逐个亮 → 海拔曲线画出来 → 成绩卡弹出，写着「🏁 本场战报由你开张 · 已交卷 1/6」。他点「发到群里，催他们交卷」。

### 怎么算做对了

- ✓ 微信文件选择器 .gpx 和 .fit 都能选到。
- ✓ 开奖动画按 demo 节奏走（逐项浮现 + 海拔曲线 + 成绩卡）。
- ✓ 解析等待 >5 秒出阶段文案，>30 秒提示"转后台，稍后在首页看结果"。
- ✓ 从战报页"交卷"按钮进来的上传，页首显示约骑名 + 已交卷 m/n，成绩卡可分享、点开落在战报页。
- ✓ 普通上传（不带约骑上下文）开奖照常，只是没有约骑横幅和战报分享。
- ✓ 真机连续传 5 个真实文件计时（T6 验收，本 task 先留好计时埋点条件）。

### 这次不做

- 不动后端解析链路（5 秒达不达标 T6 实测后才决定要不要开 D7 快路径——不为未测量的问题预建复杂度）。
- 不做成绩卡视觉精修（demo 过审结论：视觉留实装期拉设计库打磨，本期先把结构和流程做对）。
- 不做战报页本体（T4）。

### 估时

2 天，含前端协议三层自校验与三审。

---

## ─────── 执行 subagent 技术细节 ───────

<details>
<summary>展开</summary>

## 1. 起手必跑

```bash
nl -ba docs/spec-v6.md | sed -n '159,165p'               # §3.2 全文
open docs/prototypes/upload-reveal-first-rider.html       # 交互蓝本，必须真打开看一遍动画节奏
sed -n '40,60p;150,210p' miniprogram/pages/upload/upload.js
rg -n "onShareAppMessage" miniprogram/pages/upload/upload.js   # 现状预期为空
rg -n "status" app/activity/router.py | rg "router.get"   # 轻量端点确认
rg -n "GPX" miniprogram/pages/upload/upload.wxml miniprogram/pages/upload/upload.js   # 文案同步点
```

已验证事实（2026-06-11 主 agent grep）：
- `upload.js:48` `extension: ['gpx']`，改 `['gpx', 'fit']` [✓ Read]
- `upload.js:177` 轮询 setInterval 间隔 `2000`，改 `800` [✓ Read]
- 轻量端点 `GET /api/activities/{id}/status` 已存在（仅 status/error/duplicate_of），与详情端点分离 [✓ grep app/activity/router.py:247]
- 完整数据获取 `fetchResult()` 已是独立函数（completed 后单独 fetch `GET /api/activities/{id}`）[✓ Read upload.js:182-200 附近]——轮询协议"轻量轮询 + 完成后拉一次全量"的骨架已在，本 task 是把轮询目标从详情换到 status 端点 + 提速到 800ms
- 后端白名单早已收 `.fit`（`_ALLOWED_EXTENSIONS = {".gpx", ".fit"}`）[✓ grep app/activity/service.py:46]，本 task 纯前端
- demo 元素清单 [✓ Read prototype]：约骑头（约骑名 + m 人报名 · n 人交卷）→ 选文件 dropzone（文案提 .fit/.gpx）→ 开奖 theatre（轨迹点计数 → 距离/骑行时间/均速/爬升/最高时速逐项 reveal → 海拔曲线）→ 成绩卡（VELO 牌 + 路线名 + 骑手 + 六宫格数据 + 「🏁 本场战报由你开张 · 已交卷 1/6」横幅）→ 两按钮（发到群里催交卷 / 看本场战报）

## 2. 文件改动清单

- Modify `miniprogram/pages/upload/upload.js`：文件后缀 / 轮询协议 / 开奖编排 / 约骑上下文 / 分享钩子
- Modify `miniprogram/pages/upload/upload.wxml` + `upload.wxss`：开奖 theatre + 成绩卡结构（照 demo）；"正在解析 GPX 数据"等文案改成不提具体格式（fit 也适用，spec B-I2）
- **Do not** 动 `app/` 任何后端文件 / **Do not** 动其他页面 / **Do not** 新增 npm 依赖

## 3. 行为契约

### 3.1 轮询协议（spec §3.2 / B-I4 定案）

```
上传成功拿到 activity_id
→ 每 800ms GET /api/activities/{id}/status        （轻量，不拖全量轨迹）
→ status == 'completed' → 停轮询 → fetchResult() 拉一次 GET /api/activities/{id} → 开奖
→ status == 'failed'    → 停轮询 → 错误态（带 error 信息）
→ 计时 >5s：阶段文案（"正在读取轨迹点…" → "正在计算成绩…"）
→ 计时 >30s：停轮询，提示"已转后台解析，稍后在首页查看结果"
```

timer 纪律（Codex 异源审点名）：新 800ms timer 必须沿用现有模式存 `this._pollTimer`，`onUnload` 清理保留（现有 upload.js:179/240 已有正确模式，重写时不许丢）——丢了 = 用户离开页面后轮询不死 + 对已销毁页面 setData。

### 3.2 约骑上下文（跨任务契约，README 符号索引）

- 页面接收可选启动参数 `meetup_id` + `token`（T4 战报页灰格「交卷」按钮带过来）。
- 有上下文时：
  - onLoad 预拉 `GET /api/meetups/{meetup_id}/report?token=...` 的 `totals`（仅 submitted_count/rider_count 用于页首横幅与卡上 m/n）；**404/失败 → 横幅与 m/n 整块隐藏，开奖照常**（降级契约，T4 未 ship 时本页不许炸）
  - 开奖完成后成绩卡显示「🏁 本场战报由你开张 · 已交卷 m/n」（m = submitted_count+1 本地乐观 +1——**demo 蓝本明示此语义**：原型页首写「0 人交卷」而开奖后卡面写「已交卷 1 / 6」[✓ Read prototype L97 vs L137]，卡面计入自己刚交的这份；attach tick ≤5 分钟延迟是 D1 已接受的权衡，代码注释要写明）
  - `onShareAppMessage`（同步钩子只读 data）：title=「{昵称}交卷了：{路线/活动名} {距离}km」，path=`/pages/meetup-report/meetup-report?id={meetup_id}&token={token}&source=report_card`
  - 「看本场战报」按钮 → navigateTo 同路径
- 无上下文时：不显示约骑横幅 / 不注册分享到战报（用 `wx.hideShareMenu()` 或条件 return 现状行为）；其余开奖流程相同。

### 3.3 开奖编排（照 demo，数据字段以 /api/activities/{id} 真实响应为准）

- 逐项 reveal：距离 / 骑行时间（moving_time，老活动 fallback duration——现 fetchResult 已处理）/ 均速 / 累计爬升 / 最高时速；**任何缺失字段整块 wx:if 隐藏（no-dash 判例），禁止 "-" 占位**。demo 里的"消耗 kcal"若接口无此字段就不做，不许自己造。
- 海拔曲线：canvas 用 `hidden` 控制显隐，**禁止 wx:if**（陷阱 #17）；数据源 re-grep detail 页海拔图的取数方式照搬；无海拔数据整块隐藏。
- 动画用 setData 分帧 + CSS transition，不引第三方动画库。

## 4. 测试 / 自校验

- **前端协议三层自校验**（判例 frontend_protocol，逐条 grep 出结果贴交付报告）：
  - wxml 里每个 `bind*` 函数名在 js 里存在
  - js 里每个 api 调用的参数与后端 router 签名一致（status 端点无参数 / report 端点 token）
  - js setData 的每个字段在 wxml 有渲染（或注明仅逻辑用）
- 轮询协议人工走查：completed / failed / >30s 三分支各演一次（微信开发者工具 network 节流模拟慢速）
- 降级走查：report 端点不存在时（T4 未 ship）页面不炸、横幅隐藏
- 真机 5 文件计时属于 T6，本 task 交付时在报告里注明"计时入口已具备"

## 5. 自检（commit 前）

- [ ] `rg -n "extension" miniprogram/pages/upload/upload.js` → `['gpx', 'fit']`
- [ ] `rg -n "800" miniprogram/pages/upload/upload.js` → 轮询间隔已改
- [ ] `rg -n "GPX" miniprogram/pages/upload/upload.wxml` → 用户可见文案不再写死 GPX
- [ ] `rg -n "wx:if" miniprogram/pages/upload/upload.wxml` → canvas 不在其中
- [ ] `rg -n "_pollTimer" miniprogram/pages/upload/upload.js` → 存引用 + onUnload 清理两处都在
- [ ] 自检三问：做了卡外的事吗 / 验收命令都真跑了吗 / 与 spec §3.2 逐条对照过吗

## 6. commit 指令

```
feat(miniprogram): S13-T2 上传开奖重做（fit 后缀 + 800ms 双端点轮询 + 成绩卡）
```

</details>
