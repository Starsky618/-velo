# Sprint 13 Task-6 — 生产部署核实 + 真用回归（S13 收口 / 上线门之一）

> 所属：Sprint 13 闭环主链 / 第 6 个 task / commit ≠ ship 的那座桥。
> 上游：`docs/spec-v6.md` §3.8 必答 #6 / 风险 3、4、6 / T6 行；部署 SOP 单一真相源 = `docs/agent-rules/deploy-sop.md`。
> 前置门：T1-T5 全部 commit 且三审归零。**主 agent 亲自执行（生产操作不派 subagent）。**

---

## ─────── 给 Tim 看 ───────

### 干啥用

把 T1-T5 的代码真正送到用户手机上，并且把三处审查点名的"喇叭没插电源"位（代码全对但生产没真通电的地方）逐一通电验证：FIT 文件从没在生产真传过一次、私圈口令从没端到端真用过、解析到底要几秒从没量过。

### 用户故事

部署完，你自己当用户：用真实 .fit 文件连传 5 个，掐表记每次开奖耗时；拉一个不在创始团队的朋友走一遍"收到卡→点开→报名"的半生人剧本。哪一步卡住，当场就知道，而不是上线后第一个真用户替你发现。

### 怎么算做对了

- ✓ 服务器代码从 5 月 26 日的版本追到 S13 最新（约骑模块全部 commit 在其后，这是 PRD 验收项）。
- ✓ FIT 文件生产端到端真传成功一次（worker 镜像里 garmin_fit_sdk 真能 import）。
- ✓ share_token 私圈链路端到端真演一次（非参与者无口令 404、带口令进得来）。
- ✓ 5 个真实文件的解析延迟 p90 量出来，数字写进 PRD；>5 秒才回 Tim 拍是否开快路径（D7 两段式）。
- ✓ TENCENT_MAP_KEY 在生产 .env 里查过并记录（缺失则按配置步骤补）。

### 这次不做

- 不优化 worker 并发（必答 #7 否决：队列瓶颈未实测，先调优是盲调）。
- 不部署 S14 内容（T7-T9 随上线点部署）。

### 估时

1 天。

---

## ─────── 执行技术细节（主 agent 亲自） ───────

<details>
<summary>展开</summary>

## 1. 起手必跑

```bash
cat docs/agent-rules/deploy-sop.md                        # 6 步 SOP 全文，本卡不复制只补增量
nl -ba docs/spec-v6.md | sed -n '28,29p;217,229p;243,244p' # §0.1 末行 + §5 风险表 + T6 行
git log --oneline origin/main -5                          # 待部署 commit 链
```

## 2. 本期增量三项（先写进 deploy-sop.md 再执行——spec T6：SOP 本体是单一真相源，本卡只是指针）

1. **`docker compose up -d --build` 是硬要求不是 restart**（spec 风险 3）：scheduler 容器要加载 T1 新模块（bj_time / attach tick），worker 容器要确认 garmin_fit_sdk；restart 用旧镜像 = 新代码全部白部署。
2. **三喇叭位有意激活回归**（陷阱 #19 同类）：
   - FIT 端到端：生产小程序真传一个 .fit → 开奖成功 + `docker compose logs worker` 无 ImportError
   - share_token 端到端：创建 invite_only 约骑 → 无口令访问 404 → 带口令进入 → join → 战报可见
   - garmin_fit_sdk 镜像确认：`sudo docker compose exec worker python3 -c "import garmin_fit_sdk; print('ok')"`
3. **延迟实测**（spec D7 / PRD 必答 #7）：真机连传 5 个真实码表文件，逐个记录"上传完成→开奖"秒数 → 算 p90 → 数字写进 `docs/prd/sprint-13-launch-prd.md` §2 验收行。p90 ≤5s 收工；>5s 停下回 Tim 拍"小文件同步快路径"是否启动（不许自行开工）。

## 3. 执行清单（按 deploy-sop.md 6 步走，此处只列本期特有项）

- [ ] **第一步亲查 TENCENT_MAP_KEY**（spec §0.1 末行 ⚠️ 运行时）：`ssh ubuntu@114.132.190.245 "grep -c TENCENT_MAP_KEY ~/velo/.env"`（**只查存在性，禁止 cat 整个 .env——SSH 脱敏纪律**）；结果记录进本卡交付报告 + spec §0.1 该行销账；缺失则按腾讯位置服务控制台步骤补 key 再继续
- [ ] git push → 服务器 git pull → `sudo docker compose up -d --build`（全量，不指定 service——判例：漏 rebuild worker 的 Persona task-4 翻车）
- [ ] `sudo docker compose exec api python3 -m alembic upgrade head` → 确认 head = `20260611_meetup_activities`（若 S14 的 T7 已先 commit 入主干，head = `20260612_route_guides`，两者均正常——双审 I4 校正，按当时 git log 判断）
- [ ] curl verify：`/health` 200 / `GET /api/meetups/{真实id}/report` 200 / `GET /api/meetups/{id}?source=share_card` 后 `docker compose logs api | grep "SENSOR view"` 有行
- [ ] attach tick 真转：传一个约骑日活动 → ≤5 分钟后 `grep "SENSOR attach"` 有行 + 战报格子点亮
- [ ] 开奖 +1 窗口期观察（双审 hot spot）：开奖瞬间成绩卡显示 m+1 而战报格子还没亮（attach ≤5 分钟延迟）——刻意在这个窗口里点开战报看一次，确认体验不困惑；困惑则记录回 Tim 拍文案
- [ ] 三喇叭位逐一通电（上节）
- [ ] 延迟实测 5 文件 → p90 进 PRD
- [ ] 半生人剧本真演（spec 风险 4）：非创始成员真走"收卡→点开→报名"——上线前一周 Tim 点名的人选，若人未到位先用小号演练并在报告标注 🟡 待真人复演
- [ ] 本地 `git pull` 同步工作树（DEPLOY-7）+ 提醒 Tim 微信开发者工具重新上传小程序（前端通道与后端通道是两条路）
- [ ] `docs/deployment-diary.md` 记一笔（含三喇叭位激活结果）

## 4. 自检（收口前）

- [ ] 服务器 `git log -1` 哈希 = 本地 origin/main 哈希
- [ ] PRD §2 的 p90 数字已填、§4 回看查询可直接复制执行
- [ ] spec §0.1 TENCENT_MAP_KEY 行已从 ⚠️ 改为实测结果
- [ ] ship 后 1 问已答（CLAUDE.md）：使用数据从 T5 的 SENSOR 行与 SQL 可见；回看日期 = 上线后每周一，第 4 周 D-004/D-005 复检（recheck_scanner 已挂）

## 5. commit 指令（文档与 SOP 增量）

```
docs(deploy): S13-T6 部署 SOP 增量三项（--build 硬要求 + 三喇叭位 + 延迟实测）+ 部署核实记录
```

</details>
