#!/usr/bin/env python3
"""
tech-debt.md 自动验证脚本——给 agent 看的"过期食品扫描仪"。

干啥用：
    整理 tech-debt 时手动运行。扫描 docs/tech-debt.md，把"代码已变 / 文档没刷"
    的条目列出来，避免已修问题继续占着清单。

类比：
    家里贴一张"待处理"清单，但东西丢了忘划掉 → 每次看清单都焦虑。
    这个脚本 = 自动扫描仪，按"文件路径 / 行数 / ✅ 标记"3 个角度提醒哪些条目可能过期。

注意事项：
    - 只是"启发式"提醒，不是断言"这条 100% 过期"——具体过期判断由 agent / Tim 做
    - 阈值：路径里提的行数和真实行数差 > 30% 报警（避免微调误报）
    - 升级路径：未来 tech-debt.md 每条加 `<!-- verify: <cmd> | <expect> -->` 注释
      做语义级断言，本脚本同套解析逻辑加一段就行 / 不需要重写

数据流：
    入：docs/tech-debt.md 文本 + 项目根 app/ + scripts/ 目录
    出：stdout 报告（路径核对表 + ✅ 标记可删条目 + 总览）
    退出码：0（无论是否找到可疑条目）—— 这是提醒不是 lint / 不当 CI 阻断器用

升级 trigger：
    - 跑出来误报多（同一条目被 3+ 次复核仍属真 debt）→ 升级到 verify 注释
    - tech-debt 条目超 30 条 → 升级到 JSON manifest
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TECH_DEBT = ROOT / "docs" / "tech-debt.md"

# 已 ship / 已修标记词——含这些词的标题大概率是"修完没删的条目"
COMPLETED_MARKERS = ["✅", "已 ship", "已修", "已收编", "已解决", "已拆", "已全部清理"]

# 文件路径正则——只抓 app/ 和 scripts/ 下的 python / shell 文件
PATH_PATTERN = re.compile(r"`?(app/[a-zA-Z0-9_/]+\.py|scripts/[a-zA-Z0-9_/]+\.(?:py|sh))`?")


def count_lines(path: Path) -> int:
    """数文件行数。文件不存在返回 -1。"""
    if not path.exists():
        return -1
    return sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))


def find_line_claim_near(content: str, path: str) -> int | None:
    """
    在文档里找路径附近声明的行数。
    例：`app/segment/service.py` 793 行 → 返回 793。
    没找到返回 None。
    """
    pattern = re.escape(path) + r"[^\n]{0,150}?(\d{2,4})\s*行"
    m = re.search(pattern, content)
    return int(m.group(1)) if m else None


def scan_paths(content: str) -> list[dict]:
    """扫文档里所有提到的文件路径，逐个核对存在性和行数声明。"""
    paths = sorted(set(PATH_PATTERN.findall(content)))
    results = []
    for p in paths:
        full = ROOT / p
        real_lines = count_lines(full)
        claimed = find_line_claim_near(content, p)
        results.append({
            "path": p,
            "exists": real_lines != -1,
            "real_lines": real_lines,
            "claimed_lines": claimed,
        })
    return results


def scan_completed_markers(content: str) -> list[tuple[int, str]]:
    """
    扫所有 ## / ### / #### 标题行中含"已 ship / ✅ / 已修"等的——
    这些大概率是"修完忘删的条目"。
    返回 [(行号, 标题内容)]。
    """
    results = []
    for i, line in enumerate(content.splitlines(), start=1):
        if not re.match(r"^#{2,4}\s", line):
            continue
        if any(marker in line for marker in COMPLETED_MARKERS):
            results.append((i, line.strip()))
    return results


def render_report(path_results: list[dict], completed: list[tuple[int, str]]) -> str:
    """把扫描结果排版成人能看的报告。"""
    lines = ["=== tech-debt.md 验证报告 ===", ""]

    # 路径核对
    lines.append(f"📁 文件路径核对（共 {len(path_results)} 处）")
    suspicious = 0
    for r in path_results:
        if not r["exists"]:
            lines.append(f"  ❌ {r['path']} 不存在")
            suspicious += 1
            continue
        if r["claimed_lines"] is None:
            lines.append(f"  ✅ {r['path']}（{r['real_lines']} 行 / 文档无具体行数声明）")
            continue
        diff_pct = abs(r["real_lines"] - r["claimed_lines"]) / max(r["claimed_lines"], 1) * 100
        if diff_pct > 30:
            lines.append(
                f"  ⚠️ {r['path']}（真 {r['real_lines']} 行 vs 文档说 {r['claimed_lines']} 行 / 差 {diff_pct:.0f}%）"
            )
            suspicious += 1
        else:
            lines.append(f"  ✅ {r['path']}（{r['real_lines']} 行 ≈ 文档 {r['claimed_lines']} 行）")
    lines.append("")

    # ✅ 标记
    lines.append(f"🏷 含已完成标记的标题（{len(completed)} 条 / 真过期请删）")
    for line_num, title in completed:
        lines.append(f"  ⚠️ line {line_num}: {title}")
    lines.append("")

    # 总览
    lines.append("📊 总览")
    lines.append(f"  扫描路径数：{len(path_results)}")
    lines.append(f"  路径可疑数：{suspicious}")
    lines.append(f"  ✅ 标记条目数：{len(completed)}")
    lines.append("")
    lines.append("处理建议：")
    lines.append("  - 路径可疑 → 看条目是否真已 ship / 已 ship 则删")
    lines.append("  - ✅ 标记条目 → 直接删（修完没删的残留）")

    return "\n".join(lines)


def main() -> int:
    if not TECH_DEBT.exists():
        print(f"找不到 {TECH_DEBT}", file=sys.stderr)
        return 1

    content = TECH_DEBT.read_text(encoding="utf-8")
    path_results = scan_paths(content)
    completed = scan_completed_markers(content)

    print(render_report(path_results, completed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
