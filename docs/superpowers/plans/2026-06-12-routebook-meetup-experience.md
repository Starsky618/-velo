# 路书作品化 + 约骑编辑修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to execute this plan.
> **执行总闸:** 本计划按 Task 1 -> Task 7 顺序推进。每次开工先读本文件的“执行账本”，每完成一个 Task 必须补上验证结果与 commit 号；禁止只做前面止血项后忘掉后面的路书主线。
> **上游真相源:** Tim 2026-06-12 真机反馈：约骑编辑难用；路书应能从外部软件/真实骑行轨迹导入，能编辑、转发、补注意事项、照片视频、个人感受；约骑里的路线、集合点、时间、节奏门槛必须能被真实用户按直觉修改。

**Goal:** 先修掉约骑创建里最割裂的体验，再把“我的路书”做成用户可以长期沉淀、编辑、转发、再发约骑的作品。

**Architecture:** `route_book` 继续做路线几何与路书内容的家；`meetup` 继续做一次约骑活动。两者通过 `route_book_id` 连接：路书可以生成约骑，约骑结束后的真实经验可以回写到路书副本里。分享编辑采用“复制到我的路书再编辑”，避免别人改坏原作者的路书。

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + PostgreSQL / 微信小程序原生页面 / 腾讯地图 SDK / 现有文件上传链路。

---

## 执行账本

- [ ] Task 1: 约骑编辑止血：时间、集合点、节奏门槛在创建页和确认页都真能改
- [ ] Task 2: 常用集合点：保存、复用、地图选择、搜索选择
- [ ] Task 3: 路书重命名 + 全屏地图查看：腾讯生成路书不再被默认名字锁死
- [ ] Task 4: 路书内容模型：注意事项、照片视频、个人感受、分享复制
- [ ] Task 5: 我的路书页面：导入外部路书、从骑行轨迹生成、编辑、转发
- [ ] Task 6: 路书反哺约骑和路线百科：用好路书发约骑，路线页展示真实经验
- [ ] Task 7: 真机回归和体验版上传：在手机上走完整用户路径

## 一个具体用户的一天

陈哥从行者/两步路导出一条 GPX，发到微信文件里。他打开 VELO，点“导入路书”，选中文件，路书自动出现距离、爬升和地图线。他把标题改成“晋祠到天龙山轻爬坡”，补一句“晋阳大道车多，8 点后不建议走”，上传两张路面照片，再写下“最后 3 公里风大，适合练稳定输出”。

周末他想约骑，直接点“用这本路书发约骑”。集合点不是手打“晋祠公园北门”，而是在地图上搜到门口，保存成常用点。确认页里他看到推荐功率和预计均速不符合这次队伍，就改成“150-180W / 23-26km/h”。发出后，群友点开能看地图细节、注意事项和照片。另一个人觉得路线不错，复制成自己的路书，改成更适合新手的版本。

这就是本计划要交付的体验。

## 现状证据

- [✓ grep] `app/route_book/service.py:1` 已把 GPX/FIT、历史活动、腾讯路线统一生成到 `route_books`，适合继续承接“我的路书”。
- [✓ grep] `app/route_book/router.py:41` 已有文件导入接口；`app/route_book/router.py:70` 已有腾讯路线生成接口。
- [✓ grep] `app/route_book/schemas.py:17` 当前路书返回字段只有名字、距离、爬升、来源、预览点，没有注意事项、照片视频、个人感受、分享信息。
- [✓ grep] `miniprogram/pages/meetup-create/meetup-create.js:456` 腾讯生成路书名字由起终点自动拼出，用户没有顺手改名的位置。
- [✓ grep] `miniprogram/pages/meetup-create/meetup-create.wxml:152` 集合点目前是纯文本输入；`miniprogram/pages/map-picker/map-picker.wxml:1` 已有地图选点页，但尚未给集合点使用。
- [✓ grep] `miniprogram/pages/meetup-create/meetup-create.js:531` 创建流程只检查结束时间晚于出发时间，没有禁止过去时间。
- [✓ grep] `miniprogram/pages/meetup-create/meetup-create.wxml:313` “节奏与门槛”在确认页显示了推荐功率和预计均速，但没有真实编辑动作。
- [✓ grep] `app/meetup/router.py:23` 约骑返回字段已有 `pace_level`、`meeting_point`、`safety_note` 等，但没有集合点坐标、推荐功率、预计均速的自定义字段。
- [✓ grep] `docs/architecture-guide.md:117` 当前依赖方向要求 `meetup` 可以依赖 `route_book`，但不能让 `route_book` 反向依赖 `meetup`。

