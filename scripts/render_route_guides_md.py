"""route.json → guide.md + meta.json 机械投影器（开发机工具，不进容器）。

干啥用：把 route skill 工作区（~/.claude/skills/route-workspace/<路线>/route.json，
内容真相源，Tim 审过的 schema v1）机械投影成灌库脚本认识的 content/routes/ 结构。
"数据展示分离"的延续：HTML 是一种投影（build_from_json.js），本文件是另一种投影（markdown）。

操作注意事项：
- 文案一字不改：本脚本只搬运和排版，禁止任何改写——改内容回 route.json 改，再重跑投影。
- 模块协议（2026-06-11 Tim 拍）：content_md 用固定 `## 模块名` 分节，模块名 = HTML 卡板块名原文
 （这是一条什么路/给真要去的骑友/核心数据/怎么骑/骑友怎么说/安全）；前端按 ## 切成手风琴。
- 正式版禁小字备注：来源标签（［2源］）、时效提醒、数据备注括号一律不投影——溯源只活在 route.json。
- scenery 块暂不投影（多为空，待图库专项一并设计）；road_status 并入「安全」。
- 天龙山不在工作区（只有 v11 定本 HTML），不走本脚本，由主 agent 手工转写（守同一模块协议）。

输入/输出：读 workspace 各目录 route.json → 写 content/routes/<目录名>/guide.md + meta.json。
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

WORKSPACE = Path.home() / ".claude" / "skills" / "route-workspace"
OUTPUT = Path(__file__).resolve().parents[1] / "content" / "routes"


def _metric_lines(metrics: dict) -> list[str]:
    """核心数据：只出干净的"值 + 单位"，备注括号留在 route.json（正式版禁小字）。"""
    label_map = [
        ("distance_km", "距离", "km"),
        ("elevation_gain_m", "累计爬升", "m"),
        ("avg_gradient_pct", "平均坡度", "%"),
        ("max_gradient_pct", "最大坡度", "%"),
    ]
    lines = []
    for key, label, unit in label_map:
        triple = metrics.get(key)
        if not isinstance(triple, dict) or triple.get("value") is None:
            continue
        lines.append(f"- **{label}**：{triple['value']}{(' ' + unit) if unit else ''}")
    return lines


def _items_text(block: dict | None) -> list[str]:
    """把 {items: [...], note: ...} 形状的块拍平成行；条目可能是字符串或 {text}。"""
    if not isinstance(block, dict):
        return []
    lines = []
    for item in block.get("items") or []:
        text = item if isinstance(item, str) else item.get("text", "")
        if text:
            lines.append(f"- {text}")
    note = block.get("note")
    if note and block.get("status") != "not_surveyed":
        # not_surveyed 的 note 是写给维护者的占位说明，不是给用户的内容
        lines.append(f"- {note}")
    return lines


def render_guide_md(d: dict) -> str:
    identity = d.get("identity", {})
    out: list[str] = [f"# {identity.get('name', '')}"]
    subtitle = identity.get("subtitle")
    if subtitle:
        out += ["", f"> {subtitle}"]

    # —— 这是一条什么路（intro 段落原文）——
    paragraphs = (d.get("intro") or {}).get("paragraphs") or []
    if paragraphs:
        out += ["", "## 这是一条什么路", ""]
        for p in paragraphs:
            out += [p, ""]

    # —— 给真要去的骑友（for_riders 原文）——
    for_riders = (d.get("intro") or {}).get("for_riders") or []
    if for_riders:
        out += ["## 给真要去的骑友", ""]
        for item in for_riders:
            key = item.get("key")
            text = item.get("text", "")
            out.append(f"- **{key}**：{text}" if key else f"- {text}")
        out += [""]

    # —— 核心数据（干净数值，无备注）——
    metric_lines = _metric_lines(d.get("metrics") or {})
    if metric_lines:
        out += ["## 核心数据", ""] + metric_lines + [""]

    # —— 怎么骑（路书 legs + 补给/撤退 + 不与 legs 重复的赛段拆解）——
    plan = d.get("route_plan") or {}
    legs = plan.get("legs") or []
    how_lines: list[str] = []
    for leg in legs:
        how_lines.append(f"{leg.get('seq')}. **{leg.get('name', '')}** {leg.get('desc', '')}".rstrip())
    leg_descs = {leg.get("desc", "") for leg in legs}
    extra_segments = [
        seg for seg in (d.get("segments") or {}).get("items") or []
        if seg.get("desc", "") not in leg_descs
    ]
    for seg in extra_segments:
        how_lines.append(f"- **{seg.get('name', '')}** {seg.get('desc', '')}".rstrip())
    for key, label in (("resupply", "补给"), ("bailout", "撤退")):
        block = plan.get(key) or {}
        sub = _items_text(block)
        if isinstance(block, dict) and block.get("note") and block.get("status") != "not_surveyed":
            pass  # note 已由 _items_text 收录
        if sub:
            how_lines.append(f"- **{label}**：" + "；".join(s.lstrip("- ") for s in sub))
    if how_lines:
        out += ["## 怎么骑", ""] + how_lines + [""]

    # —— 骑友怎么说（评论原文 + 注释并行排版，不带标签）——
    comments = (d.get("comments") or {}).get("items") or []
    if comments:
        out += ["## 骑友怎么说", ""]
        for c in comments:
            text = c.get("text", "")
            note = c.get("note")
            quoted = "- “" + text + "”"
            out.append(quoted + (f"——{note}" if note else ""))
        out += [""]

    # —— 安全（safety 原文 + 路况时效条目并入）——
    safety_lines = _items_text(d.get("safety"))
    safety_lines += _items_text(d.get("road_status"))
    if safety_lines:
        out += ["## 安全", ""] + safety_lines + [""]

    return "\n".join(out).rstrip() + "\n"


def convert(route_dir: Path, force: bool = False) -> None:
    data = json.loads((route_dir / "route.json").read_text(encoding="utf-8"))
    identity = data.get("identity", {})
    name = identity.get("name")
    if not name:
        print(f"跳过 {route_dir.name}：route.json 缺 identity.name")
        return
    target = OUTPUT / route_dir.name
    target.mkdir(parents=True, exist_ok=True)
    # 文案真相源移交（Tim 2026-06-11 拍）：guide.md 一旦存在就归 Tim 手动编辑
    # （VS Code 直接改字，LLM 不经手），本投影器不再覆盖——除非显式 --force。
    # route.json 继续当结构化数据的真相源（轨迹/坐标/数据/证据链），文案主权在 md。
    guide_path = target / "guide.md"
    if guide_path.exists() and not force:
        print(f"· {route_dir.name} guide.md 已存在（文案归 Tim 手动维护），跳过正文投影")
    else:
        guide_path.write_text(render_guide_md(data), encoding="utf-8")

    # meta.json 同理让位：cover_url/distance_km/climb_m/简介都可能被手工维护过，
    # 已存在就不再覆盖（--force 才重建）。首次生成走下面的全量写入。
    if (target / "meta.json").exists() and not force:
        print(f"· {route_dir.name} meta.json 已存在，跳过")
        return
    meta = {
        "name": name,
        "city": identity.get("city") or "太原",
        # 一句话简介 = 副标题原文（列表页钩子 + 详情页常显行）
        "highlights": json.dumps([identity["subtitle"]], ensure_ascii=False) if identity.get("subtitle") else None,
        # 封面专项待 Tim（版权链/实拍），先空走前端占位图
        "cover_url": None,
        # 溯源指针：DB 是投影，真相源在 route skill 工作区；改内容改 route.json 重跑两步投影
        "source_ref": f"route-workspace/{route_dir.name}/route.json @ {date.today().isoformat()}",
    }
    meta = {k: v for k, v in meta.items() if v is not None}
    (target / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✓ {route_dir.name} → {target.relative_to(OUTPUT.parents[1])}")


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv[1:]
    only = args[0] if args else None
    dirs = sorted(p for p in WORKSPACE.iterdir() if (p / "route.json").exists())
    for route_dir in dirs:
        if only and route_dir.name != only:
            continue
        convert(route_dir, force=force)


if __name__ == "__main__":
    main()
