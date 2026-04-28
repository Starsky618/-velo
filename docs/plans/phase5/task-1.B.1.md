# 任务 1.B.1：agent 模块新建（segment_writer + tasks.py）

## 🎯 目标

新建 `app/agent/` 模块，含三个文件：
- `__init__.py` 标识包
- `segment_writer.py` 同步调 Anthropic API 生成赛段介绍草稿（按 ADR-009 留接口架构，v5 不实现 RAG）
- `tasks.py` RQ 异步任务入口（admin 触发后由 worker 跑）

## ⛓ 前置依赖

- task-0.8（`app/queue.py` 单一连接源 + `ai_drafts_queue` 已 expose）
- task-0.6（segment_ai_drafts 表已建）

## 📤 输出契约

| 函数 | 用途 | 调用方 |
|---|---|---|
| `app/agent/segment_writer.py` `generate_segment_draft(segment_props) -> str` | 调 Anthropic 返活人感介绍 50-100 字 | tasks.py 内部用 |
| `app/agent/tasks.py` `generate_segment_draft_task(segment_id) -> None` | RQ async task，UPSERT segment_ai_drafts | admin/service.py enqueue（task-3.A.3）+ admin/service.py PATCH curation-pool（task-3.A.2）|

## 🧱 现状

- `app/agent/` 目录**不存在**（v5 全新建）
- `requirements.txt` 无 `anthropic` —— 本 task 同 commit 加
- `app/config.py` 无 `ANTHROPIC_API_KEY` —— 本 task 加 `settings.ANTHROPIC_API_KEY: str = ""`
- 项目其他文件统一用 `httpx` 不用 `requests`（陷阱清单已记）

## 🛠 完整代码

### 1. `app/agent/__init__.py`

```python
"""AI 内容生成模块（v5 留接口，未来 v7+ 扩 RAG）。

边界：
- 调外部 LLM API（Anthropic）
- 写 segment_ai_drafts 表（v5 task-0.6 已建）
- 不反向 import 业务模块（segment / activity / user 的 service）
- 通过参数 dict 输入，不进业务逻辑
"""
```

### 2. `app/agent/segment_writer.py`

抄 `docs/spec-v5.md §3.7.2`（行 1980-2061）—— 含 `PROMPT_TEMPLATE` + `generate_segment_draft(segment_props)`。

**关键修订（spec 已修）**：
- `from app.config import settings`（不是顶层常量 import）
- `_client = Anthropic(api_key=settings.ANTHROPIC_API_KEY) if settings.ANTHROPIC_API_KEY else None`
- response.content 嵌套字段 `.get()` / `getattr` 安全访问（陷阱 #9）
- 失败返空字符串不抛异常（不阻断 RQ）

### 3. `app/agent/tasks.py`

抄 `docs/spec-v5.md §3.7.3`（行 2064-2178）—— 含 `generate_segment_draft_task(segment_id)`。

**关键修订（spec 已修）**：
- `from app.database import SessionLocal`（不是 `app.db`）
- UPSERT by `segment_id UNIQUE` + `IntegrityError` 兜底（幂等）
- 已存在 + status='pending' 才覆盖（不覆盖人工编辑）

### 4. `app/config.py` Settings 类追加

```python
class Settings(BaseSettings):
    # ... 现有字段
    ANTHROPIC_API_KEY: str = ""
    # （task-1.C.1 会加 FEISHU_BOT_WEBHOOK）
```

### 5. `requirements.txt` 加

```
anthropic==0.40.0  # spec 实施时用最新稳定版
```

### 6. `.env.example` 加

```
ANTHROPIC_API_KEY=
```

### 7. `docker-compose.yml` worker 服务 environment 加

```yaml
worker:
  environment:
    ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
    RQ_QUEUES: "velo,ai_drafts"  # task-0.8 已加
```

## ✅ 测试

```python
# tests/test_agent_segment_writer.py
def test_generate_segment_draft_no_api_key_returns_empty(monkeypatch):
    # 不设 ANTHROPIC_API_KEY → return ""
def test_generate_segment_draft_api_failure_returns_empty(mock_anthropic_500):
    # API 5xx → return "" 记 logger 不抛
def test_generate_segment_draft_normal_path(mock_anthropic_success):
    # mock 返 50-100 字草稿，函数返 .strip() 后字符串
def test_generate_segment_draft_nested_field_safe(mock_anthropic_malformed):
    # response.content 缺字段 → 返 ""，不 KeyError
```

```python
# tests/test_agent_tasks.py
def test_generate_segment_draft_task_no_segment_returns(db_session):
    generate_segment_draft_task(99999)  # 不抛
def test_generate_segment_draft_task_creates_draft(db_session, segment_factory, mock_writer):
    seg = segment_factory()
    generate_segment_draft_task(seg.id)
    draft = db_session.query(SegmentAiDraft).filter_by(segment_id=seg.id).first()
    assert draft is not None
    assert draft.status == 'pending'
def test_generate_segment_draft_task_idempotent_pending_overwrite(db_session): ...
def test_generate_segment_draft_task_skip_human_edited(db_session): 
    # 已存在 status='human_edited' → 跳过覆盖
def test_generate_segment_draft_task_concurrent_integrity_error_swallowed(): ...
```

## 📝 commit

```
feat(agent): 任务 1.B.1 agent 模块新建（segment_writer + tasks）

新建：
- app/agent/__init__.py / segment_writer.py / tasks.py
- requirements.txt 加 anthropic
- app/config.py Settings 加 ANTHROPIC_API_KEY 字段
- .env.example / docker-compose.yml 同步加 env 变量
- docker-compose worker 加 ANTHROPIC_API_KEY environment（与 task-0.8 RQ_QUEUES 一起）

设计：v5 留接口不实现 RAG，未来 v7+ 扩展时此模块为入口。
```

## 🔍 自检三问

1. **环境变量 N 处同步**（陷阱 #2）：ANTHROPIC_API_KEY 是否在 `app/config.py` / `.env.example` / `docker-compose.yml` 三处都加？  
   → 是。本 task 同 commit 改三处。生产部署时 `.env` 实际值由 Tim 配。

2. **API 失败处理**：generate 失败为何返空字符串而非抛异常？  
   → RQ task 内部抛异常会触发 RQ 重试（最多 2 次），但 Anthropic 5xx 通常是临时 / 模型限流，重试 2 次仍 5xx 可能性高，浪费配额。返空 + UPSERT 跳过让 admin 后续手动重发更可控。

3. **反向依赖**：agent 模块是否 import 了任何业务模块？  
   → grep `from app\.` /Users/macbookair/Desktop/velo/app/agent/ 应只见 `app.config / app.database / app.segment.models`（读 Segment / 写 SegmentAiDraft）。**不能 import segment.service / user.service**——这是 ADR-009 边界。