## 固定产品判断

1. 路书不是“路线详情的附件”，而是用户可积累的骑行作品。
2. 约骑不是另一个孤岛，它应该复用路书里的路线、提醒、照片和经验。
3. 共享编辑不直接改原作者内容。别人打开分享路书时，只能“复制到我的路书再编辑”，这样既自由，又不会破坏原作。
4. 先修直觉失调，再做宏大系统。用户今天卡在时间、集合点、改名、节奏门槛，这些是第一优先级。

## 文件分工

- `app/route_book/*`: 路书的路线数据、内容字段、媒体、分享复制、导入逻辑。
- `app/meetup/*`: 一次约骑活动的时间、集合点、强度预期、发布校验。
- `app/storage/*`: 图片视频文件仍走现有上传链路，不新造一套文件系统。
- `miniprogram/pages/meetup-create/*`: 约骑创建和确认页，先修最影响真机感受的地方。
- `miniprogram/pages/map-picker/*`: 地图选点页，扩展给集合点和常用点使用。
- `miniprogram/pages/route-book-*/*`: 新增“我的路书”列表、详情、编辑、分享复制页面。
- `miniprogram/utils/api.js`: 小程序调用后端的统一入口。
- `tests/*`: 后端行为测试 + 小程序静态合同测试，防止页面看起来有按钮但没有真实动作。

---

## Task 1: 约骑编辑止血

**用户多了什么体验:** 发约骑时不再像填一张死表。时间不能选过去，集合点能从地图带回来，确认页里的强度预期、推荐功率、预计均速都能改。

**为什么先做:** 这是 Tim 真机已经摸到的割裂点。它不依赖完整路书作品系统，能最快提升“这东西能不能认真用”的信任感。

**预计时间:** 1.5-2 天。

**Files:**

- `app/meetup/models.py`
- `app/meetup/schemas.py`
- `app/meetup/service.py`
- `app/meetup/router.py`
- `migrations/versions/20260612_meetup_editing_fields.py`
- `miniprogram/pages/meetup-create/meetup-create.js`
- `miniprogram/pages/meetup-create/meetup-create.wxml`
- `miniprogram/pages/meetup-create/meetup-create.wxss`
- `miniprogram/pages/map-picker/map-picker.js`
- `miniprogram/pages/map-picker/map-picker.wxml`
- `miniprogram/utils/api.js`
- `tests/test_meetup_api.py`
- `tests/test_meetup_miniprogram_static.py`

**Steps:**

- [ ] 写失败测试：创建/更新/发布约骑时，`start_time <= now` 或 `estimated_end_time <= now` 必须失败；结束时间仍必须晚于出发时间。
- [ ] 给 `meetups` 增加集合点坐标字段：`meeting_lat`、`meeting_lon`、`meeting_address`，保留旧 `meeting_point` 作为展示名。
- [ ] 给 `meetups` 增加强度展示字段：`expected_power_label`、`expected_speed_label`、`pace_note`。默认值仍从 `pace_level` 推出，但用户改过后以用户输入为准。
- [ ] 小程序时间选择器设置最小可选时间为当前时间；用户手动绕过时，前端和后端都要拦。
- [ ] 集合点输入旁加地图按钮，复用 `map-picker` 返回地点名和坐标。
- [ ] 确认页“节奏与门槛”加真实编辑入口：可改强度预期、推荐功率、预计均速，保存到 draft，再发布。
- [ ] “查看详情”跳到可缩放地图页；Task 3 前可先跳到临时路线查看页，Task 3 再统一成正式页面。
- [ ] 跑验证：`python -m pytest tests/test_meetup_api.py tests/test_meetup_miniprogram_static.py -q`。

**Done when:**

