#!/usr/bin/env bash
# 手动扫描文档中需要回看的项目；不再依赖已退役的 CLAUDE 风险表。

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "════ velo 复检扫描 $(date '+%Y-%m-%d') ════"
echo "── 待复检语义 ──"
rg -n "待复检|待重审|再回头判断|待观察|真用观察|待确认" "$ROOT/docs" \
  --glob '*.md' --glob '!archive/**' --glob '!changelog.md' | head -30 || true

echo "── tech-debt 未关闭信号 ──"
rg -n "⚠️|❌|TODO|待处理" "$ROOT/docs/tech-debt.md" | head -30 || true
