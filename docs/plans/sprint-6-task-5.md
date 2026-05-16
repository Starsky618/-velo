# Sprint 6 Task-5 — 前端 settings 子页 + 后端 unbind endpoint

> 所属：Sprint 6（"我的"页基础落地 / 共 6 task）
> 这是第 5 个 task / 前端 + 后端混合 / 无前置依赖
> v0.2（2026-05-16）：v0.1 假设解绑 endpoint 已存在 / 实际不存在 / 本 task 后端新增 / 字段名 strava_athlete_id（不是 strava_user_id）/ 用 GET /api/strava/status 查 bound
> v0.3（2026-05-16）：修第二轮集成审 Critical —— unbind_strava 同事务追加 UPDATE strava_imports active → paused（与现有 _handle_athlete_deauthorize 对齐 / 防调度器空转 + 重新绑定 dedupe 风险）/ 删 spec 内"待 grep 确认"已知 stale 注释
> 上下文：2026-05-15 brainstorm / Tim 拍 E/F 进 settings 子页 / FTP 敏感不放主页（Sprint 4 codex P1-4）

---

## ─────── 给 Tim 看（你审这层就够）───────

### 干啥用

把现在几乎空的 settings 子页（38 行 js + 16 行 wxml 的空架子）补全——里面就三件事：改 FTP / 退出登录 / 解绑 Strava。这些都是用户每天不点 / 但出问题时一定要能点到的功能。

同时本 task **后端新增** `POST /api/strava/unbind` endpoint（v5 期没有 / 必须补）。

入口：从"我的"页右上角的设置 icon（task-4 加）跳进来。

### 用户故事

**故事 A — 改 FTP**
小明做完一次正式 FTP 测试 / 测出 235W → 进 settings → 看到"账号资料"区有 FTP 一格 / 显示当前 220W → 点编辑 → 输 235 → 保存 → 后端 PUT /profile 写入 → toast "FTP 已更新" → 返回"我的"页能看到新数字。

**故事 B — 解绑 Strava**
小明想换个 Strava 账号 / 进 settings → "第三方账号"区显示"Strava：已绑定"（来源 GET /api/strava/status）→ 点解绑 → 弹二次确认（"解绑后历史活动保留 / 但不再自动同步"）→ 确认 → 调 POST /api/strava/unbind → 后端清 4 个 strava 字段 → toast "已解绑" → 那行变成"未绑定"+ 一个绑定按钮。

**故事 C — 退出登录**
小明把手机借给颜颜用 / 进 settings → "登录态"区点退出 → 弹二次确认（"退出后需要重新登录"）→ 确认 → token 清掉 → 自动跳回"我的"页 / 显示"微信一键登录"按钮。

**故事 D — FTP 范围拒收**
小明手抖输 501 → 后端拒收 → toast "FTP 范围 50-500" → 留在输入框继续改。

**故事 E — 解绑不丢活动**
小明已经从 Strava 导入了 50 条历史活动 → 解绑 Strava 后 → 这 50 条活动**还在**（不会被删）。重新绑定时 dedupe 防重复导入。

### 怎么算做对了

- ✓ 进 settings → 三区块（账号资料 / 第三方绑定 / 登录态）正确显示
- ✓ FTP 编辑：改 220 → 保存 → 返"我的"页可见
- ✓ FTP 边界：输 49 → 拒收 / 输 501 → 拒收
- ✓ **POST /api/strava/unbind** 后：user.strava_athlete_id / strava_access_token / strava_refresh_token / strava_token_expires_at **4 个字段全清 NULL**
- ✓ 解绑后 activities 表行数不变（已导入的活动保留）
- ✓ 解绑前端：弹二次确认 → 确认后 stravaBound 变 false / 显示"未绑定"
- ✓ 退出登录：弹二次确认 → token 清 / 跳回 profile 显示登录按钮
- ✓ 危险按钮（解绑 / 退出）颜色高对比 + 强制二次确认 / 防误点
- ✗ 解绑 / 退出未弹二次确认就执行 / 是 bug
- ✗ 解绑后 activities 被删 / 是 bug
- ✗ 解绑后 strava 任一字段没清 / 是 bug

### 这次**不做**的事

- 注销账号 / 删除账号（保留给未来"用户中心" Sprint）
- 隐私设置 / 通知免打扰 / 个性化（推到隐私 Sprint）
- 多设备登录管理（小程序天然单设备 / 不做）
- 数据导出 / GDPR / 法规合规（100 用户量级 / 不做）
- weight / 车辆 / 装备字段编辑（FTP 之外 / 未拍）
- 切换主题 / 字体大小（未拍）
- **解绑时主动撤销 Strava OAuth 授权**（调 Strava API）→ 不做（仅清本地 token / Strava 端用户自行去后台撤销）

### 估时

1-2 天（含双审 + 真机测试）

---

