# tests/test_notification.py
"""
通知模块测试。

测试分三层：
1. 纯函数测试（detector.classify）—— 不需要数据库
2. Service 测试（detect_events、get_notifications 等）—— 需要数据库
3. API 测试（router）—— 需要 TestClient
"""
from app.notification.detector import classify, EventResult, KomLostResult


# ===================== 纯函数测试 =====================

def test_classify_first_effort_is_pr_and_kom():
    """赛段第一条成绩：既是 PR 又是 KOM，无被夺者"""
    event, lost = classify(
        elapsed_time=300,
        rank=1,
        is_pr=True,
        previous_kom_user_id=None,
        current_user_id=1,
    )
    assert event is not None
    assert event.event_type == "kom"
    assert event.rank == 1
    assert lost is None


def test_classify_new_kom_dethrones_previous():
    """夺走别人的 KOM：生成 KOM + KOM 被夺"""
    event, lost = classify(
        elapsed_time=280,
        rank=1,
        is_pr=True,
        previous_kom_user_id=5,
        current_user_id=1,
    )
    assert event is not None
    assert event.event_type == "kom"
    assert event.rank == 1
    assert lost is not None
    assert lost.previous_holder_user_id == 5
    assert lost.new_rank == 2


def test_classify_self_dethrone_no_lost():
    """自己打破自己的 KOM：只生成 KOM，不生成被夺"""
    event, lost = classify(
        elapsed_time=250,
        rank=1,
        is_pr=True,
        previous_kom_user_id=1,
        current_user_id=1,
    )
    assert event is not None
    assert event.event_type == "kom"
    assert lost is None


def test_classify_pr_top10():
    """破 PR 且进前 10：通知带排名"""
    event, lost = classify(
        elapsed_time=320,
        rank=5,
        is_pr=True,
        previous_kom_user_id=None,
        current_user_id=2,
    )
    assert event is not None
    assert event.event_type == "pr"
    assert event.rank == 5
    assert lost is None


def test_classify_pr_outside_top10():
    """破 PR 但排名 > 10：通知不带排名"""
    event, lost = classify(
        elapsed_time=500,
        rank=15,
        is_pr=True,
        previous_kom_user_id=None,
        current_user_id=3,
    )
    assert event is not None
    assert event.event_type == "pr"
    assert event.rank is None
    assert lost is None


def test_classify_not_pr():
    """不是 PR：不生成通知"""
    event, lost = classify(
        elapsed_time=600,
        rank=20,
        is_pr=False,
        previous_kom_user_id=None,
        current_user_id=4,
    )
    assert event is None
    assert lost is None


def test_classify_tied_first_but_not_pr():
    """并列情况下 rank=1 但不是 PR（理论上不会发生，但防御）"""
    event, lost = classify(
        elapsed_time=300,
        rank=1,
        is_pr=False,
        previous_kom_user_id=None,
        current_user_id=5,
    )
    # rank==1 但不是 PR 意味着这个用户之前有更好的成绩
    # 这种情况不应该生成通知
    assert event is None
    assert lost is None
