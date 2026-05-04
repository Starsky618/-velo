# 任务 3.B.1：admin H5 独立 repo（3 主页面）

> **brainstorming v2 / 2026-05-05 决策落地**（替换 v1 task 卡）：
> 1. **A1** 纯 PC 浏览器（手机不优化，仅保证不崩）
> 2. **路径 1** 小程序复制 token + 7 天 refresh 登录态
> 3. **路径 B** Vite + React + TypeScript + AntD
> 4. **Y3** 砍 from-activity 页面（下放给 segment-creator.html，见 task-3.B.2）
> 5. **R1** 独立 GitHub repo（不在 velo backend 仓库内）
> 6. **a** 仅 admin 可创赛段（task-3.A.6 后端守卫加固）

## 🎯 目标

新建独立 `admin-h5` GitHub repo（**不在 velo backend 仓库内**），部署到 `admin.velo.com`（或先用 IP）。**3 主页面** + 项目骨架 + 部署 + 登录页。**不做 from-activity 页面**（下放 task-3.B.2）。

## ⛓ 前置依赖

- task-3.A.5 ✅（admin 后端 from-activity / commit `8be37e3`）
- task-3.A.6（新加 / admin from-gpx endpoint + 老 endpoint deprecated）
- 元层 blocker：`app/segment/service.py` 拆分（793 行红灯 / memory `feedback_project_health_dashboard_gap.md` 优先级 2）—— admin H5 实施期会再加 segment 调用 → 拆分前会进一步腐化
- 新建 `admin-h5` GitHub repo（产品 / 运维侧手工建）
- 新购域名 `admin.velo.com`（暂用 IP 也行 / CLAUDE.md 拍）

## 📤 输出契约

| 产物 | 用途 |
|---|---|
| `admin-h5` GitHub repo | 独立 React 项目，独立 CI/CD 流水线 |
| 登录页 `/login` | JWT token 粘贴 + 校验 + 存 localStorage + 7 天 refresh |
| 候选池审查页 `/admin/curation-pool` | 5.D.1 候选池筛选 + 勾选触发 AI 草稿 |
| AI 草稿审核页 `/admin/drafts` | 5.D.2 草稿 list + 编辑 + approve/reject/regenerate |
| 批量管理页 `/admin/segments` | 5.D.3 赛段元数据修复 + 删除 |
| `Dockerfile` + `nginx.conf` | 容器化部署 |
| Caddy 反代配置 | 主项目 Caddyfile 加 `admin.velo.com` 段 |

**不在本卡范围**：from-activity 页面（task-3.B.2 用 segment-creator.html 替代）。

## 🧱 现状（grep 已验证 2026-05-05）

- velo backend 仓库内**无** H5 admin 前端
- 现有小程序前端在 `miniprogram/`（不复用，admin 走独立 H5）
- Caddyfile 现有 `velo.com` 反代主站；新增 `admin.velo.com` 段
- `tools/segment-creator.html` 现存（59KB / 4 commit 历史） / task-3.B.2 搬到 admin-h5/public/
- 后端 9 admin endpoint 已实现（admin/router.py 已 grep / 见 task-3.A.1 ~ 3.A.5）
- `app/segment/service.py:49 create_segment()` 已有 service 层 `is_admin` 守卫（PermissionError → 403）

## 🛠 完整代码（骨架）

### 1. 选型

| 维度 | 选择 | 理由 |
|---|---|---|
| 框架 | Vite + React 18 + TypeScript | brainstorming 拍 / agent 训练数据最丰富 |
| UI | Ant Design 5.x（暗色主题） | 后台管理工业标准 / 表格 + 表单组件齐全 |
| HTTP | axios + @tanstack/react-query | 异步状态管理标准组合 |
| 状态 | Zustand | 轻量全局态（仅存登录 token） |
| 路由 | React Router v6 | 标准 |
| 认证 | JWT 走小程序 wx.login() 拿 token / localStorage / 7 天 refresh | brainstorming 拍 |

