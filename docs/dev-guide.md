# VELO Vibe Coding 开发者指南

> 用 Claude Code 开发本项目的实战手册。
> 不管你是 Starsky、颜颜还是 CCF，打开这份指南就能快速定位"我要改的东西在哪"。

## 项目结构地图

把整个项目想象成一栋大楼，每个文件夹是一个房间：

```
velo/                        ← 大楼入口（在这里开终端 = 全局操作）
├── app/                     ← 业务区（所有后端代码）
│   ├── main.py              ← 前台大厅（路由注册、应用启动）
│   ├── config.py            ← 配电箱（环境变量、全局配置）
│   ├── database.py          ← 水电总闸（数据库连接）
│   ├── dependencies.py      ← 安检门（JWT 认证）
│   ├── user/                ← 住户管理处
│   │   ├── models.py        ←   住户档案格式
│   │   ├── schemas.py       ←   表格模板
│   │   ├── service.py       ←   办事员（业务逻辑）
│   │   └── router.py        ←   前台接待（API 路由）
│   ├── activity/            ← 运动记录室
│   │   ├── models.py        ←   记录本格式
│   │   ├── gpx_parser.py    ←   翻译机（GPX → 结构化数据）
│   │   ├── simplify.py      ←   压缩机（轨迹抽稀）[Task 3.4]
│   │   ├── service.py       ←   办事员 [Task 3.5-3.7]
│   │   ├── router.py        ←   前台接待 [Task 3.5-3.7]
│   │   └── schemas.py       ←   表格模板 [Task 3.5-3.7]
│   ├── segment/             ← 赛段排行榜 [Task 4]
│   └── storage/             ← 档案室（文件存储）
├── tests/                   ← 质检车间
│   ├── conftest.py          ←   质检设备（测试数据库、mock）
│   └── test_user.py         ←   用户模块质检单
├── docs/                    ← 图纸室
│   ├── spec-v1.md           ←   施工图纸（唯一真相来源）
│   └── dev-guide.md         ←   本文件
├── worker.py                ← 后勤部（异步任务入口）
├── requirements.txt         ← 采购清单（依赖包）
└── .env.example             ← 钥匙模板（环境变量样例）
```

## 我要改 XX，在哪开终端？

**核心原则：始终在项目根目录 `velo/` 打开 Claude Code。**

不要在子文件夹开终端，因为：
- `import app.xxx` 需要从根目录才能正确解析
- `git` 命令需要在仓库根目录执行
- `pytest` 需要从根目录发现测试文件

```bash
cd ~/Desktop/velo
claude
```

然后告诉 Claude 你要改什么，它会自动定位到正确的文件。

## 常见修改场景速查

### "我要改登录逻辑"
```
涉及文件：app/user/service.py（wx_code_to_openid、get_or_create_user）
          app/user/router.py（POST /login）
测试文件：tests/test_user.py（test_01 ~ test_03）
告诉 Claude：「修改微信登录的 xxx 逻辑」
```

### "我要改用户资料的字段"
```
涉及文件：app/user/models.py（数据库列定义）
          app/user/schemas.py（请求/响应格式校验）
          app/user/service.py（更新逻辑）
测试文件：tests/test_user.py（test_05 ~ test_08）
告诉 Claude：「给用户资料加一个 xxx 字段」
```

### "我要改 GPX 解析规则"
```
涉及文件：app/activity/gpx_parser.py
告诉 Claude：「修改 GPX 解析中的 xxx 规则」
注意：这是纯函数，改完后跑测试验证即可，不影响其他模块
```

### "我要改 API 返回格式"
```
涉及文件：对应模块的 schemas.py（响应格式）
          对应模块的 router.py（路由函数）
告诉 Claude：「把 /api/user/stats 的返回格式改成 xxx」
```

### "我要加一个新的 API 接口"
```
涉及文件：对应模块的 router.py（加路由）
          对应模块的 schemas.py（加请求/响应格式）
          对应模块的 service.py（加业务逻辑）
          app/main.py（如果是新模块，需要挂载路由）
告诉 Claude：「在 activity 模块加一个 xxx 接口」
```

### "我要改数据库表结构"
```
涉及文件：对应模块的 models.py
之后需要：生成 Alembic 迁移（连接数据库后）
告诉 Claude：「给 activities 表加一个 xxx 字段」
注意：改表结构可能影响已有数据，需要写迁移脚本
```

### "我要排查一个 bug"
```
告诉 Claude：「/api/user/stats 返回的 distance 不对，请帮我排查」
Claude 会自动：读 router → 读 service → 读 SQL → 定位问题
```

## 模块间的依赖方向（铁律）

```
User ← Activity ← Segment
 ↑        ↑          ↑
 |        |          |
不能反向 import，信息只能从右往左流
```

- User 模块不知道 Activity 的存在（统计用 raw SQL，不 import Activity 代码）
- Activity 模块不知道 Segment 的存在
- 如果你发现自己在写反向 import，**停下来，设计有问题**

## Git 版本控制速查

```bash
# 看当前改了什么
git status
git diff

# 回退到上一个版本（最近一次 commit 之前的状态）
git log --oneline -5          # 先看最近 5 个 commit
git revert HEAD               # 创建一个新 commit 来撤销上一个（安全，推荐）

# 回退到指定版本
git revert <commit-hash>      # 撤销指定 commit

# 紧急情况：丢弃所有未提交的修改（慎用！）
git checkout -- .
```

**原则：用 `git revert`（安全回退），不用 `git reset --hard`（危险，会丢数据）。**

## 和 Claude Code 协作的最佳姿势

1. **一次只改一个东西**。别说"改登录逻辑顺便优化一下数据库查询"，拆成两次
2. **改完跑测试**。`python3 -m pytest tests/ -v` 看有没有搞坏已有功能
3. **不确定就问**。"如果我改了 models.py 的字段名，哪些文件会受影响？"
4. **commit 是存档点**。改完一个功能就 commit，随时可以回退
5. **spec 是唯一真相**。代码和 spec 不一致时，先改 spec 再改代码

## 环境搭建（新成员入职）

```bash
# 1. 克隆项目
git clone <repo-url>
cd velo

# 2. 安装依赖
pip3 install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入实际的数据库密码、微信 AppID 等

# 4. 启动数据库（需要 Docker）
docker-compose up -d db redis

# 5. 跑测试验证环境
python3 -m pytest tests/ -v

# 6. 启动开发服务器
uvicorn app.main:app --reload

# 7. 启动异步 Worker
python3 worker.py
```
