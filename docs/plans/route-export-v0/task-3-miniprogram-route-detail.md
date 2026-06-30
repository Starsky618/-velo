# Task 3：小程序路线详情入口

## 目标

在路线详情页加“导出到码表”，让用户能下载 GPX/TCX，并知道下一步去哪里导入。

## 用户多了什么体验

骑友看完路线数据后，不用复制链接、截图或去别的平台重画路线，直接下载文件。下载完成后，页面告诉他去 Garmin Connect / iGPSPORT / 顽鹿 / Wahoo 的路线导入页选择文件。

## 改动范围

- `miniprogram/utils/api.js`
- `miniprogram/pages/route-detail/route-detail.js`
- `miniprogram/pages/route-detail/route-detail.wxml`
- `miniprogram/pages/route-detail/route-detail.wxss`

## 合同

- `guide.export_ready === true` 才显示 GPX/TCX 下载按钮。
- 没有可下载轨迹或完整逐点海拔时不显示按钮，只显示轻提示。
- 下载失败要说人话，不把 403/422 直接扔给用户。
- 不承诺自动打开目标 App。

## 验收

```bash
node --check miniprogram/utils/api.js
node --check miniprogram/pages/route-detail/route-detail.js
```

真用回归要在微信开发者工具或真机里点一次 `wx.downloadFile`。