- 手机上新建约骑，不能选过去时间。
- 集合点可以地图选择，返回后确认页能看到地点名。
- 确认页修改功率/均速后，发布详情页能看到修改后的值。
- 测试覆盖过去时间、集合点坐标、强度自定义字段。

## Task 2: 常用集合点

**用户多了什么体验:** 经常从同一个地方出发的人，不用每次重新输入或重新找地图点。

**为什么现在做:** 集合点是约骑发起者最高频的重复动作。保存常用点后，发约骑从“填表”变成“选一个熟悉地点”。

**预计时间:** 1 天。

**Files:**

- `app/user_locations/models.py`
- `app/user_locations/schemas.py`
- `app/user_locations/service.py`
- `app/user_locations/router.py`
- `app/main.py`
- `migrations/versions/20260612_user_saved_locations.py`
- `miniprogram/pages/meetup-create/meetup-create.js`
- `miniprogram/pages/meetup-create/meetup-create.wxml`
- `miniprogram/pages/map-picker/map-picker.js`
- `miniprogram/utils/api.js`
- `tests/test_user_locations_api.py`
- `tests/test_meetup_miniprogram_static.py`

**Steps:**

- [ ] 新建 `user_saved_locations` 表：`user_id`、`name`、`address`、`lat`、`lon`、`usage_count`、`last_used_at`。
- [ ] 提供保存、列表、重命名、删除接口；同一用户下同名同坐标不重复创建，只增加使用次数。
- [ ] `map-picker` 增加搜索输入，优先用腾讯地点搜索；网络失败时仍允许保存地图中心点。
- [ ] 约骑创建页集合点区域展示最近常用 3 个地点，并提供“更多常用点”入口。
- [ ] 选择常用点后，自动填入 `meeting_point`、`meeting_address`、`meeting_lat`、`meeting_lon`。
- [ ] 跑验证：`python -m pytest tests/test_user_locations_api.py tests/test_meetup_miniprogram_static.py -q`。

**Done when:**

- 用户能保存一个集合点，下次创建约骑直接点选。
- 常用点删除后不再出现在约骑创建页。
- 搜索不可用时，地图中心点仍可作为集合点保存。

## Task 3: 路书重命名 + 全屏地图查看

**用户多了什么体验:** 腾讯生成的路线不再叫死板的“起点 -> 终点”，确认页里的路线也能点开真正放大缩小看。

**为什么现在做:** 这是连接约骑和路书作品的桥。名字和地图看不清，用户就不会觉得这是“我的路书”。

**预计时间:** 1-1.5 天。

**Files:**

- `app/route_book/schemas.py`
- `app/route_book/service.py`
- `app/route_book/router.py`
- `miniprogram/pages/meetup-create/meetup-create.js`
- `miniprogram/pages/meetup-create/meetup-create.wxml`
- `miniprogram/pages/route-book-map/route-book-map.js`
- `miniprogram/pages/route-book-map/route-book-map.wxml`
- `miniprogram/pages/route-book-map/route-book-map.wxss`
- `miniprogram/app.json`
- `miniprogram/utils/api.js`
- `tests/test_route_book_api.py`
- `tests/test_meetup_miniprogram_static.py`

**Steps:**

- [ ] 给路书增加 `PATCH /api/route-books/{route_book_id}`，第一版只允许 owner 修改 `name`。
- [ ] 腾讯起终点选完后，展示可编辑路书名输入框，默认仍是“起点 -> 终点”。
- [ ] 生成腾讯路线时，把用户编辑后的名字传给后端。
- [ ] 新增 `route-book-map` 页面，按 `route_book_id` 拉取 `preview_points`，在地图中展示完整路线。
- [ ] 约骑确认页的“查看详情”跳到 `route-book-map`。
- [ ] 跑验证：`python -m pytest tests/test_route_book_api.py tests/test_meetup_miniprogram_static.py -q`。

**Done when:**

- 腾讯路线生成前可以改名。
- 已生成路书可以改名。
- 约骑确认页能点进全屏地图查看路线。

## Task 4: 路书内容模型

**用户多了什么体验:** 路书不只是线条，而是一张可以写骑行经验的卡片：哪里危险、哪里补给、哪里风大、照片视频证明真实骑过。

**为什么现在做:** 没有内容模型，前端再漂亮也只是路线收藏夹。路书要成为作品，必须能承载人的经验。