### 2. 项目骨架

```bash
# 1. 新建 GitHub repo（手工 / 不能 agent 做）
# https://github.com/Starsky618/admin-h5

# 2. clone 到本地
cd ~/Desktop && git clone git@github.com:Starsky618/admin-h5.git
cd admin-h5

# 3. Vite 初始化
npm create vite@latest . -- --template react-ts
npm install antd axios @tanstack/react-query zustand react-router-dom
npm install -D @types/node
```

### 3. 目录结构

```
admin-h5/
├── public/
│   └── segment-creator.html    # task-3.B.2 搬来
├── src/
│   ├── api/
│   │   ├── client.ts          # axios 实例 + JWT interceptor + 401 重定向
│   │   ├── curation.ts        # GET/PATCH /api/admin/curation-pool
│   │   ├── drafts.ts          # POST/GET/PATCH /api/admin/ai/segment-drafts
│   │   └── segments.ts        # GET/PATCH/DELETE /api/admin/segments
│   ├── auth/
│   │   ├── store.ts           # Zustand store（token 持久化 localStorage）
│   │   └── refresh.ts         # 每次启动尝试 refresh token，失败重定向 /login
│   ├── pages/
│   │   ├── LoginPage.tsx              # JWT 输入框 + 校验
│   │   ├── CurationPoolPage.tsx       # 候选池
│   │   ├── DraftReviewPage.tsx        # AI 草稿（左右分栏）
│   │   └── SegmentsManagePage.tsx     # 批量管理
│   ├── components/
│   │   ├── AppLayout.tsx              # AntD Layout + 侧栏导航
│   │   └── （各页面专用组件按需）
│   ├── App.tsx                        # 路由 + AntD ConfigProvider（dark theme）
│   └── main.tsx
├── Dockerfile                         # 多阶段构建：node 编译 → nginx serve
├── nginx.conf                         # /api/* 转发 backend / 其他 SPA fallback
├── docker-compose.yml.example         # 给 velo 部署 ref（实际 service 加在主 docker-compose）
├── .env.example                       # VITE_API_BASE_URL=https://admin.velo.com（同域 Caddy 反代）
└── package.json
```

### 4. 登录态实现（路径 1）

#### 4.1 小程序侧（独立小任务，不在本卡）

`miniprogram/pages/profile/profile.js` 加按钮"复制 admin token"：
```javascript
// 拷贝当前 wx.login() 拿到的 JWT 到剪贴板
copyAdminToken() {
  const token = wx.getStorageSync('jwt_token');
  wx.setClipboardData({ data: token });
  wx.showToast({ title: '已复制 / 7 天有效' });
}
```

#### 4.2 admin H5 登录页

```tsx
// src/pages/LoginPage.tsx
function LoginPage() {
  const [token, setToken] = useState('');
  const setAuth = useAuthStore(s => s.setAuth);
  
  async function handleSubmit() {
    // 校验 token：调一个轻量 endpoint（如 GET /api/users/me 看 is_admin）
    try {
      const r = await axios.get('/api/users/me', {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!r.data.is_admin) {
        message.error('你不是 admin');
        return;
      }
      setAuth(token, r.data);
      navigate('/admin/curation-pool');
    } catch (e) {
      message.error('token 无效或过期');
    }
  }
  
  return (
    <div>
      <h1>velo admin 登录</h1>
      <p>1. 在小程序"我的"页点"复制 admin token"</p>
      <p>2. 粘贴到下方</p>
      <Input.TextArea value={token} onChange={e => setToken(e.target.value)} />
      <Button onClick={handleSubmit}>登录</Button>
    </div>
  );
}
```

#### 4.3 axios interceptor

```ts
// src/api/client.ts
import axios from 'axios';
import { useAuthStore } from '@/auth/store';

const client = axios.create({ baseURL: '/api' });

client.interceptors.request.use(config => {
  const token = useAuthStore.getState().token;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

client.interceptors.response.use(
  r => r,
  err => {
    if (err.response?.status === 401) {
      useAuthStore.getState().clear();
      window.location.href = '/login';
    }
    return Promise.reject(err);
  }
);

export default client;
```

