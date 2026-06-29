# Task 4：文档和验收

## 目标

把 V0 的边界、接口和失败场景写清楚，避免后续把品牌官方同步或 FIT 生成混进本次实现。

## 用户多了什么体验

用户不会被“导出到码表”误导成“一键同步所有品牌”。页面只承诺下载标准文件，并给出下一步导入说明。

## 改动范围

- `docs/spec-route-export-v0.md`
- `docs/plans/route-export-v0/README.md`
- 本目录任务卡

## 合同

- 文档必须写清 V0/V1/V2。
- 文档必须包含现状证据、接口合同、失败场景、验收命令。
- Critical/Important 风险必须进入合同：不返回 `file_id`、不暴露 `/uploads`、下载校验 artifact/job/version/format 一致。

## 验收

```bash
git diff --check
```
