# Route Export V0 · 双审记录

日期：2026-06-25
分支：`route-export-v0`

## 审查结论

- 代码质量/安全审：无未解决 Critical / Important。
- 集成审：无未解决 Critical / Important。

## 审查中修掉的问题

- 小程序下载后只保存临时路径，用户没有真实动作把文件交出去；已补 `wx.shareFileMessage`，下载后可发送到微信聊天或文件传输助手。
- `export_ready` 只看 `current_version_id`，没有看版本是否真正可导航；已补 RouteVersion 查询，并要求 `navigation_status == "ready"`。
- storage 文件丢失会从下载接口冒成 500；已把 `FileNotFoundError/KeyError/OSError` 转成 404。
- 公开匿名导出没有限流；已在创建导出接口加 IP 限流，登录用户再加 user 限流。
- 页面和文档里“手机文件/系统分享”的说法会误导用户；已统一改成微信文件转发和目标 App 手动导入。

## 已验证

- `pytest tests/test_route_export_foundation.py tests/test_route_book_api.py tests/test_route_guides_import.py tests/test_route_guides_api.py`：67 passed, 3 skipped。
- `node --check miniprogram/utils/api.js`：通过。
- `node --check miniprogram/pages/route-detail/route-detail.js`：通过。
- `git diff --check`：通过。
- `git diff --cached --check`：通过。

## 剩余真机风险

- `wx.downloadFile` 和 `wx.shareFileMessage` 需要在微信开发者工具或真机点一次；本轮只做了 JS 语法检查。
- 不同品牌 App 的导入入口名称不同；V0 只给标准文件和导入说明，不承诺自动打开目标 App。
