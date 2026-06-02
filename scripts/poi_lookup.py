"""
地点坐标查询脚本——给路线百科冷启动准备一张可靠的“地名通讯录”。

干啥用：本地输入一个或多个地名，调用腾讯地点检索，输出 WGS-84 坐标 JSON。
操作注意事项：这是命令行工具，不挂 HTTP；SK 只在服务端签名，脚本不打印配置和请求参数。
输入输出：输入地名列表 → 标准输出 JSON；单个地名输出单个对象，多个地名输出数组。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.route_book.tencent_direction import TencentMapConfigError, TencentMapError
from app.route_book.tencent_place import search_place


def _lookup(keyword: str, region: str) -> dict[str, Any]:
    result = search_place(keyword, region=region)
    if result is None:
        return {"keyword": keyword, "result": None}
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="查询腾讯地点坐标，输出 WGS-84 JSON")
    parser.add_argument("keywords", nargs="+", help="一个或多个地名，例如：蒙山大佛 太山")
    parser.add_argument("--region", default="太原", help="腾讯地点检索城市范围，默认太原")
    args = parser.parse_args(argv)

    try:
        results = [_lookup(keyword, args.region) for keyword in args.keywords]
    except (TencentMapConfigError, TencentMapError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    payload: dict[str, Any] | list[dict[str, Any]]
    if len(results) == 1:
        payload = results[0]
    else:
        payload = results
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
