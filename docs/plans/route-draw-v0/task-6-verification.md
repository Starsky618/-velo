# Task 6：验收、合规和对抗性复审

## 目标

确认“探索页画路线 -> 吸附预览 -> 保存 -> 海拔 -> 路书详情 -> 发约骑 / 导出”这条路真正走通，并把腾讯合规边界复核清楚。

## 用户多了什么体验

这一步不新增按钮，但它决定用户第一次使用时会不会觉得“这功能能信”。

## 改动范围

- `tests/test_route_draw_snap.py`
- `tests/test_route_book_api.py`
- `tests/test_route_elevation_backfill.py`

## 验收合同

- 100 条虚拟手画路线用 mock 腾讯返回跑过吸附、保存、海拔生成。
- 至少 3 条真实城市道路用真腾讯接口人工验证。
- 至少 1 条包含自由画线段的路线能保存并生成海拔。
- 保存后的路线能进入 `route-book-detail`。
- 保存后的路线能从 `route-book-detail` 跳到 `meetup-create?route_book_id=<id>`。
- 保存后的路线能导出 GPX/TCX，且每个点有海拔。
- 记录腾讯失败、超时、空路线时的用户提示。
- 记录腾讯协议复核结论：调用量、缓存方式、展示方式、数据保存方式。
- 运行两轮独立审查：一轮看 spec/plan 忠诚度，一轮看真实代码集成风险。Critical/Important 必须修完再结束。

## 证据格式

Task 6 完成时在最终回复或提交说明里记录即可，不默认新增长期 review 文档。至少记录：
- 测试 route_book_id。
- 测试城市和道路描述。
- 手势录屏或截图路径。
- 后端接口响应摘要。
- GPX/TCX 抽样证据：至少 3 个点带 `<ele>` 或 `AltitudeMeters`。
- 腾讯失败场景的用户文案截图。
- 合规复核日期和结论。

## 验收

```bash
pytest tests/test_route_draw_snap.py tests/test_route_book_api.py tests/test_route_elevation_backfill.py
node --check miniprogram/pages/explore/explore.js
node --check miniprogram/pages/route-draw/route-draw.js
node --check miniprogram/pages/route-book-detail/route-book-detail.js
node --check miniprogram/utils/api.js
git diff --check
```
