"""
app/segment/exceptions.py

这个文件是"赛段错误分类仓库"。
把赛段操作中可能出错的情况各自贴上标签，调用方 catch 特定异常后能精准响应，
而不是统统 catch ValueError 再靠文字判断错误类型。

修改注意：
- 只在这里加赛段专属异常
- 不要把全局异常（如 DB 连接失败）放进来

输入/输出：
- 无数据输入输出，只定义异常类型
- 上游：service.py raise → 下游：router.py except → HTTP 响应码
"""


class SegmentOverlapError(Exception):
    """
    当新建赛段与已有赛段轨迹高度重叠时抛出。
    判断标准：ST_HausdorffDistance < 0.0005（约 50 米内）。
    类比：你想在已有一条赛道旁边 50 米内划一条新赛道，系统拒绝防止重复。
    """
    pass


class InvalidSegmentRangeError(Exception):
    """
    当赛段起止索引非法或赛段距离太短时抛出。
    涵盖：
    - start_index >= end_index（起点不早于终点）
    - 子序列轨迹点数 < 2（无法构成线段）
    - 计算出的距离 < 1000 米（太短无意义）
    类比：你用剪刀从一段绳子上剪，但剪出的那段太短或剪错方向——系统拒绝。
    """
    pass
