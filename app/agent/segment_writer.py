"""
AI 赛段介绍草稿生成器（v5 task-1.B.1 / 5.B.2）。

干啥用：
- 接收一条赛段的属性 dict（名/城市/距离/爬升/坡度/难度），调 DeepSeek 返一段 50-100 字
  "活人感"介绍（带避雷/路面/氛围/本地黑话），不堆砌 AI 翻译腔
- v5 留接口不实现 RAG / 不上向量检索，仅直连 DeepSeek API
- 未来 v7+ 扩 RAG 时此模块为入口（加 retrieval 注入 prompt）

操作注意：
- 本模块**只调外部 API + 返字符串**，不读 / 不写数据库（DB 写在 tasks.py）
- API key 缺失（如 dev/CI）时 _client = None / generate 直接返空字符串 + warn，不抛异常
- API 5xx / 嵌套字段缺失 / 网络超时 → 一律返空字符串 + 记 logger.error
  →→ caller (tasks.py) 看到空字符串就 skip UPSERT，让 admin 后台手动重发
  （RQ 重试 2 次浪费 DeepSeek 配额比"先返空再人工重试"代价高）
- 模型解耦：DEEPSEEK_MODEL env 配置化，未来切其他厂商（阿里通义/智谱）
  只换 base_url + 这里读的 settings.DEEPSEEK_MODEL 即可

数据流：
- 入：dict 含 name / city / distance_km / elevation_gain_m / max_gradient_pct / difficulty
- 出：str 50-100 字草稿（成功）/ 空字符串（任何失败路径）
"""

import logging

from openai import OpenAI  # DeepSeek 兼容 OpenAI Python SDK

from app.config import settings


logger = logging.getLogger(__name__)


# 全局单例 client —— OpenAI SDK 内部有连接池，每次调用重建会浪费连接
# 没 key 时 _client = None，generate 函数会跳过整个 LLM 调用直接返空
# 这样 dev / CI 不需配 key，单测只 mock generate 函数本身或 _client.chat.* 即可
_client = (
    OpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )
    if settings.DEEPSEEK_API_KEY else None
)


# Prompt 模板（v5 task-1.B.1 起用）
# 设计原则：
# - 字数硬约束 50-100 字（前端卡片展示空间限制）
# - 元素稀疏：1-2 个细节，避免堆砌 4 个梗变啰嗦
# - RUBRIC-CONTENT 4 条至少 3 条（具体细节/避雷建议/本地黑话/主观感受）—— 防机翻腔
# - 禁用词清单：精准拦截 AI 翻译味（"超震撼/解锁/AI 智能开头/所有运动爱好者"等）
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

    设计思路：
    - 同步调用（caller tasks.py 已经在 RQ worker 异步上下文，本函数同步即可）
    - 任何失败路径返空字符串 + warn / error log，不抛异常打断 caller 业务流
    - 嵌套字段安全访问（陷阱 #9）：response.choices[0].message.content 任一缺失 → 返空

    参数：
        segment_props: 字典含 6 字段
            - name: str 赛段名
            - city: str 城市枚举或 '未知'
            - distance_km: float 距离公里
            - elevation_gain_m: int 累计爬升米
            - max_gradient_pct: float 最大坡度百分比
            - difficulty: str 难度枚举或 '未知'

    返回：
        str 50-100 字活人感草稿（成功路径）；
        空字符串 ""（任一失败路径：无 key / API 失败 / 嵌套字段缺失 / 异常）

    陷阱警示：
    - 不要 raise 异常打断 RQ task —— 失败让 caller 看空字符串决定是否重试
    - 不要 print，用 logger（生产容器看 docker compose logs）
    """
    # 第 1 关：API key 兜底
    # _client 单例在 import 时根据 settings.DEEPSEEK_API_KEY 决定
    # 没配 key（dev/CI）→ 返空字符串 + warn 记一笔，让 caller 知道是配置问题不是 API 错
    if _client is None:
        logger.warning("DEEPSEEK_API_KEY not configured, skip generate")
        return ""

    # 第 2-3 关合并 try：prompt 渲染 + API 调用
    # codex 异源审 2026-04-30 修 Important：原 format() 在 try 外，KeyError 会打爆 RQ task
    # 违反本文件 docstring 契约"任何失败路径返空字符串不抛"。统一纳入 try：
    # - PROMPT_TEMPLATE.format(**segment_props) 缺字段 → KeyError → catch 返空 + error log
    # - OpenAI SDK 网络异常 / 5xx / 限流 / 超时 / 任何 SDK exception → catch 返空
    # 用宽 Exception 防 SDK 升级新增异常类型漏掉，错误信息用 logger.error 留排查痕迹
    try:
        prompt = PROMPT_TEMPLATE.format(**segment_props)
        response = _client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,    # 50-100 字的中文约 100-200 token，300 上限留余量
            temperature=0.7,   # 创意性中等：避免太机械（0.0）也避免太随机（1.0+）
        )
    except Exception as exc:
        logger.error(f"generate_segment_draft failed (prompt or API): {exc}")
        return ""

    # 第 4 关：嵌套字段安全访问（陷阱 #9）
    # OpenAI SDK 返回结构正常是 response.choices[0].message.content
    # 但 SDK 升级 / 模型异常返空 / 任何字段缺失都可能炸 IndexError / AttributeError
    # 用 getattr 链 + 显式 None 检查兜底，任何缺失 → 返空 + warn
    choices = getattr(response, "choices", None)
    if not choices:
        logger.warning("DeepSeek response 无 choices 字段")
        return ""
    message = getattr(choices[0], "message", None)
    if message is None:
        logger.warning("DeepSeek response.choices[0] 无 message 字段")
        return ""
    content = getattr(message, "content", None)
    if not content:
        logger.warning("DeepSeek response.choices[0].message.content 为空")
        return ""

    # 第 5 关：清理首尾空白
    # LLM 偶尔返回带前后换行 / 空格的字符串，统一 strip 后再返
    return content.strip()
