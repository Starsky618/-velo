"""
北京时间小工具——全项目共享的"北京挂钟"。

干啥用：把数据库里的 UTC 时间换算成北京日历上的日期。约骑关联要判断
"这趟骑行是不是约骑当天骑的"，必须按北京时间切日，不能按 UTC 切，否则
晚上 8 点后的骑行容易被放进错误的日历格子。
操作注意事项：training/service.py 与 notification/progress_detector.py 还各有一份
旧的 _BJ_TZ 定义（存量豁免，已记 docs/tech-debt.md），新代码一律 import 本模块。
输入/输出：进 datetime（aware 或 naive），出北京日历 date；naive 按 UTC 语义补齐。
"""

from datetime import date, datetime, timedelta, timezone

# 北京时区 = UTC+8。
# 可以把它想成墙上的"北京钟"：不管数据库时间来自哪里，
# 判断日历日期前先把指针拨到这面钟上。
BJ_TZ = timezone(timedelta(hours=8))


def to_bj_date(dt: datetime) -> date:
    """把一个时间点换算成北京日历上的日期。

    naive（不带时区）输入按 UTC 处理：生产 PostgreSQL 字段是 timezone=True，
    读出来通常自带时区；SQLite 测试库有时会把时区信息抹掉，但语义仍是 UTC。
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BJ_TZ).date()
