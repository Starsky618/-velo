#!/usr/bin/env python3
"""只在用户要上线时提醒读取 VELO 部署 SOP；不再注入旧规则或历史上下文。"""

import json
import sys


DEPLOY_KEYWORDS = ("部署", "上线", "发布生产", "生产发布", "hotfix")
REMINDER = """<velo-deploy-reminder>
这是 VELO 生产动作。执行前完整读取 `docs/agent-rules/deploy-sop.md`，并把本地验证、CI、部署和线上真用分别举证；高风险或目标不明时先确认权限。
</velo-deploy-reminder>
"""


def read_prompt() -> str:
    raw = sys.stdin.read()
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return data.get("prompt", "") if isinstance(data, dict) else ""


def main() -> int:
    prompt = read_prompt().lower()
    if any(keyword.lower() in prompt for keyword in DEPLOY_KEYWORDS):
        sys.stdout.write(REMINDER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
