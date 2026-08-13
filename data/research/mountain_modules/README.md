# 山区路线积木薄 SOP

每个山区只新增一份版本化 manifest 和一份 gitignored 来源快照，不复制算法、不创建区域专属 skill。

1. 在 `data/research/mountain_modules/` 新增 manifest：冻结 exact observation IDs、参考轴身份/hash、方向语义、完整角色覆盖门、route blocks、typed ports 与待证 connection。
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

4. 对账 `source_slice_sha256`、`run_sha256`、module algorithm/config 版本、0 DB write / 0 network request。每个 Traversal 只绑定一条唯一、同方向、与该 Traversal extent 近似等长的完整 source/GLO fact；partial traversal 在 v1 不得借用整线距离/爬升。任何角色方向或覆盖不足直接失败；未知连接保持 `blocked_unknown_connection`。

5. 新增另一山区若必须修改通用 Python，先判断是合同缺口还是区域特例。区域特例回到 manifest；真正算法升级则换全局版本并回放全部既有 manifest。

跨山区连接另建 transition evidence，按两端 `port_sha256` 引用；端点看起来接近不算已连接。
