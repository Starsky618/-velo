"""
赛段海拔查询旧入口——保留这扇门，但门后已经接到公共海拔工厂。

操作注意事项：新代码不要再把海拔查询逻辑写在 segment 目录；这里存在只是为了让旧的
赛段创建、重算脚本和测试不需要一次性大搬家。

输入输出：对外仍提供 query_elevations / DEMServiceError，实际实现来自 app.elevation。
"""

from app.elevation.dem_client import DEMServiceError, query_elevations


__all__ = ["DEMServiceError", "query_elevations"]
