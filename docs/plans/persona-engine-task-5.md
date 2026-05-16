# Persona Engine Task-5 — 小程序 NPC 文案展示（5 个 page + 错误页）

> 所属：Persona Engine Sprint / 6 task 中的第 5 个 / 前端展示层
> 上下文：宪法 § 7.5.1 PERSONA_START/END 标记块约定
> **共用约束 / SOP / 双审**：详见 `persona-engine-handoff.md`

---

## ─────── 给 Tim 看 ───────

### 干啥用

把 NPC 接到小程序界面 / 让用户真在 velo 里看到老登说话——

- **打开"我的"页**：头像下方 / 段位卡旁出现 NPC 一句
- **打开"看他人"页**：同上（自他对称）
- **打开活动详情页**：PR 横幅 + 段位文案
- **上传完活动**：toast 3 秒显示 NPC 反应
- **网络断 / 错误页**：写死宪法 § 2.6 那 4 条错误文案

### 用户故事

**故事 A — 我的页**
小明打开"我的"页 / 头像下面除了昵称 + 签名 + 城市 / 还有一句"80km。蹬两脚意思意思。"（老登段位）他笑了。

**故事 B — 上传完 PR**
小明骑了一个 120km PR → 上传 GPX → 等 3 秒（worker 跑完）→ toast 弹出"前 1% 的一天。"3 秒后消失。他截图发朋友圈。

**故事 C — 网络断**
小明上地铁 / 信号断 → 打开 velo → 错误页显示"连不上。WiFi 切流量试试。"他不再以为是 token 过期。

**故事 D — 他人页**
小明点 CCF 头像 / 进 user 页 / 看到 CCF 的 NPC 文案"8500km 里这一天。"——他对 CCF 的骑龄有具体认知。

### 怎么算做对了

- ✓ 5 个 page（profile / user / detail / upload / 错误页）都有 PERSONA_START/END 标记块
- ✓ profile / user 页 NPC 块在头像旁 / 看得到老登一句
- ✓ 上传完 PR / 普通活动 → toast 显示对应场景文案
- ✓ 断网时错误页文案对 / 不崩
- ✓ 文案过长 → CSS truncate 兜底
- ✗ NPC API 返 null → 前端崩 / 显示 "null" / 空白长条 = 是 bug

### 这次**不做**的事

- 用户对 NPC 点赞 / 踩 / 长按反馈（v1.0+）
- NPC 文案渐入渐出动画（先静态显示）
- 多人格选择 UI（v2.0+）
- explore / segment / honor / notification 等 page（不属于宪法 § 2 八场景）

### 估时

2-3 天

---

## ─────── 折叠：技术细节 ───────

<details>
<summary>展开</summary>

### 防火墙红线（前端层）

参 handoff § 1。本 task 重点：
- § 1.2 命名前缀：`miniprogram/utils/persona_fetch.js` + wxml 块用 `<!-- PERSONA_START -->` / `<!-- PERSONA_END -->`
- § 1.4 失败隔离：API 返 null / 报错 → wx:if 隐藏整块 / 不显示空白 / 不报错给用户

### `miniprogram/utils/persona_fetch.js`（新建）

```javascript
// PERSONA_START
const api = require('./api')

/**
 * 调 /api/persona/output / 拿当前场景 NPC 文案。
 * v0.4 修 / Codex I1 / 第 3 参数 targetUserId / 看他人页拿对方 NPC
 * @param {string} sceneType
 * @param {number=} activityId       可选 / detail 页 / upload toast 传入精准定位
 * @param {number=} targetUserId     可选 / 看他人页传被看者 user_id / 未传 = 看自己
 * @returns {Promise<{template_text: string | null, scene_type: string, created_at: string | null}>}
 */
function fetchPersonaOutput(sceneType, activityId, targetUserId) {
  var params = { scene_type: sceneType }
  if (activityId) params.activity_id = activityId
  if (targetUserId) params.target_user_id = targetUserId
  return api.get('/api/persona/output', params)
    .catch(function (err) {
      console.warn('persona fetch failed (silently ignored):', err)
      return { template_text: null, scene_type: sceneType, created_at: null }
    })
}

/**
 * 拿用户最近 N 条 NPC 历史。
 */
function fetchRecentPersona(limit) {
  return api.get('/api/persona/recent', { limit: limit || 10 })
    .catch(function () { return { items: [] } })
}

module.exports = { fetchPersonaOutput, fetchRecentPersona }
// PERSONA_END
```