**预计时间:** 2 天。

**Files:**

- `app/route_book/models.py`
- `app/route_book/schemas.py`
- `app/route_book/service.py`
- `app/route_book/router.py`
- `app/route_book/media_service.py`
- `migrations/versions/20260612_route_book_content_and_media.py`
- `app/storage/models.py`
- `tests/test_route_book_api.py`
- `tests/test_route_book_media_api.py`

**Data changes:**

- `route_books.description`: 这本路书适合谁、整体感受。
- `route_books.safety_tips`: 风险提醒，例如大车多、急弯、施工、夜间照明。
- `route_books.supply_tips`: 补给提醒，例如便利店、水点、厕所。
- `route_books.personal_note`: 作者自己的骑行感受。
- `route_books.visibility`: `private` / `share_link` / `public`。
- `route_books.share_token`: 分享链接使用的随机令牌。
- `route_books.source_meetup_id`: 可选，记录这本路书是否来自某次约骑。
- `route_book_media`: `route_book_id`、`file_id`、`media_type`、`caption`、`sort_order`、`created_at`。

**Steps:**

- [ ] 写失败测试：非 owner 不能编辑原路书；有分享令牌的人可以读取；复制后 owner 变成当前用户。
- [ ] 增加路书内容字段和媒体表。
- [ ] 增加 `PATCH /api/route-books/{id}/content`，允许 owner 修改描述、提醒、感受、可见范围。
- [ ] 增加 `POST /api/route-books/{id}/media`、`DELETE /api/route-books/{id}/media/{media_id}`。
- [ ] 增加 `POST /api/route-books/{id}/share-token` 和 `POST /api/route-books/shared/{token}/copy`。
- [ ] 复制路书时复制路线几何和文字内容；媒体第一版引用同一 file，不复制文件本体。
- [ ] 跑验证：`python -m pytest tests/test_route_book_api.py tests/test_route_book_media_api.py -q`。

**Done when:**

- 用户能给自己的路书写注意事项、补给、感受。
- 用户能上传照片视频并排序。
- 分享链接不会让别人改原件，只能读取和复制。

## Task 5: 我的路书页面

**用户多了什么体验:** 他有一个属于自己的路书库：外部导入、真实骑行生成、腾讯生成、约骑沉淀，最后都能在这里整理。

**为什么现在做:** 后端有了内容模型后，必须把它变成用户每天能看到、能改、能转发的地方。

**预计时间:** 2-3 天。

**Files:**

- `miniprogram/pages/route-books/route-books.js`
- `miniprogram/pages/route-books/route-books.wxml`
- `miniprogram/pages/route-books/route-books.wxss`
- `miniprogram/pages/route-book-detail/route-book-detail.js`
- `miniprogram/pages/route-book-detail/route-book-detail.wxml`
- `miniprogram/pages/route-book-detail/route-book-detail.wxss`
- `miniprogram/pages/route-book-edit/route-book-edit.js`
- `miniprogram/pages/route-book-edit/route-book-edit.wxml`
- `miniprogram/pages/route-book-edit/route-book-edit.wxss`
- `miniprogram/app.json`
- `miniprogram/utils/api.js`
- `tests/test_route_book_miniprogram_static.py`

**Steps:**

- [ ] 新增“我的路书”列表页：官方路书、我创建的路书、我复制的路书分组展示。
- [ ] 增加“导入外部路书”入口，使用微信文件选择 GPX/FIT，调用现有文件上传接口。
- [ ] 增加“从骑行轨迹生成”入口，复用现有活动候选接口。
- [ ] 路书详情页展示地图、标题、距离爬升、照片视频、注意事项、作者感受。
- [ ] 路书编辑页可修改标题、注意事项、补给、感受、照片视频、可见范围。
- [ ] 路书详情页提供“用这本路书发约骑”按钮，跳到 `meetup-create?route_book_id=...`。
- [ ] 分享页打开后，非作者看到“复制到我的路书并编辑”，作者看到“编辑原路书”。
- [ ] 跑验证：`python -m pytest tests/test_route_book_miniprogram_static.py -q`。

**Done when:**

