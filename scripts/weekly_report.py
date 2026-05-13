#!/usr/bin/env python3
"""
velo 周报生成器——给 agent 自己看的协作复盘。

干啥用：
    每周一首次开会话时自动跑（由 session_start.py 触发）。
    扫上周对话历史 jsonl，找 Tim 否定我的瞬间（"看不懂"/"我说了"/"别"/"等等"等），
    生成 markdown 报告写到 docs/agent-weekly/YYYY-WNN.md。

    报告核心目的：让本周 agent 看到上周 agent 犯的错 → 强制做归因分析 →
    必要时沉淀新规则到 memory。这才是真"agentic engineering 进化"。

类比：
    家里每周一上"复盘会"——agent 翻自己上周笔记，看 Tim 哪几次发火 / 啥原因 / 哪些是
    重复犯老错 / 哪些是没沉淀的新坑。看完必须沉淀新经验 / 不能光说"知道了"。

数据来源：
    - ~/.claude/projects/-Users-macbookair-Desktop-velo/*.jsonl（对话 transcript）
    - 项目辅助数据：git log / 代码红黄灯 / debt / memory（次段 / 缩短）

报告结构：
    1. 上周 Tim 否定信号统计（关键词 + 次数 + 样本）→ 主段
    2. agent 必看必做 checklist（强制行为指令）
    3. 项目数据辅助（commit / 红灯 / debt 简化）
    4. 跟上周对比

注意事项：
    - jsonl 解析所有异常吞掉（schema 变化不挂报告）
    - 关键词宽泛抓（agent 看完自己判断哪些是真否定 / 哪些是中性）
    - 报告写文件 + stdout 摘要

用法：
    单跑: python3 scripts/weekly_report.py
    自动: 由 scripts/session_start.py 在本周 W-id.md 未生成时触发
"""

import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEEKLY_DIR = ROOT / "docs" / "agent-weekly"
APP_DIR = ROOT / "app"
TECH_DEBT = ROOT / "docs" / "tech-debt.md"
MEM_DIR = Path.home() / ".claude" / "projects" / "-Users-macbookair-Desktop-velo" / "memory"
TRANSCRIPT_DIR = Path.home() / ".claude" / "projects" / "-Users-macbookair-Desktop-velo"

# Tim 否定 / 不满 / 修正信号关键词（宽泛抓 / agent 看完判断真假）
NEGATIVE_KEYWORDS = {
    "看不懂": "沟通格式失败（§2.3 堆术语 / 没说人话）",
    "我说了": "重复信号未接住（§2.1 重复信号 ≥ 2 次）",
    "我已经说过": "重复信号未接住",
    "我不要": "拍板后还驳回（§2.1 重复信号护栏）",
    "别": "不听指令（§2.1 行动优先反例）",
    "停": "agent 越界 / 钻牛角尖",
    "等等": "agent 跑偏 / 需 Tim 拉回",
    "我他妈": "情绪爆发（沟通严重失败）",
    "为啥": "Tim 困惑 / 解释不清",
    "重新": "agent 输出被否 / 要重做",
    "又": "重复犯老错",
    "看不到": "缺事实核对（§3.1 凭印象说）",
}


def _safe_run(cmd: list[str], cwd: Path = ROOT) -> str:
    """跑命令 / 异常返回空串 / hook 内 robust。"""
    try:
        return subprocess.check_output(cmd, text=True, cwd=cwd, stderr=subprocess.DEVNULL)
    except Exception:
        return ""


def iso_week_id(d: datetime.datetime | None = None) -> str:
    d = d or datetime.datetime.now()
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


# ============ 主段：扫上周对话历史找否定信号 ============

def _extract_user_text(record: dict) -> str:
    """从 jsonl record 提取 user 消息文本。schema 变化 robust。"""
    msg = record.get("message", {})
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                texts.append(c.get("text", ""))
        return "\n".join(texts)
    return ""


