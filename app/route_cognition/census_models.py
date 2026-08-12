"""区域来源赛段普查的内部数据库模型。

这些表只保存来源观测和普查完整性，不创建公开 ``segments``，也不让未经
人工审核的来源线参与活动匹配或排行榜。
"""

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
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
    region_definition_json = Column(JSONB, nullable=False)
    region_polygon = Column(
        Geometry("POLYGON", srid=4326, spatial_index=False),
        nullable=False,
    )
    root_south = Column(Float, nullable=False)
    root_west = Column(Float, nullable=False)
    root_north = Column(Float, nullable=False)
    root_east = Column(Float, nullable=False)
    max_depth = Column(Integer, nullable=False)
    run_status = Column(String(32), nullable=False)
    enumeration_status = Column(String(32), nullable=False)
    request_status = Column(String(16), nullable=False)
    snapshot_status = Column(String(16), nullable=False)
    detail_status = Column(String(16), nullable=False)
    geometry_status = Column(String(16), nullable=False)
    leaderboard_status = Column(String(16), nullable=False)
    planned_request_count = Column(Integer, nullable=False)
    attempted_request_count = Column(Integer, nullable=False)
    succeeded_request_count = Column(Integer, nullable=False)
    failed_request_count = Column(Integer, nullable=False)
    blocked_request_count = Column(Integer, nullable=False)
    unique_segment_count = Column(Integer, nullable=False)
    included_segment_count = Column(Integer, nullable=False)
    outside_segment_count = Column(Integer, nullable=False)
    unknown_membership_count = Column(Integer, nullable=False)
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
            "run_status IN ('completed', 'completed_with_errors')",
            name="ck_segment_census_batches_run_status",
        ),
        CheckConstraint(
            "enumeration_status IN ('source_visible_complete', 'indeterminate')",
            name="ck_segment_census_batches_enumeration_status",
        ),
        CheckConstraint(
            "request_status IN ('complete', 'incomplete') "
            "AND snapshot_status IN ('complete', 'partial', 'failed') "
            "AND detail_status IN ('not_collected', 'complete', 'partial', 'failed') "
            "AND geometry_status IN ('not_collected', 'complete', 'partial', 'failed') "
            "AND leaderboard_status IN ('not_collected', 'partial', 'complete')",
            name="ck_segment_census_batches_axis_statuses",
        ),
        CheckConstraint(
            "root_south < root_north AND root_west < root_east",
            name="ck_segment_census_batches_bounds",
        ),
        CheckConstraint(
            "ST_IsValid(region_polygon)",
            name="ck_segment_census_batches_polygon_valid",
        ),
        CheckConstraint(
            "max_depth >= 0 AND planned_request_count >= 0 "
            "AND attempted_request_count >= 0 AND succeeded_request_count >= 0 "
            "AND failed_request_count >= 0 AND blocked_request_count >= 0 "
            "AND unique_segment_count >= 0 "
            "AND included_segment_count >= 0 AND outside_segment_count >= 0 "
            "AND unknown_membership_count >= 0 "
            "AND detail_complete_count >= 0 AND geometry_complete_count >= 0 "
            "AND leaderboard_complete_count >= 0 "
            "AND saturated_cell_count >= 0 AND error_count >= 0",
            name="ck_segment_census_batches_counts",
        ),
        CheckConstraint(
            "succeeded_request_count + failed_request_count + blocked_request_count "
            "= planned_request_count",
            name="ck_segment_census_batches_request_accounting",
        ),
        CheckConstraint(
            "(request_status = 'complete' AND failed_request_count = 0 "
            "AND blocked_request_count = 0) OR "
            "(request_status = 'incomplete' AND "
            "(failed_request_count > 0 OR blocked_request_count > 0))",
            name="ck_segment_census_batches_request_status",
        ),
        CheckConstraint(
            "included_segment_count + outside_segment_count + unknown_membership_count "
            "= unique_segment_count",
            name="ck_segment_census_batches_membership_counts",
        ),
        CheckConstraint(
            "detail_complete_count <= unique_segment_count "
            "AND geometry_complete_count <= unique_segment_count "
            "AND leaderboard_complete_count <= unique_segment_count",
            name="ck_segment_census_batches_complete_counts",
        ),
        Index("idx_segment_census_batches_region_created", "region_key", "created_at"),
        Index("idx_segment_census_batches_status", "run_status", "enumeration_status"),
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
    region_membership = Column(String(16), nullable=False)
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
            "region_membership IN ('inside', 'crosses', 'outside', 'unknown')",
            name="ck_segment_source_obs_region_membership",
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
        UniqueConstraint(
            "id",
            "census_batch_id",
            "source_segment_id",
            name="uq_segment_source_obs_id_batch_source_id",
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


class SegmentElevationFactBatch(Base):
    """对一个冻结普查批次逐条生成的不可变 GLO-30 事实批次。"""

    __tablename__ = "segment_elevation_fact_batches"

    id = Column(String(64), primary_key=True)
    census_batch_id = Column(
        String(64),
        ForeignKey("segment_census_batches.id", ondelete="RESTRICT"),
        nullable=False,
    )
    scope = Column(String(32), nullable=False)
    algorithm_version = Column(String(64), nullable=False)
    geometry_normalization_version = Column(String(64), nullable=False)
    attempt_number = Column(Integer, nullable=False)
    input_observation_set_hash = Column(String(64), nullable=False)
    run_status = Column(String(32), nullable=False)
    input_observation_count = Column(Integer, nullable=False)
    eligible_geometry_count = Column(Integer, nullable=False)
    source_incomplete_count = Column(Integer, nullable=False)
    source_incomplete_json = Column(JSONB, nullable=False)
    complete_count = Column(Integer, nullable=False)
    failed_count = Column(Integer, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "scope = 'inside_or_crosses'",
            name="ck_segment_elev_fact_batch_scope",
        ),
        CheckConstraint(
            "run_status IN ('completed', 'completed_with_failures')",
            name="ck_segment_elev_fact_batch_status",
        ),
        CheckConstraint(
            "attempt_number >= 1 AND input_observation_count > 0 "
            "AND eligible_geometry_count >= 0 "
            "AND source_incomplete_count >= 0 AND complete_count >= 0 "
            "AND failed_count >= 0",
            name="ck_segment_elev_fact_batch_counts",
        ),
        CheckConstraint(
            "input_observation_set_hash ~ '^[0-9a-f]{64}$'",
            name="ck_segment_elev_fact_batch_input_hash",
        ),
        CheckConstraint(
            "eligible_geometry_count + source_incomplete_count = input_observation_count "
            "AND complete_count + failed_count = eligible_geometry_count",
            name="ck_segment_elev_fact_batch_accounting",
        ),
        CheckConstraint(
            "(run_status = 'completed' AND source_incomplete_count = 0 AND failed_count = 0) "
            "OR (run_status = 'completed_with_failures' "
            "AND (source_incomplete_count > 0 OR failed_count > 0))",
            name="ck_segment_elev_fact_batch_outcome",
        ),
        UniqueConstraint(
            "id",
            "census_batch_id",
            "algorithm_version",
            "geometry_normalization_version",
            name="uq_segment_elev_fact_batch_identity",
        ),
        UniqueConstraint(
            "census_batch_id",
            "algorithm_version",
            "geometry_normalization_version",
            "scope",
            "attempt_number",
            name="uq_segment_elev_fact_batch_attempt",
        ),
        Index("idx_segment_elev_fact_batch_census", "census_batch_id"),
    )


