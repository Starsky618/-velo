"""区域来源赛段普查的内部数据库模型。

这些表只保存来源观测和普查完整性，不创建公开 ``segments``，也不让未经
人工审核的来源线参与活动匹配或排行榜。
"""

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base


class SegmentCensusBatch(Base):
    """一次固定范围、固定协议的两遍来源可见赛段普查。"""

    __tablename__ = "segment_census_batches"

    id = Column(String(64), primary_key=True)
    region_key = Column(String(64), nullable=False)
    region_version = Column(String(64), nullable=False)
    source_platform = Column(String(32), nullable=False)
    activity_type = Column(String(16), nullable=False)
    protocol_version = Column(String(64), nullable=False)
    visibility_context = Column(String(64), nullable=False)
    root_south = Column(Float, nullable=False)
    root_west = Column(Float, nullable=False)
    root_north = Column(Float, nullable=False)
    root_east = Column(Float, nullable=False)
    max_depth = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False)
    request_count = Column(Integer, nullable=False)
    unique_segment_count = Column(Integer, nullable=False)
    detail_complete_count = Column(Integer, nullable=False)
    geometry_complete_count = Column(Integer, nullable=False)
    leaderboard_complete_count = Column(Integer, nullable=False)
    saturated_cell_count = Column(Integer, nullable=False)
    error_count = Column(Integer, nullable=False)
    pass_summaries_json = Column(JSONB, nullable=False)
    pass_diff_json = Column(JSONB, nullable=False)
    raw_response_retained = Column(Boolean, nullable=False, server_default=false())
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("source_platform = 'strava'", name="ck_segment_census_batches_source"),
        CheckConstraint("activity_type = 'riding'", name="ck_segment_census_batches_activity"),
        CheckConstraint(
            "status IN ('source_visible_complete', 'indeterminate')",
            name="ck_segment_census_batches_status",
        ),
        CheckConstraint(
            "root_south < root_north AND root_west < root_east",
            name="ck_segment_census_batches_bounds",
        ),
        CheckConstraint(
            "max_depth >= 0 AND request_count >= 0 AND unique_segment_count >= 0 "
            "AND detail_complete_count >= 0 AND geometry_complete_count >= 0 "
            "AND leaderboard_complete_count >= 0 "
            "AND saturated_cell_count >= 0 AND error_count >= 0",
            name="ck_segment_census_batches_counts",
        ),
        CheckConstraint(
            "detail_complete_count <= unique_segment_count "
            "AND geometry_complete_count <= unique_segment_count "
            "AND leaderboard_complete_count <= unique_segment_count",
            name="ck_segment_census_batches_complete_counts",
        ),
        Index("idx_segment_census_batches_region_created", "region_key", "created_at"),
        Index("idx_segment_census_batches_status", "status"),
    )


class SegmentSourceObservation(Base):
    """某批普查在一个时间点看到的一条 Strava 赛段观测。"""

    __tablename__ = "segment_source_observations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    census_batch_id = Column(
        String(64),
        ForeignKey("segment_census_batches.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_platform = Column(String(32), nullable=False)
    source_segment_id = Column(String(64), nullable=False)
    source_url = Column(Text, nullable=False)
    source_name = Column(String(255), nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False)
    source_created_at = Column(DateTime(timezone=True), nullable=True)
    source_updated_at = Column(DateTime(timezone=True), nullable=True)
    activity_type = Column(String(16), nullable=False)
    city = Column(String(128), nullable=True)
    state = Column(String(128), nullable=True)
    country = Column(String(128), nullable=True)
    is_private = Column(Boolean, nullable=True)
    is_hazardous = Column(Boolean, nullable=True)
    climb_category = Column(Integer, nullable=True)
    distance_m = Column(Float, nullable=True)
    average_gradient_pct = Column(Float, nullable=True)
    maximum_gradient_pct = Column(Float, nullable=True)
    elevation_gain_m = Column(Float, nullable=True)
    elevation_high_m = Column(Float, nullable=True)
    elevation_low_m = Column(Float, nullable=True)
    athlete_count = Column(Integer, nullable=True)
    effort_count = Column(Integer, nullable=True)
    star_count = Column(Integer, nullable=True)
    kom_time_s = Column(Integer, nullable=True)
    qom_time_s = Column(Integer, nullable=True)
    overall_best_time_s = Column(Integer, nullable=True)
    start_lat = Column(Float, nullable=True)
    start_lon = Column(Float, nullable=True)
    end_lat = Column(Float, nullable=True)
    end_lon = Column(Float, nullable=True)
    source_line = Column(
        Geometry("LINESTRING", srid=4326, spatial_index=False),
        nullable=True,
    )
    geometry_point_count = Column(Integer, nullable=True)
    geometry_original_size = Column(Integer, nullable=True)
    geometry_resolution = Column(String(16), nullable=True)
    query_bounds_relation = Column(String(16), nullable=False)
    seen_passes_json = Column(JSONB, nullable=False)
    detail_status = Column(String(16), nullable=False)
    geometry_status = Column(String(16), nullable=False)
    leaderboard_status = Column(String(16), nullable=False)
    failure_json = Column(JSONB, nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("source_platform = 'strava'", name="ck_segment_source_obs_source"),
        CheckConstraint("activity_type = 'Ride'", name="ck_segment_source_obs_activity"),
        CheckConstraint(
            "detail_status IN ('complete', 'failed')",
            name="ck_segment_source_obs_detail_status",
        ),
        CheckConstraint(
            "geometry_status IN ('complete', 'failed')",
            name="ck_segment_source_obs_geometry_status",
        ),
        CheckConstraint(
            "leaderboard_status IN ('not_collected', 'partial', 'complete')",
            name="ck_segment_source_obs_leaderboard_status",
        ),
        CheckConstraint(
            "query_bounds_relation IN ('inside', 'crosses', 'outside', 'unknown')",
            name="ck_segment_source_obs_bounds_relation",
        ),
        CheckConstraint(
            "(detail_status = 'complete' AND distance_m > 0) OR detail_status = 'failed'",
            name="ck_segment_source_obs_detail_complete",
        ),
        CheckConstraint(
            "(geometry_status = 'complete' AND source_line IS NOT NULL "
            "AND geometry_point_count >= 2 "
            "AND geometry_original_size = geometry_point_count) "
            "OR (geometry_status = 'failed' AND source_line IS NULL)",
            name="ck_segment_source_obs_geometry_complete",
        ),
        CheckConstraint(
            "athlete_count IS NULL OR athlete_count >= 0",
            name="ck_segment_source_obs_athletes",
        ),
        CheckConstraint(
            "effort_count IS NULL OR effort_count >= 0",
            name="ck_segment_source_obs_efforts",
        ),
        CheckConstraint(
            "star_count IS NULL OR star_count >= 0",
            name="ck_segment_source_obs_stars",
        ),
        UniqueConstraint(
            "census_batch_id",
            "source_platform",
            "source_segment_id",
            name="uq_segment_source_obs_batch_source_id",
        ),
        Index(
            "idx_segment_source_obs_source_id",
            "source_platform",
            "source_segment_id",
            "observed_at",
        ),
        Index("idx_segment_source_obs_batch", "census_batch_id"),
        Index("idx_segment_source_obs_line", "source_line", postgresql_using="gist"),
    )
