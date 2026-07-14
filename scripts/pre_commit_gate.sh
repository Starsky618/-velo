#!/bin/bash
# commit 前门禁(陷阱 A 修复 / 2026-06-10 Tim 拍板)
# 把 CLAUDE.md「附加门禁」从散文升级成结构约束:违规物理上提交不进去,不靠 agent 记得。
# 安装:cp scripts/pre_commit_gate.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
# 设计:只硬拦客观可判的(承载性新文件没 stage);大改动只响铃不拦(噪音 vs 信号:
# 300 行阈值是人为线,硬拦会逼人绕过门禁本身)。

fail=0

# 一、只拦“本次 staged 新增行引用了、但仍未跟踪”的承载文件。
# 旧版扫描整个工作区：别的模块有草稿时，连一行无关文档都提交不了。这里改为读 staged patch，
# 识别常见的 Python dotted import、文件路径和小程序 page 路径；未被本次提交引用的草稿不干扰。
staged_added=$(git diff --cached --unified=0 -- . | grep '^+' | grep -v '^+++' || true)
referenced_untracked=()
while IFS= read -r -d '' path; do
  no_ext="${path%.*}"
  dotted=$(printf '%s' "$no_ext" | tr '/' '.')
  project_relative="$no_ext"
  if [[ "$project_relative" == miniprogram/* ]]; then
    project_relative="${project_relative#miniprogram/}"
  fi

  if printf '%s\n' "$staged_added" | grep -Fq -- "$path" \
    || printf '%s\n' "$staged_added" | grep -Fq -- "$no_ext" \
    || printf '%s\n' "$staged_added" | grep -Fq -- "$dotted" \
    || printf '%s\n' "$staged_added" | grep -Fq -- "$project_relative"; then
    referenced_untracked+=("$path")
  fi
done < <(git ls-files --others --exclude-standard -z -- app alembic migrations tests miniprogram scripts)

if [ "${#referenced_untracked[@]}" -gt 0 ]; then
  echo "🔴 门禁拦截:本次 staged 代码引用了仍未跟踪的文件;干净 clone 会缺件:"
  printf '    %s\n' "${referenced_untracked[@]}"
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
  if ! git diff --cached --name-only | grep -qE '(alembic|migrations)/versions/'; then
    echo "⚠️ 改了 models.py 但本次没有 migrations/versions/ 新文件——确认是否需要迁移(Alembic 迁移纪律)。"
  fi
fi

# 四、惯犯静态扫描(2026-06-10 v2 / 蒸自 80 判例中的重复违规惯犯,只扫本次新增行)
# v2.1 自指修复:只扫代码路径(app/miniprogram/tests/alembic)。文档和本脚本自身含陷阱描述文本,
# 扫它们会自爆——首次提交本脚本时被自己拦住,实证 2026-06-10。
added_lines=$(git diff --cached --unified=0 -- app miniprogram tests alembic migrations | grep '^+' | grep -v '^+++')

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

# 五、只有本次真的改了 agent 入口时，才跑 Codex CLI 提示体检；普通代码提交不付这 1-2 秒成本。
cli_checker="scripts/check_codex_cli_prompt.sh"
if git diff --cached --name-only -- AGENTS.md .codex .agents/skills scripts/pre_commit_gate.sh "$cli_checker" | grep -q .; then
  if ! git cat-file -e ":$cli_checker" 2>/dev/null; then
    echo "🔴 门禁拦截:$cli_checker 没有和调用方一起进入 Git index；干净 clone 会缺少体检器。"
    fail=1
  elif [ ! -x "$cli_checker" ]; then
    echo "🔴 门禁拦截:$cli_checker 不可执行。"
    fail=1
  elif ! "$cli_checker"; then
    fail=1
  fi
fi

if [ "$fail" -eq 1 ]; then
  echo "(硬拦项修完再 commit;响铃项确认误报可继续)"
  exit 1
fi
exit 0
