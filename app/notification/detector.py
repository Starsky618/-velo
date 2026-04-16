# app/notification/detector.py
"""
事件分类纯函数——"裁判的判定规则书"。

这个文件只做一件事：接收数字（排名、用时、是否 PR），返回判定结果。
不碰数据库，不碰文件系统，不碰网络。

好比裁判手里的规则手册：
- 排第 1 → 判定为 KOM
- 排第 1 且有前任 → 前任被夺
- 破了个人纪录 → 判定为 PR
- 其他情况 → 不播报

操作注意事项：
- 这是纯函数模块，绝对不能 import 任何项目模块（models、service 等）
- 修改判定逻辑后必须同步更新测试用例
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class EventResult:
    """
    检测结果——"裁判的判定书"。

    event_type: 'pr'（个人最佳）或 'kom'（赛段王）
    rank: 排名快照。PR 且排名 > 10 时为 None（前端只显示"新 PR"）
    """
    event_type: str
    rank: int | None


@dataclass(frozen=True)
class KomLostResult:
    """
    KOM 被夺事件——"通知原冠军的罚单"。

    previous_holder_user_id: 被夺者的用户 ID
    new_rank: 被夺者现在排第几（通常为 2）
    """
    previous_holder_user_id: int
    new_rank: int


def classify(
    elapsed_time: int,
    rank: int,
    is_pr: bool,
    previous_kom_user_id: int | None,
    current_user_id: int,
) -> tuple[EventResult | None, KomLostResult | None]:
    """
    根据排名和 PR 状态，判定应生成哪些事件。

    参数：
        elapsed_time: 成绩用时（秒，整数）
        rank: 当前排名（1 = 最快）
        is_pr: 是否为该用户在该赛段的个人最佳
        previous_kom_user_id: 原 KOM 持有者 user_id（无人时为 None）
        current_user_id: 当前骑手 user_id

    返回：
        (EventResult | None, KomLostResult | None)
        - 第一个元素：当前骑手的事件（KOM 或 PR），不是 PR 时为 None
        - 第二个元素：被夺者的事件，仅在夺走别人 KOM 时非 None

    判定优先级：KOM > PR。拿了 KOM 就不再生成 PR 通知（KOM 本身就是最好的 PR）。
    不是 PR 的成绩不生成任何通知。
    """
    # 不是 PR → 不生成通知（即使排名靠前，旧成绩更好，不值得通知）
    if not is_pr:
        return None, None

    # ---- KOM（排第 1）----
    if rank == 1:
        event = EventResult(event_type="kom", rank=1)

        # 检查是否夺走了别人的 KOM
        if (previous_kom_user_id is not None
                and previous_kom_user_id != current_user_id):
            lost = KomLostResult(
                previous_holder_user_id=previous_kom_user_id,
                new_rank=2,
            )
            return event, lost

        # 无前任（第一条成绩）或自己打破自己的 KOM
        return event, None

    # ---- PR（排名 2+）----
    # 排名 ≤ 10 时返回具体排名，> 10 时返回 None
    display_rank = rank if rank <= 10 else None
    event = EventResult(event_type="pr", rank=display_rank)
    return event, None
