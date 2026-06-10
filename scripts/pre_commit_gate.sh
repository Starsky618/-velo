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

# 四、惯犯静态扫描(2026-06-10 v2 / 蒸自 80 判例中的重复违规惯犯,只扫本次新增行)
# v2.1 自指修复:只扫代码路径(app/miniprogram/tests/alembic)。文档和本脚本自身含陷阱描述文本,
# 扫它们会自爆——首次提交本脚本时被自己拦住,实证 2026-06-10。
added_lines=$(git diff --cached --unified=0 -- app miniprogram tests alembic | grep '^+' | grep -v '^+++')

# 硬拦组(历史上被 Tim 抓过且零误报空间)
if echo "$added_lines" | grep -qE 'isoformat\(\) ?\+ ?"Z"'; then
  echo "🔴 陷阱 #11:isoformat()+\"Z\" 会产出 +00:00Z 畸形串(2026-04-29 三审实证)。让 Pydantic 自动序列化。"
  fail=1
fi
if echo "$added_lines" | grep -qE 'with db\.begin\(\)'; then
  echo "🔴 陷阱 #21:with db.begin() 在 autobegin session 上必炸 InvalidRequestError(2026-06-01 实证)。统一末尾单次 db.commit()。"
  fail=1
fi

# 响铃组(高概率违规,人工确认后可提交)
if git diff --cached --name-only | grep -q '^miniprogram/' ; then
  if echo "$added_lines" | grep -q 'created_at'; then
    echo "⚠️ 前端新增行出现 created_at:展示时间永远用业务时间(started_at),不用 DB 写入时间(2026-05-15 Tim:为什么会犯同样的错误)。确认这处不是展示用途。"
  fi
fi
if echo "$added_lines" | grep -qE 'logger\.warning' && echo "$added_lines" | grep -qE 'except'; then
  echo "⚠️ 新增代码同时含 except 和 logger.warning:except 块里必须 logger.exception 打完整 traceback(2026-05-16 实证:410 条 NULL 一天后才发现)。"
fi
if echo "$added_lines" | grep -qE '\.one\(\)'; then
  echo "⚠️ 新增 .one():零记录抛 NoResultFound→500(陷阱 #4)。确认是否该用 .first()+显式判空。"
fi
if echo "$added_lines" | grep -qE 'with_for_update\(\)' && ! echo "$added_lines" | grep -qE 'populate_existing'; then
  echo "⚠️ 新增 with_for_update() 未见 populate_existing():行锁拿到但字段值 stale(陷阱 #12)。"
fi

if [ "$fail" -eq 1 ]; then
  echo "(硬拦项修完再 commit;响铃项确认误报可继续)"
  exit 1
fi
exit 0
