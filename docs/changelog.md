# VELO 开发变更日志

## 2026-06-13(二): 集合点搜索重做+UX 组件化一轮（Tim 原则：给现成组件挑，不让骑友打字）✅ 后端已部署

> **缘起**：Tim 四点拍板——①战报挂格窗口放宽 ②搜索要像高德实时联想多结果且真机不卡 ③集合地点并入编辑行、唯一路径=搜索/选点→地图确认 ④功率/均速改区间选择器；并要求按"组件挑选 > 手打文字"原则审全链路、Codex 审核开发。

**四件落地**：
1. **D2 窗口修订**（spec-v6 D2/伪码/边界表三处同步）：同北京日 → `started_at ∈ [出发−30min, 出发+6h]`（ATTACH_LATE_START_HOURS=6）。跨午夜夜骑不掉格；同日 19.5h 后的无关骑行不再误挂（旧规则两头都错）。测试三面锁：跨午夜挂/同日远程不挂/+6h 整点闭区间挂。
2. **实时联想搜索**：后端新增 `tencent_place.suggest_places`（腾讯 suggestion API，region_fix 锁城、page_index+page_size 成对、单条坏坐标只丢不炸）+ `GET /api/meetups/place-suggestions`（≤8 条，替换删除旧单结果 place-search，限流 60/5min）；前端 350ms 防抖+起搜门槛 2 字+序号作废在途响应（含清空输入/离页）。**真机卡顿根因**：onRegionChange 每次拖图都 getCenterLocation+setData 坐标回写 `<map>` 形成"拖动→回写→再动"反馈循环——已拆除，中心只在确认那一刻读一次。
3. **集合地点组件化**：编辑页整行点击进地图选点（chevron 行，删行内手填 input）；map-picker 删"位置名称"手填框（名字跟选中候选走）+ 搜索框对起点/终点/集合点全开放；常用集合点 chips 保留一点即用。
4. **功率/均速区间选择器**：POWER_OPTIONS（不限功率/120-140W…250W+）+ SPEED_OPTIONS（15-18…30+ km/h）picker 替换自由文本输入，强度档位联动默认档（PACE_DISPLAY 改为档位成员）。

**Codex 异源审（Tim 点名）**：抓 1 Critical——搜索开放给起点/终点后，WGS-84 源坐标被直接喂给只吃 GCJ-02 的腾讯路线规划（生成路线整体偏移一两百米）→ 按 kind 分流坐标系已修；另 4 Important（page_index 成对/在途响应作废盲区/spec 内部矛盾/架构与数据流文档旧端点残留）+ 2 Nit（搜索框回显/闭区间边界测试）全修。1072 passed。

**原则审计遗留（手打文字残余，待 Tim 拍下一轮）**：①报名门槛 eligibility_note 仍是 textarea → 建议 preset chips（无门槛/能跟住均速/会修补胎/带夜骑灯具…）②补给点 supply_point 仍手填 → 可同走地图选点 ③safety_note 的 SAFETY_TEMPLATES 数组在 js 里备着但 wxml 从未渲染成模板挑选、UI 还是裸 textarea（半成品）。

## 2026-06-13: "能看不能用"全模块走查——3 个已报 bug 根因全修 + 走查再挖 3 窝隐藏 bug ✅ 后端已部署

> **缘起**：Tim 报三症状（约骑编辑"下一步"PATCH 422 / 地图无搜索 / 全部轨迹图白屏）+ 拍板"彻底检查所有模块，把核心功能走一遍修遇到的 bug，velo 完全属于能看不能用的状态"。

**三个已报 bug 根因与修复**：
1. **PATCH 422 + 搜索失踪 = 同一根因"commit≠ship"**：codex 前晚 `99fdcf84`（meetup 强度提示字段+常用集合点+地点搜索，前后端+迁移）从未部署——前端发新字段、生产老 schema `extra="forbid"` 直接 422；搜索端点生产 404。部署时又踩**迁移 revision id 33 字符超 alembic_version varchar(32)**（陷阱 #23）：schema 全执行成功后版本登记炸事务整体回滚。改短 id（`a761eb9c`）后部署+迁移成功，新列在库、`place-search`/`favorite-places` 端点 401（活着要鉴权）、腾讯 KEY/SK 生产已配。
2. **全部轨迹图白屏 = drawRouteThumb 双重归一化格式断裂**（`005144cf`）：先把点转成 `{x,y}` 再传 projectTracks，后者二次归一化只认 `[lon,lat]`/`{latitude,longitude}`，全部点被当非法丢弃 → 静默画空白。codex 静态测试只断言字符串、从未真执行绘制。修复 + **wx 桩真执行回归测试**（断言 lineTo/draw 真调用，三种点位格式全覆盖）。

**全模块走查产出**（A 契约矩阵 + B 协议自校验双 subagent 并行 + 生产侧人工）：
- 前后端 65 个接口契约对全验证 **0 断裂**；路由顺序全对；js 语法/事件绑定/api 调用/canvas-id/setData 字段 5 类共 300+ 检查点 0 异常
- **挖出第 3 窝：6 处用 navigateTo/redirectTo/默认 navigator 跳 tabBar 页**（微信硬规则=静默 fail，陷阱 #24）：settings 退出登录/注销后卡死原页 ×4、home"去登录"按钮无反应、**约骑战报"交卷"跳不进上传页**。修法：switchTab + 战报上下文走 `pendingUploadMeetup` globalData 寄存柜（upload 是 tabBar 页收不到 url 参数）；新增静态守卫测试锁红线
- **挖出第 4 窝：attach tick 测试随墙上时钟随机红**（集成审顺带实锤，凌晨 01:41 三测试齐挂）：测试裸用 now() 当约骑时间，北京 00:00-02:30（CI 即 UTC 14:00-16:30）分钟偏移跨北京日。统一换 `_midday_bj_anchor()`（北京正午锚）。**附带浮出产品边缘待 Tim 拍**：规则"同北京日才挂战报"意味着 23:30 出发的夜骑、骑友 00:05 动身则格子永远灰（清徐夜骑场景真实存在）
- 删未注册死文件 segment-explore.bak.js（含 search min_length 422 隐患）
- 生产巡检：11 容器全 Up / worker 正常监听 / api 日志干净

**验证**：1069 passed；集成审 2 轮（大合并批 Critical=0/Important 2 修，走查批 Critical=0/Important 2 修）。

**待 Tim 真机复验清单**：①约骑编辑"下一步"进确认页 ②map-picker 搜地名出结果 ③路线详情/活动列表/约骑列表轨迹缩略图显形 ④个人页热力图 ⑤战报"交卷"跳上传带横幅 ⑥退出登录回"我的"页。

## 2026-06-13: 地图无法显示根因定案（个性化底图=付费能力）+ 地图免费化架构大合并 ✅

> **缘起**：Tim "地图功能总是无法正常显示，codex 做了好几轮全失败"。systematic-debugging 走完取证：**根因不在代码在商务层**——微信官方文档明文"自 2023-06-29 0 点起，该能力【个性化地图】需要先购买再使用"，入口在微信公众平台-付费管理。velo 只在腾讯位置服务控制台做了建 key/调样式/绑定/授权 AppID（`fb2052ad`→`b86185a5` 修的就是这半套），**微信侧付费能力从未购买** → subkey 挂上 `<map>` 真机鉴权必失败、地图卡死。codex 前几轮全在改代码中间链路所以注定失败；其最后一轮（剥 subkey + canvas 自绘）方向正确，一直躺在工作区没合并。

**本次合并内容**（codex 最后一轮 WIP + Claude 审计收尾 + 实景图前端三件）：
- **地图免费化架构定案**：装饰性展示（路线缩略/热力图卡）→ `utils/route-thumb.js` canvas 自绘纸面+橙轨迹；交互性地图 → 免费默认底图（map-picker 选点 + 新增 `pages/route-map/` 全屏查看页，经 `utils/route-map-nav.js` globalData 寄存跳转）；**全工程 `<map>` 禁传 subkey/layer-style**。
- **Claude 审计收尾**：3 页 data 里的死配置 `getPaperMapData()` 注入清除（wxml 已零消费，留着诱导未来 agent 重新接 subkey）；map-theme.js 拆除个性化底图机器，文件头焊死付费教训；静态测试换新契约 + **新增全局红线守卫**（任何 wxml 出现 subkey/layer-style 即 fail）。
- **实景图前端三件随合并落地**（上一段挂账销账）：route-detail hero 图文融合 + 实景图横滑长廊 + wx.previewImage。
- 陷阱清单 #22 已沉淀（CLAUDE.md）：第三方能力真机故障先查官方文档"开通条件/收费政策"，再动代码——调试硬规则 Step 2 又一实证。

**遗留**：纸面底图想复活 = Tim 在微信公众平台-付费管理购买个性化地图（按量付费）后填回 subkey，纯商务决策零代码改动；当前免费方案待 Tim 真机验收。

## 2026-06-12: 路线百科实景图链路（38 张图上线 + Tim 访达自助增删 + hero 图文融合）✅ 后端部署生产 + 图已灌库

> **缘起**：Tim "明明大多数路线 html 介绍中都有一堆实景图，可现在这些图都不在真机里"。HTML 卡时代策划的实景图一直锁在 route-workspace / base64 里，没接进小程序管道。

**做了什么**（后端 `4327400c` + 保活修复 `99344dce` + 内容 `27ae955a`）：
- **内容约定升级**：`content/routes/<路线>/` 里 cover 开头的图片是封面（不变），**其余图片按文件名排序全是实景图**——Tim 访达扔图/删图 + 双击发布即生效，meta.json 指针由脚本自动维护（README 已更新）。
- **新基建 `scripts/sync_route_images.py`**（带 6 测试）：扫图 → 写 meta 指针 → 备 staging。服务器名 `gNN_内容哈希8位.ext`（**换图必换 URL**，小程序图片缓存天然失效）；过滤 `._` AppleDouble/隐藏文件/符号链接（Codex 异源审抓的访达伴生破图防线）。
- **DB/API**：`route_guides.gallery_urls` 可空 Text 列（迁移 `20260612_route_guide_gallery`）；详情端点返回数组、列表端点不返；`_json_list` 坏数据降级不 500。
- **初始搬运 38 张**：10 条路线的 route.json 策划图（超 1MB 的 sips 压 1600px JPEG）+ 天龙山 3 张从 v11 HTML base64 解码。狼坡/奥申 0 张维持缺图挂账。
- **前端**（route-detail，**未 commit**——与并行会话"路书作品化"线程共享文件，等那边落地后一起收）：hero 图文融合（520rpx 出血 + 底部 140rpx 小面积渐变淡入 + 标题上提坐进淡出区，Tim 拍"渐变面积要小"）+ 实景图横滑长廊（scroll-view + wx.previewImage 全屏翻页保存）。
- **发布脚本健壮性**：staging trap 清理 / docker cp 子目录注释 / 空 glob 守卫 / 迁移前置条件注释 / ssh-scp 保活 60 秒（首跑实证：远端全部完成后本地 ssh 僵挂 13 分钟）。

**验证**：三审归零（双审 6I + Codex 3C/2I 全修）；1055 passed；生产 curl 逐条核对 11 条路线 gallery 数全对；静态图 HTTP 200 image/webp 实测；docker cp 目录合并行为实测正确。

**数据回看**（ship 后 1 问）：实景图被看 = 详情页打开即加载，看 Caddy 日志 `grep route_covers` 量级即可；2026-06-19 回看一次（无埋点端点，路线详情 SENSOR 行待 S15 统一补）。

## 2026-06-12: 全 app UI 苹果方案重构收官（五批 / Tim 逐批真机过审 / "很不错"）✅ 已 push main + 后端部署生产

> **缘起**：Tim "前端真的很丑，忍了很久"。历经五轮原创设计语言探索全部被否后定案**苹果方案**（趴 Apple HIG + 系统橙 #FF9500，零原创——真相源 `miniprogram/design-system/MASTER.md` v0.4，逐批进度账在 §8）。本段只记收官全貌与教训，单批细节见 MASTER §8 + 各 commit。

**五批 ship 轨迹**：①探索页/路线详情/home（方向定案 + token 层总阀 + 22 页旧色清零）②路线详情常显数据卡+海拔缩略线 / meetup-detail 白卡化 / detail 图表 iOS 五色 ③约骑六页+profile 全量重构 `1c58547a`（create 废"红色原型×0.879"整套：#ff1744×20+、13-19rpx 蚂蚁字=真机字小根源；编辑/确认步小 `<map>` 换 canvas 自绘轨迹=位置冲突 bug 根除；列表卡嵌轨迹缩略后端零改动）④upload 夜场退场（全 app 最后旧语言飞地）+ detail 深 hero 白卡化 + tabBar 5 png 重着色橙 + Tim 填 subkey 激活纸面底图 `b86185a5` ⑤"我的"页四件套 `eafceff2`：统计卡本周|生涯切换（period=all 零后端）/ bio 移设置页 / settings iOS inset-grouped 重构（六家骑行 App 官方文档调研定稿；**不做假功能**：单位/多语言/深色/缓存清理均无底层支持或微信统管）/ 活动列表 iGPSport 式轨迹缩略图（唯一后端增量：新只读端点 `GET /api/activities/track-thumbs`，simplified_track 抽稀 ≤60 点 owner-only，TDD 5 测试，已部署生产 curl 401 验证）。

**新基建**：`utils/route-thumb.js`（canvas 画"路线形状"非地图，⚠ wxss rpx 与 js 绘制 px 必须 2:1）+ `utils/ride-thumbs.js`（轨迹点批量拉取+模块级缓存）——约骑列表/创建缩略/活动列表三处共用。

**本场教训（复盘三问）**：
1. **新 bug 模式**：`tests/` 有静态断言前端文件内容的测试（图表色板）——"纯前端改动跳过 pytest"的惯例不成立，第④批漏跑导致陈旧断言滞后一批才发现。**以后前端-only commit 也跑全套 pytest（8 秒）**。
2. **设计判断**：原生组件（map）做小尺寸缩略图是结构性错误（层级盖按钮+抢手势+不受 overflow 裁剪），canvas 自绘是修法不是妥协；产品层"假开关"=表面信号≠真实结果（深色模式开关没有暗色样式支撑 = 喇叭没插电源的 UI 版）。
3. **流程**：真机验收链路必须说清改动处于哪一环（本地模拟器 → 预览扫码 → 上传体验版），"改完了"≠"Tim 手机能看到"——教训已焊进任务卡顶部。

**剩余挂账**（MASTER §8）：水印分享功能实现（形态已定）/ 首页 feed 形态（产品层另议）/ 设置页"活动默认可见性+隐私区域"（需后端字段待拍）/ segment 系长尾布局。

## 2026-06-03 → 06-05: 发起约骑新原型（接口/字段 + 私圈口令 + UI 逐像素还原 + 流程重排）✅ 已部署 + push main

> **缘起**：Codex 出了两张高保真 HTML 原型（四步向导发布页 + 发布前总览页），把"发起约骑"做成真正好看好用的入口。
> **特点**：完整走了 设计文档(三审 + Codex 异源审) → 6 task(Codex 写 / Claude 异源双审) → 部署 → UI 还原 → 流程重排 全流程。head `aefd411`。

**后端（已部署生产 / 迁移 `20260603_meetup_create_fields`）**：
- `meetups` 加 6 列：`supply_point` / `audience_tags`(sa.JSON) / `visibility`(public/invite_only + CHECK) / `eligibility_note` / `safety_note` / `share_token`（双默认值防 ORM 插入写 NULL）。
- **私圈口令门禁**（核心安全）：`invite_only` 约骑的 详情/join/participants/media 必须带 `?token==share_token`（creator/已加入者豁免），否则 **404**（防猜连号 int id 闯私圈）。token 比对用 `secrets.compare_digest` 恒定时间。
- 新增 `GET /api/meetups/{id}/participants`（JOIN users 返回骑友昵称/头像，正向依赖）。
- `publish` 加出发前 30min 截止校验（进截止窗的草稿不许发布）。
- `update_meetup` 字段白名单扩展（防 PATCH 静默丢新字段）；`list_meetups` 加 `visibility='public'` 过滤（owner 的 mine/my-draft 不过滤）。

**前端（commit + push main，待 Tim 重新上传小程序）**：
- 逐像素还原两张原型：步骤圈三态指示器 + **16 个 lucide SVG 图标**（按原型描边色烘色存 `miniprogram/assets/icons/meetup/`，小程序 `<image>` 渲 SVG）。
- **流程重排（Tim 拍）**：选路线 → **图二就地编辑**（时间 picker / 集合·补给·说明 input / 人数加减器 / 节奏 picker / 照片网格全可编辑）→ **图一总览确认**（适合谁 pill / 可见范围盒子 / 门槛 / 安全模板 / 骑友）→ 发布。旧 details/media/publish/preview 步合并删除，改 route/edit/confirm 三步。
- 草稿懒建（加照片/下一步时落库，先校验集合点）；出发时间变自动顺延结束 +3h；微信原生转发邀请（invite_only 链接带 share_token）。

**翻车教训（2 次返工）**：① 我把"接口/逻辑设计完"当成"做完"，**没一开始讲清"原型→小程序保真是独立一大块工作"并纳入 scope** → Tim 真机看到朴素表单才发现。② 静态测试只验"字段在不在"、不验"像不像/顺不顺" → 绿灯给了虚假安全感，**视觉+流程必须真机对照**。详 [[feedback_design_done_not_equal_ui_shipped]]。

**设计文档/计划**（已 commit）：`docs/superpowers/specs/2026-06-03-meetup-create-prototype-design.md` + `docs/superpowers/plans/2026-06-03-meetup-create-prototype.md`。

## 2026-06-02: 约骑创建照片步骤 + 注销账号 + tech-debt 清理 ✅（全程 Codex 异源审）

> **特点**：补足约骑创建体验 + 上线账号注销（合规）+ 清约骑遗留 tech-debt。这几项都是 Claude 自写，
> 吸取上一轮教训**全部补跑了 Codex 异源审**（原则 8：自写代码也必须异源审）。

- **约骑创建加"照片"步骤**（`41f08f1`）：选路线→填详情→**加照片**→发布（之前只能发布后补图）。details→media 转场先存草稿拿 id，照片挂草稿上。Codex 异源审抓回归：从骑行生成路线退回再前进会重复建路书留孤儿 → 缓存 `generatedRouteBookId` 复用。
- **格式化函数三页去重**（`46b1d30`）：list/detail/mine 重复的 formatTime/paceText/formatDistance 等抽到 `miniprogram/utils/meetup-format.js`。刻意和通用 `utils/format.js` 分开（后者 formatTime 是秒数→时长，约骑是时间戳→"6月2日 14:30"，同名不同义）。
- **注销账号**（`9907480`）：Tim 拍"彻底物理删除全部个人数据"。`delete_user` 扩成完整级联删（按外键安全顺序删 efforts/breakthroughs/strava/activities 再删 user，旧版只删约骑会被外键挡住 500）+ 新端点 `DELETE /api/user/me`（JWT 锁本人）+ 设置页两步确认入口。Codex 异源审 I1：breakthrough_events.activity_id 也 RESTRICT，按 user_id OR activity_id 双向兜底删防脏数据。OPEN 约骑取消保留、路书置无主（有意决策）。全量 927 passed。
- **文档/tech-debt 清理**（`040d530`）：架构·数据流 guide 补约骑章节（修子 agent 脑补路由总数 61→81）；tech-debt 删已完成项（删号端点/format 去重/guide 章节）。
- 部署：后端 rebuild + curl 验证（DELETE /api/user/me 无 token 返 401）。前端本地重新编译已确认可见。

