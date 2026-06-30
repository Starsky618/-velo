# Task 5：探索页入口

## 目标

在“探索”页新增“画一条路线”入口，并让它和路线百科列表平行存在。

## 用户多了什么体验

探索页不再只是看官方路线。用户能从这里直接开始创造自己的路线。

## 前置依赖

- Task 4 已创建 `pages/route-draw/route-draw.*` 并在 `app.json` 注册页面。
- 不能在 route-draw 文件不存在时先加入口。

## 改动范围

- `miniprogram/pages/explore/explore.wxml`
- `miniprogram/pages/explore/explore.js`
- `miniprogram/pages/explore/explore.wxss`

## 输入输出合同

- 探索页顶部标题调整为“探索”。
- 新增“创建路线”区块，主按钮为“画一条路线”。
- 路线百科列表保留在下方，仍使用 `/api/route-guides`。
- 点击按钮进入 `/pages/route-draw/route-draw`。
- 不把画路线入口塞进单条路线卡片。
- 未登录用户点击时提示登录；不要让他进入后画完才发现不能保存。

## 验收

```bash
node --check miniprogram/pages/explore/explore.js
```

真用：
- 打开探索页，第一屏能看到“画一条路线”。
- 原路线百科列表仍能加载和进入官方路线详情。