def scan_negative_signals(days: int = 7) -> list[dict]:
    """
    扫近 N 天的 jsonl / 找 user 消息含否定关键词 / 返回 [{keyword, text, file, ts}]。

    过滤规则：
    - 只看 type=user 且 message.role=user 的真用户消息（不算 tool_result）
    - 跳过系统注入（slash command stdout / system-reminder 文字）—— 这些是 user 角色但不是 Tim 真话
    """
    if not TRANSCRIPT_DIR.exists():
        return []
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    signals = []
    for jsonl in TRANSCRIPT_DIR.glob("*.jsonl"):
        # mtime 过滤（性能优化 / 老文件跳过）
        if datetime.datetime.fromtimestamp(jsonl.stat().st_mtime) < cutoff:
            continue
        try:
            with jsonl.open(encoding="utf-8", errors="ignore") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if rec.get("type") != "user":
                        continue
                    text = _extract_user_text(rec)
                    if not text or len(text) > 500:
                        # 太长大概率是注入的 tool result / system reminder / 跳过
                        continue
                    # 跳过系统注入
                    if any(skip in text for skip in (
                        "<system-reminder>",
                        "<local-command",
                        "tool_use_error",
                        "Caveat: The messages",
                        "Result of calling",
                    )):
                        continue
                    for kw, label in NEGATIVE_KEYWORDS.items():
                        if kw in text:
                            signals.append({
                                "keyword": kw,
                                "label": label,
                                "text": text.strip()[:200],
                                "file": jsonl.name,
                                "ts": rec.get("timestamp", ""),
                            })
                            break  # 一条消息只算一次（避免"看不懂 + 我说了"双计）
        except Exception:
            continue
    return signals


def render_negative_section(signals: list[dict]) -> list[str]:
    """否定信号主段渲染。"""
    lines = ["## 🚨 上周 Tim 否定我的瞬间", ""]
    if not signals:
        lines.append("- ✅ 0 次否定 / 协作顺滑")
        return lines

    # 按 keyword 聚合
    by_kw: dict[str, list[dict]] = {}
    for s in signals:
        by_kw.setdefault(s["keyword"], []).append(s)

    lines.append("| 关键词 | 次数 | 对应规则违反 | 最强 1 个样本 |")
    lines.append("|---|---|---|---|")
    for kw in sorted(by_kw.keys(), key=lambda k: -len(by_kw[k])):
        items = by_kw[kw]
        # 选最长样本作代表（信息密度最高）
        rep = max(items, key=lambda i: len(i["text"]))
        sample = rep["text"][:80].replace("\n", " ").replace("|", "丨")
        lines.append(f'| "{kw}" | {len(items)} | {rep["label"]} | "{sample}..." |')

    lines.append("")
    lines.append(f"**总否定信号：{len(signals)} 次**（涉及 {len(by_kw)} 类关键词）")
    return lines


def render_agent_checklist(signals: list[dict]) -> list[str]:
    """强制 agent 行为指令——这才是周报真正的价值。"""
    lines = [
        "",
        "## 🤖 agent 必看 + 必做（看完报告本会话起手强制跑）",
        "",
        "> 这份报告不是给 Tim 看的项目数据 / 是给你（本周 agent）看的协作错误教训。",
        "> 上周那个 agent 犯的错你不能重犯——必须做完下面 3 步才算【看完报告】。",
        "",
        "### Step 1：归因分析（必跑）",
        "",
        "- 把上面【否定信号表】每行拿来 grep memory 目录看是否已有对应规则",
        "  - 命令：`grep -l \"<关键词上下文>\" ~/.claude/projects/-Users-macbookair-Desktop-velo/memory/*.md`",
        "- 已有规则 → 标记【重复违反】 / 警惕本周别再犯",
        "- 没有规则 → 候选【新沉淀模式】 / 进 Step 2",
        "",
        "### Step 2：沉淀候选（agent 自填）",
        "",
        "- 列出本周可能要沉淀的新错误模式（≥ 1 条 或 写【无】）",
        "- 每条含：错误模式描述 / 触发场景 / 推荐沉淀去向（memory / CLAUDE.md / vault concept）",
        "- 提议给 Tim 等他拍 / 不要擅自写 memory",
        "",
        "### Step 3：高频违反规则提醒（开 session 时主动 grep）",
        "",
        "- 本周高频违反的 TOP3 规则 → 起手时主动 grep 对应 memory 复习",
        "- 例：上周违反 §2.3 沟通格式 5 次 → 本会话起手 grep `memory/feedback_no_priority*`",
        "",
        f"**Agent 你看完了吗？请在回复 Tim 时显式说【我看到了 {len(signals)} 个否定信号 + 我的归因分析如下...】。**",
        "",
    ]
    return lines