#### 4.4 Token refresh

每次 admin H5 启动时自动 refresh：调一个 backend endpoint `POST /api/auth/refresh`（已存在 / v0 期 JWT 模块），新 token 替换 localStorage。**只要 7 天内访问过 admin H5 一次，token 就续期**。一周不访问的人本来也不需要 admin。

### 5. 候选池审查页

```tsx
// src/pages/CurationPoolPage.tsx
function CurationPoolPage() {
  const [filters, setFilters] = useState({ city: undefined, difficulty: undefined, selected: undefined });
  const { data, refetch } = useQuery(['curation-pool', filters], () =>
    client.get('/admin/curation-pool', { params: filters }).then(r => r.data)
  );
  
  const cols = [
    { title: '赛段名', dataIndex: 'segment_name' },
    { title: '城市', dataIndex: 'city' },
    { title: '距离', dataIndex: 'distance', render: (v: number) => `${v.toFixed(1)} km` },
    { title: '爬升', dataIndex: 'elevation_gain' },
    { title: '难度', dataIndex: 'difficulty' },
    { title: '本周刷榜次数', dataIndex: 'attempts_count' },
    {
      title: '已选',
      dataIndex: 'selected_for_v5',
      render: (v: boolean, row: any) => (
        <Switch
          checked={v}
          onChange={async checked => {
            await client.patch(`/admin/curation-pool/${row.id}`, { selected_for_v5: checked });
            refetch();
            message.success(checked ? '已选 + 触发 AI 草稿生成' : '已取消');
          }}
        />
      ),
    },
  ];
  
  return (
    <div>
      <FilterBar filters={filters} setFilters={setFilters} />
      <Table columns={cols} dataSource={data?.items} pagination={data?.pagination} />
    </div>
  );
}
```

### 6. AI 草稿审核页（左右分栏）

```tsx
// src/pages/DraftReviewPage.tsx
function DraftReviewPage() {
  const [statusFilter, setStatusFilter] = useState('pending');
  const [selectedDraft, setSelectedDraft] = useState<any>(null);
  const { data: drafts, refetch } = useQuery(['drafts', statusFilter], () =>
    client.get('/admin/ai/segment-drafts', { params: { status: statusFilter } }).then(r => r.data)
  );
  
  return (
    <Row>
      <Col span={8}>
        <Segmented
          options={['pending', 'human_edited', 'approved', 'rejected']}
          value={statusFilter}
          onChange={setStatusFilter as any}
        />
        <List
          dataSource={drafts?.items}
          renderItem={d => (
            <List.Item onClick={() => setSelectedDraft(d)} className={selectedDraft?.id === d.id ? 'selected' : ''}>
              {d.segment_name} <Tag>{d.status}</Tag>
            </List.Item>
          )}
        />
      </Col>
      <Col span={16}>
        {selectedDraft && (
          <DraftEditor draft={selectedDraft} onSaved={refetch} />
        )}
      </Col>
    </Row>
  );
}

function DraftEditor({ draft, onSaved }) {
  const [text, setText] = useState(draft.human_edited_text || draft.ai_generated_text);
  const charCount = text.length;
  const isInRange = charCount >= 50 && charCount <= 100;
  
  return (
    <div>
      <h3>{draft.segment_name}</h3>
      <Input.TextArea value={text} onChange={e => setText(e.target.value)} rows={10} />
      <div style={{ color: isInRange ? 'green' : charCount > 100 ? 'red' : 'orange' }}>
        {charCount} / 50-100 字
      </div>
      <Space>
        <Button type="primary" onClick={async () => {
          await client.patch(`/admin/ai/segment-drafts/${draft.id}`, {
            human_edited_text: text,
            status: 'approved',
          });
          onSaved();
        }}>通过</Button>
        <Button danger onClick={async () => {
          await client.patch(`/admin/ai/segment-drafts/${draft.id}`, { status: 'rejected' });
          onSaved();
        }}>打回</Button>
        <Button onClick={async () => {
          await client.post(`/admin/ai/segment-drafts/${draft.segment_id}/generate`);
          message.info('已重新触发 AI 生成 / 5 秒后刷新');
          setTimeout(onSaved, 5000);
        }}>重新生成</Button>
      </Space>
    </div>
  );
}
```

