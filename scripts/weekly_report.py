#!/usr/bin/env python3
"""
velo 周报生成器——让 Tim 感受到 agentic engineering 进化。

干啥用：
    每周一首次开会话时自动跑（由 session_start.py 触发）。
    扫一遍项目当下状态（代码量 / 红灯 / debt / memory），跟上周报告对比，
    生成 markdown 报告写到 docs/agent-weekly/YYYY-WNN.md，并算一个进化指数。

类比：
    家里每周一早晨自动盘点——上周乱在哪 / 这周清了哪些 / 跟上周比好了还是糟了。
    一个进化指数 = "这家整体活得比上周好"的单一数字。

数据来源：
    - git log（commit 数 / 改动行数 / 按 feat/fix/refactor 分类）
    - app/**/*.py（红灯黄灯文件 / 总代码量）
    - memory 目录（本周新增 / 总数）
    - docs/tech-debt.md（行数 / 条目数）
    - 上次周报（对比基准）

报告结构：
    - 本周做了啥（commit 分类 + 总行数变化）
    - 跟上周比（数字对比表 + 红绿箭头）
    - 本周新学（新 memory 列表）
    - 翻车统计（fix commit 数）
    - 进化指数（0-10 / 综合红灯/debt/翻车）
    - 下周提醒（debt top 3）

注意事项：
    - cold start（第一次跑没有上周报告）→ 输出 baseline / 不算对比
    - 所有外部命令 try/except / 失败用 N/A 占位 / 不挂 hook
    - ISO 周编号（YYYY-WNN）= 周一起算

用法：
    单跑: python3 scripts/weekly_report.py
    自动: 由 scripts/session_start.py 在距上次报告 ≥ 7 天时触发
"""

import datetime
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEEKLY_DIR = ROOT / "docs" / "agent-weekly"
APP_DIR = ROOT / "app"
TECH_DEBT = ROOT / "docs" / "tech-debt.md"
MEM_DIR = Path.home() / ".claude" / "projects" / "-Users-macbookair-Desktop-velo" / "memory"


def _safe_run(cmd: list[str], cwd: Path = ROOT) -> str:
    """跑命令，挂了返回空串，不抛异常。hook 内 robust。"""
    try:
        return subprocess.check_output(cmd, text=True, cwd=cwd, stderr=subprocess.DEVNULL)
    except Exception:
        return ""


def collect_git_stats(days: int = 7) -> dict:
    """近 N 天 git log：commit 数 + 改动行数 + 按 conventional commit 前缀分类。"""
    since = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    log = _safe_run(["git", "log", f"--since={since}", "--pretty=format:COMMIT::%s", "--shortstat"])
    if not log:
        return {"commit_count": 0, "insertions": 0, "deletions": 0, "categories": {}}

    commits = []
    current_msg = None
    for line in log.split("\n"):
        if line.startswith("COMMIT::"):
            current_msg = line[len("COMMIT::"):].strip()
            commits.append({"msg": current_msg, "ins": 0, "del": 0})
        elif "insertion" in line or "deletion" in line:
            if not commits:
                continue
            ins_m = re.search(r"(\d+) insertion", line)
            del_m = re.search(r"(\d+) deletion", line)
            if ins_m:
                commits[-1]["ins"] = int(ins_m.group(1))
            if del_m:
                commits[-1]["del"] = int(del_m.group(1))

    categories = {"feat": 0, "fix": 0, "docs": 0, "refactor": 0, "chore": 0, "test": 0, "other": 0}
    for c in commits:
        msg = c["msg"]
        matched = False
        for k in list(categories.keys())[:-1]:
            if re.match(rf"^{k}(\(|:)", msg):
                categories[k] += 1
                matched = True
                break
        if not matched:
            categories["other"] += 1

    return {
        "commit_count": len(commits),
        "insertions": sum(c["ins"] for c in commits),
        "deletions": sum(c["del"] for c in commits),
        "categories": categories,
        "commits": commits,
    }