## 2026-06-01: 约骑模块 task1-9 实施 ship + 取消/个人页/照片墙 + 隐私修复 + Codex 异源审补审 ✅（已合 main + 部署生产）

> **特点**：约骑 design/plans（5-29）落地。Codex Desktop 写 task1-9，Claude 逐 task 异源双审 + 修 bug。后续补取消/个人页/照片墙（Claude 自写），**合 main 后补跑 Codex 异源审抓出 7 隐患并修**。现行 head `322510c`，生产已部署。

### 实施 + 复审（task1-9）
- task1 建表 / task2 路书 / task3 约骑生命周期 service / task4 约骑 API / task5 加入退出（FOR UPDATE 防超员）/ task6 媒体墙 / task7 cron 自动完成 + 删号 hook / task8 赛段页 upcoming-meetups / task9 小程序 3 页
- **Claude 双审抓的 bug（Codex 写、Claude 修）**：task4 详情人数恒 0 / task5 错误码回归（共享门卫 CANCELLED→410 污染 delete/update）/ task6 删媒体后首图口径分裂 + 序号撞号 / task7 `delete_user` 用 `with db.begin()` 接端点必 500（autobegin / 见技术栈陷阱 #21）/ task9 时间输入文本框敲 ISO（改 date+time picker）+ `--` 占位符违规
- codex 系统性盲区观察：单点逻辑/算法/安全扎实，但跨端点一致性、共享代码影响、事务边界反复漏（task4/5/6/7 一致）

### Tim 真用回归驱动的后续
- **距离单位 bug**：约骑快照抄赛段距离漏 米→km，详情显示"10049 km"（实为 10km）。出口 `round(/1000, 2)`
- **约骑 tab 入口**：task9 漏了 tabBar，补底部"约骑"tab（占位 leaderboard 图标**待换**）+ 列表 onShow 刷新
- **发起人取消 + 详情角色按钮**：详情接口加 is_creator/has_joined（可选登录）+ 前端按身份显示 取消/退出/加入（保留出发前 30min 截止）
- **个人页"我的约骑"**：profile 入口 + 两 tab（我发起的含草稿 / 我加入的排除自己发起）+ 后端 `GET /api/meetups/mine`
- **照片墙**：详情页展示/上传/删除 + caddy 静态服务 + body 55MB 限制

### 隐私 Critical 修复（Codex 异源审抓 / Claude 双审漏）
- caddy 原 `handle /uploads/*` 把整个 uploads 卷（混着所有人私密 GPX 轨迹）当静态文件公开 → 绕过隐私判断泄露轨迹。改 `handle /uploads/meetup_media/*`，照片存 `meetup_media/` 子目录与 GPX 隔离（`81d5d54`）

### Codex 异源审补审（`322510c` / 补 CLAUDE.md 原则 8 漏跑的第三审）
> 取消/个人页/照片墙是 Claude 自写仅 Claude 自审，漏了 Codex 异源第三审。补两路审 + 一轮复查，抓 7 issue：
- **`/api/meetups/mine` is_creator/has_joined 永 False**（漏传 current_user_id）→ 个人页卡片按钮状态全错。按 role 批量置标记（无 N+1）
- **media 上传孤儿文件**：storage 成功但 commit 失败无补偿删除（陷阱 #14）。加 try/except 补偿
- **`_safe_path` startswith 同前缀绕过** → 改 commonpath；upload 加 subdir 白名单
- 前端：照片墙加载失败静默吞（误显示"还没有照片"）/ uploadFile `JSON.parse` 未兜底致上传 loading 卡死 / meetups-mine 切 tab 时下拉刷新圈卡死（复查抓的回归）
- 生产验证 `meetup_media` 0 行 → 隐私修复无老路径媒体，不需迁移

### 部署
- 合 main（`de7e21c` 起）+ alembic 建约骑 4 表 + `docker compose up -d --build` 全量 rebuild + curl 验证（list 200 / mine 401 / 根 GPX 404 不外泄）。**反代是 caddy 不是 nginx**
- 遗留 → `docs/tech-debt.md`（format 函数 3 页复制 / 正式约骑图标 / 删号端点接通 / 架构·数据流 guide 待补约骑章节 / 真机图片需 https 域名）
- 遗留 → `docs/tech-debt.md`（format 函数 3 页复制 / 正式约骑图标 / caddy 上传大小限制 / 删号端点接通 / 架构·数据流 guide 待补约骑章节）

## 2026-05-29: 约骑模块 brainstorm + spec v1.8 + plans 4712 行 ship gate ✅（代码未实施）

> **特点**：仅 brainstorm + spec + plans 三阶段完成 / **代码待 Codex Desktop 一气呵成实施 task 1-10**。velo v5 社交主线模块设计 + 元层 reviewer 工程升级。

### design doc v1.8（8 轮三审收敛 / commit chain `89f71f2` → ... → `3349ae8`）

**主轴**：velo v5 社交主线约骑模块设计 / Critical+Important=0 ship gate 达成 / 文档 530 行。

- **v1 范围**：5 个功能（约骑活动 CRUD + segment 下拉 + 路书 GPX/FIT 上传 + 路线详情页约骑入口 + 媒体）/ ~16.5 天工程量 / 跨 3 sprint
- **架构决策**：新建 2 模块 `app/meetup/` + `app/route_book/` / 防火墙隔离不动核心表 / **微信小程序备案约束 → 砍所有用户互动**（私信/关注/评论/点赞/打招呼）/ 路书复利原则（默认公开 / 不参与 KOM 排行 / 防野鸡 KOM 污染）
- **关键产品决策**：路书 = 用户自建图纸 ≠ segment 精选赛段 / 状态机 `DRAFT → OPEN → (CANCELLED | COMPLETED)` / 出发前 30 min ±30s 截止报名+退出+取消 / 满员抢位 FOR UPDATE + populate_existing
- **新表**：4 张新表（meetups + meetup_participants + meetup_media + route_books）+ partial unique on `creator_id WHERE status='DRAFT'` + 复合 CHECK on route_books（**方案 B**：service 层补 source_activity_id 校验 + DB 允许孤儿态 = 防 FK ON DELETE SET NULL 与 CHECK NOT NULL 死锁 / Tim 拍）
- **路书 2 种创建**：上传 GPX/FIT（复用 `app/parsing/gpx_parser.py` + `fit_parser.py` 现有解析器）+ 从已骑活动衍生（trackpoints 反向转 LINESTRING / 含 IDOR 校验）
- **反向 hook 2 处明确标记**：`app/user/service.py` 新增 `delete_user`（hook 顺序：先 cancel OPEN → 硬删 DRAFT → 删 user）+ `app/segment/router.py` 加 `/api/segments/{id}/upcoming-meetups`（spec §15.2 含删除 SOP）
- **复盘**：项目级既有依赖漂移 surface（CLAUDE.md 声明"User ← Activity"但 `app/user/` 已反向 import `app/activity/` 7 处 / Sprint 9+10 训练分析引入 / 属项目级治理待办）

### Codex Desktop ship plans 4712 行（commit `d8e610d`）

- 1 README + 10 task 卡 / `docs/superpowers/plans/2026-05-28-meetup-module/`
- 2 轮异源审 Critical+Important=0
- 验证全跑：禁词 grep 空 / DAG 无循环 / file:line 实证 / task 结构（Files / TDD / Steps / Self-review / Commit）全过
- **遗留**：README + task 卡英文（Codex 没遵守项目 §2.3 中文规则 / Tim 拍接受不重写 / 后续如阅读单独翻 README）

### 元产出：reviewer 工程升级（commit `999a948`）

**最大教训**：Tim 一次抽查发现 reviewer 12 次漏抓反向依赖 = **reviewer 工程系统性盲区**（不是 spec 设计差 / 8 轮收敛主因）。

升级清单（跨平台 / `~/.claude/`）：
- `reviewer-integration.md` Step 2.1-2.6 加强制 grep 清单（反向 import + 正向 import + 循环 import + 模块删除假想 SOP + 项目声明 vs 真 grep 漂移）
- `reviewer-spec-faithful.md` Step 7.5 加架构层双保险
- `docs/agent-rules/agent-collaboration.md` §4.0.1 项目级 grep 强制清单

**Codex 异源价值再次实证（Round 6 FK+CHECK 死锁）**：Claude 双 reviewer 12 轮全漏 schema 联动 race / codex 抓出 / 该死锁 = `source_activity_id` 字段 ON DELETE SET NULL + CHECK NOT NULL 互斥 → activity DELETE 失败 / DB 级死锁。

新 memory（3 条 / 详 MEMORY.md 索引）：
1. `feedback_wechat_miniprogram_no_direct_social` — 微信备案约束硬规则
2. `feedback_spec_bug_fix_before_plans` — spec Critical+Important=0 才进 plans
3. `feedback_reviewer_must_grep_dependency` — reviewer 必强制 grep 架构层依赖

### 收敛 stats

```
Round    1   2  3  4  5  6  7  8
Critical 7   2  0  0  0  1  0  0 ✅
Imp     13  10  9  2  5  0  1  0 ✅
```

每轮抓到的真问题（不是为找而找）：R1 IDOR/媒体上传顺序倒置 / R2 cron 实现细节 / R3 storage 签名 / R4 我 §15 文字事实错（service.py vs service_stats.py 张冠李戴）/ R5 main.py 挂载漏（codex 抓）/ R6 FK+CHECK 死锁（codex 抓）/ R7 字段表 markdown 被切。

### 下一步（不在本 changelog 范围 / 等代码实施完再单独入条目）

- Codex Desktop 一气呵成实施 task 1-10（不走 subagent-driven-development / 防同源审 + task-09 842 行 MCP 卡死风险）
- 完成后回 Claude 派 reviewer 异源审整 sprint commit
- ship gate Critical+Important=0 → 部署 + 真用回归（8 类 hot spot / 含满员抢位并发 / activity_derived 路书 LINESTRING / partial unique 并发 / admin 删 segment 后 snapshot 展示 / DRAFT 删除 storage 清理 / scheduler 双 tick 互不拖死 等）

---

## 2026-05-28: 单次骑行功率曲线分析 + 工程基础设施升级 ✅

### 用户可见新功能：单次骑行功率曲线分析

**commit 链**：`4a03f60`（Codex 写原始功能）→ `f49a365`（三审收敛重构 / 抽 power_curve.py + timeseries.py）→ PR #1 → merge `e9ddcb3` 到 main → 生产部署完成 + 真机回归通过

**做了什么**：详情页加独立卡片"**功率曲线分析**"——回答"这次骑行任意持续时长下最强的一段是多少 W？"
- 滑动 canvas 看任意持续时长 / 手指停住触发精确秒级查询
- 2 个新 endpoint：`GET /api/activities/{id}/power-curve`（智能抽样曲线 / 1000 点上限）+ `GET /api/activities/{id}/power-curve/effort?duration_sec=秒`（精确读数）
- 1 个新前端组件：`miniprogram/components/activity-power-curve-card/`（自请求 / 自画 canvas / 父页面只传 activity-id）
- 隐私门禁：owner 永远看全 / hide_power=true 时他人看到"像没装功率计一样"空响应

**抽取重构**（service.py 1063 → 665 行 / 出红灯）：
- 新文件 `app/activity/power_curve.py`（256 行 / 纯函数 / 不查 DB）—— 含 DurationOutOfRange 异常类 + 10 个纯函数
- 新文件 `app/activity/timeseries.py`（203 行 / 纯函数）—— 把 timeseries 路径 7 个纯函数从 service.py 抽出 / `_haversine` 改用 `geo_math.haversine` 兑现 DRY / 与 power_curve.py 共享 `_sample_indices`
- service.py 现在只剩 DB 入口 + 隐私门禁 helper（业务总账房 / 职责统一）

**三审收敛**（两轮 6 reviewer / Claude A spec-faithful + Claude B integration + Codex 异源）：第一轮 4 Important（红灯 / 中文子串路由 / hide_power 共享逻辑 / forward reference）+ 第二轮 4 Important（init.py 漏列 / DurationOutOfRange 引用风格 / duration<1 前置校验对称 / _haversine DRY 复用）/ Critical=0 / 全修。

**性能 hot spot 记 tech-debt 等触发**：长骑行（>4hr）`_build_power_curve_result` O(N×D) ≈ 1440 万次循环估算阻塞 worker 2-4 秒 / 100 用户量级低概率触发 / 真出现再优化。

### 工程基础设施一组

- **CI workflow（commit `951e5b8`）**：`.github/workflows/test.yml` / 每次 push + PR 自动跑 pytest 兜底"忘跑测试就 commit"。OAuth App scope 限制踩坑 → 通过 `gh auth refresh -s workflow` 加 workflow scope 解决 / 第一次 CI 跑 50 秒全过。
- **DB 异地备份**：发现 velo 早有 Sprint 5 task-1 的 `db-backup` 容器（每天 23:05 写 ~/velo/backups/ / 保留 7 天本地）→ **加 COS 异地兜底**：`~/scripts/backup_db.sh` 改成"镜像本地 backups/ 到腾讯云 COS daily/" + host crontab `30 23 * * *` 紧跟 docker 备份 25 分钟后跑 / 保留 30 天 / S3 协议接入（转云时只改 2 个 export 行）。COS bucket = `velo-db-114514-1421559057`（广州同地域内网）/ 凭证 `~/.cos_backup_creds` chmod 600 / CAM 子账号 `velo-backup-writer` 带 QcloudCOSFullAccess。**恢复演练通过** / 5 关键表 row count 完全一致。
- **fail2ban**：服务器装好 + 启动 + 开机自启 + sshd jail 监控 /var/log/auth.log / 默认 maxretry=5 / bantime=10min。
- **deploy-sop.md DEPLOY-7（commit `8a14df6`）**：服务器 deploy 完后必跑 `cd ~/Desktop/velo && git pull` 同步本地工作树 / 否则微信开发者工具读旧 miniprogram → 用户报"完全看不到" 30 分钟绕路。
- **tech-debt.md SRTM 降级 P2（commit `575cb62`）**：识别"velo 用户都是气压计码表 + 当前 SRTM 90m 替换是降级"的设计盲区 / Sprint 12 教练引擎想用精确海拔曲线时必修。

### 元产出（5 条 memory + 复利兑现）

session 实证踩坑 + 元反思沉淀 5 条 memory（详 MEMORY.md 索引）：
1. `feedback_ignore_phantom_commits_other_threads` —— 本地 ahead 的非本线程 commit 视为别人的事
2. `feedback_deploy_must_pull_local_worktree` —— deploy 完必须本地 pull（已升级 deploy-sop DEPLOY-7）
3. `feedback_pre_build_must_grep_server_state` —— 建新基础设施前必跑 5 项 grep（防重复造轮子）
4. `feedback_user_pushback_framework_4_questions` —— Tim 自己 push back AI 的 4 问框架（3-of-4 yes 才做）

**复利兑现**：5 项 grep 规则一立刻挡掉了 staging 类重复造轮子 + 让 Tim 学会"真问题 vs AI 完整性 itch"的杀手锏判断 / staging + 飞书告警都被 4 问筛掉等触发。

**重大失误复盘**：本 session DB 备份事故损耗 Tim ~90 分钟陪我创 COS bucket / CAM 子账号 / 测试 / 演练 → 后期才发现 velo 早有 `db-backup` 容器 ship 2 周。根因 = 我没 grep docker-compose.yml 就脑补"velo 没备份" / 触发 Tim 怒怼"我操你妈"+ 元反思 4 问框架。沉淀规则防再犯。

---

## 2026-05-26: Sprint 11 训练分布分析 ✅（模块 C / 真机反馈驱动多轮迭代）

**主轴**：训练分布（Polarized / Pyramidal / Sweet Spot / Threshold / Mixed 五类型）上生产 / Codex 主写核心 + Claude 异源审 / Tim 真机反馈驱动多轮增量，最终收束为默认不计 0W 的单一展示口径。

**7 commit 链**：
- `7426b6e` feat：训练分布核心（Codex 主写 / 纯函数 distribution.py + service + `GET /api/training/distribution` + 小程序页 + 75 测试）
- `5e2b576` fix：Claude 异源审收敛（aggregate 去重复 normalize + 不足态文案断言）
- `c17bec4` feat：task-6 排滑行 0W 开关 + 历史回填脚本（power_zones 记 Z1.zero_seconds / exclude_zero 只扣展示口径不碰分类 / snapshot_ftp 重算避免污染历史区间）
- `907ecf4` feat：v2（门槛 3→2 + sweet_spot 动态百分比 + 圆饼图 conic-gradient + 数据不足态补开关）
- `77dca05` feat：全 5 类型 explanation 动态百分比
- `05338fc` fix：按 Sprint11 demo 精修训练结构 UI，饼图右侧直接展示 Z1-Z6；活动详情页默认按真实蹬踏时间展示功率区间
- `93e820e` fix：训练结构页删掉 0W 开关，前端 / router / service / 纯函数默认统一不计 0W；`exclude_zero=false` 仅保留为旧口径兼容和测试通道

**真机反馈驱动迭代（产品打磨范例 / Tim 每次真机一看就暴露一个真问题）**：
1. Z1 占 79% 被滑行 0W 灌水 → 加"不计滑行/停顿"开关（只扣 Z1 展示 / 分类分母本就剔除 Z1 不受影响）
2. 历史活动开开关无效果（老 power_zones 无 zero_seconds）→ backfill 重算 184 条
3. 卡在"数据不足"（最近 6 周仅 2 次有功率 < 3 条门槛）→ 门槛 3→2（3h 时间门槛兜底）→ 解锁 Pyramidal 分类
4. 数据不足态看不到开关 → 补到不足态 + 圆饼图
5. 要 demo 那种动态百分比 → 全类型 explanation 嵌真实占比 + conic-gradient 圆饼图
6. 开关影响的 raw_zones 埋得太深，用户视觉上像"按钮无效" → 饼图右侧直接展示 Z1-Z6 秒数/百分比
7. 产品口径最终收束：所有功率区间分析默认不计 0W，不再把"含不含 0W"交给用户选择

**backfill 184 条**：本地无真 DB（velo 既定架构 = 本地 SQLite 测试 / 真数据只在生产容器）→ dry-run + apply 都在生产 api 容器内跑 / 默认 dry-run gate / 0 失败。

**生产验证**：服务器已部署到 `93e820e`。Tim user_id=2 → data_complete=True / current_type=pyramidal / 耐力 60% · 中强度 31% · 高强度 9% / explanation 含动态数字。部署后 curl 验证：默认响应等同 `exclude_zero=true`（total=11243 / Z1=5002），显式 `exclude_zero=false` 保留旧含 0W 口径（total=24479 / Z1=18238），groups 不变。

**异源审实证**：Claude 审 Codex 写的核心 + task-6 / 自己写的 v2 也派双审（防长会话末端疲劳）/ 多轮 Critical=0 / 抓 5+ Important（双重 normalize / backfill 缺口 / 门槛文档漂移 / 圆饼图 round 白缝 / 文档仍写开关）全修。

