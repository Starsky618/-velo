"""
NPC 文案后置过滤（task-3 实施）。

干啥用：
- 防漂移最后一道闸：选中模板后跑反 pattern 检测 / 长度检测 / emoji 检测
- 命中宪法 § 3 任一反例 → reject → service 返 None 不展示
- 即便 seed 模板字面正确 / 未来 LLM 生成 / 人工编辑 / 仍有可能跑偏

类比：菜上桌前的最后一道质检——
- 看汤里有没有头发（emoji）
- 尝盐放多了没（客服腔）
- 称份量够不够（字数 5-25）

操作注意：
- 纯函数 / 不查 DB / 不 import 业务 service
- ANTI_PATTERN_KEYWORDS = 宪法 § 3 全 9 类反例关键词（详见 plan）
- 命中任一关键词 / emoji / 长度越界 = 整条文案 reject（不"修正" / 直接弃用）

输入输出：
- 入：渲染后的 str
- 出：bool（is_safe = True 放行 / False reject）

参考：docs/agent-rules/persona-constitution.md § 3（反例禁区 9 类）+ § 2.5 字数标尺
"""

import re


# ─── 宪法 § 3 反例关键词清单（9 类全覆盖）───


ANTI_PATTERN_KEYWORDS: tuple[str, ...] = (
    # § 3.1 开场禁区（"亲" + "亲爱的" 是两个独立关键词 / Claude A 抓 / 漏 "亲" 让 "亲~最近怎么没看到你呀~" 漏 filter）
    "恭喜你", "您", "亲", "亲爱的", "哥哥", "小可爱", "小老弟",
    # § 3.2 套娃数学
    "相当于", "等于", "等同于", "绕地球", "次珠峰", "根香蕉",
    # § 3.3 表演式鼓励
    "棒棒哒", "真厉害", "太牛了", "加油",
    "突破自我", "创造奇迹", "永不放弃",
    "Keep going", "Stay strong",
    # § 3.4 客服腔
    "您还没有", "请检查", "感谢您", "建议您", "适度休息",
    # § 3.5 笑场字面（emoji 由独立 regex 检查）
    "哈哈哈",
    # § 3.6 结构化表达
    "首先", "其次", "最后",
    # § 3.7 破圈梗（污染骑行圈语境）
    "yyds", "绝绝子", "蚌埠住了", "泰裤辣",
    "不是吧不是吧", "我直接好家伙",
    "doge", "狗头保命",
    # § 3.8 中年油腻
    "哎呦不错哦", "牛批",
    # § 3.9 拙劣模仿英式（解释笑点 = 死）
    "我觉得", "我严重怀疑",
)


# ─── emoji / 颜文字 / 装饰符 regex ───


_EMOJI_PATTERN = re.compile(
    # emoji unicode 主要范围（Codex 第三轮补 1FA00-1FA9F 新 emoji 段 / 🫠 🪿 等 + FE0F variation selector）
    r"[\U0001F300-\U0001F9FF\U0001F600-\U0001F64F\U0001FA00-\U0001FA9F️☀-➿]|"
    # 装饰符（波浪号 / 中括号装饰）
    r"~~|【|】|"
    # ASCII 颜文字（含 :-) :-( :-D :-P 中划线 variant / Codex 抓）
    r":-?\)|:-?\(|:-?D|:-?P|;-?\)|\^_\^|\^\.\^|T_T|>_<|orz|=口="
)


def _contains_emoji(text: str) -> bool:
    """检测文本是否含 emoji / 颜文字 / 装饰符（§ 3.5 / 字面关键词无法穷举）。"""
    return bool(_EMOJI_PATTERN.search(text))


# ─── 公开检查函数 ───


def check_anti_pattern(text: str) -> bool:
    """命中宪法 § 3 任一反例关键词 / emoji → True（应 reject）。

    返 True = 危险 / 应该 reject。
    返 False = 安全 / 可以放行。

    （注意：本函数语义是"命中反例 = True" / 调用方 is_safe() 取反）
    """
    for keyword in ANTI_PATTERN_KEYWORDS:
        if keyword in text:
            return True
    if _contains_emoji(text):
        return True
    return False


def check_length(text: str) -> bool:
    """5 ≤ Unicode codepoint 长度 ≤ 25 → True（合格）/ 否则 False（reject）。

    宪法 § 2.5 字数标尺：
    - < 5 字 = AI 极简味（暴露身份）→ reject
    - 5-25 字 = 真人甜区 + 高密度上限
    - > 25 字 = 稀释味 → reject

    用 len(text) 是 Python 字符串 Unicode codepoint 长度（中文 1 字 = 1 codepoint）。
    """
    return 5 <= len(text) <= 25


def is_safe(text: str) -> bool:
    """组合检查 / 通过所有 filter → True（放行）。

    顺序：长度 → 反例关键词 → emoji（任一 fail 返 False）。
    """
    if not check_length(text):
        return False
    if check_anti_pattern(text):
        return False
    return True