- 用户能从小程序导入 GPX/FIT 成路书。
- 用户能从历史骑行生成路书。
- 用户能编辑路书文字和照片视频。
- 分享给别人后，对方能复制成自己的版本。

## Task 6: 路书反哺约骑和路线百科

**用户多了什么体验:** 好路书不止躺在“我的路书”里。路线百科能看到真实骑友的经验，约骑结束后也能把新的注意事项沉淀回路书。

**为什么现在做:** 这一步让 VELO 从“发一次活动”走向“越骑越厚的路线资料”。但它依赖前面路书编辑已经稳定，所以排在后面。

**预计时间:** 2 天。

**Files:**

- `app/route_book/service.py`
- `app/route_book/service_guides.py`
- `app/route_book/schemas.py`
- `app/meetup/service.py`
- `app/meetup/router.py`
- `miniprogram/pages/route-detail/route-detail.js`
- `miniprogram/pages/route-detail/route-detail.wxml`
- `miniprogram/pages/meetup-detail/meetup-detail.js`
- `miniprogram/pages/meetup-detail/meetup-detail.wxml`
- `miniprogram/pages/route-book-detail/route-book-detail.js`
- `tests/test_route_guides_api.py`
- `tests/test_meetup_api.py`

**Steps:**

- [ ] 路线百科详情返回关联路书数量、最近公开路书摘要、是否有近期约骑。
- [ ] 路线详情页增加“看骑友路书”和“用路书发约骑”入口。
- [ ] 约骑详情页在结束后给 organizer 展示“把这次经验写回路书”入口。
- [ ] 写回时创建当前用户的路书副本或更新他拥有的源路书；不改别人原路书。
- [ ] 保持依赖方向：`route_book` 不引入 `meetup` 服务；需要约骑信息时由 `meetup` 调用 `route_book` 或新增查询函数。
- [ ] 跑验证：`python -m pytest tests/test_route_guides_api.py tests/test_meetup_api.py -q`。

**Done when:**

- 路线百科能露出真实骑友路书。
- 约骑结束后，组织者能把本次经验沉淀到自己的路书。
- 依赖方向没有违反 `docs/architecture-guide.md` 的约束。

## Task 7: 真机回归和体验版上传

**用户多了什么体验:** Tim 能在手机上从头走完：导入路书 -> 编辑 -> 分享复制 -> 用路书发约骑 -> 地图选集合点 -> 修改强度 -> 发布。

**为什么必须做:** 小程序页面经常出现“代码存在但手机上不顺手”的问题。这个任务不是收尾礼仪，而是决定产品是否真的可用。

**预计时间:** 0.5-1 天。

**Files:**

- `docs/plans/meetup-ui-rebuild.md`
- `docs/superpowers/plans/2026-06-12-routebook-meetup-experience.md`
- `miniprogram/project.config.json`
- 微信开发者工具预览/上传记录

**Steps:**

- [ ] 后端完整测试：`python -m pytest tests/test_meetup_api.py tests/test_route_book_api.py tests/test_route_book_media_api.py tests/test_route_guides_api.py -q`。
- [ ] 小程序静态合同测试：`python -m pytest tests/test_meetup_miniprogram_static.py tests/test_route_book_miniprogram_static.py -q`。
- [ ] 微信开发者工具预览，手机真机走 5 条路径：外部导入、历史骑行生成、腾讯生成改名、分享复制、用路书发约骑。
- [ ] 把真机发现写回本计划“执行账本”，严重问题回到对应 Task 修。
- [ ] 上传体验版，记录版本号和验证账号。

**Done when:**

- Tim 在真机上能完整走通 5 条路径。
- 没有“按钮看起来能点但点了没反应”的假入口。
- 本文件执行账本全部打勾，并记录最终 commit。

---

## 每次恢复任务的开工口令

下一位 agent 或未来的我继续时，先做这四件事：

1. 读本文件“执行账本”，确认已经完成到哪个 Task。
2. 读 `git status`，区分自己改动和 Tim/其他 agent 改动。
3. 读当前 Task 里列出的真实文件，不凭记忆改。
4. 完成当前 Task 后更新本文件账本，再进入下一个 Task。

这张计划的存在，就是为了防止“先把显眼 bug 修了，然后把真正的路书主线忘掉”。
