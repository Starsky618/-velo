# 任务 3.B.1：H5 admin 项目（独立 repo）

## 🎯 目标

新建独立 H5 admin 前端项目（不在 backend 仓库内），部署到 `admin.velo.com`。**仅包含项目骨架 + 4 主页面 + Caddy 反代配置**——具体 UI 设计由 admin 团队按需迭代。

## ⛓ 前置依赖

- task-3.A.5（admin 后端 5 串行任务全部完成 → API 全可调）
- 新购域名 `admin.velo.com`（产品 / 运维侧拍）

## 📤 输出契约

| 文件 / 配置 | 用途 |
|---|---|
| `admin-h5/`（独立 repo 或 monorepo 目录） | React/Vue 前端项目 |
| 4 主页面 | 候选池 / AI 草稿审核 / 批量管理 / from-activity 工具 |
| Caddyfile 反代配置 | admin.velo.com → admin-h5 容器 |
| 部署文档 | docker-compose 加 admin-h5 容器（可选） |

## 🧱 现状

- 项目仓库内**无 H5 admin 前端**（v5 全新建）
- 现有小程序前端在 `miniprogram/`（不复用，admin 走独立 H5）
- Caddyfile 现有 `velo.com` 反代主站；新增 `admin.velo.com` 段

## 🛠 完整代码（骨架）

### 1. 选型（推荐）

- **框架**：Vite + React 18 + TypeScript（团队 React 熟悉度高于 Vue）
- **UI**：Ant Design（admin 后台标准，免费组件齐全）
- **HTTP**：axios（项目其他位置也用，团队熟）
- **状态**：React Query（异步状态管理）+ Zustand（轻量全局态）
- **认证**：JWT 走主站 `/api/login` 共用 token，存 localStorage

### 2. 项目骨架

```bash
mkdir admin-h5 && cd admin-h5
npm create vite@latest . -- --template react-ts
npm install antd axios @tanstack/react-query zustand react-router-dom
```

目录结构：

```
admin-h5/
├── src/
│   ├── api/
│   │   ├── client.ts          # axios 实例 + JWT interceptor
│   │   ├── curation.ts        # GET/PATCH /api/admin/curation-pool
│   │   ├── drafts.ts          # POST/GET/PATCH /api/admin/ai/segment-drafts
│   │   ├── segments.ts        # GET/PATCH /api/admin/segments
│   │   └── from_activity.ts   # POST /api/admin/segments/from-activity
│   ├── pages/
│   │   ├── CurationPoolPage.tsx
│   │   ├── DraftReviewPage.tsx
│   │   ├── SegmentsManagePage.tsx
│   │   └── FromActivityPage.tsx
│   ├── components/
│   │   └── （admin UI 组件按需）
│   ├── App.tsx                # 路由 + AntD ConfigProvider
│   └── main.tsx
├── Dockerfile                 # nginx serve build/
├── nginx.conf                 # /api/* 转发到 backend container
└── package.json
```

### 3. Caddy 配置

`Caddyfile` 加：

```caddyfile
admin.velo.com {
    reverse_proxy admin-h5:80
    
    # /api/admin/* 转发到 backend
    @api path /api/*
    handle @api {
        reverse_proxy api:8000
    }
}
```

### 4. docker-compose.yml 加（可选）

```yaml
  admin-h5:
    build: ./admin-h5
    restart: unless-stopped
    # 无暴露端口；通过 Caddy 反代
```

## ✅ 测试

### 端到端验收

- [ ] admin 登录 admin.velo.com 用 JWT 跳转主站登录页 → 拿 token 回 admin
- [ ] 候选池页：list / filter / 切换 selected_for_v5 → 后端确认 enqueue
- [ ] AI 草稿审核页：list → 编辑 human_edited_text → 改 approved → segments.description 同步更新
- [ ] 批量管理页：list → PATCH 修改 city/difficulty → 后端确认
- [ ] from-activity 页：选 activity → 标 start/end → 创建 → 后端 201（or 409 重复）

## 📝 commit（独立 repo）

```
feat(admin-h5): 任务 3.B.1 admin H5 前端骨架

- Vite + React + TS + AntD 项目初始化
- 4 主页面（CurationPool / DraftReview / SegmentsManage / FromActivity）
- axios + React Query API client
- JWT 走主站 /api/login 共用 token
- Caddyfile 反代 admin.velo.com → admin-h5 容器
- docker-compose.yml 加 admin-h5 service
```

> 若用 monorepo，commit 直接进 backend 仓库 admin-h5/ 子目录。

## 🔍 自检三问

1. **认证打通**：admin 用主站 JWT 还是独立 token？  
   → 复用主站 JWT（is_admin 字段做 admin 鉴权）。admin.velo.com 跳到主站登录后回跳 callback 拿 token。

2. **CORS / 跨域**：admin.velo.com 调 velo.com/api/admin/* 跨域吗？  
   → Caddy 反代后实际同域（admin.velo.com/api/admin/*），无 CORS 问题。

3. **开发节奏**：本 task 只做骨架不做 UI 美化。admin 团队可在 v6+ 迭代。  
   → 是。spec §7 已限定"admin H5 跟主站独立部署流水线，不依赖 backend CI/CD"。