## ─────── 折叠：执行 subagent 看的技术细节 ───────

<details>
<summary>展开</summary>

### 起手必跑：现状 grep

```bash
# settings 现状（空架子）
wc -l miniprogram/pages/settings/settings.*

# Strava endpoint 全集（PRD § 0.1 实证：无 unbind）
rg "@router\.(get|post|put|delete)" app/strava/router.py

# User strava 字段名（PRD § 0.1 实证：strava_athlete_id 不是 strava_user_id）
rg "strava_" app/user/models.py

# 退出登录前端是否有 helper
rg "logout|clearToken|globalData.token" miniprogram/app.js miniprogram/utils/

# FTP 校验范围（PRD § 0.1 实证 schemas.py:74 ge=50 le=500）
rg "ftp.*Field|ge=50|le=500" app/user/schemas.py
```

**事实表实证（PRD § 0.1）**：
- settings.js 38 行 / wxml 16 行 / 空架子 / 大幅改造
- Strava endpoint：authorize / callback / status / webhook / sync / import-progress（**无 unbind** / 本 task 补）
- User strava 字段：**strava_athlete_id**（BigInteger / unique）/ strava_access_token / strava_refresh_token / strava_token_expires_at（4 字段）
- FTP 校验：`Field(None, ge=50, le=500)` 已实证

### 页面布局（3 区块）

```xml
<view class="settings-page">
  <!-- 区块 1：账号资料 -->
  <view class="section">
    <view class="section-title">账号资料</view>
    <view class="row" bindtap="onEditFtp">
      <text class="row-label">FTP</text>
      <text class="row-value">{{ftp ? ftp + ' W' : '未设置'}}</text>
      <text class="row-arrow">›</text>
    </view>
  </view>

  <!-- 区块 2：第三方账号 -->
  <view class="section">
    <view class="section-title">第三方账号</view>
    <view class="row">
      <text class="row-label">Strava</text>
      <text class="row-value" wx:if="{{stravaBound}}">已绑定</text>
      <text class="row-value" wx:else>未绑定</text>
      <button class="danger-btn" wx:if="{{stravaBound}}" bindtap="onUnbindStrava">解绑</button>
      <button class="primary-btn" wx:else bindtap="onBindStrava">绑定</button>
    </view>
  </view>

  <!-- 区块 3：登录态 -->
  <view class="section">
    <view class="section-title">登录态</view>
    <button class="danger-btn full-width" bindtap="onLogout">退出登录</button>
  </view>
</view>
```

### 前端 js 逻辑（用 GET /api/strava/status 查 bound）

```javascript
const api = require('../../utils/api')
const app = getApp()

Page({
  data: {
    ftp: null,
    stravaBound: false,
  },

  onShow() {
    if (!app.globalData.token) {
      wx.redirectTo({ url: '/pages/profile/profile' })
      return
    }
    // 拉 FTP（来自 self profile）
    api.get('/api/user/profile').then(p => {
      this.setData({ ftp: p.ftp })
    })
    // 拉 Strava 绑定状态（用 /api/strava/status / v0.2 修 / 不从 profile 拉 strava_athlete_id）
    // 实证：app/strava/service_token.py:71 返字段名 = "bound" (boolean / connected 别名)
    api.get('/api/strava/status').then(s => {
      this.setData({ stravaBound: !!s.bound })
    })
  },

  onEditFtp() {
    wx.showModal({
      title: 'FTP',
      editable: true,
      placeholderText: '50-500',
      success: (res) => {
        if (!res.confirm) return
        const ftp = parseInt(res.content, 10)
        if (isNaN(ftp) || ftp < 50 || ftp > 500) {
          wx.showToast({ title: 'FTP 范围 50-500', icon: 'none' })
          return
        }
        // FTP 走 PUT /profile（主资料字段 / v5 期分工）
        api.put('/api/user/profile', { ftp }).then(() => {
          this.setData({ ftp })
          wx.showToast({ title: 'FTP 已更新', icon: 'success' })
        })
      },
    })
  },

  onUnbindStrava() {
    wx.showModal({
      title: '解绑 Strava',
      content: '解绑后历史活动保留 / 但不再自动同步新活动',
      confirmColor: '#e64340',
      success: (res) => {
        if (!res.confirm) return
        api.post('/api/strava/unbind').then(() => {
          this.setData({ stravaBound: false })
          wx.showToast({ title: '已解绑', icon: 'success' })
        })
      },
    })
  },

  onBindStrava() {
    api.get('/api/strava/authorize').then(r => {
      // 复用 v4 既有授权流程 / 跳浏览器
      // ... 已有逻辑
    })
  },

  onLogout() {
    wx.showModal({
      title: '退出登录',
      content: '退出后需要重新登录',
      confirmColor: '#e64340',
      success: (res) => {
        if (!res.confirm) return
        wx.removeStorageSync('token')
        app.globalData.token = null
        wx.redirectTo({ url: '/pages/profile/profile' })
      },
    })
  },
})
```

