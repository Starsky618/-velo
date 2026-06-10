#!/bin/bash
# 复检点火器(陷阱 D 修复 / 2026-06-10 Tim 拍板)
# 病灶:复检条件写了没人触发——persona「晾 3-5 天」逾期 16 天无人问,tech-debt ❌ 从 v4 躺到 Sprint 12。
# 用法:每期开工前跑一次(CLAUDE.md 防黑盒化已挂钩);也扫战略决策库。
# 输出:所有「写了要回头看」的条目清单,人眼扫一遍,逾期的逼拍板。

echo "════ velo 复检点火器 $(date '+%Y-%m-%d') ════"

echo ""
echo "── 1. 带复检语义的条目(velo 文档)──"
grep -rn -E "待复检|晾着|待重审|再回头判断|待观察|真用观察|待 v[0-9]|待确认" \
  ~/Desktop/velo/CLAUDE.md ~/Desktop/velo/docs/*.md ~/Desktop/velo/docs/agent-rules/*.md 2>/dev/null \
  | grep -v "recheck_scanner" | sed 's|/Users/macbookair/Desktop/velo/||' | head -30

echo ""
echo "── 2. 风险表 ⚠️/❌ 未关闭项(CLAUDE.md 已知风险)──"
grep -n -E "⚠️|❌" ~/Desktop/velo/CLAUDE.md | grep -v "门禁\|红灯" | sed 's|/Users/macbookair/Desktop/velo/||' | head -15

echo ""
echo "── 3. tech-debt 现存条目数 ──"
grep -c -E "^[-|#]|^[0-9]" ~/Desktop/velo/docs/tech-debt.md 2>/dev/null || echo "tech-debt.md 不存在"

echo ""
echo "── 4. 战略决策库待点火项(inspiration-vault)──"
grep -n -E "status: (待确认|拍板·未盘问)|复检条件" ~/Projects/inspiration-vault/strategy/*/decisions.md 2>/dev/null \
  | sed 's|/Users/macbookair/Projects/inspiration-vault/||' | head -10

echo ""
echo "════ 扫描完毕:每条要么拍板关闭,要么写新日期续期——不许静默滚动 ════"
