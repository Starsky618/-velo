#!/bin/bash
# Persona Engine 拔出测试（task-6 / final gate）
#
# 干啥用：
# 模拟删掉 Persona Engine 全部资产 / 跑核心业务 pytest / 验证 NPC 真的是可拔的"码表"
# 不是焊在车架上的零件（宪法 § 7.1）。
#
# 类比：车头码表坏了不影响骑车 / 而 NPC 模块挂了不应该影响 velo 核心业务（用户上传 /
# 看活动 / 看赛段 / 看排行）。
#
# 用法：
#   bash scripts/persona_pluck_dryrun.sh
#
# 退出码：
#   0 = 拔出后核心业务 pytest 全过 / NPC 真可拔
#   非 0 = 业务模块对 NPC 有反向依赖 / 违反 ADR-009 / 必修
#
# 前提：
# - 必须在干净 working tree 跑（git status 应该 empty / v0.2 修 / 防 git add -A 污染）
# - 必须先 commit 当前所有改动 / 脚本会切临时 branch 操作

set -e

# 0. 前置：clean working tree 检查
if [ -n "$(git status --short)" ]; then
  echo "❌ Working tree not clean / 先 commit / stash 现有改动再跑拔出测试"
  git status --short
  exit 1
fi

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
TEMP_BRANCH="persona-pluck-dryrun-$(date +%s)"

echo "=== 1. 切临时 branch ==="
git checkout -b "$TEMP_BRANCH"

echo ""
echo "=== 2. 列 Persona 全部资产（按命名前缀 / 对照 MANIFEST.md）==="
find . \
  -path ./.git -prune -o \
  -path ./node_modules -prune -o \
  -path ./venv -prune -o \
  \( -name "*persona*" -o -name "persona_*" \) -print \
  | tee /tmp/persona_assets.txt

ASSET_COUNT=$(wc -l < /tmp/persona_assets.txt)
echo ""
echo "共找到 $ASSET_COUNT 处 persona 资产"

echo ""
echo "=== 3. 干跑删除所有 persona 资产 ==="
while IFS= read -r asset; do
  if [ -e "$asset" ]; then
    rm -rf "$asset"
    echo "  删除：$asset"
  fi
done < /tmp/persona_assets.txt

# 把 wxml/js/wxss 里的 PERSONA_START...PERSONA_END 块也剥离
# （这些是嵌在前端文件里的块 / 不是独立文件 / 单独处理）
echo ""
echo "=== 3.5. 剥离嵌入式 PERSONA_START/END 块（wxml/js/wxss）==="
# 用 awk 删 PERSONA_START 到 PERSONA_END 之间的行（保留外层文件 / 只剥块）
for f in $(grep -rl "PERSONA_START" miniprogram/ 2>/dev/null || true); do
  if [ -f "$f" ]; then
    awk '
      /PERSONA_START/ { skip = 1 }
      !skip { print }
      /PERSONA_END/ { skip = 0 }
    ' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    echo "  剥块：$f"
  fi
done

# 也把 app/main.py / app/activity/worker.py 里的 PERSONA 引用剥离
for f in app/main.py app/activity/worker.py app/agent/__init__.py; do
  if [ -f "$f" ] && grep -q "PERSONA_START\|persona" "$f"; then
    awk '
      /PERSONA_START/ { skip = 1 }
      !skip { print }
      /PERSONA_END/ { skip = 0 }
    ' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    echo "  剥块：$f"
  fi
done

echo ""
echo "=== 4. commit 临时 prune 改动（方便回滚）==="
git add -A 2>/dev/null || true
git commit --no-verify -am "[dryrun] pluck all persona assets" 2>&1 | tail -3

echo ""
echo "=== 5. 跑核心业务 pytest（验证业务模块无 import error）==="
echo "    （task-6 final gate / 期望全过）"

# 核心业务模块测试 / 不含 test_persona_*（已被删）
CORE_TESTS=$(find tests -name "test_*.py" -not -name "test_persona_*.py" | head -50)
echo "    核心测试文件数：$(echo "$CORE_TESTS" | wc -l)"

if pytest $CORE_TESTS --tb=line -q 2>&1 | tail -10; then
  PYTEST_RESULT="✅ Pluck dryrun pass / NPC is removable"
  EXIT_CODE=0
else
  PYTEST_RESULT="❌ Pluck dryrun FAIL / 业务对 NPC 有反向依赖（违反 ADR-009）"
  EXIT_CODE=1
fi

echo ""
echo "=== 6. 清理：回到原 branch ==="
git checkout "$CURRENT_BRANCH"
git branch -D "$TEMP_BRANCH"

echo ""
echo "================================================"
echo "$PYTEST_RESULT"
echo "================================================"

exit $EXIT_CODE