**遗留 follow-up**：① 小程序待 Tim 用微信开发者工具上传发布（服务器部署不会自动发布小程序包）② 发布后真机复核圆饼图 conic-gradient；若旧设备白块则换 SVG ③ tech-debt 记 2 项 P3（range 死防御 / activity_type 索引）。无新 alembic 迁移（power_zones JSONB 加字段不需迁移）。

---

## 2026-05-25: Sprint 10 PMC 训练负荷曲线 ✅（双主驾协作里程碑 / Codex Desktop 首次主写代码）

**主轴**：模块 B 训练负荷曲线（CTL/ATL/TSB）上生产 / 同时验证"Codex Desktop 主写 + Claude 异源审"分工。

**协作机制突破（本 session 元产出 / 比代码更重要）**：
- **plans 派 Codex Desktop 原生写**：B 对照实验实证 Codex 写 task-1 plan 抓 Claude 漏的 2 Critical（migrations/env.py import + conftest fixture）→ 工作流升级"通道决定行为"（Codex Desktop 原生 OK / Claude Code 插件写大文档 ban）
- **代码首次 Codex Desktop 主写全 6 task**（2669 行）+ Claude 异源审读真 diff 抓 2 Critical（canvas 陷阱 #17 重现 / 参数名偏离 plan 合同）+ 5 Important / Codex 自跑 6 reviewer 全漏 → 印证异源审是必须不是 nice-to-have
- **Tim 介入从 20 次砍到 ~4 次**：mega-brief 一次 copy + Codex 串行跑 + Claude 4 reviewer 并行审 + 后台监控自动触发

**commit 链**：`f6ff00d`（6 task 实施）→ `a514881`（双审 fix 2C+3I）→ `b400c60`（round 统一）→ `2292048`（覆盖率门槛）→ `21cebb4`（覆盖率按 range 联动）→ `3c24dd1`（图表人话解释）

**dry-run 真用回归救场**：Tim 账号最近 42 天功率覆盖率 11.1% → CTL 失真 4.8（真实应 40-70）/ TSB -116 → Tim 拍覆盖率 < 50% 不展示 PMC（跟砍 max_gradient 同判断 / 防鬼图）。分阶部署（dry-run 先看）让鬼数据卡在生产门外。

**部署全链路**：push → rebuild 所有容器 → alembic 真 PG（idx date DESC + CHECK + FK 全对）→ 回填 1493 天 → 覆盖率门槛验证 → 真机"⚡功率数据不足"

**收尾修正**：原 P2“覆盖率固定 42 天 / 全年被一刀切挡”已改成按 range 判断；训练分析页也补了“绿线/黄线/蓝线怎么看”的用户提示。Sprint 10 不再有阻断项，后续只做真实用户观察。

**测试**：733 passed / 0 fail

---

## 2026-05-23 → 25: 双主驾协作机制系统化 + dev-guide HTML 升级正式版 ✅

**主轴**：从"dev-guide.md 老了 / 看不懂架构"出发 / 走通"Claude × Codex 模块化协作 + cross-project 复用 pattern" / 收尾把 dev-guide markdown 升级 HTML v4 七 tab 正式版。

**6 个 commit 完整链**：

- `0d55eb9` feat(agent-collab): §10.Y 任务路由表 v1 + hook 关键词触发自动注入
- `ef4f2e1` feat(agent-collab): §10.Y v2 双端对称 hook（.codex/hooks.json 新建）+ 借鉴外部 AI Coding 文档（角色画像 / 决策三轴 / 5 字段速查）
- `ee9587c` feat(hook): D 方案 4 通道动态注入（路由 / 模块 / PRD / SOP）+ SessionStart 精简兜底
- `7d5aff6` docs: 双主驾协作认知闭环产出（dev-guide-demo + task skill spec + Codex Sprint 10 原型）
- `3b68b12` docs(dev-guide): 升级正式版 HTML v4 替代 stale markdown（mv + rm + README:245 改）
- `80f77e4` docs(dev-guide): 补 v4 Tab 6/7 内容（3b68b12 漏 stage 修复）

**核心设计沉淀**（cross-project reusable pattern）：

- **§10.Y 双主驾分工原则表 v2**：角色画像（Codex 任务执行器 / Claude 结对同事）+ 决策三轴（歧义 / 可测 / 可回滚）+ 10 类任务路由 + Codex 反指标 3 条 + 派 Codex 5 字段 issue 速查 + Tim 主权条款
- **三层架构**：~/.codex/AGENTS.md（精简规则）+ Hook（动态 4 通道注入）+ Skill（完整工作流）
- **task skill spec**（`docs/superpowers/specs/2026-05-24-task-skill-spec.md` / ~600 行 / 给 codex-skill-creator）：5-phase SOP（Specify / Plan / Task / Execute / Verify）+ 5 测试场景 + 跨项目"约定大于配置"加载
- **双端 hook 对称**：`.claude/settings.json` + `.codex/hooks.json` 跑同一脚本 `scripts/user_prompt_mental_check.py`（4 通道 + cap 200 行）
- **dev-guide.html v4**：7 tab 可交互可视化（数据流 / 模块对比 / 扩展沙盘 / 判断层 trigger / 协作机制 / 反馈环 / 物理拓扑）/ 1246 行 single-file / 0 依赖 / 替代 stale markdown 203 行

**task skill 真用回归**：Tim 在 Codex Desktop 用 task skill 跑 Sprint 10 PRD 准备阶段 → Codex 教科书级表现（识别 §10.Y 反指标 "大文档" / 反向 push back 建议 Claude 主写 / 自荐预读 + 原型 + 异源审角色 / file:line 实证 4 处引用 0 脑补）/ 产出 `docs/prototypes/sprint10-pmc-demo.html`。

**元洞察**：双 agent 切换的人类信息传递是结构性瓶颈 / 我们当前架构（shared filesystem + §10.Y 边界 + task skill push back + 4 通道 hook）已最小化 / 完全消除需 MCP / 工程量大 / 单人项目不值得。Tim 切换时用 5 字段一句话上下文（`[切自 X / 用 Y skill / 跑 Z 任务 / 它建议 W / 上次 commit: hash]`）即可。

**关键决策（Tim 拍）**：
- D 方案动态加载（不是单 §10.Y 注入 / 升级为 4 通道按 prompt 内容自适应）
- 否决 `project.yml` 引入（约定大于配置 / Tim 维护负担最小化）
- 砍 Hook 通道 5 well-framed 诊断（启发式准确率低 / 让 skill 自己判断）
- 否决"完全平等双向对话"（Codex 装等价 brainstorming 是工程量过大 / 模块化非镜像才是真平等）
- dev-guide.md 替代选 B（mv HTML + 删 .md / 单文件 / 维护负担最简）

---

## 2026-05-19 → 22: Sprint 7+8 Strava 同步链全 ship ✅

**主轴**：从"Strava 上传后 velo 看不到 / 跑步徒步污染骑行列表"修到"Strava 上传 7-15 秒 velo 完整显示 + 跑步永不入库"。

**两条链路收尾**：
- **Sprint 7 兜底链**（scheduler 闹钟 + 数据层 13 处过滤 + 130 行历史脏数据清）
- **Sprint 8 实时链**（Strava webhook 注册 + worker_strava 异步处理）

**真用回归 2 次通过**：
- 5-19 Evening Ride 55km（短期 SQL unblock 5-18 卡 importing）
- 5-22 Afternoon Ride 10km（webhook 实时链 / 7-15 秒到达）

### Sprint 7 ship 链（7 Fix + 脏数据 SQL + hotfix / commits 倒序）

| 项 | commit | 内容 |
|---|---|---|
| Fix 4 hotfix | `3539d57` | tier1 加 all_exists 短路防死扫历史（真用回归暴露设计 bug） |
| 脏数据 SQL | `5c7e6f5` | scripts/sprint7_dirty_data_cleanup.sql 三审收敛 Critical |
| Fix 7+ | `47683e7` | segment_query.py 2 处 cycling filter（Codex 异源审抓 spec 漏点 / Tim 拍扩 13 处） |
| Fix 7 | `5ac1ca7` | service_stats + service_social + dedupe + progress 11 处加 activity_type='cycling' |
| Fix 6 | `b4c6f14` | service_sync manual_sync 加 _is_cycling 守卫 |
| Fix 5 | `f67d1d8` | activity/service.py:get_activity_list 加 activity_type + status filter |
| Fix 3 二修 | `3bf28ec` | 取消 _MIN_DISTANCE_METERS 短距离阈值（Tim 拍）/ 短骑行也拉详情 |
| Fix 3 修订 | `ce3112b` | 短距离回填 'other' → 'cycling'（reviewer Important-1 + spec 修订） |
| Fix 3 | `5e13ff9` | import_scheduler tier1/tier2 加 _is_cycling 双字段守卫 + 短距离回填 |
| Fix 4 | `1af86fa` | scheduler `_reactivate_idle_imports` 每 10 分钟兜底重启 idle 用户 |
| Plans v5 | `60f432c` | sprint plans v5 ship（4 轮双审 / 3 轮 codex / Critical=0 收敛） |

**脏数据清理实证**：DB 删 130 行（跑步 / 徒步 / 空骨架 / >24h importing）/ FK CASCADE 自动清 trackpoints/efforts/notifications / Redis heatmap+power_curve 缓存清。

### Sprint 8 ship 链（webhook 实时链）

| 项 | commit | 内容 |
|---|---|---|
| 注册脚本兼容 | `33a148e` | strava_webhook_register.py 改 os.environ 优先 / 容器内可跑 |
| Fix 1+2 | `8f5146f` | worker_strava.py 新文件 411 行 + service_sync.handle_webhook_event 改 enqueue + 注册脚本 / 三审收敛 3 Critical |

**关键三审 Critical 收敛**：
1. **集成审 Critical**：worker_strava avg_speed * 3.6 双重转换（GPX worker.py:424 同源已修 / 我没同步）→ 改 `"avg_speed_kmh": activity.avg_speed`
2. **集成审 + spec 审 Critical**：service_sync create 路径缺 `if created:` 守卫（spec 字面要求）→ 防重复 webhook 污染 RQ 队列
3. **Codex Critical**：worker_strava 拉详情/拉轨迹/解析 3 处 except 改异常分流 → `StravaRateLimitError + httpx.HTTPError + httpx.TransportError` raise 让 RQ retry / 业务异常 logger.exception + status='failed' / 防 429 限流永久失败

**Strava webhook 注册实证**：`POST /push_subscriptions` 返 `sub_id=347703` / Strava handshake GET callback 返 200 / 写 .env `STRAVA_WEBHOOK_SUBSCRIPTION_ID=347703` / docker compose up -d --build api 让新 env 生效。

**回归测试**：708 全套 pytest（新 26 case：reactivate_idle 5 / fix3_cycling 8 / fix5_list 6 / fix6_manual_sync 3 / fix7_data 7 / fix7_segment 2 / worker_strava 5）。

### Sprint 7 留下的 P2 tech debt

`docs/tech-debt.md` 新条目（commit `ed0d59c`）：Fix 4 scheduler 周期重启 hotfix（all_exists 短路）需长期完整重写——用 Strava API `after` 时间戳参数避免重启从头扫历史。Sprint 8 webhook ship 后影响下降 / 但代码 debt 仍在。

---

## 2026-05-21: Persona Engine 彻底清理（分 5 stage / 进行中）🧨

