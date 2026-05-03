"""管理后台模块（v5 新建）。

边界：
- 所有 /api/admin/* endpoint 集中在此
- 调用其他模块 service public API 编排（候选池 + AI 草稿 + segment + activity）
- 禁止业务用户访问（require_admin 依赖把关）
"""
