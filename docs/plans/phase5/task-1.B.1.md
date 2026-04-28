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

调 **DeepSeek** API（Tim 2026-04-29 拍：国产 + 国内访问稳 + 价格极低）。DeepSeek 兼容 OpenAI Python SDK 格式，仅需改 `base_url` 即可。

**完整实现**：

```python
# app/agent/segment_writer.py（新建）
"""AI 赛段介绍草稿生成器（5.B.2）。

v5 留接口不实现 RAG / 不上向量检索，仅直连 DeepSeek API。
未来 v7+ 扩展 RAG 时此模块为入口。
模型解耦：`DEEPSEEK_MODEL` env 配置，未来切其他模型只换 base_url + model 名。
"""
import logging
from openai import OpenAI  # DeepSeek 兼容 OpenAI Python SDK
from app.config import settings

logger = logging.getLogger(__name__)
_client = (
    OpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )
    if settings.DEEPSEEK_API_KEY else None
)


PROMPT_TEMPLATE = """你是 velo 平台的本地骑友写手。给一条赛段写**活人感介绍**：

赛段属性：
- 名称：{name}
- 城市：{city}
- 距离：{distance_km} km
- 总爬升：{elevation_gain_m} m
- 最大坡度：{max_gradient_pct}%
- 难度：{difficulty}

调性要求（必须遵守）：
- **单条 50-100 字**，超过算违规
- **元素稀疏**：1-2 个细节（避雷 / 氛围 / 路面 等），不堆砌 4 个梗
- 满足 RUBRIC-CONTENT 4 条至少 3 条：具体细节 / 避雷建议 / 本地黑话 / 主观感受
- 禁用词：超震撼 / 用户体验 / 解锁 / AI 智能开头 / 所有运动爱好者 等

输出：直接给草稿正文，不加引号 / 不解释 / 不署名。
"""


def generate_segment_draft(segment_props: dict) -> str:
    """
    调 DeepSeek API 生成赛段活人感介绍草稿。
    
    参数：
        segment_props: dict 含 name / city / distance_km / elevation_gain_m / max_gradient_pct / difficulty
    返回：
        str 50-100 字活人感草稿；调用失败返回空字符串（不抛异常打断业务流）
    
    陷阱 #9（API 嵌套）：response 字段用 .get() 链 / getattr 显式存在性检查
    """
    if _client is None:
        logger.warning("DEEPSEEK_API_KEY not configured, skip generate")
        return ""
    
    prompt = PROMPT_TEMPLATE.format(**segment_props)
    
    try:
        response = _client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,  # 默认 'deepseek-chat'，env 可覆盖（如切 v4-pro）
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.7,  # 创意性中等，避免太机械
        )
        # 嵌套字段安全访问（陷阱 #9）
        choices = getattr(response, 'choices', None)
        if not choices:
            return ""
        msg = getattr(choices[0], 'message', None)
        if not msg:
            return ""
        text = getattr(msg, 'content', None)
        if not text:
            return ""
        return text.strip()
    except Exception as e:
        logger.error(f"generate_segment_draft failed: {e}")
        return ""
```

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
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_MODEL: str = "deepseek-chat"  # 默认通用对话模型；可 env 覆盖切 'deepseek-reasoner' / 未来 v4-pro 等
    # （task-1.C.1 会加 FEISHU_BOT_WEBHOOK）
```

### 5. `requirements.txt` 加

```
openai>=1.0.0  # DeepSeek 兼容 OpenAI SDK，spec 实施时用最新稳定版
```

> ⚠ 不装 `anthropic` 包。

### 6. `.env.example` 加

```
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-chat
```

> ⚠ 真实 key 只放生产 `.env`（不进 git）。Tim 已于 2026-04-29 提供 key，部署时手工配置。

### 7. `docker-compose.yml` worker 服务 environment 加

```yaml
worker:
  environment:
    DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY}
    DEEPSEEK_MODEL: ${DEEPSEEK_MODEL}
    RQ_QUEUES: "velo,ai_drafts"  # task-0.8 已加
```

## ✅ 测试

```python
# tests/test_agent_segment_writer.py
def test_generate_segment_draft_no_api_key_returns_empty(monkeypatch):
    # 不设 DEEPSEEK_API_KEY → return ""
def test_generate_segment_draft_api_failure_returns_empty(mock_openai_500):
    # API 5xx → return "" 记 logger 不抛
def test_generate_segment_draft_normal_path(mock_openai_success):
    # mock 返 50-100 字草稿，函数返 .strip() 后字符串
def test_generate_segment_draft_nested_field_safe(mock_openai_malformed):
    # response.choices[0].message.content 缺字段 → 返 ""，不 KeyError
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
- requirements.txt 加 openai（DeepSeek 兼容 OpenAI SDK）
- app/config.py Settings 加 DEEPSEEK_API_KEY / DEEPSEEK_MODEL 字段
- .env.example / docker-compose.yml 同步加 env 变量

设计：
- 模型选 DeepSeek（Tim 2026-04-29 拍：国产 + 国内访问稳 + 价格极低）
- DEEPSEEK_MODEL env 配置化解耦，未来切其他模型只换 base_url + model 名
- v5 留接口不实现 RAG，v7+ 扩展时此模块为入口

⚠ API key 不进 git，仅生产 .env 配置
```

## 🔍 自检三问

1. **环境变量 N 处同步**（陷阱 #2）：DEEPSEEK_API_KEY / DEEPSEEK_MODEL 是否在 `app/config.py` / `.env.example` / `docker-compose.yml` 三处都加？  
   → 是。本 task 同 commit 改三处。生产部署时 `.env` 实际值由 Tim 手工 echo 配置。

2. **API 失败处理**：generate 失败为何返空字符串而非抛异常？  
   → RQ task 内部抛异常会触发 RQ 重试（最多 2 次），但 DeepSeek 5xx 通常是限流 / 模型负载，重试 2 次仍 5xx 可能性高浪费配额。返空 + UPSERT 跳过让 admin 后续手动重发更可控。

3. **反向依赖**：agent 模块是否 import 了任何业务模块？  
   → grep `from app\.` /Users/macbookair/Desktop/velo/app/agent/ 应只见 `app.config / app.database / app.segment.models`（读 Segment / 写 SegmentAiDraft）。**不能 import segment.service / user.service**——这是 ADR-009 边界。

4. **模型解耦**：未来切非 DeepSeek 模型（如阿里通义 / 智谱）需改什么？  
   → 切其他厂商需把 `base_url="https://api.deepseek.com"` 也变量化（如 `LLM_BASE_URL` env）。v5 暂不抽（YAGNI）—— DeepSeek 短期不换。
