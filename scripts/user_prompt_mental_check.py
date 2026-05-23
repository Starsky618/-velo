#!/usr/bin/env python3
"""
UserPromptSubmit hook: 双注入。

1) 总是注入 evidence ledger 提示（每个 prompt 必看）
2) prompt 含派工类 keyword 时 / 注入 agent-collab §10.Y 任务路由表

设计源: docs/agent-rules/agent-collaboration.md §10.Y (2026-05-24 Tim 拍)
单一真相源 / hook 运行时读 §10.Y 整段 / 改文档自动同步 / 无需改本脚本
"""

import json
import re
import sys
from pathlib import Path

EVIDENCE = """<evidence-ledger-before-response>
回答前先确认：
1. 涉及现有文件 / 字段 / API / 路径 / 状态值：先 Read 或 rg，结论带 file:line。
2. 没查到就写“未验证”，不要用记忆、注释或 commit message 补猜。
3. schema / 生产数据 / 部署 / commit 等高风险动作：先查 CLAUDE.md 启动卡和 agent-collaboration 对应门禁。
</evidence-ledger-before-response>
"""

# 命中任一即注入路由表 / 设计原则: sharp 不宽（"让/做"等通用动词不算）
ROUTE_KEYWORDS = [
    "派 codex", "派codex", "派 subagent", "派subagent",
    "实施", "动手", "开干", "开始干", "写代码",
    "review", "审核", "异源", "三审",
    "commit", "提交代码",
]

AGENT_COLLAB_DOC = (
    Path(__file__).resolve().parent.parent
    / "docs/agent-rules/agent-collaboration.md"
)


def get_user_prompt() -> str:
    """从 hook stdin 提取 prompt 文本 / 多种格式兜底。

    Claude Code UserPromptSubmit hook 传 JSON 到 stdin / 含 prompt 字段。
    其他形态 fallback 到原始文本 / 解析失败返空串（不阻断 evidence 注入）。
    """
    try:
        raw = sys.stdin.read()
    except Exception:
        return ""
    if not raw:
        return ""
    try:
        return json.loads(raw).get("prompt", "") or ""
    except (json.JSONDecodeError, AttributeError, TypeError):
        return raw


def extract_route_table() -> str:
    """从 agent-collab.md 提取 §10.Y 整段 / 单一真相源避免漂移。"""
    try:
        text = AGENT_COLLAB_DOC.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r"### §10\.Y[^\n]*\n(.*?)(?=\n### |\n## )", text, re.DOTALL)
    if not match:
        return ""
    body = match.group(0).strip()
    return (
        "<task-routing-reminder>\n"
        "接到派工类 prompt / 注入 agent-collab §10.Y 路由表:\n\n"
        f"{body}\n"
        "</task-routing-reminder>\n"
    )


def should_inject_route(prompt: str) -> bool:
    if not prompt:
        return False
    lower = prompt.lower()
    return any(kw.lower() in lower for kw in ROUTE_KEYWORDS)


def main() -> int:
    sys.stdout.write(EVIDENCE)
    prompt = get_user_prompt()
    if should_inject_route(prompt):
        table = extract_route_table()
        if table:
            sys.stdout.write(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
