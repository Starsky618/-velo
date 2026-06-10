#!/bin/bash
# commit 前门禁(陷阱 A 修复 / 2026-06-10 Tim 拍板)
# 把 CLAUDE.md「附加门禁」从散文升级成结构约束:违规物理上提交不进去,不靠 agent 记得。
# 安装:cp scripts/pre_commit_gate.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
# 设计:只硬拦客观可判的(承载性新文件没 stage);大改动只响铃不拦(噪音 vs 信号:
# 300 行阈值是人为线,硬拦会逼人绕过门禁本身)。

fail=0

# 一、承载性新文件检查(原 CLAUDE.md L26 附加门禁):
# app/ alembic/ tests/ miniprogram/ 下的 untracked 文件,若被本次 staged 代码 import/引用,
# 干净 clone 会 ImportError——这里先宽口径列出所有承载性目录的 untracked,逼一次显式决定。
untracked=$(git status --porcelain | grep '^??' | awk '{print $2}' | grep -E '^(app|alembic|tests|miniprogram)/' )
if [ -n "$untracked" ]; then
  echo "🔴 门禁拦截:承载性目录存在 untracked 文件,先决定 stage 还是 .gitignore:"
  echo "$untracked" | sed 's/^/    /'
  fail=1
fi

# 二、大改动响铃(>300 行新增 → 提醒双审留痕,不硬拦)
added=$(git diff --cached --numstat | awk '{s+=$1} END {print s+0}')
if [ "$added" -gt 300 ]; then
  echo "⚠️ 本次 staged 新增 ${added} 行(>300):CLAUDE.md 原则 8 要求代码层双审。"
  echo "   双审报告留痕了吗?(docs/reviews/ 或 commit message footer)"
fi

# 三、迁移与模型同步检查:动了 models.py 却没有新迁移文件 → 响铃
if git diff --cached --name-only | grep -q 'models\.py' ; then
  if ! git diff --cached --name-only | grep -q 'alembic/versions/'; then
    echo "⚠️ 改了 models.py 但本次没有 alembic/versions/ 新文件——确认是否需要迁移(Alembic 迁移纪律)。"
  fi
fi

if [ "$fail" -eq 1 ]; then
  echo "(确认无误后用 git add 补齐或加入 .gitignore,再重新 commit)"
  exit 1
fi
exit 0