**主轴**：Tim 拍 C 方案 = 前端 + 后端代码 + DB 表全清。装饰展示层不应上 sprint 主线 / 战略复盘见 [2026-05-20 段](#2026-05-20-战略-reset--persona-砍--训练分析线立项-)。

**stage 进度**：

| stage | commit | 内容 |
|---|---|---|
| 1 | `a1babdc` | `pg_dump` 3 张 persona 表到 `docs/archive/persona-db-backup/2026-05-21-persona-tables.sql`（193+168+0=361 条 INSERT / 含 schema + FK / archive 自包含） |
| 2 | `e723906` + `07a0256` | `app/agent/persona/` 整目录（9 文件）+ 5 处跨模块引用（main.py / agent/__init__ / worker.py / worker_strava.py / docker-compose persona-scanner service）+ scripts 4 文件 + tests 5 文件 + 历史脚本注释化 / **净删 3463 行 / pytest 657 passed**  |
| 3 | `8073ab9` | 新写 `migrations/versions/sprint9_persona_cleanup.py` reverse migration（drop_table feedback → templates → outputs / downgrade NotImplementedError）+ 清 `docs/tech-debt.md` 5 条 persona 债 + 同步 `docs/data-flow-guide.md` + `docs/architecture-guide.md` |
| 4 | 待 | 前端 miniprogram 14 文件清（utils/persona_fetch + persona_static 整删 + api.js 剔 endpoint + 4 page 按 PERSONA_START/END 段剔 / 1569 行总量 / 派 subagent 拆 4 page-level task） |
| 5 | 待 | 生产部署 SOP（git push → ssh server git pull → docker compose up -d --build api worker → docker stop persona-scanner 孤儿容器 → alembic upgrade head 真跑 reverse migration → curl verify 旧 endpoint 404 → 小程序真机回归） |

**三审收敛**（stage 2 + 3 各跑 Claude A spec-faithful + Claude B integration + Codex 异源审三轮）：

- stage 2：Critical 0 / Important 10（worker_strava docstring × 3 + docs 同步 × 4 + 死 import × 2 + sql 注释 × 1）/ fix commit `07a0256`
- stage 3：Critical 0 / Important 4（migration docstring 措辞 × 2 + tech-debt 文案超前 × 1 + changelog 没记 × 1）/ 本 commit 即修

**关键决策记忆**：

1. **archive 自包含**：pg_dump --inserts --no-owner --no-acl / 含 CREATE TABLE + INSERT + ALTER FK / 直接 `psql -U velo -d velo < archive.sql` 恢复
2. **不删历史 migration**：persona_engine_init.py + persona_engine_seed.py 保留 alembic chain 完整性 / 新环境跑会"建了又删"浪费几秒但语义对
3. **downgrade NotImplementedError**：诚实做法 / drop 表不可逆 / 强制人工介入从 archive restore
4. **CLAUDE.md:320 留 follow-up**：Tim 拍"第三组不做" / 部署 SOP 注释仍写"persona-scanner / cleanup / monitor"过时 / 防夹带不动 / 等 Tim 自己改或拍我精确 add hunk
5. **persona_feedback 0 条数据**：实证"装饰展示无人理"决策正确（用户从不点反馈 / 验证砍掉 ROI 高）

---

## 2026-05-20 → 21: Sprint 9 / FTP 智能化全部 ship ✅

**主轴**：模块 A（路线图首块）/ 8 task + 9 hotfix 落地 / snapshot_ftp 快照式架构 + IF/TSS 量化数字 + CP 3-param eFTP 估算器 + W/kg 显示 + Breakthrough 自动检测。

**Alembic head**：`sprint9_breakthrough_events` / **git main**: `5ba4229`。

**8 task ship 链**：

| task | commit | 内容 |
|------|--------|------|
| 1 | `65620b3` | activities 加 snapshot_ftp/IF/TSS + Alembic 迁移 + scipy>=1.11 |
| 2 | `e5adee1` | worker save_parse_result 签名加 user + 算 IF/TSS + 3 调用方同步（worker.py + worker_strava + import_scheduler） |
| 3 | `684330d` | ActivityDetail schema 加 4 字段 + service.py 算 W/kg + detail.wxml"按 FTP 220W 算"小字 + 一次性 baseline SQL 同步 184 条 |
| 4 | `9c5cdc3` | backfill_ftp.py + update_profile PUT 检测首次填 ftp → RQ 异步回填 |
| 5 | `3110df3` | ftp_estimator.py CP 3-param + scipy curve_fit + 滑窗 best efforts + 4 档 confidence |
| 6 | `9eb805d` | GET /me/ftp-estimate + settings 体重输入 + "让系统估算"按钮 + 自定义 modal 弹窗 |
| 7 | `5b2929a` | 详情页加 W/kg / NP / IF / TSS 4 行 metric-row |
| 8 | `fffe293` | BreakthroughEvent ORM + 迁移 + breakthrough_detector + worker hook（GPX/FIT + Strava webhook + import_scheduler 三路）+ GET/PATCH endpoints + settings 弹窗 + 13 pytest |

**9 hotfix**（三轮收敛实证 / Codex 异源审多次抓 Claude 双审漏过的真问题）：

| hotfix | commit | 抓出方 | 内容 |
|--------|--------|--------|------|
| 1 | `f0c654c` | task-2 spec reviewer | conftest.py `_activities_table` 补 4 列防 80 fail baseline noise |
| 2 | `9e5c0a3` | task-3 Codex 异源审 | hide_power 隐私挖空补 calories（calories+duration 反推 avg_power） |
| 3 | `b09bf55` | task-4 Codex + quality 独立抓 | enqueue 失败补偿（陷阱 #14 / Redis 挂 PUT 不返 500 / try/except 兜底） |
| 4 | `a8baa9a` | task-5 Codex 异源审 | **Critical**：3 efforts = 自由度 0 → R²=1.0 虚假 high 置信度（强制降级 + bounds + 非单调过滤 + guard 收紧） |
| 5 | `b0f0730` | task-6 quality reviewer | **Critical**：button 嵌 .row-right flex 行拦截兄弟 tap（微信硬上限 #2 / 2026-05-16 task-4 hotfix 同坑）+ toast 文案条件化 |
| 6 | `f1a0bf7` | task-8 Codex + quality 独立抓 | PATCH /me/breakthroughs 原子 UPDATE 防并发 race + import_scheduler 第 3 caller 漏接 hook + Response schema 加 expires_at + mask 误触防 reject + 注释 5→6 hook |
| 7 | `5ba4229` | task-5 Tim 真用回归发现 | 滑窗算法 bug（90% 容差 + index 平均双 bug）/ 改严格时间加权 prefix sum |

**关键产品决策记忆**：

1. **快照式 ftp**（Tim 拍）：每活动 `snapshot_ftp` 永久锁定当时 ftp / 改 user.ftp 不动历史 power_zones / 物理事实"那段路骑的时候是 Z5 强度"不被未来 ftp 涨改写
2. **首次填 ftp 触发回填 / 之后改不触发**（Tim 拍）：单次 escape hatch / 防回填风暴
3. **三路 save_parse_result 全覆盖**（三轮 reviewer 抓 import_scheduler 漏处）：worker.py + worker_strava.py + import_scheduler.py 同步加 user 参数
4. **CP 3-param Morton 1996 公式**：`P(t) = CP + W' × (P_max - CP) / (W' + t × (P_max - CP))` / 第二项分母 P_max - CP（spec §5.3 line 339 typo）/ implementer 按 PMID 8854981 实测核对
5. **物理合理性 + 自由度 + 单调性 + bounds 4 层 guard**（task-5 hotfix 后）：拒绝数学有效但物理不可能的拟合结果
6. **Breakthrough 状态机 4 态**（pending / accepted / rejected / expired）+ 7 天自动过期 + 防抖（新 pending 标老 pending expired）+ accepted 不触发回填（保快照式纯粹）
7. **隐私挖空 5 字段**（hide_power 时）：power_per_kg / IF / TSS / snapshot_ftp / calories（防反推 avg_power）

**真用回归实证**：
- 场景 1 W/kg ✓ Tim 直接验
- 场景 3 手动改 ftp 202→215→210 ✓ Tim 直接验
- 场景 4 Breakthrough "更新 FTP" ✓ fake INSERT id=1 触发弹窗 + accepted 状态机 + user.ftp 更新

**P1 tech debt（Sprint 9 收尾发现 / 留 Sprint 10 后专题）**：
- ftp_estimator 算 Tim ftp=117W vs 真实 1200s best 250W 差 100W+ → 详见 `docs/tech-debt.md` P1 条目

---

## 2026-05-20: 战略 reset / Persona 砍 + 训练分析线立项 ⚠

**主轴**：Tim + Claude 一次 brainstorm 复盘 / 发现 Persona Engine（NPC 老登嘴贱便利贴）是装饰展示层 / 用户不会看 / 一个 sprint 战略失误 → 决策砍掉 + 沉淀元教训 + 立训练分析新线。

**关键决策**：

1. **Persona Engine 砍**：整目录 `app/agent/persona/` + 3 张 persona_* 表 + 6 task plans + 宪法 v0.1 暂停不删 / 整套晾着 / 等 3-5 天看真实反应再判断（永久砍 / 部分复用 / 还是激活）
2. **元教训沉淀**：全局 `~/.claude/CLAUDE.md` §2.1 新原则"装饰展示 vs 主动指导（每加新 feature 前必过这一关）" + memory `feedback_decoration_vs_guidance_velo_persona_lesson.md` 含 persona 完整始末
3. **训练分析线立项**：跟另一线 brainstorm（roadmap.md）合并 / 5 模块 6-8 周完整版 / Sprint 9（FTP 智能化）→ 10（PMC 训练负荷曲线）→ 11（训练分布）→ 12（LLM 教练总结 / 替原"规则版"AI）→ 13 取消（HRV 永久不做）
4. **HRV 永久不做**：research subagent 实证微信小程序 `wx.getWeRunData` 只返步数 / 不能调 Apple HealthKit / Strava API 不返 HRV / 蓝牙手环协议不一。velo 100 用户量级 + 微信小程序入口 → 永远拿不到 HRV / 装就崩塌

**文档产出**：

- 新建 `docs/superpowers/specs/2026-05-20-coach-engine-design.md` 设计稿（8 大块 / Sprint 12 模块 D 详细设计 / 等 Sprint 9-11 ship 后转 `sprint-12-prd.md`）
- 改 `docs/superpowers/specs/2026-05-20-training-analytics-roadmap.md` 三处（模块 D 规则版→LLM 版 + 指针 / 模块 E 选做→永久不做 / §7 加 persona 已砍）
- 改本项目 `CLAUDE.md` 文档清单段（标注 persona 已砍 + 链向训练分析线）
- 改 `docs/tech-debt.md` persona-1~5 加搁置 banner

**当前主线**：Sprint 9 / FTP 智能化（按另一线已写好的 `docs/prd/sprint-9-prd.md` 8 个 task 跑）。

**zero 代码改动**：本日全是文档 + memory + 全局 CLAUDE.md 同步。

---

## 2026-05-16 → 2026-05-17: Sprint 6 "我的"页基础落地全部 ship ✅

**主轴**：把 `pages/profile` 从字段表格升级为骑手身份名片——签名 + 训练统计 + 热图 + 历史活动列表。

**子任务 ship 链**（实施期 2026-05-16）：
- task-1 User.bio 一行短签名（commit `ce5ec78` / Alembic `sprint6_user_bio`）
- task-2 数据徽章 + 6 城共享常量 `app/user/cities.py`（`3b34769`）→ Tim 真用拍砍"成都骑友"后缀改裸字"成都"（`38718ec`）
- task-3 activities.city + worker hook 3 路径接入（GPX / FIT / Strava）+ city-medals endpoint + 286 历史回填（`2caa456` / Alembic `sprint6_activity_city` / backfill ORM import 漏写修 `6d1f7ba`）
- task-5 settings 子页 3 区块（FTP / Strava / 退出）+ 后端 POST /api/strava/unbind（`6c6bff2`）
- task-4 profile 页改造 4 模块布局 + 提取 ride-card 组件（`3488ea4`）

**task-6 真用回归 8 hotfix 链**（2026-05-16 → 2026-05-17 / 验证真用价值）：

1. `bbfbb0c` 真用 5 处：头像微信 button / city 编辑入口 / **砍 badges 前端展示**（初期没用）/ **砍城市勋章前端展示**（莫名其妙）/ 热图改用既有 `<heatmap-card />` 组件（原占位文本不渲染腾讯地图）
2. `7a6fb6e` 二次 hotfix：修登录跳不存在路由 + 修头像 button 在 flex 行拦截 city 点击（退回 image bindtap）
3. `64d3615` 三次 hotfix：登录卡 loading 不消失 / 改先 hideLoading 后台 fetchAllData
4. `a754606` 加 5s 兜底 timeout + 全程 console.log 埋点（定位真根因前的防卡死兜底）
5. `7ffdb0d` 真根因 = profile.js 缺模块级 `const app = getApp()` ReferenceError（task-4 续工 subagent 漏写 / Tim Console 截图一次定位）
6. `7885904` Strava 一键授权 web-view 内嵌（弃复制链接 / 切微信传输助手粘贴的旧麻烦流程）
7. `23b86b7` + `d08227b` city 切换失败根因 = wx.showActionSheet itemList **微信硬上限 6 项**（我传 7 项含"清空主城" → 直接拒 / 砍掉清空项）
8. `6f514af` + `ebd09b1` city 放宽到全国省+市 picker mode="region"（小程序内置全国行政区数据 / 不用维护 333 个地级市清单）

**关键架构语义解耦**（防未来 agent 混淆）：
- `users.city` = 用户手填家乡标签（任意中文 / picker 选省+市拼接如"山西-太原" / String(64) / 删 ck_users_city CHECK）
- `activities.city` = worker hook 自动推断起点（仍 6 城+unknown / ck_activities_city 不动 / city-medals 用）

**前端砍 / 后端保留**：badges + 城市勋章前端展示砍掉（Tim 真用拍初期没用）/ 但后端 endpoint + DB 数据 286 条全保留 / 未来恢复只需取消 wxml 注释。

**新沉淀 memory**（5 条）：
- reviewer 抓 Critical 必须 cross-check task 卡 + Tim 意图
- subagent 异常退出主 agent 必须 grep 实证
- 独立 python 脚本必须显式 import 所有外键 ORM
- 真机前端 bug 第 2 次没修好立刻加 console.log 埋点不盲改
- 微信小程序硬上限速查（actionSheet 6 项 / button 拦截 / web-view 业务域名等）

**Alembic head 推进**：`sprint5_activity_privacy → sprint6_user_bio → sprint6_activity_city → persona_engine_init → sprint6_user_city_widen`

**tech-debt 新增 6 条 P2/P3**（见 docs/tech-debt.md）：profile 头像微信一键导入 / badges 隐私 effort / SQL 重复聚合 / Strava worker hook e2e / PG partial index 命中 / PATCH /me 双 commit / unbind 在途 worker 竞态。

**总改动**：~3500 行新增（含 spec docs 2600+ 行 + 代码 ~900 行）/ 测试 585 → 589 passed。

---

## 2026-05-16: Persona Engine Sprint plans v0.4 ship（NPC 文案系统规划全套 / 4 轮双审收敛）✅

**为什么要做**：velo 真正的护城河 = NPC 老登人格（数据 / 功能 / 视觉都可被 copy / 但人格 copy 不了）。Tim 拍独立大型 Sprint / 不和"我的"页基础混。

**产物**（9 个文档 / 共 ~3000 行）：
- `docs/agent-rules/persona-constitution.md` ~558 行：NPC 灵魂源（§ 1-8 + 50 条精选 + 信息密度双标尺 + 9 类反例禁区 + 黑话词典 + § 7 架构约束"可拔的码表"+ § 7.5 持续可拔性验证三招）
- `docs/prd/persona-engine-sprint-prd.md` ~510 行：Sprint PRD v0.2（6 task × 9 章节 + § 0.1 真实代码事实表 + 算法 vs LLM 分工 92/8）
- `docs/plans/persona-engine-handoff.md` + 6 个 task 卡 ~1480 行：共用约束 + 实施细则

**4 轮双审收敛节奏**：5 → 3 → 1 → 0 Critical（vs Sprint 6 实证 3 轮 14→8→3→0 / 跨模块新工程多走 1 轮合理）

**关键架构决策**：
- ADR-009 子工程 / `app/agent/persona/` 独立目录 / 拔了 velo 主功能照样跑（验收标准明确）
- v0.1 = 100% 算法 + 模板（0 LLM 调用 / 0 漂移 / 0 成本）/ v0.5+ 才接 LLM（跨时间镜像等动态场景）
- 每场景 ≥ 5 条（Tim 拍 / 防 broken record）/ 总扩到 ~158 条 / 副线 cycle 完成

**实施阶段 ready**：等新 claude 进程接手按 task-1 → task-6 顺序执行。

---

## 2026-05-16: Sprint 6 "我的"页基础 ship（task-1 ~ task-5 + 2 次 hotfix）✅

**为什么要做**：从 v5 期字段表格升级为骑手身份名片（签名 / 数据徽章 / 城市勋章 / profile 页改造 / settings 子页）。

**主要 commit**：
- `3488ea4` feat(profile): Sprint 6 task-4 profile 页改造 + ride-card 组件提取
- `6c6bff2` feat(strava): Sprint 6 task-5 settings 子页 + POST /api/strava/unbind
- `bbfbb0c` fix(profile): task-4 真用回归 5 处 hotfix（Tim 2026-05-16）
- `7a6fb6e` fix(profile): 修登录失败 + city 不可点击（task-4 二次 hotfix）

**关键产物**：
- 后端 task-1: User.bio 字段（≤30 字签名）
- 后端 task-2: 数据徽章规则模块（badges.py 纯函数）
- 后端 task-3: `activities.city` 字段 + worker hook + 城市勋章 endpoint
- 前端 task-4: profile 页三模块布局 + ride-card 公共组件
- 前端 task-5: settings 子页 + POST /api/strava/unbind

**Sprint 范围外（明确延后）**：NPC 拟人化文案 → Persona Engine Sprint（同日 plans ship）

---

## 2026-05-14 ~ 2026-05-15: 赛段海拔曲线 + 坡度修复（Step 1 + Step 2-DEM 全套）✅ ship

### Step 1（2026-05-14）：赛段详情页加海拔曲线

**改动**：
- 后端 `GET /api/segments/{id}` detail endpoint 加 `elevation_profile` 字段反序列化
- 前端 segment.wxml 加 canvas + segment.js 加 `drawElevationProfile`（仿活动详情页灰色面积图风格）

**commit**：`f18c76d`

### Step 2-DEM（2026-05-15）：坡度数据修复（6 次迭代 + Tim 拍砍）

**为什么要做**：生产 segment id=24 "夜骑清徐" 11km 平路 GPS 算 max_gradient=26.1% 假数据（Tim 体感真值 < 5%）。GPS 海拔 ±15m 噪声物理限制 / 任何平滑算法都洗不掉。

**6 次算法迭代**：
1. v1 单纯 100m 滑窗 / max=26.1%
2. v2 中位数平滑（window=15）+ cap 25% / max=23%
3. v2 + 500m 窗口 / max=10% / 仍超 Tim 体感
4. + 短赛段 fallback（window > 总距离时用 总长/4）/ 491m 短陡坡 18.8%（合理）
5. 切自托管 SRTM 90m（消除合规 + 稳定性）/ max=12% 反而升
6. 前端二次 movingAverage 平滑 / 视觉改善但 max 数字仍虚高
7. **Tim 拍砍 max_gradient 前端显示** ← 真智慧 / 不是失败

**真根因**：SRTM 30/90m 像素 vs 公路 5-10m 宽 / DEM 像素采到的是路边山势不是路面 / Strava 用气压计（±0.1m）+ 群体融合达到 / velo 100 用户 + 手机 GPS 物理上做不到。

**配套改动**：
- DEM 数据源从 opentopodata.org 公共 API 切到 SRTM.py + CGIAR-CSI 90m 自托管（commit `fed8249`）/ 消除数据出境合规瑕疵 + 解决第三方 API 稳定性
- docker-compose 加 `srtm_cache` volume 持久化懒下载的 tile
- 回填脚本 `scripts/recompute_segment_stats.py` 完整重写（PostGIS ST_LineInterpolatePoint 等距 400 点采样 + DEM 查表 + 中位数平滑 + 500m 滑窗 max_gradient + 80 点 elevation_profile）
- `service_create.create_segment_from_activity` 修补 `elevation_profile` 字段漏存（codex 旧 review I2）
- `service_create.create_segment` from-gpx 路径 `avg_gradient` 公式统一净高差 `(gain - loss) / dist`（之前永远 ≥ 0 / 下坡赛段拿不到负数）
- 部署 SOP 加 `alembic upgrade head` 硬性必跑步骤（CLAUDE.md commit `6c6d78d`）/ 2026-05-15 实证 sprint5_activity_privacy 迁移漏跑导致全 endpoint 500

**前端砍 max_gradient**（commit `b2ae57c`）：
- segment.wxml 4 数字 grid → 3 数字 grid（距离 / 米爬升 / 平均坡度）
- 海拔曲线前端二次平滑（movingAverage window=7）+ 后端 window=21 中位数平滑双层
- DB `Segment.max_gradient` 字段保留 / API 仍返 / 给 Step 3 群体融合后恢复

**关键经验沉淀**（memory）：
- DEM 物理精度限制 / 算法极限早识别（`feedback_dem_precision_physical_limit.md`）
- 用户 escape hatch 是真智慧 / 砍功能比改算法到完美更智慧（`feedback_user_escape_hatch_is_wisdom.md`）

**Step 3 计划**：用户量 ≥5-10 用户骑过同段路时 / 群体融合 DEM + 多用户 GPS 数据中位数校正 / 或气压计数据接入后恢复 max_gradient。详 tech-debt.md。

---

## 2026-05-11 hotfix: Strava OAuth scope 升级 `activity:read_all`（私密活动同步事故）✅ ship

### 事故复盘

用户在 Strava 上传"仅自己可见"活动 → velo 永远拉不到 → 用户报"看不到新活动" → agent **跳过 grep `scope=` + 跳过读 Strava 官方文档**，直奔 webhook → scheduler → token → cursor → dedupe → 跑 SQL 改 `strava_imports` 表 5 层中间链路 debug 30+ 分钟，连续给出 5 个错误根因（含"webhook 链路从来没生效""Strava 那边没你今天的活动"反向误导），用户被错误"严重事故"叙事**情绪崩溃**。

### 真根因（5 秒 grep 锁定）

Strava 官方文档原话：
- `activity:read` — 只读 Everyone / Followers 可见活动
- `activity:read_all` — **同时含**私密活动（Only You）+ privacy zone data
- API endpoint 明确："**Only Me activities will be filtered out** unless requested by a token with activity:read_all."

velo OAuth 默认申请 `read,activity:read` → Strava API **静默过滤**所有 Only You 活动（不报错 / 列表少一条无任何提示）。

### 修复

| 文件 | 改动 |
|---|---|
| `app/strava/service.py:89` | `generate_authorize_url` 旧版 / `scope=read,activity:read_all` |
| `app/strava/service.py:143` | `build_authorize_url` v4 版 / `scope=read,activity:read_all` + 注释补 |
| `CLAUDE.md` 顶部 | 新增 "🔍 调试/排查硬规则" 段 / 4 步强制顺序 / 红线条款 / 压过"行动优先" |
| `CLAUDE.md` 陷阱清单 | #20 Strava scope 入册 |

### 升级后必要动作

- ✅ 所有已绑定 Strava 的用户**必须重新 OAuth 一次**——旧 token 没有 `read_all` scope，Strava 强制重新授权流程
- ✅ 重新授权完成后 scheduler 会自动跑 tier1 拉新可见活动（包括所有历史私密活动）
- ✅ 部署前确认生产 `.env` 的 `STRAVA_CLIENT_ID/SECRET` 不变（OAuth app 注册时申请 scope 是 user 授权时确认，不是 app 端配置）

### 沉淀

- CLAUDE.md "调试/排查硬规则" — 用户报"X 看不到/不工作"前 4 步强制顺序（grep 配置 → 读官方文档 → 验证源头 → 才能动中间链路）
- CLAUDE.md 陷阱清单 #20 — Strava scope 字面陷阱
- 历史档案 sunset 注释：`docs/archive/spec-v2.md:852` / `archive/spec-v4.md:445` / `archive/plans-phase4-task-7.2.md:91`（不删原值 / 加"⚠️ 历史档案 / 勿照抄"标记防未来 agent 误抄）

### Codex 第 2 轮异源审补强（2 真 Critical + 1 Important + 1 Nice → 全修）

- **C1 query string tampering 防御**：用户在 Strava 授权页取消勾选 `read_all` 后**手动篡改** callback URL 加 `scope=read,activity:read_all` 可绕过 Step 1.5 query 校验 → 加 Step 2.5 用 Strava token response 里的 `data["scope"]` 字段（**空格分隔的 granted scope** / Strava 官方文档明确建议校验）二次拦截
- **C2 老用户 forced reauth**：当前真实老 token 用户**仅 Tim 一人** + 升级后立刻重新 OAuth = 隐含修复 / 不做 `needs_reauth` 字段 + migration（违反防火墙式扩展 / YAGNI）/ 写 tech-debt P2 由颜颜 / CCF 接入时再做
- **I1 route-level tampering 测试**：`tests/strava/test_callback.py` 新增 `TestCallbackRouteScopeTampering` 2 case — query 篡改场景 + 合规授权场景，通过 TestClient + monkeypatch _redis + mock httpx.post 真走 router 防回归
- **N1**：`app/strava/exceptions.py` docstring 半角全角引号统一

### Codex review 收敛节奏（symbolic / 验证三审分工有效）

| 轮 | Critical | Important | Nice | 收敛信号 |
|---|---|---|---|---|
| 第 1 轮 | 5 | 2 | 1 | 初审广撒网 |
| 第 2 轮 | 2 | 1 | 1 | Critical 递减 5→2 / 焦点上升到攻击面 + 产品级影响 |
| 第 3 轮 | 待跑 | — | — | 目标 Critical=0 收敛

---

## 2026-05-11 Sprint 5 task-3: 探索 tab 骑友 section ✅ ship

### 背景

v5 task-4.3 commit `5de9f40` 加了 `/api/user/{id}/profile` + 看他人 power-curve / heatmap 后端能力 / 但前端唯一进入路径是通知中心 kom_lost 头像跳转 = **后端写完前端没消化**（v4 task-7.x 同款病）。Sprint 5 task-3 让能力真活起来。

### 2 commit 链（codex 1 轮 review 收敛）

| commit | 摘要 |
|---|---|
| `82086f9` | task-3 ship：后端 GET /api/user/active + 前端 explore tab 骑友 section + 9 case 测试 |
| `f001a4d` | codex review 3 项收口：NULLS LAST + 前端 ISO→人话 + endpoint limit 边界测试 |

### 后端实现

| 维度 | 决策 |
|---|---|
| endpoint | `GET /api/user/active?limit=10` / 跟 task-2.C.3 拍的 /api/user 单数前缀一致 |
| schema | `ActiveUserItem` + `ActiveUsersResponse` / 精简字段防过度暴露 |
| 排序 | `ORDER BY MAX(started_at) DESC NULLS LAST` / codex 抓防 PG/SQLite NULL 行为不一致 |
| 过滤 | INNER JOIN activities + status='completed' + duplicate_of IS NULL + is_admin=False + 排除自己 |
| 防御 | limit < 1 或 > 50 → 兜底 reset 10（防恶意大 limit 拖 DB） |

### 前端实现

| 维度 | 决策 |
|---|---|
| 位置 | explore tab 城市筛选**之后** / 赛段瀑布流**之前**（社交优先） |
| UI | 横向 scroll-view / 96rpx 圆头像 + nickname + city + 总里程 + "X 天前活跃" |
| 隐私处理 | last_activity_at ISO timestamp → "今天/昨天/X 天前/X 周前" 人话渲染 / 不暴露具体到分钟 |
| 跳转 | 点头像 wx.navigateTo `/pages/user/user?id=X` / 复用 task-4.3 看他人 profile 路径 |
| 0 用户态 | wx:if 整 section 隐藏 / 不强出空态 |
| 失败处理 | API 失败静默 / 不阻断赛段瀑布流主功能 |

### 部署 verify

```
HTTP 200
{"items": []}
```

当前 prod 只有 user 1=Admin（被 is_admin 过滤）+ user 2=Tim（被 token 排除自己）→ 0 候选 / 骑友 section 隐藏。**符合预期**。CCF / 颜颜注册上传 GPX 后自动出现。

### Codex review 1 轮 / Critical=0

- Critical=0
- Important 2：last_activity_at 暴露但前端没用（已修：渲染人话） + ORDER BY NULL 排序漂移（已修：NULLS LAST）
- Nice 1：limit 边界端到端测（已修：加 2 case）

新 review 规则（feedback_review_agent_must_read_diff_not_prompt）继续起作用 — codex 自由探索抓到 schema/前端协议不对齐 + DB 行为差异。

### 测试覆盖

- `tests/test_user_active.py`：11 case（service 7 + endpoint 4）
- 全套 443 + 11 - 9（已计入） = **445 passed**

### 下一步

**Sprint 5 task-3 ✅ ship**。Sprint 5 进度：
- ✅ task-1 pg_dump 备份 MVP
- ✅ task-2 GPX dedupe MVP + parser timezone fix
- ✅ task-3 探索 tab 骑友 section
- 待选：加更多赛段（持续动作）/ admin H5 hotfix loop（按需）/ 1 周真用回归收集痛点

---

## 2026-05-11 Sprint 5 task-2: GPX 语义级 dedupe MVP ✅ + parser timezone bug 顺手修

### 触发

Tim 真上传 GPX 时发现：file_hash 字节级 dedupe 漏识 Strava 同步 vs GPX 后传的同骑行（语义级重复）。
brainstorm 7 拍后实施 1-2 天 task。

### 5 commit 链（codex 4 轮 review 收敛）

| commit | 摘要 |
|---|---|
| `853bd5b` | dedupe MVP：4 维 signature 算法 + dedupe.py 纯函数 + dedupe_service.py + worker 集成 + 6 处列表查询过滤 + schema/endpoint + 前端 toast UX |
| `ec8ae57` | Codex round-1 抓 Critical fix（pipe 退码已修） + Important（pg_advisory_xact_lock per-user）+ Nice（30h 边界 case） |
| `95df6be` | Codex round-2 抓 2 Critical → Tim 反思切修法 A：砍 score 比较 / 永远新的标 duplicate（避免 efforts 迁移复杂度爆炸）+ Strava import_scheduler 路径集成 dedupe |
| `fb9c805` | Codex round-3 Important：/api/user/stats 也过滤 duplicate |
| `a4df6d5` | 部署 verify 实证 GPX timezone bug：parser naive timestamp 假设北京时间 → 转 UTC（中国主用户群） |

### 关键设计决策（Tim brainstorm 7 拍 / 详对话记录）

1. **算法 4 维**：起骑时间 ± 5min / 距离 ± 100m / 时长 ± 60s / 起点 GPS ± 100m（容差从 GPS 物理误差推导）
2. **修法 A（永远新的标 duplicate）**：旧的为主 / new 标 duplicate_of=existing / 不比 score（避免 efforts 迁移 / 字段重算 / 通知关联失效等深层耦合）
3. **trade-off**：用户后传"数据更全"GPX 仍隐藏 / 但实际 Strava 同步通常在前 / 后传隐藏不损失什么
4. **per-user advisory lock**：`pg_advisory_xact_lock(hashtext('dedupe-activity'), user_id)` / 同 user 串行 / 不同 user 并发 / 防多 worker scale 后 race
5. **Strava 路径集成**：worker.py（GPX/FIT）+ import_scheduler.py（Strava）双路径都调 dedupe

### 部署 verify（生产实证）

发现 user 2 的 326（GPX 上传）跟 Strava 同骑行 103 时间差 8h（**GPX timezone bug**）：
- 326 started_at = `2024-12-21 19:40:23+00`（实际是北京时间被错存 UTC）
- 103 started_at = `2024-12-21 11:40:23+00`（真 UTC / Strava 已 normalize）
- 时差 8h / dedupe 5min 容差外漏判

修 GPX parser timezone：
- naive timestamp（无 tzinfo）→ 假设北京时间 → 转 UTC
- aware timestamp → astimezone(UTC) 标准化
- +3 测试覆盖（naive 北京 / Z 后缀 / +08:00）

手动模拟 parser 修复后状态（SQL 改 326 started_at -8h）→ 跑 dedupe → ✅ 326 标 duplicate_of=103 / 完整链路 verify 通过。

### Codex 4 轮 review 复盘（按新 review 规则跑）

应用 memory `feedback_review_agent_must_read_diff_not_prompt` 新规则：
- 不列待审文件清单
- 不告诉"已 fix""Tim 拍"
- 给 commit hash + 让 reviewer 自由探索

新规则下 codex 抓得更准：
- round-1（853bd5b）：1 Critical（pipe 退码 / 我自查抓的）+ 1 Critical（cron spec drift）+ 1 Important（pg_isready）+ 1 Nice（30h 边界）
- round-2（ec8ae57）：抓 2 真 Critical 揭露修法 B 复杂度爆炸（efforts/通知不迁移 + Strava 路径漏接）→ Tim 反思切 A
- round-3（95df6be）：1 Important（/api/user/stats 漏过滤）
- round-4（a4df6d5）：Critical=0 / 2 Important 都是 trade-off 类（海外北京假设 / 集成测试 ROI 低）→ 收口

新规则下 reviewer 视野不被框定 / 跨模块影响（Strava 路径 / segment_efforts 双计 / stats 漏过滤）才被抓出来。

### 测试覆盖

- `tests/test_activity_dedupe.py`：17 case（4 维比对 + 容差边界 + score 公式）
- `tests/test_activity_dedupe_service.py`：8 case（标 duplicate / 时间窗 / 跨用户 / advisory lock 守卫 / 不迁移）
- `tests/test_parsing.py`：+3 case（naive 北京假设 / Z UTC 保持 / +08:00 转 UTC）
- 全套：434 passed / 53 skipped / 0 failed

### 留 backlog

- 海外用户 GPX 上传时 naive timestamp 仍按北京时间假设（接受 / Sprint 5 task-2 trade-off）
- 历史 timezone-affected GPX（如 326 这类已存 DB 的）→ 不会自动 retroactive backfill / 留独立 dedupe_historical.py 脚本未来跑
- 多 worker scale 后真并发场景集成测试（advisory lock 设计已就位 / 但生产单 worker 暂无法 verify）

### 下一步

**Sprint 5 task-2 ✅ ship 完整闭环 / 待 Tim 选 task-3**：
- 探索 tab 加骑友 section（Sprint 5 task-3 Tim 之前拍的 day 3-4 任务）
- 加更多赛段（持续动作）
- admin H5 hotfix loop（按需）

---

## 2026-05-10 task-4.3 §2: alembic 双向 + restore 演练 ✅ / v5 期 100% 完结 🏁

> v5 期最后一项遗留 / Sprint 5 task-1 pg_dump 解锁后立即跑 / 完整闭环验证备份-恢复路径真 work。

### 触发

Sprint 5 task-1 pg_dump 备份 ✅ ship → task-4.3 §2 alembic 双向解锁前置满足 → Tim 拍"完整闭环（双向 + restore 演练 / 45 分钟）"。

### 5 step 全过

| Step | 操作 | 结果 |
|---|------|------|
| 1 | `docker compose exec db-backup /scripts/backup_db.sh` | marker backup `velo_20260510_151014.sql.gz` / 28.2 MB / 8 秒 ✅ |
| 2 | `alembic current` + `upgrade head` | current=`phase5_v5_db_changes (head)` / upgrade no-op ✅ |
| 3 | `alembic downgrade phase4_frontend_consume` | 跑 2 步：v5_db_changes → tz_aware → phase4 / verify users.city + segments.{city/max_gradient/difficulty} + segment_curation_pool/ai_drafts 全消失 ✅ |
| 4 | `alembic upgrade head` | 跑 2 步重建 / verify schema 回 + 数据 NULL/server_default（city='unknown' difficulty='medium' max_gradient NULL）✅ |
| 5 | restore 演练（用新 db `velo_test_restore` 隔离 / 不污染 prod） | create db → gunzip backup → psql restore → verify users.city=taiyuan + segments 4 字段完整 + 行数对齐 prod（users 2 / segments 24 / activities 326 / efforts 121）→ drop velo_test_restore ✅ |

### prod 恢复（backfill_phase5）

restore 演练验证了 backup 真可用 / 但 prod v5 字段仍 NULL/server_default（downgrade 副作用）。Tim 拍"backfill_phase5（推荐 / 5 分钟 / 零风险）"恢复路径。

实测：
- segments 阶段：success=24 / failed=0 / 16 分钟跑完（PostGIS 距离查询 + max_gradient 算法慢）
- users.city 阶段：updated=1 / unchanged_null=1 / failed=0

**user 1 (Admin)**: city 仍 NULL（无 activity / 算法无法推断 / 预期）
**user 2**: city = 'shenzhen'（**与 prod 之前 'taiyuan' 不一致**）

### user 2 city 推断算法差异（设计差异 / 不 bug / Tim 拍接受）

| 路径 | 算法 | user 2 结果 |
|---|------|-------|
| `worker.py` city hook（每次上传 GPX 后跑） | latest activity 起点 | latest_act 2026-05-03 在太原 → 'taiyuan' |
| `backfill_phase5.py backfill_users_city`（一次性 / 跳过式幂等） | first activity 起点 | first_act 2022-04-24 在深圳 → 'shenzhen' |

两种合理推断 / `backfill_users_city` 设计文档明确说"首次推断 / 不覆盖人工值"。Tim 拍接受 / 下次上传 GPX 时 worker hook 会自然改回 latest（不会因 city 已存在跳过 / worker hook 是覆盖式）。

### v5 期 100% 完结 🏁

- 4 个 Sprint（0/1/2/3/4）+ 4 个收尾 task（4.1 文档 / 4.2 黑盒 / 4.3 part-1/2/3/4 / 4.4 复盘）全部 ✅
- 0 遗留项

### 下一步

**Sprint 5 task-2 待 Tim 选**。backlog 候选（按 ROI 排序）：
- D33 map matching（赛段匹配精度 / 1-3 天）
- D28 高德地图未来 tab（2-3 天）
- tied PR my_rank off-by-one fix（半天）
- admin H5 真用回归 hotfix（按需）

---

## 2026-05-10 Sprint 5 task-1: pg_dump 自动备份 MVP ✅ ship

> v5 期 closure 后 Sprint 5 第一项 / tech-debt 顶部 P0 / 也是 task-4.3 §2 alembic 双向解锁前置。

### 触发

task-4.3 part-3 完成 / Tim 拍"开 Sprint 5"+ 7 个 brainstorm 决策（详 task 卡 §1）。

### 核心实现

| 文件 | 干啥 |
|---|------|
| `scripts/backup_db.sh` | 备份脚本 / pg_isready 等待 / pg_dump 拆 pipe / 7 天滚动 |
| `app/monitor/backup_freshness.py` | 监测探针 / 30h 阈值 / log-only 告警 / 健康路径 silent |
| `tests/test_backup_freshness.py` | 7 case（5 主路径 + 2 边界）/ 全过 |
| `docker-compose.yml` | 加 `db-backup` 服务（postgres:16-alpine）+ monitor 加第 3 探针 + `./backups:/backups` 卷 |
| `.gitignore` | `backups/` |
| `docs/archive/plans-sprint-5-task-1-pg-dump-backup.md` | 任务卡 + 7 个决策入册 |

### Tim brainstorm 7 拍（详 task 卡 §1）

1. **范围 = MVP 本地**（异地留 backlog / 100 用户量级 + log-only + 服务器物理炸概率极低）
2. **触发 = 每 24h 启动相对周期**（不强制凌晨 / 跟现有 cleanup/monitor/curation-pool-cron 同 while-true 模式 / 100 用户量级 + pg_dump MVCC 不锁表 → 中午跑也不影响）
3. **告警 = log-only**（D 决策 / 不接通飞书 webhook）
4. **路径 = ~/velo/backups/**
5. **检查 = monitor backup_freshness 探针**（log-only / 跟 admin_h5_health 同路线）
6. **首次 = 部署完手动跑**
7. **不开整期 PRD**

### 双审 + Codex 异源审 2 轮收敛

- **主 agent 自审抓 1 Critical**：原 backup_db.sh 用 `pg_dump | gzip > file` pipe / sh 默认只看 gzip 退码 / pg_dump 失败时 gzip 写空文件成功退 0 → freshness 探针被骗。修：拆 pipe / 先 pg_dump 到 .sql 临时文件 / 成功才 gzip。
- **Codex round-1**：抓 1 Critical + 1 Important + 1 Nice
  - Critical（cron 时间漂移 spec drift）→ push back 一半 / 改文档消 drift / 保 while-true 架构一致
  - Important（depends_on 不等 PG ready）→ 加 `pg_isready` 等待循环
  - Nice（30h 边界 case 缺）→ 加 2 个边界测试
- **Codex round-2**：3 处 fix 全闭环 / Critical=0 / 唯一 Nice 是注释精度（"60s" 实际最坏 ~115s）→ 改注释精确化

### 部署 verify（生产 ubuntu@114.132.190.245）

```
NAME                        STATUS
velo-db-backup-1            Up 16 seconds   ← 新增
velo-monitor-1              Up 15 seconds   ← 重建挂卷 + 第 3 探针
velo-api-1                  Up 16 seconds   ← depends_on 链路触发 recreate
velo-admin-h5-1             Up 16 seconds   ← depends_on 链路触发 recreate
... 其余 7 容器无变化
```

手动跑 backup_db.sh：8 秒完成 / 29 MB 文件 / `gunzip | head` 看到真实 PostgreSQL 16.4 + PostGIS tiger schema dump 头。

monitor backup_freshness 探针：容器启动初期有 1 条"backup dir 为空"日志（race / monitor 比 db-backup 先跑探针）/ 之后健康路径 silent（按设计不打日志）。

### 配套文档同步

- `docs/changelog.md`（本条目）
- `docs/archive/plans-sprint-5-task-1-pg-dump-backup.md` 验收清单 ✅
- `CLAUDE.md` 当前位置段更新（task-1 ship / 下一步 Sprint 5 待 Tim 选第 2 项）

### 兜底（未来真灾难时 restore 步骤）

```bash
ssh ubuntu@114.132.190.245
ls -lh ~/velo/backups/   # 找最新 dump
cd ~/velo
gunzip -c ~/velo/backups/velo_<TS>.sql.gz | sudo docker compose exec -T db psql -U velo -d velo
```

注意：restore 会**完全覆盖**当前 DB 状态 / 真灾难时再用 / 平时不要瞎跑。

### 下一步

**Sprint 5 task-1 ✅ / 待 Tim 选第 2 项**。Sprint 5 backlog 候选（按 ROI 排序）：
- D33 map matching（赛段匹配精度 / 太原西山外骑行也能匹配）/ 1-3 天
- task-4.3 §2 alembic 真 PG 双向（v5 task-1 解锁前置已完成）/ 30 分钟
- D28 高德地图未来 tab（2-3 天）
- tied PR my_rank off-by-one fix（半天）
- admin H5 真用回归 hotfix（按需 / Tim/CCF/颜颜每天用时触发）

---

## 2026-05-10 task-4.3 part-3: 真 E2E 走通 ✅ / v5 期完全 closure 🎯

### 触发

Tim 真上传 GPX 文件（晚上 22:09）→ task-4.3 part-3 §4 真 E2E 触发条件满足。按 CLAUDE.md "新会话起手必读" task-4.3 part-3 起手版执行 5 步 SSH verify。

### Verify 5 步全过

| 步 | 项 | 结果 |
|---|------|------|
| 1 | worker 日志 | `velo: app.activity.worker.parse_activity(326)` 1.5 秒 Job OK ✅ |
| 2 | activities 表 | id=326 / user_id=2 / status=completed / 8km / 825m 爬升 / 25 分钟 / 起骑日 2024-12-21 ✅ |
| 2 | segment_efforts | 0 行（不是 bug，下方分析）⚠ |
| 2 | notifications | 最近 2h 无新通知（GPX 真实日期 2024-12-21 在 progress_detector 滚动窗口外）⚠ |
| 2 | users.city | user 2 city=taiyuan ✅（worker city hook 自动设置 / SAVEPOINT 隔离工作） |
| 3 | /api/user/me/power-curve last_30_days | HTTP 200 / 7 档 schema 正确 / 全 0（GPX 无功率数据，符合）✅ |
| 3 | /api/user/me/heatmap (no city) | HTTP 200 / 237 tracks polylines / 含 326 新轨迹 ✅ |
| 4 | /api/segments/{id}/efforts/me | 跳过（活动 0 segment 匹配）|
| 5 | hotfix | 无 5xx / 无数据缺失 → 不需要 hotfix ✅ |

### "0 segment 匹配"分析（不是 bug，是真实情况）

activity 326 GPS 范围 lat 37.82-37.88 / lng 112.55-112.56（太原市区附近）。DB 24 条赛段全在西山一带：

```
万柏林生态园（长风口-启春阁）  距活动中心 7.98 km
凤颐谷-万亩爬坡               9.93 km
蒙山冶峪放坡                  10.94 km
西山旅游公路 奥申正爬         12.50 km
...
```

**最近赛段距活动 7.98 km** → 任何匹配算法都不可能 match。这条骑行不在已建赛段路径上是物理事实，而非算法 bug。

**Sprint 5 backlog 实证加成**：D33 map matching + "赛段覆盖稀疏"两项都拿到了真实证据。Tim 真用反馈预期：用户在西山外骑行就看不到任何赛段板块内容。

### "0 progress 通知"分析（正常 / 非 bug）

GPX 起骑日是 **2024-12-21**（17 个月前），不在 progress_detector 的 last_30_days 计算窗口内。如要测进步推送，需用最近 30 天内真实骑行的 GPX。

### 验收清单收口

- [x] pytest 全 passed（part-1 / 398 / commit `d9bcbc0`）
- [ ] alembic 双向跑通（**仍推迟到 Sprint 5 pg_dump 落地后** / 不阻塞 v5 closure）
- [x] 部署清单 9 项审完（part-1 / commit `d9bcbc0`）
- [x] **E2E 1 条核心反馈环手工走通**（part-3 / activity 326）
- [x] 10 容器生产 Up + 无 ERROR logs（part-2 / commit `d79c523`）

### 顺手修

CLAUDE.md pg_dump 命令 user 错（写 `-U postgres velo`，实测 DB user 是 `velo`）→ 改成 `-U velo velo`。Sprint 5 真跑 pg_dump 时不会再踩这个坑。

### v5 期 closure 🎯

- 4 个 Sprint（0/1/2/3/4）+ 4 个收尾 task（4.1 文档 / 4.2 黑盒 / 4.3 集成验证三 part / 4.4 复盘）全部 ✅
- 唯一遗留：task-4.3 §2 alembic 双向（被 pg_dump 阻塞 / Sprint 5 第一项解锁）

### 下一步

**Sprint 5 待 Tim 正式启动**。第一项 = 🔴 pg_dump 备份脚本（任意 DB 故障 = 数据全损 / tech-debt P0 / 也是 alembic 双向解锁前置）。

---

## 2026-05-10 task-4.4: v5 复盘归档（memory + ADR + tech-debt 沉淀）

> v5 期 4 个 Sprint 经验沉淀到跨会话载体，让 v6+ 不重蹈覆辙。按 architect 信条 11 + task 卡 §1 三问框架。

### 新增 memory（2 条 / 真正新模式）

- `feedback_spec_three_round_review_convergence.md` —— 大型 spec 双审多轮收敛节奏（v5 Critical 14→8→3→0 实证）/ 每轮 reviewer prompt focus 升级（自洽→边界→跨模块）/ 按 batch 隔离 / Critical=0 才停
- `feedback_spec_pre_grep_code_facts_table.md` —— spec §0.1 代码事实表写法 / [查询] 标 file:line / [推断] 标推断逻辑 / v5 实证把"现有代码事实错"占 Critical 比例从 71% → 12% → 0%

### 更新 memory（1 条 / 加 v5 实证段）

- `feedback_three_review_pipeline.md` —— 新增 § Codex 异源审甜区 vs 不擅长（甜区：纯函数边界 / 数据流跨模块 / API 契约 / 第三方库行为 / 生产配置 vs spec；不擅长：spec 自洽 / 命名风格 / 中文文档语义 / 跨 commit 历史决策追溯 / UI/UX / 业务规则正当性）+ 派 codex prompt focus 模板

### 新增 ADR（1 份）

- `docs/adr/011-为什么抽-app-common-层.md` —— v5 task-1.A.1 第二轮 spec 双审抓的反向依赖问题 / 解法 = `app/common/` 独立层 / 任意业务模块向下依赖 / common 不反向 import 业务模块 / 准入规则 + 失败边界 / 触发重评估条件
- ADR README v1.0 → v1.1 / 总表 10 → 11 / 下个编号 ADR-012

### 更新 tech-debt（4 条 P2/P3）

- v5-1 `power_curve` 1Hz 采样假设（P2 / spec §7 限定）
- v5-2 `infer_city_from_coords` 跨省 / 海外起点不准（P2 / 靠 admin 人工修）
- v5-3 候选池脚本周一次跑（P2 / 新赛段最长 7 天进候选池）
- v5-4 AI 草稿质量依赖人工审核（P3 / PRD D-P10 拍）

每条都标"重评估触发"条件，防 v6+ agent 主动优化没必要的项。

### 候选 ADR-012（AI 草稿走 RQ 异步）— 不写

理由：是 ADR-002（rq + Redis 异步队列）+ ADR-009（agent 层独立）的具体应用，不引入新架构 pattern。如果未来真出现"是否改同步阻塞"的争议，再开 ADR-012。

### Q1/Q2/Q3 三问复盘的处理路径

- Q1 新 bug 模式：v5 主要新 bug 模式都已在 v5 期内入 CLAUDE.md 技术栈陷阱清单（#11-#19 共 9 条）+ memory（SAVEPOINT / Python UnboundLocal 等）/ 不二次沉淀
- Q2 设计判断：spec 三轮收敛节奏 + 代码事实表 = 本次 2 条新 memory；其余如"主 agent 中层管理" / "codex 不可用 3 层兜底" / "真用回归 vs mock 盲区" 已存
- Q3 流程改进：双向异源审 / git diff 强制 / 部署 5 步 SOP 全在 feedback_three_review_pipeline.md + feedback_deploy_must_curl_verify_not_just_docker_ps.md

### v5 期 spec drift 项（保留状态 / 不再追平）

- requirements 用 deepseek 不是 spec 写的 anthropic（Tim 2026-04-29 拍 / 已落地）
- 单 worker 不是 spec 写的 --scale 3（用户量级满足）
- admin 走 IP + 9000 不是 admin.velo.com 域名（Tim 暂不买）
- pg_dump 备份脚本缺失（Sprint 5 必修 / tech-debt.md 顶部）

### 自检三问（task 卡 §3）

- 诚实：写了 v5 期 4 fail 一次性堆的 hotfix 链 / subagent 越界 / spec drift / 不美化
- 可复用：每条 memory 都通过 v6+ 场景测试（spec 双审收敛适用任何大型 spec / 代码事实表适用任何 spec writer 派工 / codex 甜区适用所有 codex 派审）
- 可执行：每条都有具体执行点（"派 codex 时 prompt 加 X" / "spec writer prompt 强制 §0.1" / "tech-debt 重评估触发条件"）

---

## 2026-05-10 task-4.3 part-2: §5 容器 verify ✅ / §2 + §4 推迟（Tim 拍）

### §5 生产容器 verify — 通过

```
sudo docker compose ps  # 10 容器全 Up
velo-admin-h5-1            Up 3 days     admin-h5
velo-api-1                 Up 13 hours   api
velo-caddy-1               Up 3 weeks    caddy
velo-cleanup-1             Up 4 days     cleanup
velo-curation-pool-cron-1  Up 4 days     curation-pool-cron
velo-db-1                  Up 3 weeks    db
velo-monitor-1             Up 3 days     monitor
velo-redis-1               Up 3 weeks    redis
velo-scheduler-1           Up 16 hours   scheduler
velo-worker-1              Up 16 hours   worker
```

api / worker logs 无 ERROR / Traceback / redis ping True。10 容器 = task-4.2 黑盒度补强后实数（含 v5 新增 curation-pool-cron + admin-h5 / 任务卡 §5 写的"8 容器"是旧值已过时）。

### §2 alembic 真 PG 双向 — 推迟到 Sprint 5 pg_dump 落地后

Tim 2026-05-10 拍：

**风险盘点**（读 v5 downgrade 脚本实证）：
- `phase5_v5_db_changes` downgrade 会 drop：
  - `notifications.payload` 列（v5 进度推送 payload 数据全失）
  - `segment_curation_pool` 整表（候选池清空）
  - `segment_ai_drafts` 整表（AI 草稿清空）
  - `users.city` 列（city 数据失）
  - `segments.{city, max_gradient, difficulty}` 列（24 赛段 v5 数据失）
- 脚本内置警告：`progress_monthly_summary`（24 字符）VARCHAR 缩 20 → truncation 报错
- 加上**生产无 pg_dump**（part-1 抓的真 gap），裸跑 downgrade 万一挂没法恢复

**推迟逻辑**：
- 生产 upgrade 已实证稳定（Sprint 1+2+3 部署 2026-05-05 / 4 天稳定运行 / 0 ERROR）
- downgrade 只在真回滚紧急场景需要 → 该场景下必须先有 pg_dump 兜底
- 无备份裸跑 = 数据无法恢复风险 ≫ 双向验证收益

**等待**：Sprint 5 pg_dump 备份脚本 + cron 容器落地后再跑 §2，关联记入 tech-debt.md 顶部 pg_dump 条目"blocker 关联"。

### §4 真 E2E — 留 part-3 单独跑

Tim 2026-05-10 拍：part-3 单独跑（Tim 下次真骑车上传 GPX 时同步走，不另搞 ad-hoc 测试 GPX）。

verify 路径（part-3 跑时）：worker 日志 → segment_efforts 写入 → progress_detector 触发 → notification.payload → power-curve 缓存失效 → 重新拉曲线 → /api/segments/{id}/efforts/me 即时反馈对比。

### 整体 part-2 结论

- §5 容器 verify ✅ 10 容器 Up + 0 ERROR + redis OK
- §2 推迟 / 关联到 tech-debt.md pg_dump 条目
- §4 留 part-3 / 等真用回归同步
- task-4.3 卡可关 part-2 闸；part-3 触发条件 = Tim 真上传 GPX

---

## 2026-05-09 Sprint 4 小程序 4 tab 重构 + D7 hotfix ✅ 全部完成

> v5 期末 / 主轴 = 小程序 5 → 4 tab 重构 + admin H5 真用回归 / 期间发现 6 hotfix 链 + D7 真排名后端补强。

### Sprint 4 baseline（开工前修 4 处文档 drift）

- `5dc4c33` test fixture 漂移修（period 真实枚举 / city 必填 / self profile 加 city / 看他人砍 ftp）
- `cbe34ca` 后端 P1-3 + P1-4：self profile schema 加 city / 看他人 schema 砍 ftp
- `96e599f` PRD/plans 4 处 drift 修复 + D16-D20 决策记录
- 入册记忆 `feedback_grep_endpoint_schema_before_specs.md`（写 PRD/plans 前必 grep schemas.py 实证）

### task-4.1 个人页框架改造

- `1fd0c43` 5 区块 + city badge fallback + 2 槽位 placeholder / 三审通过 + 真机验证

### task-pre-4.2 后端 power-curve 滚动窗口升级

- `7396ea5` period 5 档自然历法 → 滚动窗口 `last_30_days/90/180/365/all_time` / 文档 4 处同步 / D21 component 化哲学入册

### task-4.2 个人页内容塞入 + v2/v3 polish + 真闭环（6 次 hotfix 链）

- `81862e5` v1 双 component 路线（power-curve-card + heatmap-card / D21 落实）
- `5d7cba9` v2 polish — power-curve 7 档 [0,3,30,60,300,1200,3600] + heatmap polylines（marker→polyline / D26 + D27 + D28 + D29）
- `f519170` v3 polish — D30 city 改可选 + D31 GCJ-02 坐标转换 + D32 power-curve period 切换 UI
- `e232604` hotfix v3-1 heatmap-card polyline 总点数 cap 8000（防 setData 1MB 上限）
- `3321c46` hotfix v3-2 heatmap polyline cap 8000 → 50000（修网格状直线视觉灾难）
- `46a4fc0` hotfix v3-3 heatmap segment split / 修虚假对角长直线
- `b0c1799` hotfix v3-4 heatmap 砍 cap / 恢复 v3 polish 第一次部署精度
- `9f7d9b7` hotfix v3-5 power-curve N+1 修 / 24s → 1-2s（IN 查询 + only 字段）
- `bb94a4e` + `5c8228c` hotfix v3-6 heatmap 分层虚实线 + simplify 1500 + backfill（修山区物理 GPS 误差散网 / 中位数 30m → 21m / >500m segment 1263 → 443）
- `faba98f` task-4.2 真闭环总结 + D33 map matching backlog 入册（Sprint 5/6 跟 D28 高德 webview 一起做）

### task-4.3 用户详情页（看他人主页）

- `5de9f40` 后端补 2 endpoint：`GET /api/user/{user_id}/power-curve` + `GET /api/user/{user_id}/heatmap`（同 self 函数 + 不同 user_id / city 同 v3 polish 改可选）
- `203ed44` 小程序新建用户详情页 page + 头像跳转入口（notification only / D-P09 范围）/ component reuse（power-curve-card + heatmap-card 已建好 / 4.3 不重写）

### task-4.4 explore tab 改造 + 砍 leaderboard tab（5 → 4 tab）

- `224f22f` explore tab 瀑布流 + 6 城筛选 + NEW 标签（30 天判断）
- `4d0ab12` 砍 leaderboard tab + 跳转改向（D5 决策 / "完全没用"）
- `9250106` hotfix - SegmentListItem 加 created_at 让 NEW 标签生效

### task-4.5 赛段详情页（4 区块）

- `813e96d` step 1 空架子（让 task-4.4 能跳转）
- `958c5bd` 4 区块完整 ship（含全网排行榜 top 10 + 我的排名 / D7 反转后展示）

### review fixup + D7 真排名 hotfix

- `9b558af` batch 2 review fixup（3 Important + 1 Nice）
- `33212a1` D7 hotfix - LeaderboardResponse 加 my_rank + my_elapsed_time（后端真排名 / 前端可直接用）
- `5062793` D7 hotfix fixup - 补 2 边界测试 + tied 语义文档（tied PR my_rank off-by-one 留 backlog）

### Sprint 4 元层升级（2026-05-08 ~ 05-10）

- memory `feedback_v2_polish_must_dispatch_subagent.md`（v2 polish 类任务必派 subagent / 元认知偷懒"自己快"是错觉 / 实证 77 min）
- memory `feedback_deploy_must_curl_verify_not_just_docker_ps.md`（部署后必须 curl 真 endpoint 验证 / 三次踩坑实证 / 部署 SOP 5 步）
- D33 map matching backlog（山区 GPS 散网根治 / OSRM 容器或高德 navigation match API）
- **2026-05-10 Tim 升级硬规则（双向适用）**：codex 异源审 + Claude 双审 + 主 agent commit 前自审 / 全部必须**先读真 git diff** / 不只读 agent 报告。派 codex / Claude reviewer 时 prompt 第一动作必须强制 `git show <commit>` / `git diff HEAD <files>` / **禁止预先告诉 agent "改动内容摘要"**（误导源 / agent 跳过 diff 走推断 / 假阳性 + 漏关键盲区）。memory `feedback_three_review_pipeline.md` § 2026-05-10 升级硬规则双向适用。实证：D7 hotfix 第二轮 codex 抓 2 真 Important + 1 Nice 全是基于真 diff（vs 信息框架推断会全漏）/ task-4.1 文档刷新双 review 抓 5 Critical+Important（subagent 黑盒化脑补）反向证明硬规则 ROI。

---

## 2026-05-10 task-4.3 part-1: 集成测试 + 部署清单审（§1 + §3 完成 / §2/4/5 待 Tim 明天）

### §1 全单元 + 集成测试 — 通过

```bash
python3 -m pytest tests/ --no-header -q
398 passed, 53 skipped, 0 failed in 3.24s
```

实际测试数 398（远超 spec 预期 250 / v4 期 181 + v5 新增 217）/ 53 skipped 主要是真 PG 测试（dialect 守卫 SQLite 不跑）+ 网络调用 mock-only 场景。

### §3 部署前 9 项清单审 — 5 项 ✅ / 3 项 spec drift（不阻塞）/ 1 项真 gap

| # | spec 要求 | 实际 | 状态 |
|---|---|---|---|
| 1 | requirements.txt 含 anthropic | 用 **deepseek**（Tim 2026-04-29 拍 / 国产 + 国内访问稳 / 极便宜）| ⚠ spec drift（已落地 / spec 没刷）|
| 2 | env: ANTHROPIC + FEISHU + RQ_QUEUES | ✅ DEEPSEEK_API_KEY + FEISHU_BOT_WEBHOOK + RQ_QUEUES="velo,ai_drafts"（实证）| ✅ |
| 3 | worker --scale 3 部署 | 实际**单 worker**（用户量级满足 / 100 活跃 ≪ 3 worker 必要量）| ⚠ spec drift（不阻塞）|
| 4 | alembic 真 PG 跑通 | **留 §2 / 待 Tim 明天 SSH 跑** | ⏳ |
| 5 | backfill_phase5 unknown < 30% | ✅ commit daf6f1f + 5c8228c / 24 segments + 2 users 全回填 / unknown 占比 0% | ✅ |
| 6 | admin.velo.com 域名 + Caddyfile | 实际 **IP + 9000 端口**（Tim 暂不买域名 / Sprint 3 D.5 决策）| ⚠ spec drift（不阻塞）|
| 7 | DeepSeek API 连通 | ✅ Sprint 1 task-1.B.1 ship 时已验证 / 生产 .env 已配 | ✅ |
| 8 | 飞书 webhook 连通 | ✅ **D 决策（Tim 2026-05-06）**：生产 .env 不配 webhook / log-only 模式 / 探针真生效 | ✅ D 决策落地 |
| 9 | pg_dump 备份范围 | 🔴 **scripts/ 0 hits / 完全没备份脚本**（已 ship 半年生产 / 真 gap） | 🔴 tech-debt |

### 真 gap：生产无 pg_dump 备份脚本

velo 生产已 ship 半年（v0 至 v5 / 100 活跃用户 / 数据库每日增长）/ 但 `scripts/` 里**完全没有备份脚本**。pg_dump / volume snapshot / cron 全无。

任意场景命中 = 数据全损：
- db 容器 OOM / docker prune / 磁盘故障 / 误删 → users / activities / segments / segment_efforts / strava_imports 等核心表全丢
- v5 新加 segment_ai_drafts / segment_curation_pool 也无保护

**修法**：写 scripts/backup_pg.sh + cron 容器（每天 pg_dump 写到 /backups volume / 留最近 30 天）/ 简单 sh 脚本 + 30 行 docker-compose / 0.5d 工作。**进 tech-debt 高优先级 / Sprint 5 必修**。

### 整体 part-1 结论

§1 测试全过 / §3 5 项 OK + 3 项 spec drift（不阻塞 production / spec 待刷）+ 1 项真 gap（备份脚本 / Sprint 5 修）。

**待 Tim 明天**：§2 真 PG alembic 双向（SSH 服务器跑）+ §4 真 E2E（Tim 真机上传 GPX 走核心反馈环）+ §5 部署 verify 8/10 容器 Up（已 partial verify / 完整跑一次）。

---

## 2026-05-10 task-4.2 黑盒度三问体检（v5 收尾防黑盒化）

主 agent 自我体检（CLAUDE.md "防黑盒化"硬要求 / 每期收尾必跑）：

### 第一问：10 分钟讲全貌 — 通过 / 1 处补强

主 agent 对 architecture-guide.md 不查文档讲：v5 4 主轴（B/C/A/D）+ 8 业务模块 + common 共享层
+ 9 张表（v5 +2: segment_ai_drafts / segment_curation_pool）+ 核心反馈环 + 容器拓扑。能 10 min 内讲清。

**补强**：architecture-guide §3.1 容器清单 8 → 10（加 curation-pool-cron + admin-h5 / 之前 task-4.1 文档刷新漏了 / 真 docker-compose 10 个 service 实证）

### 第二问：16 条数据流复述 — 通过

不查文档 mental check 复述：
- v0-v4 9 条：核心反馈环 / Strava OAuth / Strava 历史导入 / Strava Webhook / 微信登录 / 通知 / 详情聚合 / 赛段排行榜 / cleanup 僵尸扫描
- v5 新增 7 条：AI 草稿 / monitor 探针 / power-curve + 缓存 / heatmap + city / 看他人主页 / 赛段创建 (from-gpx + from-activity) / 即时反馈 (EffortCompareResponse)

链路 4 Strava Webhook + 链路 8 赛段排行榜的具体 SQL / 校验细节模糊 / 但 data-flow-guide.md 已写清 / 不算"卡壳"（任何 reviewer 都需要查文档看细节）。

### 第三问：30 秒读懂任意文件 — 抽 5 个 / 1 处补强

抽样：
- ✅ `app/agent/tasks.py`：开头"AI 草稿 RQ 异步任务入口" + 干啥用 + 操作注意（3 项）/ 30 秒懂
- ✅ `app/monitor/admin_h5_health.py`：开头"admin H5 端到端监测探针 / 2026-05-06 事故防御" + 干啥用 + 操作注意（5 项）/ 30 秒懂
- ✅ `app/common/geo.py`：开头"GPS → 城市的查表器" + 生活类比（前台中英名牌）+ "为什么矩形不多边形" / 30 秒懂
- ✅ `app/segment/service_create.py`：4 行说明（来历 + 行为不变）/ 30 秒懂
- ❌ → ✅ `app/admin/dependencies.py`：原顶部仅 1 行 `"""admin 模块依赖函数。"""`不达标 → **本次补强为完整 docstring**："管理后台门口的保安"+ 干啥用 + 类比（办公楼保安）+ 操作注意（6 项）+ 输入输出

### 整体结论：**通过 / 防黑盒化达标**

下次任何新 subagent / 新人打开任意文件秒懂"这个文件干啥的 / 改它什么坑"。下个 v6 期可基于此架构图扩展，不会因黑盒化重构。

---

## 2026-05-09 task-4.1 文档刷新（v5 收尾索引刷新）

- `docs/architecture-guide.md`：加 v5 4 新模块（common / agent / monitor / admin）+ 模块依赖图新边 + 数据表 9 / API 总路由 41 / 9.1 已修 12 + 9.2 删 Sprint 0 已修 P1 5 项 + 附录 C 加 v5 收尾体检
- `docs/data-flow-guide.md`：加链路 15（赛段创建 admin from-gpx + from-activity）+ 链路 16（即时反馈对比 6 字段）/ 链路 14 加 task-4.3 看他人 power-curve + heatmap 扩展段
- `docs/changelog.md`：追加 Sprint 4 完整 task 清单（含 6 hotfix 链 + D7 真排名）+ 本次刷新条目
- `docs/tech-debt.md`：移除 Sprint 0 已修 P1 5 项（datetime / ensure_valid_token 行锁 / 未绑定路径 / .get() / scheduler Redis 复用）+ 新增 v5 实施期发现的 4 项（D33 map matching / tied PR my_rank / AI 角色重定义 / app/admin/service.py 拆分）

---

## 2026-05-06 Sprint 1+2+3 收尾会话（task-3.B.2 + 502 hotfix + monitor 探针 + D 决策）

### task-3.B.2 segment-creator.html 增强 + 搬到 admin-h5 repo
- velo `c01b7fd` 后端新增 `GET /api/admin/activities/{id}/trackpoints`（require_admin / 不限 owner）+ 5 单测 + `tools/` 整目录删除
- admin-h5 `71de031` HTML 加"从已上传活动"模式 / fetch URL 切到 admin from-gpx / API_BASE_URL 相对路径 / AppLayout 侧栏第 4 项"赛段创建工具"
- Codex 异源审 Critical=0 / 2 Important 全修（parseInt 严格化 + AbortSignal.timeout）

### 2026-05-06 admin H5 502 事故 hotfix
现象：admin H5 公网 502 + 前端 toast 显示"token 无效或过期"。Tim 重签 token 仍失败 / 浪费 30 分钟。

三层 root cause：
1. 表层 — LoginPage catch-all 把 401/403/5xx/网络错全显示同一句"token 失效"
2. 中层（真根因）— admin-h5 nginx `proxy_pass http://api:8000` 缓存 api 容器旧 IP / api 重启换 IP 后一直连旧 IP → 502
3. 深层 — admin H5 没端到端监测探针 / 真用打开页面才发现

修复（2026-05-06 双 commit）：
- velo `f5c4cc2` deployment-diary 加事故复盘 + 4 条未来 agent 硬规则
- admin-h5 `91ca336`：nginx.conf 加 resolver + 变量化 proxy_pass / src/api/error.ts 升级 getErrorDetail 单一真相源 / src/api/client.ts interceptor 修 race（codex 异源审抓到）

### task-monitor-admin-h5 端到端监测探针 + D 决策
- velo `6d6657f` 加 `app/monitor/admin_h5_health.py`（探静态站 + 反代到 api / 严格断言 4xx 防 SPA fallback 漏报 / Redis SETNX 5min 去抖 / 11 单测）
- velo `357285f` D 决策（Tim 拍）：velo 现阶段告警通道暂不接通 / 探针 log-only / 飞书 webhook 代码沉淀 / .env 加一行可激活

### 元层 lessons（已沉淀）
- velo `CLAUDE.md` 技术栈陷阱清单加 #18（nginx + docker DNS 缓存）+ #19（第三方依赖激活状态 mock 测不到）
- velo `CLAUDE.md` 已知风险表加 3 条全 🟢
- memory 加 1 条 project（D 决策）+ 1 条 feedback（诊断顺序）+ 更新 1 条（mock 盲区第 5 类）

---

## 2026-04-29 起 第 5 期：赛段内容深化 + 数据成长 + 个人页 + admin 工具（进行中）

### 启动期（2026-04-26 ~ 04-29）

- 战术 PRD `docs/prd/phase-5-prd.md` v0.4 完工（Tim 拍 11 yes 决策点）
- 技术 spec `docs/spec-v5.md` 2879 行，3 轮双审 Critical 14→8→3→0 收敛
- 实施计划 `docs/archive/plans-phase5-*` 29 张 task 卡 + README

### Sprint 0：地基修补（5-8 天）✅ 全部完成

| 任务 | 状态 | commit |
|------|------|--------|
| 0.1 datetime 全局 tz-aware | ✅ 三审通过 + alembic 真 PG 双向验证 | `4a94097` |
| 0.2 ensure_valid_token 签名改造 + populate_existing | ✅ Codex 异源抓陷阱第 12 条 | `022e2b1` + `db7e475` |
| 0.3 ensure_valid_token 未绑定路径 + scheduler 兜底 | ✅ | `07327b1` |
| 0.4 SQLAlchemy legacy `.get()` 替换 | ✅ | `5e44c4f` |
| 0.5 + 0.8 scheduler Redis 复用 + app/queue.py 单一源 | ✅（0.5 并入 0.8）| `04bb17d` |
| 0.6 v5 主迁移（segments + users + 2 新表）| ✅ Codex 异源抓 2 Critical | `91a3691` |
| 0.7 老数据回填脚本 + 生产部署 | ✅ 24 segments + 2 users 全部回填 / 双主驾首次互审 | `daf6f1f` + `01caa5e` |

### Sprint 1：赛段内容深化（5-7 天）✅ 全部完成 / 2026-04-30

| 任务 | 状态 | commit | 测试 |
|------|------|------|------|
| 1.A.1 segment 算法纯函数 + common 包 | ✅ Codex 异源抓 2 Critical（haversine 对跖点 / spec import 路径） | `a9c1bff` | 41 |
| 1.A.2 segment service 扩展（搜索 + 即时反馈 + from-activity）| ✅ **双主驾首战**：codex 主开发 + Claude 异源审 2 轮收敛（I1 SQL seq 切片 / I2 elevation_loss 字段缺）| `9b24465` | 13 |
| **E1 修 task-1.A.2 service 契约对齐 spec §3.2.1** | ✅ task-1.A.3 开工时发现 codex 第一轮把 6 字段对比类语义换成 4 字段排名类（current/last/pr/diff/is_pr/is_first → my_best/my_latest/rank/total_riders），已重写 | （并入 1.A.3 commit） | （并入 1.A.3 测试）|
| 1.A.3 segment router 扩展 + 即时反馈 endpoint | ✅ Claude 主开发 + codex 异源抓 distance_km/distance 字段名漂移（doc fix `1a0631f` 同步 spec）| `bbef245` + `1a0631f` | 11 |
| 1.B.1 agent 模块（DeepSeek + RQ 异步 + 状态机保护） | ✅ Claude 主开发 + codex 异源抓 1 Critical（生产 docker-compose worker 缺 DEEPSEEK_* env）+ 3 Important（PROMPT_TEMPLATE.format 漏 catch / 状态机测试只验 1/3 / 并发测试可能假通过）| `fc3f007` + `70d4104` | 15 |
| 1.C.1 monitor 模块（worker 软目标 4min + 飞书告警）| ✅ Claude 主开发 + codex 异源抓 1 Important（httpx.post 默认遇 5xx 不抛 → raise_for_status 修补）| `f228a6c` | 6 |

**Sprint 1 收尾 metrics**：
- 7 commit / 全套 pytest 281 passed / 2 failed（task-0.7 _FakeSegment tech-debt / 0 回归）
- 双主驾两类协作模式都跑过：codex 主+Claude 审（task-1.A.2）/ Claude 主+codex 审（task-1.A.3 / 1.B.1 / 1.C.1）
- codex 异源审 4 task 全抓到非平凡问题（spec 字段语义换 / distance_km 漂移 / format 漏 catch / httpx 5xx 静默）
- **3 次同类 spec/契约偏离失职**（详见 2026-04-30 §7 升级）

### Sprint 2：A + B + C 主轴 ✅ 全部完成 / 2026-04-30

| 任务 | 状态 | commit | 测试 |
|------|------|------|------|
| 2.B.1 power_curve 算法 | ✅ codex 抓 1 Important（拼接测试假阳性）| `661a717` | 15 |
| 2.A.1 progress_detector + worker hook + SAVEPOINT 升级 | ✅ 主动捕获 spec §3.4 隐患 / codex 网络断走 3 层兜底 | `7611042` + `3abcd83` | 10 |
| 2.C.2 part1 power_curve service + 真 invalidate | ✅ codex Critical=0 / 1 Nice-to-have 已修 | `a306bd1` | 7 |
| 2.C.1 city 字段防回退测试（verify-only）| ✅ task 卡 grep 实证 ORM/Constraint/migration 全已落地 | `eee3d98` | 5 |
| 2.C.2 part2 余下 3 函数 + worker city hook | ✅ codex 抓 2 Important（白名单测试弱 / SAVEPOINT 隔离）/ ⚡ UnboundLocalError 修（重复 import 触发 Python 函数作用域）| `1250df1` | 16 |
| 2.C.3 user.router 4 个新 endpoint | ✅ 路径命名修订（spec /api/users → /api/user / Tim 拍 A）/ codex 配额上限走 3 层兜底 | `bdec206` | 17 |

**Sprint 2 闭环 metrics**（2026-04-30）：
- 6 commit + 1 docs（CLAUDE.md 陷阱 #13）+ 1 doc-sync（neat-freak 中期）= 8 commit
- 全套 pytest 347 passed（v5 新增 70 / 0 回归）
- 反馈环完整：上传 → worker (detector + city 自动推断 + invalidate cache) → 用户进个人页查 power-curve / heatmap / 看他人主页

**Sprint 2 沉淀**（2026-04-30 早晨 + 中午两轮复盘 + 收尾）：
- memory 新建 `feedback_savepoint_isolation_for_inner_modules.md`（跨模块 SAVEPOINT pattern）
- memory 更新 `feedback_phase5_task_card_grep_stale.md`（加 2.A.1 + 2.C.3 实证 / 硬依赖 + 路径命名两类漏写）
- memory 更新 `feedback_three_review_pipeline.md`（加 codex 网络断 + 配额上限 3 层兜底段）
- CLAUDE.md 陷阱清单第 13 条（跨模块 SAVEPOINT）
- spec-v5.md §3.4 SAVEPOINT 升级注释 + §4.2 路径命名修订段
- ⭐ **SAVEPOINT pattern 复利**：早晨为 detector 升级，中午 codex 又指出 worker city hook 同样需要——同模式第二次落地

### 2026-04-30 §7 mental check 3 问 → 5 问升级

**触发**：Sprint 1 内连续 3 次同类失职：
1. task-1.A.2 service 偏离 spec §3.2.1 字段名/语义全换（codex 第一轮 + Claude 第一轮异源审都漏）
2. task-1.A.3 决策点 2 拍"保留 distance"后只动代码不改 spec → codex 异源审才抓
3. task-1.C.1 描述错把 monitor（运维监控）说成 progress detector（用户进步推送）

**落地（commit `02261e4`）**：
- §7 mental check 加第 4 问"承诺立刻动作落实"（来自 memory `feedback_promise_must_action.md`）
- §7 mental check 加第 5 问"决策即同步 spec/task/文档"（来自 2026-04-30 task-1.A.3 失职）
- CLAUDE.md 顶部 mental check 同步 3 问 → 5 问
- 5 条翻车实证表沉淀（每个 mental check 问都有锚）
- 2 条对应 memory 标记"已升级 §7"避免双轨漂移
- 新增 memory `feedback_spec_drift_immediate_doc_fix.md`

### 2026-04-29 战略升级：双主驾协作架构 v2.0 ⭐

**触发**：task-0.7 部署链路暴露 6 个真实问题（mock ≠ 真环境 / 容器 rebuild 验证 / PAT 泄露 / progress_records 误报 / EWKB hex 字段 / 信息整流原则违反）→ Tim ↔ Claude 长讨论收敛 4 议题。

**落地（4 commits）**：
- `1bd15ec` `codex-division-of-labor.md` 改名 → `agent-collaboration.md` v2.0（660 行，从 Claude 中枢改为双主驾）+ CLAUDE.md 顶部加协作硬规则（信息整流 / 少增文档 / 动作 trigger 自查）+ 5 文件 11 处引用更新
- `a836637` `docs/README.md` §5.F 加升级路由表（教训类型 → 进哪份文档）
- `daafe62` changelog 加战略升级总结 + 明日交接桥梁
- `038dd5e` Tim 双重 push back 后立规则：CLAUDE.md 顶部加 §🧭 决策反向索引（7 类决策 → 必查规则）+ agent-collaboration.md §10.X 工作交接桥梁机制 + §12.X 规则成熟度原则（含 80% 高频例外）
- 3 条新 memory：`feedback_promise_must_action.md`（承诺必落实）/ `user_decision_style_defense_and_roi.md`（Tim 决策风格画像）/ `feedback_rule_system_entropy_risk.md`（第三阶熵增警觉）

**核心规则（4 议题决议，详见 agent-collaboration.md）**：
- **B 议题**：信息整流原则——给 Tim 用翻译层句式，禁止贴 raw diff；高风险动作硬 checklist；最低限度不确定度自报；动作 trigger 自查（mental check 4 问）
- **A 议题**：运行时验证门禁——动 DB / 外部 API / 文件系统类代码必跑命令，配本地 docker stack 替代频繁 SSH 生产
- **C 议题**：memory → 文档升级机制——半自动 + agent 自决目标 + 翻译层问 Tim
- **D 议题**：切换 trigger——按自然边界切 + 例外清单 + Tim 主权

### Sprint 3：admin 工具 + admin H5（✅ 完成 / 2026-05-05 代码层 + 2026-05-06 生产部署）

| 任务 | 状态 | commit | 备注 |
|---|---|---|---|
| 3.A.1-3.A.5 admin 模块框架 + 候选池 + 草稿 + 批量管理 + from-activity | ✅ | 多 commit | A 主轴 5 connection 串行 / 10 endpoint |
| 3.A.6 admin from-gpx + 老 endpoint Sunset 2026-06-30 + Hausdorff 共享 helper | ✅ | `1432fad` | reviewer 抓 5 真问题全闭环 |
| 3.A.6 follow-up dev stack 真 PG Hausdorff 集成测试 | ⏳ tech-debt | `777ae79` 记入 | 留 Sprint 3 收尾 |
| 3.A.7 admin whoami endpoint | ✅ | `4796704` | C2 方案 C / admin H5 登录验证用 |
| 3.C.1 候选池脚本 + cron | ✅ | `6c14efa` | C 主轴 |
| pre-3.B segment/service.py 拆分（红灯清理）| ✅ 793→189 | `1c70a02` | 元层 blocker / D.1 实施前必做 |
| 3.B.1 D.1 admin H5 项目骨架 + 登录 + 路由壳 | ✅ vite build 262ms / 0 TS errors | admin-h5 repo `b8d4043` | 独立 repo / Vite + React 19 + TS + AntD 6 |
| 3.B.1 D.2 候选池审查页 | ✅ | admin-h5 `772be83` | codex 主开发 + Claude 集成审 I1/I2/I3 整改 |
| 3.B.1 D.3 AI 草稿审核页 | ✅ | admin-h5 `5047d98` | codex 主开发 / mutation 三泛型 + useRef 防 timer 泄漏 |
| 3.B.1 D.4 批量管理页 + I1/I2 整改 | ✅ | admin-h5 `c7cbfcb` | 抽 `getErrorDetail` 公共 helper（3 处复利修补 / 双向异源审首次实证） |
| 3.B.1 D.5 容器化部署文件 | ✅ | admin-h5 `7e736d4` + velo `c48ab8f` | Claude 主开发 Dockerfile/nginx.conf/docker-compose / codex 异源审 |
| Sprint 1+2+3 一次性生产部署（39 commit / 12 周积压） | ✅ | velo `1f06155` (含 9 hotfix) | 详 `deployment-diary.md` "✅ Sprint 1+2+3 部署完成" 章节 |
| 3.B.2 segment-creator.html 增强 | ⏳ | - | 下一步 / 真生产已就绪可起手 |

**Sprint 3 元层升级（2026-05-05 本会话）**：
- 全局 `~/.claude/CLAUDE.md` TL;DR + §2.1 加"元认知批判性思考（决策前必跑 / 区分合格 vs 顶级工程师的核心层）"为最高优先级锚点
- velo CLAUDE.md 技术栈陷阱清单第 15 条（PostGIS `ST_*` 函数 SQLite 测试不可用 / 加 dialect 守卫）
- memory 6 处升级（含元认知批判 / 视觉冲击 vs 真复杂度 / 读 diff 不只读报告 / pytest exit code 不可信 / Edit 全角标点 / untracked 待办列表 / 详 MEMORY.md）

**Sprint 3 完整 metrics（截止 2026-05-06 部署完成）**：
- velo backend：~12 commit / admin endpoint 11 个 / admin pytest 17 passed / 9 hotfix（部署后真用回归暴露 / 详 deployment-diary）
- admin-h5 repo：5 commit（D.1 → D.5 / Vite + React 19 + TS + AntD 6）
- 一次性部署 Sprint 1+2+3 = 39 commit / 12 周积压清空 / 实际窗口 ~1h（image cache 复用 / 远低于 2.5h 预算）
- **工作流核心收获**（本 Sprint 独有 / 已沉淀别处不重复）：
  - codex 主开发 + Claude 多轮审 = 连续 4 次成功（D.2/D.3/D.4 codex 主 / D.5 Claude 主）
  - **双向异源审硬规则升级**：Claude 主开发也必须 codex 异源审（Tim 拍"旁观者清"原则 / D.4 实证：Claude 写错 typing → codex 模仿 baseline 抄成 3 处复利 / 单向审查 = 盲区暴露 / 详 agent-collaboration §3.5）
  - **真用回归 = final gate**：三审 + 单测 + Codex 全过 ≠ 生产工作 / 9 hotfix 中 5+ 个真用才暴露（详 memory `feedback_real_usage_vs_mock_blindspot.md`）

### 待办（2026-05-06 起）⭐ 新 session 必读

1. **下一个 sub-task = task-3.B.2 segment-creator.html 增强**（admin H5 收尾）：
   - task 卡：`docs/archive/plans-phase5-task-3.B.2.md`
   - 前置都满足（D.1-D.5 完成 + 生产部署 + admin POST endpoints 已 hotfix 跑通）
   - 起手第一动作：grep verify task 卡现状（task 卡 grep 数据普遍 stale / 详 memory `feedback_phase5_task_card_grep_stale.md`）
2. ⏳ 待 Tim 触发：学 git 分支多线程开发 / 专题讨论"规则系统熵增"（第三阶问题）/ 项目根 untracked 目录集中处理（`.claude/worktrees/` + `app/middleware/`）

**新 session 起手必读顺序**（compact 后或 /clear 后）：
1. CLAUDE.md（项目规则 + 进度 / **Sprint 3 D.1-D.5 + 部署完成** / 下一个 = task-3.B.2）
2. 本 changelog 待办段（task-3.B.2 入口）
3. memory 自动加载（26 条 / 含元认知批判 / 双向异源审 / 真用回归 final gate / 等）
**禁止**：读 spec-v5.md 全文（task 卡有 spec 行号引用，需要时只读那段）。

**dev stack 已就绪**（task `3e9f50d` 落地）：
- `docker compose -p velo-dev -f docker-compose.dev.yml up -d` 独立 project name 不撞生产
- 端口 db:5435 / redis:16379 / api:8001 / monitor 容器同步生产
- `python -m scripts.seed_dev_data` 写入 7 segments + 2 users + 60-tp activity + 乱序 efforts

### 关键决策

- LLM API 走 DeepSeek（OpenAI 兼容 SDK，Tim 2026-04-29 拍）
- 赛段目录公开访问 / 看他人主页默认公开 / AI 草稿 202 异步
- admin H5 独立部署（域名暂不买，先 IP）
- **agent 协作模式：双主驾 + 单一裁决链**（v1.x Claude-中枢 → v2.0 双主驾对称）

---

## 2026-04-17 ~ 2026-04-18 第 4 期：前端反馈环闭合 + Strava 集成加固

### 一、产品目标
把后端早就做好的成就数据（通知/荣誉/Strava 同步）真正送到用户眼前，顺手修 8 个 Critical + 11 个 Important 历史风险。

### 二、9 批闭环 + 双审制度（2026-04-17 晚 → 04-18 凌晨）

| 批 | 任务 | 主体改动 | 双审收获 |
|----|------|---------|---------|
| 7.1 | Alembic 迁移 + 4 model 改动 | is_read / activity_type / mute_notifications / updated_at tz / 外键 SET NULL | 上线后发现 conftest 遗漏，事后补 fix commit |
| 7.2+7.3 | OAuth state 加固 + callback 防重复 | Redis nonce GETDEL 一次性消费 / 7 步 callback 流程 / UNIQUE 检测先于 cleanup | 合并成单 commit（中间态会炸不可拆）|
| 7.4 | Webhook subscription_id 校验 | 双门校验（未配置 503 / 不匹配 403）| 老 webhook 测试需补 subscription_id mock |
| 7.5 | import-progress stalled + Redis 限速 | view_status 派生态 / 1s/user 限速 | 老测试契约迁移 |
| 7.6 | Strava 现有函数加固 | I7/I8/I9/I10：401 pause imports / 行锁 / 连续 2 次空确认 / 手动 sync 联动 | — |
| 7.7 | 解析器入口 activity_type 分流 | 抢锁后、下载前分流，省 I/O | — |
| 7.8 | mark-all-read + unread_count | service.mark_all_read + GET 加 unread_only / 响应永远带 unread_count + outerjoin Segment | — |
| 7.9 | scheduler 容器部署 | scheduler.py + docker-compose 加 7th 容器 | **集成审抓出 tier1_completed 无行锁 → SQL 原子表达式修复**（code-reviewer 没看到）|
| 7.10（瘦身）| 小程序前端通知反馈环 | 通知中心 + 荣誉页 + 红点 + 免打扰 + api.js 扩展（**砍 Strava 绑定 UI** 留第 5 期）| **集成审抓出 leaderboard.js 不读 segment_id → 反馈环断**（差点把核心目标交付一半）|

### 三、双审制度沉淀

第 4 期最大教训：**v1-v3 单 agent 模式 → v4 多 subagent 模式后我没及时同步纪律 → 批 1-6 跑完才发现没做"代码层双审"违反 CLAUDE.md 明文**。

事后双审一次抓 1 Critical + 6 Important（ORM/DB schema 不一致、重复 detect_events、非骑行活动 activity_type 错、行锁测试假通过等），证明双审硬性的价值。

**沉淀**：
- `~/.claude/skills/architect/SKILL.md` 信条 5 升级为"两处必做硬性"（spec 层 + 代码层），强调 prompt 互补
- `velo/CLAUDE.md` 顶部加 3 条硬规则：commit 前 4 问 / 任务规模预算（每期 ≤6 任务）/ 防火墙式扩展（新功能默认放新表）
- `velo/CLAUDE.md` 大瘦身 482 → 231 行（与 architect skill 重叠的方法论砍掉留指针）

### 四、规模数据

- 13 个 commit（含双审修复 4 个 fix commit）
- ~3500 行净增（后端 + 小程序 + 文档 + 测试）
- 50+ 新测试用例
- 全套：181 passed / 0 failed
- 工时：约 10 小时（含规划、双审、3 次重大反思）

### 五、留 P1 给第 5 期（详见 docs/tech-debt.md）

- datetime 栈内不一致（naive vs aware 全量迁移）
- ensure_valid_token 行锁约束封装（防绕过）
- service.py 727 行（红灯）拆分（OAuth / token / sync）
- handle_callback 7 步流程拆函数
- _run_tier1 拆 fetch / persist / progress 三步
- N+1 查询历史 TODO 清理

### 六、未做（明确推迟）

- Strava 绑定 UI（task-7.10 砍掉，留第 5 期）—— 当前用户走后台手动绑定
- 后端集成测试（mock 链路，单元测试已覆盖关键路径，价值低）
- 真实 Strava E2E（生产部署后做）
- 前端手工回归（部署后小程序开发者工具跑）

---

## 2026-04-09 ~ 2026-04-13 本轮开发总结

### 一、GCJ-02 → WGS-84 坐标系转换（04-09）
- **问题**：赛段创建接口 reference_points 无坐标系约定，腾讯地图坐标（GCJ-02）与 GPX 轨迹（WGS-84）偏移 100~700m，导致 50m 容差下匹配必然失败
- **修复**：新增 `app/segment/coord_convert.py` 纯函数模块，SegmentCreateRequest 增加 `coordinate_system` 字段（默认 gcj02），service 层自动转换
- **测试**：7 个转换测试（`tests/test_coord_convert.py`）
- 文件：`coord_convert.py`、`schemas.py`、`service.py`、`router.py`

### 二、赛段创建工具（04-09）
- **功能**：Strava 风格的管理员工具（`tools/segment-creator.html`），从 GPX 文件截取赛段
- **交互**：GPX 导入 → Chart.js 海拔剖面图 + 双滑块拖选 → Leaflet+OSM 地图联动 → POST /api/segments 创建或 JSON 降级下载
- **键盘微调**：点击"起点/终点"标签选中，← → 箭头每次 ±20m，长按连续调整
- **后端增强**：Segment 模型新增 `elevation_loss`、`avg_gradient`、`elevation_profile` 三个 nullable 字段；距离精度 1→2 位小数；`_geo_utils.py` 拆分避免 service.py 超 500 行
- **部署**：Caddyfile 新增 `/tools/*` 静态文件路由
- **测试**：4 个字段计算测试（`tests/test_segment_fields.py`）

### 三、本地 Docker 部署（04-12）
- **环境**：`docker-compose.dev.yml`（不含 Caddy），PostgreSQL+PostGIS / Redis / FastAPI / rq Worker
- **迁移**：Alembic 初始迁移脚本，清理 PostGIS tiger 内置表干扰，修复 geoalchemy2 自动空间索引冲突
- **配置修复**：`.env` 与 pydantic-settings 兼容（`extra="ignore"`）；端口冲突改用 5434；CORS 中间件允许跨域
- **验证**：24 条太原赛段 JSON 全部导入成功，上传 GPX 自动匹配 21 条赛段

### 四、Matcher 算法增强（04-13）
1. **独立端点容差**：`endpoint_tolerance` 与 `match_tolerance` 分离，起终点检测和覆盖率校验可独立调整
2. **Moving Time 自动暂停**：速度 + 时间双条件（连续低于阈值 ≥30 秒才扣除），阈值 0.5 km/h，避免误扣陡坡慢速骑行
3. **DELETE /api/segments/{id}**：管理员删除赛段接口，连带清除所有成绩记录
- 与 Strava 成绩对比验证：柴化线两条赛段误差缩至 9~16 秒

### 五、API 接入调研（04-10）
- Strava API：免费，2000 次/天，Webhook 推送，但条款限制数据缓存 ≤7 天
- Garmin API：免费基础接入，需企业身份申请，Push 模式秒级推送
- 行者：有官方开发者中心（XOSS 开放平台）
- 顽鹿/iGPSport：无官方 API
- **结论**：先接 Strava（秒批），同时申请 Garmin（用"共演纪"个体户身份）

### 当前状态
- 后端 API 功能完整，本地 Docker 端到端验证通过
- 24 条太原赛段已入库，匹配算法与 Strava 成绩误差 <20 秒
- 赛段创建工具可用（HTML 单文件，在线/离线双模式）
- **待做**：云服务器部署 → 微信小程序前端 → Strava API 接入

## 2026-04-09 赛段创建工具 + Segment 模型增强

### 新功能
1. **赛段创建工具**（`tools/segment-creator.html`）：Strava 风格的管理员工具，从 GPX 文件中截取赛段。功能：GPX 导入解析 → Chart.js 海拔剖面图 + 双滑块拖选 → Leaflet 地图联动 → POST /api/segments 创建 + JSON 降级下载。单 HTML 文件，CDN 依赖 Chart.js + Leaflet，部署在 Caddy /tools/ 路由下。

### Segment 模型增强
2. **新增 3 个字段**：`elevation_loss`（累计下降）、`avg_gradient`（平均坡度%）、`elevation_profile`（海拔采样 JSON，约 80 个值，供前端画 sparkline 缩略图）
3. **距离精度提升**：API 返回距离从 1 位小数改为 2 位小数（如 48.25 km）
4. **service.py 拆分**：`_haversine` 和 `_sample_elevation_profile` 提取到 `_geo_utils.py`，service.py 从 533 行降至 491 行

### 部署
5. **Caddyfile**：新增 `/tools/*` 静态文件路由

### 隔离验证
- app/activity/ 和 app/user/ 零修改
- 72 个测试全部通过（新增 4 个字段计算测试）
- 所有新 Segment 字段 nullable，向后兼容

## 2026-04-09 GCJ-02 → WGS-84 坐标系转换

### 问题
赛段创建接口（POST /api/segments）的 `reference_points` 没有坐标系约定。管理员从腾讯地图取的坐标是 GCJ-02（偏移 100~700m），而 GPX 轨迹点是 WGS-84。两套坐标在 matcher 里做距离计算时会偏移，导致 50m 容差下匹配必然失败。

### 修复
1. **新增 `app/segment/coord_convert.py`**：纯函数模块，GCJ-02 → WGS-84 转换，精度 <1m
2. **`SegmentCreateRequest` 新增 `coordinate_system` 字段**：`"gcj02"`（默认，腾讯/高德地图）或 `"wgs84"`（GPS/GPX 原始坐标）
3. **`service.create_segment` 集成转换**：在距离计算前调用 `convert_points_to_wgs84`，确保存入 PostGIS 的 reference_line 始终是 WGS-84（SRID=4326）
4. **新增 5 个测试用例**（test_21 ~ test_25）验证转换精度和边界情况

### Spec 偏离记录
- 原 spec 未提及坐标系，现在 API 层明确约定默认 GCJ-02 输入、内部统一 WGS-84 存储
- 向后兼容：不传 `coordinate_system` 字段默认走 GCJ-02 转换

## 2026-04-08 Alembic 迁移初始化 + Worker 超时保护 + 卡片天气字段决策

### 基础设施
1. **Alembic 初始化**：生成 `alembic.ini` + `migrations/env.py`，数据库地址从 `app/config.py` 统一读取。部署时执行 `alembic revision --autogenerate` + `alembic upgrade head` 即可生成并应用迁移。

### 功能增强
2. **Worker 超时保护（方案 A）**：`get_activity_status` 新增超时判断——activity 在 processing 状态超过 10 分钟时，自动标记为 failed 并提示"解析超时，请重新上传"。轻量方案，仅在前端轮询时触发，不引入额外基础设施。未来流量增长后可叠加定时扫描方案，两者不冲突。

### Spec 偏离记录
3. **v1 骑行卡片不显示天气**：spec 5.1 卡片设计包含 `22°C · 晴`，但 Activity 表无天气字段，前端获取天气也增加复杂度。决定 v1 卡片标题区仅显示日期（如 `2026.04.07`），天气留到 v2 按需添加。

## 2026-04-08 Task 4.5 排行榜接口 + 代码拆分

### 架构变更
1. **service.py 拆分**：自动匹配逻辑（`match_activity_against_segments` + `_parse_linestring_wkt`）从 `service.py` 拆到 `auto_match.py`。原因：service.py 达 468 行接近 500 行红线，新增排行榜函数后会突破。拆分后 service.py 410 行、auto_match.py 206 行。

### Spec 增强（向后兼容）
2. **排行榜 bike_type 字段**：`get_segment_detail` 的 TOP20 排行榜增加 `bike_type` 字段（来自 User 表）。Spec 原始定义无此字段，但 Task 4.5 的独立排行榜接口需要它，为保持一致性统一添加。不影响已有消费方（多返回一个可选字段）。

### 设计决策
3. **bike_type 过滤语义**：排行榜按 `bike_type` 过滤时，查的是用户当前车型（User 表），非骑行时车型。用户换车后历史成绩的车型会随之变化。MVP 阶段可接受。

## 2026-04-07 技术文档终版（v3 → 终版）

基于 ChatGPT 编写的 v3 技术文档，经 Claude 审查后修正 9 个问题：

### 严重修复
1. **ST_DWithin 单位错误**：PostGIS `geometry` 类型的 `ST_DWithin` 距离单位是度，不是米。所有空间查询加 `::geography` 转换
2. **缺少 HTTPS**：微信小程序强制要求 HTTPS。部署方案新增 Caddy 反向代理，自动 SSL 证书

### 功能修复
3. **距离单位不统一**：活动接口返回米、统计接口返回公里。统一为所有 API 返回公里
4. **时区未定义**：新增约定——数据库存 UTC，周期计算按 UTC+8
5. **GPX BOM 头**：上传校验增加 BOM 跳过处理
6. **活动标题不可编辑**：新增 `PATCH /api/activities/{id}` 接口
7. **路段创建无权限**：users 表增加 `is_admin`，创建路段需管理员权限
8. **JWT 无续期说明**：新增静默续期机制文档
9. **分页参数不一致**：统一为 `page_size`

---

## 2026-05-18：Persona Engine Sprint v0.1 全 6 task ship 🎉

**这次干了啥**（用大白话讲）：

velo 终于有"老登 NPC"了——一个 35 岁、骑龄 10+ 年、半句话不刷屏的 AI 角色。
他会在你上传 PR 时说"今天嗑药了？"，看到你 8 天没骑会问"最近去哪儿了"，
看到你 200km 极限骑会问"腰还连着腿吗"。

不刷屏、不客服腔、不家长式。168 条精金文案分 7 个场景由 Tim 8 轮 cycle 亲手拍板。

**6 task 全 ship 时间线**：

- task-1 地基（3 表 + 5 空骨架）— commit `f3490fc`
- task-2 文案库（168 条 + 4 函数 template_lib）— commit `fd8308c` + `7a2f5d4`
- task-3 决策大脑（router 7 event / filters 反 pattern / cache 7 天去重 / service 6 步流水）— commit `af3c603`
- task-4 业务接入（worker hook + endpoint + 2 scanner + persona-scanner 容器）— commit `ee555ad`
- task-5 小程序展示（5 page + utils + api 拦截器 + 20 处 PERSONA 标记）— commit `68c6742`
- task-6 final gate（拔出脚本 + diary + Sprint 收尾）— commit TBD

**这次产品决策亮点**（Tim 的 8 轮 cycle 拍板）：

1. **normal 桶 80km → 40km**：velo 用户群周末甜区 30-60km / 80 已 long
2. **§2.6 过拟合裁定**：uploading + delete_confirm 用系统标准客服 / 不入 NPC 库
3. **loading 戏剧化候选全砍**："高光出炉"过拟合 / 保留 v0.1 "算你的高光中…" 一条
4. **错误页用 NPC 文案接 api.js 拦截器**：单一真相源（persona_static.js 改一处全生效）
5. **PR 优先 > 极端 > 段位**：用户最想看的是 PR 反应 / 极端次之 / 段位垫底
6. **拔出可拔性 = 架构纪律**：NPC 是码表不是车架 / 拔目录就拔模型

**Critical bug 修复记录**（task-1 ~ task-5 累计 8 项三审 Critical 全修）：

- task-1 Codex：persona_outputs.activity_id 加 ondelete=SET NULL（防生产删活动 500）
- task-2 Codex：3 normal segment 各 4 条违反 v0.2 ≥ 5 红线（cycle 2 补 5 条候选）
- task-3 Claude A：filters 漏"亲"独立关键词（"亲~"客服腔漏 filter）
- task-3 Claude A：milestone_type 字段位置（spec line 90 user_data 不是 activity_data）
- task-3 Claude B + Codex：夜骑 hour 4 边界（spec 23-04 / 代码 23-03 漏判）
- task-4 Claude A+B：milestone scanner today_bj astimezone() 系统 TZ → ZoneInfo BJ
- task-5 共识 3 个：api.js 没 require persona_static / persona_static 含违宪 uploading+delete_confirm / upload.wxml 缺 PERSONA 标记

**测试覆盖**：

- 后端：60 条 persona 测试通过（task-1 4 + task-2 12 + task-3 35 + task-4 9）/ 全套 663 测试 0 回归
- 前端：20 处 PERSONA_START/END 标记 / 5 page 全覆盖可拔
- 拔出脚本：scripts/persona_pluck_dryrun.sh 准备好（Tim dev env 跑 final gate）

**未结清**（task-6 final gate / 留 Tim 真用 8 场景）：

- 微信开发者工具上传体验版 / 真打开 profile / 真上传 PR / 真测沉寂 / ...
- 模板覆盖率 ≥ 80%（168 × 80% ≈ 134 条被触发过 / SQL 查 persona_outputs 验）
- deployment-diary 真用激活记录
