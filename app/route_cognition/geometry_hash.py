"""路线认知几何指纹工具——给 segment 线条贴一张稳定的“身份证”。"""

from app.route_book.service import _line_hash as _route_book_line_hash


SEGMENT_GEOMETRY_NORMALIZATION_VERSION = "route_cognition_segment_geometry_v1"


def hash_segment_geometry_wkt(reference_line_wkt: str) -> str:
    """
    复用 route_book 的线条 hash 口径。

    这里不重新发明算法：route_book 已经用“去掉多余空白后 sha256”的方式判断路线线条是否一致。
    Batch 6 只是在 segment 白名单入口沿用同一套指纹算法，并用 normalization_version 标记本入口语义。
    """
    return _route_book_line_hash(reference_line_wkt)