def collect_health_stats() -> dict:
    """红黄灯文件 + 后端总代码量。"""
    if not APP_DIR.exists():
        return {"total_lines": 0, "red_count": 0, "yellow_count": 0, "red_files": []}
    red, yellow, total = [], [], 0
    for f in APP_DIR.rglob("*.py"):
        try:
            lines = sum(1 for _ in f.open(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        total += lines
        rel = str(f.relative_to(ROOT))
        if lines > 600:
            red.append((rel, lines))
        elif lines > 300:
            yellow.append((rel, lines))
    return {
        "total_lines": total,
        "red_count": len(red),
        "yellow_count": len(yellow),
        "red_files": red,
        "yellow_files": yellow,
    }


def collect_memory_stats(days: int = 7) -> dict:
    """本周新增 / 总数。MEMORY.md 索引不算条目。"""
    if not MEM_DIR.exists():
        return {"total": 0, "new_this_week": []}
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    new_files = []
    total = 0
    for f in MEM_DIR.glob("*.md"):
        if f.name == "MEMORY.md":
            continue
        total += 1
        if datetime.datetime.fromtimestamp(f.stat().st_mtime) >= cutoff:
            new_files.append(f.name)
    return {"total": total, "new_this_week": sorted(new_files)}


def collect_debt_stats() -> dict:
    """tech-debt.md 当前行数 + 条目数（## 标题数）。"""
    if not TECH_DEBT.exists():
        return {"lines": 0, "entries": 0}
    content = TECH_DEBT.read_text(encoding="utf-8")
    return {
        "lines": content.count("\n"),
        "entries": len(re.findall(r"^##\s", content, re.MULTILINE)),
    }


def find_last_report() -> dict | None:
    """找上一份周报（按文件名排序最后一个）/ 提取关键数字用于对比。"""
    if not WEEKLY_DIR.exists():
        return None
    reports = sorted(p for p in WEEKLY_DIR.glob("*.md") if re.match(r"\d{4}-W\d{2}\.md", p.name))
    if not reports:
        return None
    last = reports[-1]
    content = last.read_text(encoding="utf-8")
    # 从表格里抠数字（格式：| 红灯文件 | 3 | 0 | ⬇ |）
    extract = {}
    for label, key in [
        ("红灯文件", "red_count"),
        ("黄灯文件", "yellow_count"),
        ("tech-debt 条目", "debt_entries"),
        ("memory 总数", "memory_total"),
        ("后端代码量", "total_lines"),
        ("进化指数", "evolution_index"),
    ]:
        m = re.search(rf"\|\s*{re.escape(label)}\s*\|\s*[\d.]+\s*\|\s*([\d.]+)", content)
        if m:
            extract[key] = float(m.group(1))
    return {"path": last.name, "data": extract}


def _count_real_hotfix(git: dict) -> int:
    """
    数真翻车 commit。严格识别：
    - commit type 必须是 fix(...) 或 revert(...)
    - msg 体内必须含 hotfix / 紧急 / 回滚 关键字
    单纯 fix(...) 不算（v5 真闭环 review-fix 大量是正常迭代不是翻车）。
    单纯 docs(...) 含 "事故"/"hotfix" 也不算（那是回顾文档不是翻车本身）。
    """
    keywords = ("hotfix", "revert", "紧急", "回滚", "rollback")
    count = 0
    for c in git.get("commits", []):
        msg = c["msg"].lower()
        is_fix_or_revert = bool(re.match(r"^(fix|revert)(\(|:)", msg))
        if is_fix_or_revert and any(kw in msg for kw in keywords):
            count += 1
    return count


def calc_evolution_index(git, health, debt, mem) -> float:
    """
    进化指数 0-10 综合算法（v1 / 待迭代）：
    - 基线 5
    - 红灯文件每个 -0.8（>600 行）
    - 黄灯文件超 10 个每个 -0.05（>300 行）
    - debt 条目超 12 每条 -0.15
    - commit 数 ≥ 5 +1（活跃）
    - 新增 memory ≥ 1 +0.5（在学习 / 沉淀经验）
    - 真翻车（hotfix/revert/紧急/回滚）每个 -0.6
    """
    score = 5.0
    score -= 0.8 * health["red_count"]
    score -= 0.05 * max(0, health.get("yellow_count", 0) - 10)
    score -= 0.15 * max(0, debt["entries"] - 12)
    if git.get("commit_count", 0) >= 5:
        score += 1.0
    if len(mem.get("new_this_week", [])) >= 1:
        score += 0.5
    score -= 0.6 * _count_real_hotfix(git)
    return max(0.0, min(10.0, round(score, 1)))


def _delta(current: float, last: float | None) -> str:
    """对比箭头：⬆ 好转 / ⬇ 恶化 / → 持平 / N/A cold start。"""
    if last is None:
        return "—"
    if current == last:
        return "→"
    return "⬆" if current > last else "⬇"


def _delta_inverse(current: float, last: float | None) -> str:
    """对越小越好的指标取反：红灯 / debt / 黄灯。"""
    if last is None:
        return "—"
    if current == last:
        return "→"
    return "⬆" if current < last else "⬇"


def render_report(week_id, git, health, mem, debt, evo, last) -> str:
    last_data = last["data"] if last else {}
    lines = [
        f"# velo 周报 / {week_id}",
        "",
        f"> 生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 上份报告：{last['path'] if last else '（首次跑 / 无对比）'}",
        "",
        "## 一句话",
        "",
        f"**进化指数：{evo} / 10** {_delta(evo, last_data.get('evolution_index'))}",
        "",
        "## 本周做了啥",
        "",
        f"- {git['commit_count']} commit / +{git['insertions']} / -{git['deletions']} 行",
        "- 分类：" + " / ".join(f"{k} {v}" for k, v in git["categories"].items() if v > 0),
        "",
        "## 跟上周比",
        "",
        "| 指标 | 上周 | 本周 | 变化 |",
        "|---|---|---|---|",
        f"| 红灯文件 | {last_data.get('red_count', '—')} | {health['red_count']} | {_delta_inverse(health['red_count'], last_data.get('red_count'))} |",
        f"| 黄灯文件 | {last_data.get('yellow_count', '—')} | {health['yellow_count']} | {_delta_inverse(health['yellow_count'], last_data.get('yellow_count'))} |",
        f"| tech-debt 条目 | {last_data.get('debt_entries', '—')} | {debt['entries']} | {_delta_inverse(debt['entries'], last_data.get('debt_entries'))} |",
        f"| memory 总数 | {last_data.get('memory_total', '—')} | {mem['total']} | {_delta(mem['total'], last_data.get('memory_total'))} |",
        f"| 后端代码量 | {last_data.get('total_lines', '—')} | {health['total_lines']} | — |",
        f"| 进化指数 | {last_data.get('evolution_index', '—')} | {evo} | {_delta(evo, last_data.get('evolution_index'))} |",
        "",
        "## 本周新学（新 memory）",
        "",
    ]
    if mem["new_this_week"]:
        for m in mem["new_this_week"]:
            lines.append(f"- {m}")
    else:
        lines.append("- 无新增")

    lines += [
        "",
        "## 翻车统计",
        "",
        f"- fix commit：{git['categories'].get('fix', 0)} 次",
        f"- revert / hotfix 关键字：{sum(1 for c in git.get('commits', []) if 'revert' in c['msg'].lower() or 'hotfix' in c['msg'].lower())} 次",
        "",
        "## 当前红灯文件",
        "",
    ]
    if health["red_files"]:
        for path, n in health["red_files"]:
            lines.append(f"- ⚠️ {path}（{n} 行）")
    else:
        lines.append("- ✅ 0 红灯")

    lines += [
        "",
        "## 下周提醒",
        "",
        f"- tech-debt.md 当前 {debt['entries']} 条 / {debt['lines']} 行 → 看 top 3 优先级",
        "- 跑 `python3 scripts/verify_tech_debt.py` 看是否有新过期条目",
        "",
        "---",
        "",
        "**进化指数算法**（v1）：基线 5 / 红灯每个 -0.8 / 黄灯超 10 每个 -0.05 / debt 超 12 每条 -0.15 / commit≥5 +1 / 新 memory≥1 +0.5 / 真翻车（hotfix/revert/紧急）每个 -0.6",
    ]
    return "\n".join(lines)


def iso_week_id(d: datetime.datetime | None = None) -> str:
    d = d or datetime.datetime.now()
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def main() -> int:
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)

    week_id = iso_week_id()
    git = collect_git_stats(7)
    health = collect_health_stats()
    mem = collect_memory_stats(7)
    debt = collect_debt_stats()
    last = find_last_report()
    evo = calc_evolution_index(git, health, debt, mem)
    report = render_report(week_id, git, health, mem, debt, evo, last)

    out = WEEKLY_DIR / f"{week_id}.md"
    out.write_text(report, encoding="utf-8")

    # stdout 摘要（hook 起手时塞给 agent / Tim 间接看）
    print("=== velo 周报已生成 ===")
    print(f"📄 {out.relative_to(ROOT)}")
    print(f"🌡 进化指数：{evo} / 10  {_delta(evo, (last or {}).get('data', {}).get('evolution_index'))}")
    print(f"🔴 红灯文件：{health['red_count']}  🟡 黄灯：{health['yellow_count']}")
    print(f"📋 tech-debt：{debt['entries']} 条 / {debt['lines']} 行")
    print(f"🧠 memory：本周新增 {len(mem['new_this_week'])} / 总 {mem['total']}")
    print(f"📝 commit：{git['commit_count']} 次 / fix {git['categories'].get('fix', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