### **后端新增 POST /api/strava/unbind**（v0.2 / v5 期没有 / 本 task 补）

```python
# app/strava/router.py 追加：

@router.post("/unbind", status_code=204)
def unbind_strava(
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """解绑 Strava 账号。

    清 User 表 4 个 strava 字段：
    - strava_athlete_id（注意字段名 / 不是 strava_user_id）
    - strava_access_token
    - strava_refresh_token
    - strava_token_expires_at

    历史 strava_imports 记录 + 已导入 activities 保留（仅停止后续同步）。
    解绑时不调 Strava API 撤销授权（用户自行去 Strava 后台撤销 / 简化设计）。

    Worker 并发场景（解绑时 worker 正用旧 token 同步）→ token 清后 worker 下次调用拿到 None
    → handle_strava_api_call 容错跳过（已有 UnboundStravaError 翻译 / 不在本 task scope）。
    """
    service.unbind_strava(db, user_id)


# app/strava/service.py 追加：
def unbind_strava(db, user_id: int) -> None:
    """主动解绑 Strava（与 _handle_athlete_deauthorize 行为对齐 / v0.3 加 strava_imports 暂停）。"""
    user = db.query(User).filter(User.id == user_id).one()
    user.strava_athlete_id = None
    user.strava_access_token = None
    user.strava_refresh_token = None
    user.strava_token_expires_at = None

    # v0.3 加（集成审 Critical）：同事务把该用户所有 active 的 strava_imports 转 paused
    # 防止：1) 调度器下一 tick 继续 pick active job 白消耗
    #      2) 重新绑定后 active 行对新 token 继续导入触发 dedupe
    # 与 service_sync.py:115-123 _handle_athlete_deauthorize 行为一致
    from app.strava.models import StravaImport  # 实际 import 位置实施时确认
    db.query(StravaImport).filter(
        StravaImport.user_id == user_id,
        StravaImport.status == 'active',
    ).update({'status': 'paused'}, synchronize_session=False)

    db.commit()
```

**红线**（v0.2/v0.3 Critical 实证）：
- 字段名 **strava_athlete_id**（BigInteger / unique）/ **不是 strava_user_id**
- 4 个字段全清 / 漏一个 = bug
- 不能 cascade 删除 activities / strava_imports（保留历史轨迹 / 仅 status 改 paused）
- **v0.3**：与 `_handle_athlete_deauthorize` 行为对齐（grep `app/strava/service_sync.py:115-123` 实证 pattern）/ 漏暂停 strava_imports = 调度器破坏
- Codex 异源审重点扫这条

### 测试要求

**后端 pytest**（v0.3：最少 7 条）：
1. POST /api/strava/unbind → user.strava_athlete_id IS NULL（DB 验证）
2. POST /api/strava/unbind → 4 个 strava 字段全 NULL
3. POST /api/strava/unbind → activities 表行数不变（已导入活动保留）
4. POST /api/strava/unbind → strava_imports 表**行数不变 + 但 active 行全 → paused**（v0.3 加 / 集成 Critical 修）
5. POST /api/strava/unbind → strava_imports 'completed' / 'paused' 行状态**不变**（只动 active）
6. 重新绑定 / Strava OAuth 流程能正常完成（dedupe 防重复导入 / paused 行不会被调度器 pick）
7. 调度器 import_scheduler 下一 tick 不会 pick 该用户已 paused 的 import 任务

**前端真机测试**：
- 打开 settings → 三区块正确显示
- FTP 边界（49 / 50 / 500 / 501 各一次）
- 解绑流程 / 退出流程 / 各场景二次确认

### "-" 占位符永久规则

- ✅ "FTP" 行：`{{ftp ? ftp + ' W' : '未设置'}}`（'未设置' 是占位文案 / 不是"-" / 允许）
- ❌ 不能写 `{{ftp || '-'}}`

### 双审顺序

1. **Claude A 忠 PRD**：3 区块全在 / FTP 范围严控 / 二次确认强制 / 后端新增 unbind endpoint / 字段名 strava_athlete_id（不是 strava_user_id）
2. **Claude B 集成审**：解绑 4 字段全清 / activities + strava_imports 保留 / 重新绑定 dedupe 不重导入 / worker 并发 token NULL 容错
3. **Codex 异源审**：扫"解绑误删活动" + "Strava 4 字段名实证" + "二次确认能否被绕过" + "POST /api/strava/unbind 路径前缀 strava 不是 user"

### 依赖 / 顺序

- 依赖：无（独立 task / 可与 task-1/2/3 并行起草）
- 阻塞：task-6 真用回归

### 部署 SOP

5 步 SOP / 真机测试三个流程都跑一遍。

</details>
