"""
翻译层统一数据结构——"标准文档模板"。

所有数据来源（GPX、FIT、Strava）解析后都必须变成这里定义的格式，
就像不管你写的是英文报告还是日文报告，翻译完都要按同一个模板装订。

下游模块（Worker、数据库写入、赛段匹配）只认这套格式，
不关心数据原来是什么样子、从哪里来的。

模块内定义了 6 个东西：
1. CoordSystem（枚举）：坐标系标签，标记数据用的是 GPS 标准坐标还是中国火星坐标
2. DataSource（枚举）：数据来源标签，标记数据是从 GPX/FIT/Strava 哪个渠道来的
3. Trackpoint（数据类）：单个轨迹点，骑行数据的最小单元
4. ActivitySummary（数据类）：活动统计摘要，一次骑行的"成绩单"
5. ParseMetadata（数据类）：解析元数据，记录数据的"出生证明"
6. ParseResult（数据类）：解析器的统一输出，把上面几个打包成一个"文件袋"

注意事项：
- 所有数据类都是 frozen（不可变），创建后不能修改任何字段
- Trackpoint 额外加了 slots，50000 个点能省约 14MB 内存
- 速度单位统一 m/s（不是 km/h），API 层输出时再 ×3.6 转换
- 距离单位统一米（m），API 层输出时再 ÷1000 转公里
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol


# ==================== 枚举类型 ====================


class CoordSystem(Enum):
    """
    坐标系枚举——标记数据用的是哪套"地图语言"。

    WGS84：GPS 卫星的原生坐标系，全球通用，所有码表硬件都输出这个。
    GCJ02：中国特有的"火星坐标"，在 WGS84 基础上做了随机偏移（100-600 米），
           国内手机 App（行者、Keep、咕咚）导出的数据可能是这个坐标系。
    """
    WGS84 = "wgs84"
    GCJ02 = "gcj02"


class DataSource(Enum):
    """
    数据来源枚举——标记数据是从哪个渠道进来的。

    好比快递包裹上的发件渠道：顺丰、京东、邮政，
    收件人不关心用的哪家快递，但仓库需要知道以便分拣处理。
    """
    GPX = "gpx"
    FIT = "fit"
    STRAVA = "strava"


# ==================== 核心数据结构 ====================


@dataclass(frozen=True, slots=True)
class Trackpoint:
    """
    统一轨迹点——骑行数据的最小单元。

    好比心电图上的一个采样点：记录了某一瞬间你在哪、骑多快、心跳多少。
    所有数据源（GPX/FIT/Strava）解析后都变成这个格式，
    下游模块只认这一种"货币"，不关心它原来是什么"外币"。

    frozen=True：创建后不可修改，防止下游模块意外篡改解析结果。
           好比打印出来的考试成绩单，只能看不能改。
    slots=True：内存优化，Python 默认用字典存对象属性（灵活但占内存），
           slots 改用固定数组存（省空间），50000 个点能省约 14MB。
    """
    seq: int                        # 序号（0 开始，按时间顺序递增）
    lat: float                      # 纬度（度，WGS84）
    lon: float                      # 经度（度，WGS84）
    ele: float | None               # 海拔（米），GPS 可能无高程数据
    time: datetime | None           # UTC 时间戳，极少数文件可能无时间
    hr: int | None                  # 心率（bpm），无心率传感器为 None
    cad: int | None                 # 踏频（rpm），无踏频传感器为 None
    power: int | None               # 功率（W），无功率计为 None
    speed: float | None             # 速度（m/s），GPX 需计算，FIT/Strava 直接提供
    distance: float | None          # 累计距离（米），GPX 需计算，FIT/Strava 直接提供
    # ---- 以下字段仅预留定义，本期不实现 ----
    # temperature: int | None       # 温度（°C）
    # grade: float | None           # 坡度（%）


@dataclass(frozen=True)
class ActivitySummary:
    """
    活动统计摘要——一次骑行的"成绩单"。

    FIT 和 Strava 数据源自带这些数据（设备端或服务端已经算好，精度更高）。
    GPX 没有摘要，需要由 stats_calculator 从 trackpoints 逐点计算得出。

    好比考试成绩：有的学校直接发成绩单（FIT/Strava），
    有的学校只给你原始答题卡，需要自己数对了几题（GPX）。
    """
    distance: float                 # 总距离（米）
    duration: int | None            # 总时间（秒），无时间戳时为 None
    elevation_gain: float           # 总爬升（米）
    avg_speed: float | None         # 平均速度（m/s）
    max_speed: float | None         # 最大速度（m/s）
    avg_power: float | None         # 平均功率（W）
    max_power: int | None           # 最大功率（W）
    avg_hr: float | None            # 平均心率（bpm）
    max_hr: int | None              # 最大心率（bpm）
    avg_cadence: float | None       # 平均踏频（rpm）
    calories: float | None          # 估算卡路里（kcal）
    started_at: datetime | None     # 骑行开始时间（UTC）
    finished_at: datetime | None    # 骑行结束时间（UTC）
    splits: list[dict] | None       # 每 10km 分段统计
    normalized_power: int | None    # 标准化功率（NP），FIT 自带，GPX 无法算


@dataclass(frozen=True)
class ParseMetadata:
    """
    解析元数据——数据的"出生证明"。

    记录这份数据从哪来、什么格式、什么坐标系。
    CoordNormalizer 会读这个信息来判断是否需要做坐标转换。

    好比进口商品上的原产地标签：
    产地（source）、语言（coord_system）、品牌（creator）、条形码（file_hash）。
    """
    source: DataSource              # 数据来源（GPX / FIT / Strava）
    coord_system: CoordSystem       # 坐标系（WGS84 / GCJ02）
    title: str | None               # 活动标题（GPX 的 track name / Strava 的 activity name）
    creator: str | None             # 生成软件/设备（GPX 的 <creator> / FIT 的 manufacturer）
    file_hash: str | None           # 文件 SHA-256 哈希（去重用，Strava 导入为 None）


@dataclass(frozen=True)
class ParseResult:
    """
    解析器的统一输出——"翻译完成的标准文件袋"。

    不管原始数据是 GPX、FIT 还是 Strava Streams，
    解析后都变成这一个格式。Worker 只认这个格式，不关心数据从哪来。

    好比出版社收到的终稿：不管作者是手写的、打字的还是语音转录的，
    编辑拿到手的都是同一个排版格式的文档。
    """
    trackpoints: list[Trackpoint]           # 轨迹点列表（按时间排序）
    summary: ActivitySummary                # 统计摘要（成绩单）
    metadata: ParseMetadata                 # 元数据（出生证明）
    simplified_track: list[dict] | None     # Douglas-Peucker 简化轨迹（前端地图用）
    power_zones: list[dict] | None          # 功率区间分布（需要 user.ftp，可能为 None）


# ==================== 解析器接口契约 ====================


class RideParser(Protocol):
    """
    解析器接口——所有解析器必须实现的方法签名。

    用 Protocol（鸭子类型）而不是继承：
    三个解析器文件之间零依赖，互不 import，只要各自实现了 parse() 方法，
    就自动满足这个接口，不需要写 "class GPXParser(RideParser)"。

    好比餐厅的出餐标准：不管你是川菜师傅还是粤菜师傅，
    上菜时都得用同一规格的盘子（ParseResult），但做菜过程互不干涉。
    """

    def parse(self, content: bytes, **kwargs) -> ParseResult:
        """
        解析原始数据，返回统一格式的 ParseResult。

        参数：
            content: 原始文件字节流（GPX 的 XML / FIT 的二进制）
            **kwargs: 额外参数（如 weight 用于卡路里估算）

        返回：
            ParseResult — 统一格式的解析结果
        """
        ...
