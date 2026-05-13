#!/usr/bin/env python3
"""
UserPromptSubmit hook —— 每次 Tim 发消息后 / agent 收到消息前 / 自动注入 mental check 到上下文。

干啥用：
    这是补 hook + 周报 + memory 都救不了的真盲区——
    "规则在 context" ≠ "规则在决策时被激活"。
    必须每个 turn 起手强制注入规则 trigger，让 agent 看到 Tim 消息前先过 3 问。

类比：
    SessionStart hook = 早上出门前看一眼日程表（开会话才看一次）
    UserPromptSubmit hook = 每次有人对你说话前 / 耳机里都先响一段"先想 3 问再开口"
    这是把"规则进眼"变成"规则进决策"的唯一机制。

输出机制：
    stdout 输出会作为 additional context 注入到 agent 看到的 user message 之前。
    agent 实际收到的 = [本脚本 stdout] + [Tim 的原始消息]。

注意事项：
    - 输出极简（每 turn 都注入 / 太长会污染上下文）
    - 含具体 mental check 问题 + 具体反模式样本（不抽象）
    - 引用 CLAUDE.md / memory 章节 / 但不抄全文
"""

import sys

INJECTION = """<mental-check-before-response>
⚠️ 回答前必过 3 问（任一违反 → 删重写 / 别假装看完了又犯）：

【问 1】我下面要做的是「中层职责」还是「CEO 职责」？
   ❌ 中层（自己拍 / 不发 Tim）：列方案让选 / 选 A 还是 B / 要不要 / 怎么做 / 用什么模板 / 风格对吗 / 粒度对吗 / 装哪个
   ✅ CEO（给 Tim 拍）：战略方向 / 产品决策 / 资源分配 / 用户价值取舍
   → 反模式样本（你已重复违反 ≥ 6 次）：「两件事等你拍」/「装哪个」/「要不要写 X」/「α/β/γ 选哪个」
   → 参考：memory/feedback_simplification_rule_vs_tool.md 末段「禁止越级上报清单」

【问 2】我说人话了吗？
   ❌ 禁用词：颗粒度 / 闭环 / 触点 / 二级页 / 赋能 / 抓手 / 对齐 / 启发式扫描 / 路径核对
   ❌ 堆术语 / 教科书式抽象语言 / 不讲用户故事
   ✅ 我妈三问 fail → 删重写 / 不抱已有版本做小修小补
   → 参考：CLAUDE.md §2.3 沟通格式

【问 3】我亲自 grep / Read 了吗 / 还是凭印象？
   ❌ 凭印象说"CLAUDE.md 写过""那个 memory 里有""文件 X 行数应该是 Y"
   ✅ 涉及现有文件 / 规则 / 行数 / 字段 → 必先 Read / grep 实证 / 用 file:line 引用
   → 参考：CLAUDE.md §3.1 写代码前

⚠️ 还有 1 条铁律：被 Tim push back 时不要立刻"对我重写"——先苏格拉底追问 + 找 reference + 第一性原理分析为什么 fail。
</mental-check-before-response>
"""


def main() -> int:
    sys.stdout.write(INJECTION)
    return 0


if __name__ == "__main__":
    sys.exit(main())
