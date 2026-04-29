"""
通用工具层——"水电气这种基础设施"。

这一层放任何业务模块都可能用到的小工具：地理坐标、日期处理、字符串规范化等。
特点是"不知道也不关心业务"——它只做小而通用的活，由各业务模块按需调用。

模块依赖方向（CLAUDE.md "单向依赖" 强化版）：
    user ← activity ← segment ← notification ← strava
                                                ↑
                                            common 在所有业务模块下方

common 可以被任意业务模块依赖，但 common 自己不依赖任何业务模块——
否则就是循环依赖（用户模块要用 common.geo，common.geo 又反过来 import 用户模块就乱了）。

操作注意事项：
- 在 common 下新加文件时，禁止 import app.user / app.activity / app.segment 等业务模块
- 如果某个工具发现自己离不开业务对象（比如要传 User 实例），说明它不该住 common，
  应该挪回业务模块自己的 utils 文件
"""
