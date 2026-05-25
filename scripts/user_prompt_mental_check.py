#!/usr/bin/env python3
"""
UserPromptSubmit hook · 双端对称 + 4 通道动态注入（D 方案 / 2026-05-24 Tim 拍）

evidence-ledger 始终注入。

按 prompt 内容触发的 4 通道（按优先级 1 > 4 > 2 > 3）：
  1. 派工 keyword → agent-collab §10.Y 整段
  4. SOP keyword → CLAUDE.md / agent-collab.md 对应章节
  2. app/* 模块名 → 该模块 __init__.py docstring
  3. sprint/PRD 名 → docs/prd/ + docs/superpowers/specs/ 顶部摘要

设计源：docs/agent-rules/agent-collaboration.md §10.Y (v3 / 2026-05-24)
单一真相源 / 运行时按需扫文档 / 改文档自动同步 / 无需改本脚本
失败兜底：任一通道异常不影响其他 / evidence 始终注入
"""

import json
import re
import sys
from pathlib import Path
from typing import Optional

VELO_ROOT = Path(__file__).resolve().parent.parent
AGENT_COLLAB = VELO_ROOT / "docs/agent-rules/agent-collaboration.md"
CLAUDE_MD = VELO_ROOT / "CLAUDE.md"
DEPLOY_SOP = VELO_ROOT / "docs/agent-rules/deploy-sop.md"

EVIDENCE = """<evidence-ledger-before-response>
回答前先确认：
1. 涉及现有文件 / 字段 / API / 路径 / 状态值：先 Read 或 rg，结论带 file:line。
2. 没查到就写"未验证"，不要用记忆、注释或 commit message 补猜。
3. schema / 生产数据 / 部署 / commit 等高风险动作：先查 CLAUDE.md 启动卡和 agent-collaboration 对应门禁。
</evidence-ledger-before-response>
"""

MAX_TOTAL_LINES = 200  # 单次 hook 总注入上限（防 context 爆炸）

# ============================================================
# 通道 1 · 派工 keyword → agent-collab §10.Y 路由表
# ============================================================

ROUTE_KEYWORDS = [
    "派 codex", "派codex", "派 subagent", "派subagent",
    "实施", "动手", "开干", "开始干", "写代码",
    "review", "审核", "异源", "三审",
    "commit", "提交代码",
]


def channel_1_routing(prompt: str) -> Optional[str]:
    """命中派工 keyword → 注入 §10.Y 整段（v2 含角色画像 / 决策三轴 / 5 字段速查）。"""
    if not any(kw.lower() in prompt.lower() for kw in ROUTE_KEYWORDS):
        return None
    try:
        text = AGENT_COLLAB.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"### §10\.Y[^\n]*\n(.*?)(?=\n### |\n## )", text, re.DOTALL)
    if not m:
        return None
    return (
        "<task-routing-reminder>\n"
        "接到派工类 prompt / 注入 agent-collab §10.Y 路由表:\n\n"
        f"{m.group(0).strip()}\n"
        "</task-routing-reminder>\n"
    )


# ============================================================
# 通道 4 · SOP keyword → CLAUDE.md / agent-collab.md 对应章节
# ============================================================

SOP_MAP = [
    # (keyword, file, section_marker, max_lines)
    ("部署", DEPLOY_SOP, "# velo 部署 SOP", 18),
    ("调试", CLAUDE_MD, "## 🔍 调试 / 排查硬规则", 30),
    ("排查", CLAUDE_MD, "## 🔍 调试 / 排查硬规则", 30),
    ("commit 前", CLAUDE_MD, "## 🔴 commit 前 4 问", 20),
    ("commit前", CLAUDE_MD, "## 🔴 commit 前 4 问", 20),
]


