# 约骑编辑止血交互 · 双审记录

日期：2026-06-12
分支：`codex/meetup-editing-triage`

## 审查结论

- spec 忠诚审：0 findings，可提交。
- 集成审：0 findings，可提交。

## 审查中修掉的问题

- 确认页改“强度预期”后，原先只更新屏幕展示，没有随发布保存到后端；已在发布前保存 `pace_level`。
- 出发时间离现在太近时，原先会走到后端再返回 `meetup cutoff passed`；已按后端同款 30 分 30 秒截止线在前端中文拦截。
- 腾讯路线名可能被超长地图点名拖爆，并暴露后端原始错误；已限制点名/路线名长度，并把 422/503 映射成短中文。

## 已验证

- `pytest -q tests/test_meetup_miniprogram_static.py`：33 passed。
- `node --check miniprogram/pages/meetup-create/meetup-create.js`：通过。
- `node --check miniprogram/pages/map-picker/map-picker.js`：通过。
- `git diff --check`：通过。

## 剩余真机风险

- 微信原生 `map` 浮层关闭按钮需要在真机点一次：“查看详情” → “关闭”。
- 发布截止线前端依赖手机时间；后端仍是最终防线。
- 腾讯路线真实生成仍依赖生产 key、配额和 WebServiceAPI 状态。