class SegmentElevationFact(Base):
    """一条来源线在固定 hash 和算法版本上的 GLO-30 派生事实。"""

    __tablename__ = "segment_elevation_facts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    fact_batch_id = Column(String(64), nullable=False)
    census_batch_id = Column(String(64), nullable=False)
    source_observation_id = Column(Integer, nullable=False)
    source_segment_id = Column(String(64), nullable=False)
    source_geometry_hash = Column(String(64), nullable=False)
    geometry_normalization_version = Column(String(64), nullable=False)
    algorithm_version = Column(String(64), nullable=False)
    fact_status = Column(String(16), nullable=False)
    method_metadata_json = Column(JSONB, nullable=False)
    # 这些列参与 SQL ``IS NULL`` 约束；JSON literal null 不是 SQL NULL。
    elevation_snapshot_json = Column(JSONB(none_as_null=True), nullable=True)
    elevation_profile_json = Column(JSONB(none_as_null=True), nullable=True)
    source_point_count = Column(Integer, nullable=False)
    elevation_point_count = Column(Integer, nullable=True)
    derived_distance_m = Column(Float, nullable=True)
    climb_m = Column(Float, nullable=True)
    descent_m = Column(Float, nullable=True)
    start_elevation_m = Column(Float, nullable=True)
    end_elevation_m = Column(Float, nullable=True)
    minimum_elevation_m = Column(Float, nullable=True)
    maximum_elevation_m = Column(Float, nullable=True)
    net_elevation_change_m = Column(Float, nullable=True)
    average_gradient_pct = Column(Float, nullable=True)
    maximum_gradient_pct = Column(Float, nullable=True)
    maximum_gradient_window_m = Column(Float, nullable=True)
    source_distance_difference_pct = Column(Float, nullable=True)
    quality_flags_json = Column(JSONB, nullable=False)
    failure_json = Column(JSONB(none_as_null=True), nullable=True)
    computed_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            [
                "fact_batch_id",
                "census_batch_id",
                "algorithm_version",
                "geometry_normalization_version",
            ],
            [
                "segment_elevation_fact_batches.id",
                "segment_elevation_fact_batches.census_batch_id",
                "segment_elevation_fact_batches.algorithm_version",
                "segment_elevation_fact_batches.geometry_normalization_version",
            ],
            ondelete="RESTRICT",
            name="fk_segment_elev_fact_batch_census",
        ),
        ForeignKeyConstraint(
            ["source_observation_id", "census_batch_id", "source_segment_id"],
            [
                "segment_source_observations.id",
                "segment_source_observations.census_batch_id",
                "segment_source_observations.source_segment_id",
            ],
            ondelete="RESTRICT",
            name="fk_segment_elev_fact_source_observation",
        ),
        CheckConstraint(
            "fact_status IN ('complete', 'failed')",
            name="ck_segment_elev_fact_status",
        ),
        CheckConstraint(
            "source_point_count >= 2 AND "
            "(elevation_point_count IS NULL OR elevation_point_count >= 2)",
            name="ck_segment_elev_fact_point_counts",
        ),
        CheckConstraint(
            "source_distance_difference_pct IS NULL OR source_distance_difference_pct >= 0",
            name="ck_segment_elev_fact_distance_diff",
        ),
        CheckConstraint(
            "source_geometry_hash ~ '^[0-9a-f]{64}$'",
            name="ck_segment_elev_fact_geometry_hash",
        ),
        CheckConstraint(
            "(fact_status = 'complete' AND elevation_snapshot_json IS NOT NULL "
            "AND elevation_profile_json IS NOT NULL "
            "AND elevation_point_count = source_point_count "
            "AND derived_distance_m > 0 AND climb_m >= 0 AND descent_m >= 0 "
            "AND start_elevation_m IS NOT NULL AND end_elevation_m IS NOT NULL "
            "AND minimum_elevation_m IS NOT NULL AND maximum_elevation_m IS NOT NULL "
            "AND net_elevation_change_m IS NOT NULL AND average_gradient_pct IS NOT NULL "
            "AND maximum_gradient_pct IS NOT NULL AND maximum_gradient_window_m > 0 "
            "AND failure_json IS NULL) OR "
            "(fact_status = 'failed' AND elevation_snapshot_json IS NULL "
            "AND elevation_profile_json IS NULL AND elevation_point_count IS NULL "
            "AND derived_distance_m IS NULL AND climb_m IS NULL AND descent_m IS NULL "
            "AND start_elevation_m IS NULL AND end_elevation_m IS NULL "
            "AND minimum_elevation_m IS NULL AND maximum_elevation_m IS NULL "
            "AND net_elevation_change_m IS NULL AND average_gradient_pct IS NULL "
            "AND maximum_gradient_pct IS NULL AND maximum_gradient_window_m IS NULL "
            "AND failure_json IS NOT NULL)",
            name="ck_segment_elev_fact_payload",
        ),
        UniqueConstraint(
            "fact_batch_id",
            "source_observation_id",
            name="uq_segment_elev_fact_batch_observation",
        ),
        Index("idx_segment_elev_fact_batch", "fact_batch_id"),
        Index("idx_segment_elev_fact_source", "source_segment_id"),
        Index("idx_segment_elev_fact_geometry_hash", "source_geometry_hash"),
    )
