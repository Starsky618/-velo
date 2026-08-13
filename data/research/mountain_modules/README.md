# 山区路线积木薄 SOP

每个山区只新增一份版本化 manifest 和一份 gitignored 来源快照，不复制算法、不创建区域专属 skill。

1. 在 `data/research/mountain_modules/` 新增 manifest：冻结 exact observation IDs、参考轴身份/hash、方向语义、完整角色覆盖门、目的地 route blocks 与 typed ports。**来源赛段端点只是观察边界，不是道路端点。**
2. 从生产只读导出完整来源/GLO/热度事实；导出器只允许写入该 manifest 的 `outputs/...` artifact 目录：

   ```bash
   python3 scripts/export_mountain_module_snapshot.py \
     --spec data/research/mountain_modules/REGION.json \
     --output outputs/REGION/source-slice.json
   ```

3. 离线重放同一通用程序，冻结坐标外的 public manifest 与可视化摘要：

   ```bash
   python3 scripts/analyze_mountain_module.py \
     --spec data/research/mountain_modules/REGION.json \
     --snapshot outputs/REGION/source-slice.json \
     --output outputs/REGION/run.json \
     --public-manifest-output data/research/mountain_modules/REGION_run_manifest.json \
     --summary-output outputs/REGION/summary.json
   ```

4. 对账 `source_slice_sha256`、`run_sha256`、module algorithm/config 版本、0 DB write / 0 network request。每个 Traversal 只绑定一条唯一、同方向、与该 Traversal extent 近似等长的完整 source/GLO fact；partial traversal 在 v1 不得借用整线距离/爬升。任何角色方向或覆盖不足直接失败。

完整 source slice 含来源坐标，不进 Git。生成 run 后将同一字节副本保存到本机证据账 `~/.codex/evidence/velo/mountain-modules/<manifest-name>/source-slice.json`，并用 JSON 内的 `slice_sha256` 回读；临时 `/private/tmp` 文件不是权威存放。仓库 public manifest 的 `source_slice_sha256` 指向这份可重放输入。

5. 新增另一山区若必须修改通用 Python，先判断是合同缺口还是区域特例。区域特例回到 manifest；真正算法升级则换全局版本并回放全部既有 manifest。

跨山区不是默认“直接相连”：先把横岭、桃花沟等保存为目的地积木，再由完整过境路径连接。过境道路即使没有 Strava 赛段也可使用，但必须单独重算距离、爬升、access 与证据覆盖；热度缺失记 `unobserved`，不能记成 0，也不能把过境路宣传成热门目的地。

只有完整路线真的在相邻 RoadArc 上立即反向时才检查 typed turnaround。通常公路爬坡赛段只是道路的一段，路线应继续沿道路组装；不得因为赛段在“山顶”结束就自动生成往返或 `blocked_unknown_connection`。像枣杜公路这种经道路/路由事实确认的断头路，且目标要求进入后返回，才建立 `forced_out_and_back` 与掉头证据。
