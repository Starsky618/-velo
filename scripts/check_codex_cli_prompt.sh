#!/bin/bash
# 只测 Codex CLI 每个任务被迫携带多少东西，不覆盖 Codex Desktop 的插件/skill 注入。

set -u

ROOT=$(cd "$(dirname "$0")/.." && pwd)
MAX_PROJECT_AGENTS_BYTES=${MAX_PROJECT_AGENTS_BYTES:-8192}
MAX_INSTRUCTION_BYTES=${MAX_INSTRUCTION_BYTES:-12000}
MAX_IMPLICIT_SKILLS=${MAX_IMPLICIT_SKILLS:-35}
MAX_SKILLS_PAYLOAD_BYTES=${MAX_SKILLS_PAYLOAD_BYTES:-18000}
fail=0

cd "$ROOT"

project_agents_bytes=$(wc -c < AGENTS.md | tr -d ' ')
if [ "$project_agents_bytes" -gt "$MAX_PROJECT_AGENTS_BYTES" ]; then
  echo "🔴 AGENTS.md 已到 ${project_agents_bytes} 字节，超过 ${MAX_PROJECT_AGENTS_BYTES}。把案例、状态或专项流程移出常驻入口。"
  fail=1
fi

# Codex 或 jq 不存在时仍保留静态体积检查，避免让非 Codex 环境无法提交。
if ! command -v codex >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
  echo "⚠️ 未找到 codex 或 jq；已检查项目 AGENTS.md，跳过 Codex CLI 提示体检。"
  exit "$fail"
fi

if ! prompt_json=$(codex debug prompt-input 'harness-check' 2>/dev/null); then
  echo "🔴 无法生成真实 Codex CLI 提示，不能确认本次 CLI harness 改动是否重新膨胀。"
  exit 1
fi

instructions=$(printf '%s' "$prompt_json" | jq -r '[.[] | select(.role == "user") | .content[] | (.text // .input_text // empty) | select(startswith("# AGENTS.md instructions"))][0] // empty')
developer_text=$(printf '%s' "$prompt_json" | jq -r '[.[] | select(.role == "developer") | .content[] | (.text // .input_text // empty)] | join("\n")')

if [ -z "$instructions" ] || ! printf '%s' "$developer_text" | grep -q '<skills_instructions>'; then
  echo "🔴 Codex 提示结构已变化，体检器无法可靠读数；先更新体检器，不能静默放行。"
  exit 1
fi

instruction_bytes=$(printf '%s' "$instructions" | wc -c | tr -d ' ')
skills_section=$(printf '%s\n' "$developer_text" | awk '/<skills_instructions>/{inside=1} inside{print} /<\/skills_instructions>/{exit}')
implicit_skills=$(printf '%s\n' "$skills_section" | awk '/### Available skills/{inside=1; next} /<\/skills_instructions>/{inside=0} inside && /^- /{count++} END{print count+0}')
skills_payload_bytes=$(printf '%s' "$skills_section" | wc -c | tr -d ' ')

if [ "$instruction_bytes" -gt "$MAX_INSTRUCTION_BYTES" ]; then
  echo "🔴 常驻 AGENTS 指令 ${instruction_bytes} 字节，超过 ${MAX_INSTRUCTION_BYTES}。"
  fail=1
fi
if [ "$implicit_skills" -gt "$MAX_IMPLICIT_SKILLS" ]; then
  echo "🔴 常驻 skill ${implicit_skills} 个，超过 ${MAX_IMPLICIT_SKILLS}；把低频流程改成仅点名调用或关闭。"
  fail=1
fi
if [ "$skills_payload_bytes" -gt "$MAX_SKILLS_PAYLOAD_BYTES" ]; then
  echo "🔴 skill 菜单 ${skills_payload_bytes} 字节，超过 ${MAX_SKILLS_PAYLOAD_BYTES}；Codex 可能开始截短描述。"
  fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo "✅ Codex CLI 提示体检：指令 ${instruction_bytes}/${MAX_INSTRUCTION_BYTES} 字节；skill ${implicit_skills}/${MAX_IMPLICIT_SKILLS} 个；菜单 ${skills_payload_bytes}/${MAX_SKILLS_PAYLOAD_BYTES} 字节。Desktop 暂未覆盖。"
fi

exit "$fail"