# ============ 次段：项目数据辅助（缩短版） ============

def collect_health_stats() -> dict:
    if not APP_DIR.exists():
        return {"total_lines": 0, "red_count": 0, "yellow_count": 0}
    red, yellow, total = 0, 0, 0
    for f in APP_DIR.rglob("*.py"):
        try:
            n = sum(1 for _ in f.open(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        total += n
        if n > 600:
            red += 1
        elif n > 300:
            yellow += 1
    return {"total_lines": total, "red_count": red, "yellow_count": yellow}


def collect_git_summary(days: int = 7) -> dict:
    since = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    log = _safe_run(["git", "log", f"--since={since}", "--pretty=format:%s"])
    msgs = [m for m in log.split("\n") if m.strip()]
    cats = {"feat": 0, "fix": 0, "docs": 0, "refactor": 0, "chore": 0, "test": 0}
    for m in msgs:
        for k in cats:
            if re.match(rf"^{k}(\(|:)", m):
                cats[k] += 1
                break
    real_hotfix = sum(
        1 for m in msgs
        if re.match(r"^(fix|revert)(\(|:)", m.lower())
        and any(kw in m.lower() for kw in ("hotfix", "revert", "紧急", "回滚"))
    )
    return {"count": len(msgs), "categories": cats, "real_hotfix": real_hotfix}


def collect_debt_stats() -> dict:
    if not TECH_DEBT.exists():
        return {"lines": 0, "entries": 0}
    content = TECH_DEBT.read_text(encoding="utf-8")
    return {
        "lines": content.count("\n"),
        "entries": len(re.findall(r"^##\s", content, re.MULTILINE)),
    }


def collect_memory_stats(days: int = 7) -> dict:
    if not MEM_DIR.exists():
        return {"total": 0, "new_this_week": 0}
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    new_count, total = 0, 0
    for f in MEM_DIR.glob("*.md"):
        if f.name == "MEMORY.md":
            continue
        total += 1
        if datetime.datetime.fromtimestamp(f.stat().st_mtime) >= cutoff:
            new_count += 1
    return {"total": total, "new_this_week": new_count}


# ============ 上周对比 ============

def find_last_report() -> dict | None:
    """找上一份周报 / 提取关键数字。"""
    if not WEEKLY_DIR.exists():
        return None
    reports = sorted(p for p in WEEKLY_DIR.glob("*.md") if re.match(r"\d{4}-W\d{2}\.md", p.name))
    if not reports:
        return None
    last = reports[-1]
    if last.name == f"{iso_week_id()}.md":
        # 本周报告（避免拿自己对比自己）
        if len(reports) < 2:
            return None
        last = reports[-2]
    content = last.read_text(encoding="utf-8")
    extract = {}
    # 抠总否定信号数
    m = re.search(r"总否定信号：(\d+) 次", content)
    if m:
        extract["negative_total"] = int(m.group(1))
    m = re.search(r"\|\s*红灯文件[^\|]*\|\s*\d+\s*\|\s*(\d+)", content)
    if m:
        extract["red_count"] = int(m.group(1))
    m = re.search(r"\|\s*tech-debt 条目[^\|]*\|\s*\d+\s*\|\s*(\d+)", content)
    if m:
        extract["debt_entries"] = int(m.group(1))
    return {"path": last.name, "data": extract}


def _delta(cur: float, prev: float | None, less_is_better: bool = False) -> str:
    if prev is None:
        return "—"
    if cur == prev:
        return "→"
    if less_is_better:
        return "⬆ 改善" if cur < prev else "⬇ 恶化"
    return "⬆" if cur > prev else "⬇"


# ============ 报告组装 ============

def render_report(week_id, signals, git, health, debt, mem, last) -> str:
    last_data = last["data"] if last else {}
    lines = [
        f"# velo 周报 / agent 协作复盘 / {week_id}",
        "",
        f"> 生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 上份报告：{last['path'] if last else '（首次跑 / 无对比）'}",
        "> **这份报告给 agent 自己看 / 不是给 Tim 看的项目仪表盘。**",
        "",
    ]

    # 主段：否定信号
    lines += render_negative_section(signals)

    # 强制 agent 行为
    lines += render_agent_checklist(signals)

    # 跟上周对比（含否定数 + 红灯 + debt）
    lines += [
        "## 📊 跟上周对比",
        "",
        "| 指标 | 上周 | 本周 | 变化 | 解读 |",
        "|---|---|---|---|---|",
        f"| 总否定信号 | {last_data.get('negative_total', '—')} | {len(signals)} | "
        f"{_delta(len(signals), last_data.get('negative_total'), less_is_better=True)} | "
        f"{'agent 协作变顺' if last_data.get('negative_total') and len(signals) < last_data['negative_total'] else '基线 / 待跟踪'} |",
        f"| 红灯文件 | {last_data.get('red_count', '—')} | {health['red_count']} | "
        f"{_delta(health['red_count'], last_data.get('red_count'), less_is_better=True)} | 代码健康 |",
        f"| tech-debt 条目 | {last_data.get('debt_entries', '—')} | {debt['entries']} | "
        f"{_delta(debt['entries'], last_data.get('debt_entries'), less_is_better=True)} | 债务清理 |",
        "",
    ]

    # 次段：项目数据（缩短）
    lines += [
        "## 📁 项目数据（辅助 / 给 Tim 看）",
        "",
        f"- commit：{git['count']} 次（feat {git['categories']['feat']} / fix {git['categories']['fix']} / docs {git['categories']['docs']} / refactor {git['categories']['refactor']} / chore {git['categories']['chore']} / test {git['categories']['test']}）",
        f"- 真翻车（hotfix/revert）：{git['real_hotfix']} 次",
        f"- 代码健康：{health['total_lines']} 行 / 🔴 {health['red_count']} 红 / 🟡 {health['yellow_count']} 黄",
        f"- tech-debt：{debt['entries']} 条 / {debt['lines']} 行",
        f"- memory：本周新增 {mem['new_this_week']} / 总 {mem['total']}",
        "",
        "---",
        "",
        "**算法说明**：否定信号扫描宽泛抓关键词（看不懂 / 我说了 / 别 / 停 / 等等 / 我他妈 等）/ ",
        "会有误报（如【等等】可能是补充不是否定）/ agent 自己判断 / 关键词清单见 weekly_report.py NEGATIVE_KEYWORDS。",
    ]
    return "\n".join(lines)


def main() -> int:
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    week_id = iso_week_id()

    signals = scan_negative_signals(7)
    git = collect_git_summary(7)
    health = collect_health_stats()
    debt = collect_debt_stats()
    mem = collect_memory_stats(7)
    last = find_last_report()

    report = render_report(week_id, signals, git, health, debt, mem, last)
    out = WEEKLY_DIR / f"{week_id}.md"
    out.write_text(report, encoding="utf-8")

    # stdout 摘要（hook 起手时塞 agent 上下文）
    print("=== agent 协作复盘 / 上周 Tim 否定信号扫描完毕 ===")
    print(f"📄 {out.relative_to(ROOT)}")
    print(f"🚨 上周否定信号：{len(signals)} 次")
    if signals:
        from collections import Counter
        kw_counts = Counter(s["keyword"] for s in signals)
        top = kw_counts.most_common(3)
        print(f"   TOP3：{' / '.join(f'{k}×{n}' for k, n in top)}")
    print()
    print("⚠️ agent 你必须看 docs/agent-weekly/{}.md 做归因分析（Step 1-3）/ 报告 Tim".format(week_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