### profile.wxml 加 NPC 块（`miniprogram/pages/profile/profile.wxml`）

```xml
<!-- PERSONA_START -->
<view wx:if="{{personaText}}" class="persona-line">
  {{personaText}}
</view>
<!-- PERSONA_END -->
```

profile.js onShow 加：

```javascript
// PERSONA_START
const { fetchPersonaOutput } = require('../../utils/persona_fetch')

// 在 onShow 现有逻辑里追加：
fetchPersonaOutput('profile_open').then(res => {
  this.setData({ personaText: res.template_text || null })
})
// PERSONA_END
```

### user.wxml（看他人 / 同 profile 结构 / 自他对称）

```xml
<!-- PERSONA_START -->
<view wx:if="{{personaText}}" class="persona-line">{{personaText}}</view>
<!-- PERSONA_END -->
```

user.js onShow 调 `fetchPersonaOutput('user_page_open', null, targetUserId)`（v0.4 修 / Codex I1 / utils 第 3 参数 target_user_id / 让看他人页拿对方 NPC 而不是自己的 NPC）。

```javascript
// user.js onShow 内 / 在 onLoad 时保存 targetUserId 到 this.data
// v0.4 修 / Codex 第四轮抓 / 真实 user.js onLoad 用 options.id (不是 options.user_id) / grep 实证 user.js:62
// onLoad 内：const userId = parseInt(options && options.id, 10); this.setData({ targetUserId: userId })
// onShow 内：用 this.data.targetUserId 调 fetchPersonaOutput
const targetUserId = this.data.targetUserId  // 路由参数 options.id 解析后存的
if (targetUserId) {
  fetchPersonaOutput('user_page_open', null, targetUserId).then(res => {
    this.setData({ personaText: res.template_text || null })
  })
}
```

utils 第 3 参数 target_user_id 加进 persona_fetch.js（详 utils 段）。

### detail.wxml 加 PR 横幅 + 段位文案

```xml
<!-- PERSONA_START -->
<view wx:if="{{personaPrText}}" class="persona-pr-banner">{{personaPrText}}</view>
<view wx:if="{{personaSegmentText}}" class="persona-segment-text">{{personaSegmentText}}</view>
<!-- PERSONA_END -->
```

detail.js onLoad：调 2 次 fetchPersonaOutput / 分别拿 scene_type='pr' + 'segment_distance' / 都写入 setData。

### upload.js 上传完 toast（v0.2 修 / Claude B 抓 I-8 / 改 polling status 替代固定等待）

```javascript
// PERSONA_START
// 上传完成后 / polling activity status 直到 completed / 再调 persona fetch
const { fetchPersonaOutput } = require('../../utils/persona_fetch')
const api = require('../../utils/api')

function _pollUntilCompleted(activityId, maxAttempts) {
  // 每 2 秒 poll 一次 / 最多 maxAttempts 次（30 次 ≈ 60s 上限）
  return new Promise(function (resolve) {
    var attempts = 0
    var timer = setInterval(function () {
      attempts++
      api.get('/api/activities/' + activityId + '/status')
        .then(function (res) {
          if (res.status === 'completed') {
            clearInterval(timer)
            resolve(true)
          } else if (res.status === 'failed' || attempts >= maxAttempts) {
            clearInterval(timer)
            resolve(false)
          }
        })
        .catch(function () {
          if (attempts >= maxAttempts) {
            clearInterval(timer)
            resolve(false)
          }
        })
    }, 2000)
  })
}

// 上传 success callback 内（res.activity_id = 新建 activity id）：
_pollUntilCompleted(res.activity_id, 30).then(function (ok) {
  if (!ok) return  // worker 没完成 / NPC 文案没生成 / 静默不显示
  // v0.2 修 / Claude B 抓 I-9 / 传 activity_id 让 endpoint 精准拿当前活动文案
  fetchPersonaOutput('activity_upload', res.activity_id).then(function (r) {
    if (r.template_text) {
      wx.showToast({ title: r.template_text, icon: 'none', duration: 3000 })
    }
  })
})
// PERSONA_END
```

