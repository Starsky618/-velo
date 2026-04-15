"""
翻译层模块——"国际翻译中心"。

这个模块负责把各种来源的骑行数据（GPX 文件、FIT 文件、Strava API）
翻译成统一的内部格式（ParseResult），就像一个翻译中心有多个翻译官，
不管收到的是英文、日文还是法文，最终都输出标准中文文档。

模块内文件一览：
- types.py：定义"标准文档模板"（Trackpoint、ParseResult 等数据结构）
- geo_math.py：地理计算工具（距离、爬升、速度），相当于"尺子和量角器"
- stats_calculator.py：统计计算器（从轨迹点算摘要），相当于"成绩单计算器"
- gpx_parser.py：GPX 翻译官（从 activity/ 搬过来并升级）
- fit_parser.py：FIT 翻译官（新增，解析码表二进制文件）
- strava_adapter.py：Strava 翻译官（新增，第 2 期实现）
- coord_normalizer.py：坐标纠偏仪（GCJ-02 火星坐标 → WGS84 标准坐标）

注意事项：
- 所有解析器之间互不 import，坏一个不影响其他
- 数据流单向：types ← 解析器们 ← coord_normalizer ← Worker
- 这个模块是纯计算层，不碰数据库、不碰文件系统
"""