### 7. 批量管理页

```tsx
// src/pages/SegmentsManagePage.tsx
// 类似候选池页，但多了行内编辑 city/difficulty 下拉 + 删除按钮
// 用 EditableProTable 或 Table + Form 模式
```

### 8. Caddyfile 反代（velo 主项目内）

`Caddyfile`（velo backend repo / 部署机）加：

```caddyfile
admin.velo.com {
    # 静态资源走 admin-h5 容器（nginx serve build）
    @api path /api/*
    handle @api {
        reverse_proxy api:8000
    }
    handle {
        reverse_proxy admin-h5:80
    }
}
```

### 9. Dockerfile（admin-h5 repo 内）

```dockerfile
# 阶段 1：build
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# 阶段 2：serve
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
```

### 10. velo 主项目 docker-compose.yml 加

```yaml
  admin-h5:
    build: ../admin-h5    # 假设 admin-h5 repo 在 velo backend repo 同级目录
    restart: unless-stopped
    networks:
      - velo-net
    # 无暴露端口；Caddy 反代
```

部署时：先 `cd ../admin-h5 && git pull`，再 `cd velo && sudo docker compose up -d admin-h5`。

## ✅ 端到端验收

- [ ] **登录流**：小程序复制 token → admin.velo.com 粘贴 → 校验通过 → 跳转候选池页
- [ ] **登录流 - 失败**：粘错 token → 提示"token 无效"；非 admin 用户 token → 提示"你不是 admin"
- [ ] **登录流 - refresh**：已登录状态打开 admin → 自动 refresh token → 不用再粘
- [ ] **候选池**：filter（城市 / 难度 / 已选）正确生效；勾选切换 → backend 确认 enqueue AI 任务
- [ ] **AI 草稿**：list 切 status filter；编辑 + approve → segments.description 同步更新；regenerate 触发后 5 秒看到新草稿
- [ ] **批量管理**：搜索 + filter；行内改 city/difficulty → backend 确认；删除确认弹窗 → 204
- [ ] **404 / 500 处理**：API 报错有 toast 提示，不白屏
- [ ] **手机访问**：手机浏览器打开能看到内容（不优化但不崩）

## 📝 commit（admin-h5 独立 repo 内 / 多 commit）

```
chore: 项目骨架（Vite + React + TS + AntD）
feat(auth): 任务 3.B.1.1 登录页 + JWT token 粘贴 + 7 天 refresh
feat(curation): 任务 3.B.1.2 候选池审查页（filter + 行内勾选）
feat(drafts): 任务 3.B.1.3 AI 草稿审核页（左右分栏 + 50-100 字校验）
feat(segments): 任务 3.B.1.4 批量管理页（行内编辑 + 删除）
feat(deploy): 任务 3.B.1.5 Dockerfile + nginx.conf + docker-compose 集成
docs: README + 部署说明
```

## 🔍 自检三问

1. **认证打通**：复用小程序生成的 JWT，is_admin 字段做 admin 鉴权。**不申请微信开放平台"网站应用"**（避免企业资质审核风险，brainstorming 路径 2 已 push back）。
2. **CORS**：Caddy 反代后实际同域（`admin.velo.com/api/*`），无 CORS 问题。
3. **from-activity 哪去了**：下放给 segment-creator.html（task-3.B.2），通过 `admin.velo.com/segment-creator.html` 访问。admin H5 在合适位置（如批量管理页）加链接"打开赛段创建工具"。