**注**：fetchPersonaOutput 第 2 参数 = activity_id（task-4 endpoint v0.2 已加该 query 参数）/ task-4 endpoint signature 实证后调用一致。

### 错误页 / 空状态 / loading（全局组件）

不调 endpoint / 直接写死宪法 § 2.6 那 8 条对应场景文案：

```javascript
// miniprogram/utils/persona_static.js
// PERSONA_START
const PERSONA_STATIC_TEXTS = {
  empty: '还没数据。先去蹬两圈。',
  upload_failed: '今天轨迹丢了。下次记得开 GPS。',
  network_down: '连不上。WiFi 切流量试试。',
  server_5xx: '服务器在打盹儿。',
  loading: '算你的高光中…',
  unauth_401: '要重新登录一下了。',
  uploading: '正在抢救你今天的轨迹。',
  delete_confirm: '这条骑行要丢了哦。',
}

function getPersonaStatic(key) {
  return PERSONA_STATIC_TEXTS[key] || ''
}

module.exports = { getPersonaStatic }
// PERSONA_END
```

各错误处理 utils（如 api.js 的 401 / 5xx 拦截器）调 `getPersonaStatic('network_down')` 等。

### CSS 兜底（profile.wxss / detail.wxss / 等）

```css
/* PERSONA_START */
.persona-line {
  font-size: 26rpx;
  color: #888;
  margin-top: 12rpx;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;  /* 单行 truncate / 防文案过长溢出 */
}

.persona-pr-banner {
  font-size: 32rpx;
  font-weight: 600;
  color: #c97e2e;  /* 金色暗示 PR */
  text-align: center;
  padding: 20rpx 0;
}
/* PERSONA_END */
```

### 测试要求（前端真用 + 必要时单测）

真用 5 个 page：

1. 注册新用户 → 打开 profile → 看到至少 1 条 NPC 文案
2. 上传 PR 活动 → 等 3-5s → toast 显示 PR 场景文案
3. 上传普通 80km → toast 显示段位场景文案
4. 关 WiFi → 打开 velo → 错误页文案对（不显示"token 过期"或 "网络错误"通用提示）
5. 点别人头像进 user 页 → 看到他人 NPC 文案
6. 拔出测试：搜 `<!-- PERSONA_START -->` / `<!-- PERSONA_END -->` 在 wxml 里 → 5 个 page 各有一对

### 双审 focus（前端协议自校验）

参 memory `feedback_frontend_protocol_self_check.md`。本 task **重点扫**：
- wxml ↔ js 函数名 grep 自校验（personaText 在 wxml 和 js 都对得上）
- js ↔ api helper 参数（fetchPersonaOutput 调 sceneType 实际后端要 scene_type）
- setData 字段 ↔ wxml 渲染（防"data 字段没设 wxml 拿不到"）
- PERSONA_START/END 标记是否真在 5 个 page 都有 / 可剥离（拔出测试前提）

### 依赖

- 依赖：task-3（service api）+ task-4（endpoint）
- 阻塞：task-6（真用回归）

### 部署 verify

无后端部署 / 小程序端真用回归是唯一标准（详 task-6）。

</details>
