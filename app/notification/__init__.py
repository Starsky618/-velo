"""
通知模块——"广播室"。

这个模块负责在用户破 PR、拿 KOM 时生成通知，
在 KOM 被夺时提醒原持有者。

好比体育馆里的广播室：计时裁判（auto_match）登记完成绩后，
广播室拿到成绩单，判断有没有破纪录，然后广播给相关人。
广播室只读成绩单，不干预比赛。

操作注意事项：
- 这个模块和 segment 模块是单向依赖：notification 读 SegmentEffort，但 segment 不知道 notification 的存在
- detect_events() 是对外唯一写入接口，必须用 try/except + SAVEPOINT 隔离
- 不要在这个模块里 import segment/auto_match 或 segment/service（除了 get_effort_rank 共享函数）
"""