def extract_section(path: Path, marker: str, max_lines: int = 30) -> str:
    """从 marker 行开始 / 截到下个 ## 同级标题 / 上限 max_lines。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    out = []
    capturing = False
    for ln in lines:
        if ln.startswith(marker):
            capturing = True
            out.append(ln)
            continue
        if capturing:
            if ln.startswith("## ") and not ln.startswith("### "):
                break
            out.append(ln)
            if len(out) >= max_lines:
                break
    return "\n".join(out).strip()


def channel_4_sop(prompt: str) -> Optional[str]:
    """prompt 含 SOP keyword → 注入对应章节。"""
    hits = []
    seen = set()
    for kw, file_path, marker, max_lines in SOP_MAP:
        if kw.lower() not in prompt.lower():
            continue
        key = f"{file_path}::{marker}"
        if key in seen:
            continue
        seen.add(key)
        section = extract_section(file_path, marker, max_lines)
        if section:
            hits.append(section)
    if not hits:
        return None
    body = "\n\n---\n\n".join(hits[:2])
    return f"<sop-context-reminder>\n{body}\n</sop-context-reminder>\n"


# ============================================================
# 通道 2 · 模块名 → app/*/__init__.py docstring
# ============================================================

def channel_2_modules(prompt: str) -> Optional[str]:
    """prompt 含 app/* 模块名 → 注入该模块 __init__.py docstring。"""
    app_dir = VELO_ROOT / "app"
    if not app_dir.is_dir():
        return None
    hits = []
    for mod_dir in sorted(app_dir.iterdir()):
        if not mod_dir.is_dir() or mod_dir.name.startswith("__"):
            continue
        name = mod_dir.name
        # 边界匹配：前后非字母数字下划线 / 防 "user" 误命中 "users"
        pattern = rf'(?<![a-zA-Z0-9_]){re.escape(name)}(?![a-zA-Z0-9_])'
        if not re.search(pattern, prompt, re.IGNORECASE):
            continue
        init_file = mod_dir / "__init__.py"
        if not init_file.exists():
            continue
        try:
            content = init_file.read_text(encoding="utf-8")
        except OSError:
            continue
        m = re.search(r'^"""(.*?)"""', content, re.DOTALL)
        if not m:
            continue
        summary = m.group(1).strip()
        if summary:
            hits.append(f"### app/{name}/\n{summary}")
    if not hits:
        return None
    hits = hits[:3]  # 最多 3 个模块
    body = "\n\n".join(hits)
    return f"<module-context-reminder>\n{body}\n</module-context-reminder>\n"


# ============================================================
# 通道 3 · sprint/PRD 名 → docs/prd/ + docs/superpowers/specs/ 顶部摘要
# ============================================================

PRD_DIRS = ["docs/prd", "docs/superpowers/specs"]

# 文件 stem → 额外别名（关键词触发）
PRD_ALIASES = {
    "sprint-9-prd": ["FTP", "sprint 9", "sprint9"],
    "sprint-6-prd": ["sprint 6", "sprint6"],
    "phase-4-prd": ["v4", "phase 4", "phase4"],
    "phase-5-prd": ["v5", "phase 5", "phase5"],
    "persona-engine-sprint-prd": ["persona", "NPC"],
    "velo-vision": ["vision", "愿景"],
    "velo-strategy": ["strategy", "战略"],
    "velo-product-spec": ["product spec"],
    "2026-05-20-coach-engine-design": ["coach engine", "教练总结", "教练"],
    "2026-05-20-training-analytics-roadmap": [
        "PMC", "训练负荷", "训练分析", "CTL", "ATL", "TSB",
        "training analytics", "roadmap",
    ],
}


def build_prd_keywords(stem: str) -> list:
    """从文件 stem 构造匹配关键词集合。"""
    keywords = set()
    parts = stem.lower().split("-")
    # 去掉 yyyy-mm-dd 前缀（spec 文件）
    if len(parts) >= 3 and parts[0].isdigit() and len(parts[0]) == 4:
        parts = parts[3:]
    # 去掉尾部 prd
    if parts and parts[-1] == "prd":
        parts = parts[:-1]
    if parts:
        keywords.add("-".join(parts))
        keywords.add(" ".join(parts))
        keywords.add("".join(parts))
    # 加别名
    keywords.update(PRD_ALIASES.get(stem.lower(), []))
    return [k for k in keywords if k]


def extract_top_summary(path: Path, max_lines: int = 30) -> str:
    """读文档顶部到第一个 ## 之间内容。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    out = []
    for ln in lines:
        if ln.startswith("## "):
            break
        out.append(ln)
        if len(out) >= max_lines:
            break
    return "\n".join(out).strip()


def channel_3_prds(prompt: str) -> Optional[str]:
    """prompt 含 sprint/PRD 关键词 → 注入对应文档顶部摘要。"""
    hits = []
    prompt_lower = prompt.lower()
    for prd_dir_rel in PRD_DIRS:
        prd_dir = VELO_ROOT / prd_dir_rel
        if not prd_dir.is_dir():
            continue
        for f in sorted(prd_dir.glob("*.md")):
            if f.name == "README.md":
                continue
            kws = build_prd_keywords(f.stem)
            if not any(kw.lower() in prompt_lower for kw in kws):
                continue
            summary = extract_top_summary(f, max_lines=20)
            if summary:
                hits.append(f"### {prd_dir_rel}/{f.name}\n{summary}")
    if not hits:
        return None
    hits = hits[:2]  # 最多 2 个 PRD
    body = "\n\n".join(hits)
    return f"<prd-context-reminder>\n{body}\n</prd-context-reminder>\n"


# ============================================================
# 主入口
# ============================================================

def get_user_prompt() -> str:
    """从 hook stdin 提取 prompt 文本 / 多种格式兜底。"""
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


def main() -> int:
    sys.stdout.write(EVIDENCE)
    prompt = get_user_prompt()
    if not prompt:
        return 0

    # 优先级顺序：路由 > SOP > 模块 > PRD
    channels = [
        ("routing", channel_1_routing),
        ("sop", channel_4_sop),
        ("modules", channel_2_modules),
        ("prds", channel_3_prds),
    ]

    total_lines = 0
    for _name, fn in channels:
        try:
            chunk = fn(prompt)
        except Exception:
            continue
        if not chunk:
            continue
        chunk_lines = chunk.count("\n")
        if total_lines + chunk_lines > MAX_TOTAL_LINES:
            continue
        sys.stdout.write(chunk)
        total_lines += chunk_lines

    return 0


if __name__ == "__main__":
    sys.exit(main())
