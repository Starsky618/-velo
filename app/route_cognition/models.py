"""
路线认知台账模型——给路线判断建立一间“审稿室”。

这个文件登记判断、证据、外部研究问题，以及正式 segment 进入路线认知系统前的几何来源门禁：
像论文审稿记录一样，说明某个结论是谁在什么时候、依据哪些材料做出的。操作注意事项：
这里不是路线正文编辑器，不能直接改 `route_guides.content_md`，也不能给旧 segment 伪造来源；
证据默认只在内部流转，用户展示必须走未来的受控接口。输入输出：judgment/research/review 服务写入
这些表，后续人工审核和内容导入只读取结构化摘要与来源编号。
"""

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import false, func

from app.database import Base


class JudgmentRun(Base):
    """判断运行表——记录一次算法、agent 或人工审查的判断过程摘要。"""

    __tablename__ = "judgment_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_type = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False)
    trigger_type = Column(String(64), nullable=False)
    route_book_id = Column(Integer, ForeignKey("route_books.id", ondelete="SET NULL"), nullable=True)
    route_version_id = Column(Integer, ForeignKey("route_versions.id", ondelete="SET NULL"), nullable=True)
    segment_id = Column(Integer, ForeignKey("segments.id", ondelete="SET NULL"), nullable=True)
    engine_name = Column(String(64), nullable=True)
    engine_version = Column(String(64), nullable=True)
    model_name = Column(String(64), nullable=True)
    model_version = Column(String(64), nullable=True)
    code_version = Column(String(64), nullable=True)
    params_json = Column(JSONB, nullable=True)
    input_hash = Column(String(64), nullable=True)
    confidence = Column(Numeric(5, 4), nullable=True)
    confidence_method = Column(String(64), nullable=True)
    confidence_state = Column(String(32), nullable=False)
    result_summary_json = Column(JSONB, nullable=True)
    missing_data_json = Column(JSONB, nullable=True)
    contradiction_json = Column(JSONB, nullable=True)
    defensive_silence_recommended = Column(Boolean, nullable=False, server_default=false())
    parent_run_id = Column(Integer, ForeignKey("judgment_runs.id", ondelete="SET NULL"), nullable=True)
    challenged_run_id = Column(Integer, ForeignKey("judgment_runs.id", ondelete="SET NULL"), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_service = Column(String(64), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["route_version_id", "route_book_id"],
            ["route_versions.id", "route_versions.route_book_id"],
            name="fk_judgment_runs_route_version_book",
        ),
        CheckConstraint(
            "run_type IN ('spatial_algorithm', 'semantic_agent', 'adversarial_agent', "
            "'human_review', 'research_synthesis', 'hybrid')",
            name="ck_judgment_runs_run_type",
        ),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'cancelled')",
            name="ck_judgment_runs_status",
        ),
        CheckConstraint(
            "confidence_state IN ('raw', 'proposed', 'challenged', 'stable', "
            "'human_accepted', 'stale', 'inconclusive')",
            name="ck_judgment_runs_confidence_state",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_judgment_runs_confidence_range",
        ),
        Index("idx_judgment_runs_type_created", "run_type", "created_at"),
        Index("idx_judgment_runs_status_created", "status", "created_at"),
        Index("idx_judgment_runs_route_version", "route_version_id"),
        Index("idx_judgment_runs_route_book", "route_book_id"),
        Index("idx_judgment_runs_segment", "segment_id"),
        Index("idx_judgment_runs_parent", "parent_run_id"),
        Index("idx_judgment_runs_challenged", "challenged_run_id"),
    )


class RouteCollection(Base):
    """路线专题容器表——给一组未来路线成员先发一张独立“专题身份证”。

    这张表只保存专题自身的信息、地图范围和审核来源；它还不能直接装 route 或 segment。
    后续成员关系必须另走受控关系表，避免把 collection 偷偷写成 concept 或候选池。
    """

    __tablename__ = "route_collections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    slug = Column(String(128), nullable=False)
    collection_type = Column(String(32), nullable=False)
    city = Column(String(64), nullable=False, server_default="unknown")
    visibility = Column(String(16), nullable=False, server_default="private")
    publish_status = Column(String(16), nullable=False, server_default="draft")
    description_md = Column(Text, nullable=True)
    cover_url = Column(Text, nullable=True)
    geom = Column(Geometry("GEOMETRY", srid=4326, spatial_index=False), nullable=True)
    center_lat = Column(Numeric(9, 6), nullable=True)
    center_lon = Column(Numeric(9, 6), nullable=True)
    source = Column(String(16), nullable=False, server_default="manual")
    source_ref = Column(String(512), nullable=True)
    confidence = Column(Numeric(5, 4), nullable=True)
    stats_json = Column(JSONB, nullable=True)
    metadata_json = Column(JSONB, nullable=True)
    source_judgment_run_id = Column(Integer, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", name="fk_route_collections_created_by", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["source_judgment_run_id"],
            ["judgment_runs.id"],
            name="fk_route_collections_source_judgment_run",
        ),
        CheckConstraint("length(btrim(name)) > 0", name="ck_route_collections_name_nonempty"),
        CheckConstraint(
            "slug ~ '^[a-z0-9][a-z0-9_-]{1,127}$'",
            name="ck_route_collections_slug_format",
        ),
        CheckConstraint(
            "collection_type IN ('area_system', 'route_family', 'race_route_family', "
            "'training_corridor', 'theme_pack', 'other')",
            name="ck_route_collections_collection_type",
        ),
        CheckConstraint(
            "visibility IN ('private', 'unlisted', 'public')",
            name="ck_route_collections_visibility",
        ),
        CheckConstraint(
            "publish_status IN ('draft', 'published', 'archived')",
            name="ck_route_collections_publish_status",
        ),
        CheckConstraint("source IN ('manual', 'imported')", name="ck_route_collections_source"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_route_collections_confidence_range",
        ),
        CheckConstraint(
            "center_lat IS NULL OR (center_lat >= -90 AND center_lat <= 90)",
            name="ck_route_collections_center_lat_range",
        ),
        CheckConstraint(
            "center_lon IS NULL OR (center_lon >= -180 AND center_lon <= 180)",
            name="ck_route_collections_center_lon_range",
        ),
        CheckConstraint(
            "(center_lat IS NULL AND center_lon IS NULL) OR "
            "(center_lat IS NOT NULL AND center_lon IS NOT NULL)",
            name="ck_route_collections_center_pair",
        ),
        CheckConstraint(
            "visibility <> 'public' OR publish_status = 'published'",
            name="ck_route_collections_publication_state",
        ),
        CheckConstraint(
            "publish_status <> 'published' OR source_judgment_run_id IS NOT NULL",
            name="ck_route_collections_published_judgment",
        ),
        CheckConstraint(
            "source <> 'imported' OR source_ref IS NOT NULL OR source_judgment_run_id IS NOT NULL",
            name="ck_route_collections_import_source_ref",
        ),
        CheckConstraint(
            "geom IS NULL OR ("
            "ST_IsValid(geom) "
            "AND upper(replace(GeometryType(geom), 'ST_', '')) IN "
            "('POLYGON', 'MULTIPOLYGON', 'LINESTRING', 'MULTILINESTRING')"
            ")",
            name="ck_route_collections_geom_valid_type",
        ),
        UniqueConstraint("city", "slug", name="uq_route_collections_city_slug"),
        Index("idx_route_collections_city", "city"),
        Index("idx_route_collections_slug", "slug"),
        Index("idx_route_collections_collection_type", "collection_type"),
        Index("idx_route_collections_visibility_publish_status", "visibility", "publish_status"),
        Index("idx_route_collections_created_by", "created_by"),
        Index("idx_route_collections_source_judgment_run", "source_judgment_run_id"),
        Index("idx_route_collections_source", "source"),
        Index("idx_route_collections_geom", "geom", postgresql_using="gist"),
    )


class ResearchQuestion(Base):
    """研究问题表——记录为什么要去外部搜索，避免自由抓取。"""

    __tablename__ = "research_questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    parent_question_id = Column(Integer, ForeignKey("research_questions.id", ondelete="SET NULL"), nullable=True)
    spawned_by_research_run_id = Column(
        Integer,
        ForeignKey(
            "research_runs.id",
            name="fk_research_questions_spawned_run",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )
    trigger_judgment_run_id = Column(Integer, ForeignKey("judgment_runs.id", ondelete="SET NULL"), nullable=True)
    trigger_evidence_item_id = Column(
        Integer,
        ForeignKey(
            "evidence_items.id",
            name="fk_research_questions_trigger_evidence",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )
    question_text = Column(Text, nullable=False)
    question_type = Column(String(64), nullable=False)
    trigger_reason = Column(Text, nullable=True)
    expected_evidence_type = Column(String(64), nullable=True)
    stop_condition_json = Column(JSONB, nullable=True)
    route_book_id = Column(Integer, ForeignKey("route_books.id", ondelete="SET NULL"), nullable=True)
    route_version_id = Column(Integer, ForeignKey("route_versions.id", ondelete="SET NULL"), nullable=True)
    segment_id = Column(Integer, ForeignKey("segments.id", ondelete="SET NULL"), nullable=True)
    priority = Column(String(16), nullable=False, server_default="normal")
    status = Column(String(16), nullable=False, server_default="open")
    resolution = Column(String(32), nullable=True)
    resolution_summary = Column(Text, nullable=True)
    created_by_run_id = Column(Integer, ForeignKey("judgment_runs.id", ondelete="SET NULL"), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["route_version_id", "route_book_id"],
            ["route_versions.id", "route_versions.route_book_id"],
            name="fk_research_questions_route_version_book",
        ),
        CheckConstraint(
            "question_type IN ('event_association', 'route_family_membership', 'name_origin', "
            "'safety_condition', 'abnormal_popularity', 'foreign_rider_spike', "
            "'platform_metric_conflict', 'physical_semantic_gap', 'content_rights_check', 'other')",
            name="ck_research_questions_question_type",
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="ck_research_questions_priority",
        ),
        CheckConstraint(
            "status IN ('open', 'researching', 'answered', 'unknown', 'contradicted', 'dismissed')",
            name="ck_research_questions_status",
        ),
        CheckConstraint(
            "resolution IS NULL OR resolution IN ('answered', 'unknown', 'contradicted', 'dismissed')",
            name="ck_research_questions_resolution",
        ),
        Index("idx_research_questions_status_priority", "status", "priority"),
        Index("idx_research_questions_route_version", "route_version_id"),
        Index("idx_research_questions_route_book", "route_book_id"),
        Index("idx_research_questions_trigger_run", "trigger_judgment_run_id"),
        Index("idx_research_questions_spawned_run", "spawned_by_research_run_id"),
        Index("idx_research_questions_trigger_evidence", "trigger_evidence_item_id"),
        Index("idx_research_questions_parent", "parent_question_id"),
    )


class ResearchRun(Base):
    """研究运行表——记录某个具体问题的一次外部搜索或资料核验。"""

    __tablename__ = "research_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    research_question_id = Column(Integer, ForeignKey("research_questions.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(16), nullable=False)
    queries_json = Column(JSONB, nullable=True)
    searched_sources_json = Column(JSONB, nullable=True)
    engine_name = Column(String(64), nullable=True)
    engine_version = Column(String(64), nullable=True)
    model_name = Column(String(64), nullable=True)
    model_version = Column(String(64), nullable=True)
    summary_json = Column(JSONB, nullable=True)
    result_judgment_run_id = Column(Integer, ForeignKey("judgment_runs.id", ondelete="SET NULL"), nullable=True)
    used_evidence_count = Column(Integer, nullable=False, server_default="0")
    contradicting_evidence_count = Column(Integer, nullable=False, server_default="0")
    unknown_summary_json = Column(JSONB, nullable=True)
    discarded_results_summary_json = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_research_runs_status",
        ),
        CheckConstraint("used_evidence_count >= 0", name="ck_research_runs_used_evidence_count"),
        CheckConstraint(
            "contradicting_evidence_count >= 0",
            name="ck_research_runs_contradicting_evidence_count",
        ),
        Index("idx_research_runs_question", "research_question_id"),
        Index("idx_research_runs_status_created", "status", "created_at"),
        Index("idx_research_runs_result_judgment", "result_judgment_run_id"),
    )


class EvidenceItem(Base):
    """证据表——只保存被某次判断真正使用过的一条原子证据。

    fidelity_tier 像证据的“离现场远近”：1 = raw geometry / raw profile（最高保真），
    2 = structured metric，3 = image / screenshot，4 = UGC / web text，
    5 = model inference（最低保真）。
    """

    __tablename__ = "evidence_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    first_judgment_run_id = Column(Integer, ForeignKey("judgment_runs.id", ondelete="CASCADE"), nullable=False)
    research_run_id = Column(Integer, ForeignKey("research_runs.id", ondelete="SET NULL"), nullable=True)
    evidence_type = Column(String(64), nullable=False)
    fidelity_tier = Column(Integer, nullable=False)
    route_book_id = Column(Integer, ForeignKey("route_books.id", ondelete="SET NULL"), nullable=True)
    route_version_id = Column(Integer, ForeignKey("route_versions.id", ondelete="SET NULL"), nullable=True)
    segment_id = Column(Integer, ForeignKey("segments.id", ondelete="SET NULL"), nullable=True)
    source_platform = Column(String(64), nullable=True)
    source_url = Column(Text, nullable=True)
    source_file_id = Column(String(512), nullable=True)
    file_id = Column(String(512), nullable=True)
    content_hash = Column(String(64), nullable=True)
    geometry_hash = Column(String(64), nullable=True)
    coordinate_system = Column(String(32), nullable=True)
    normalization_version = Column(String(64), nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=True)
    observed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    metrics_json = Column(JSONB, nullable=True)
    text_excerpt = Column(Text, nullable=True)
    text_summary = Column(Text, nullable=True)
    metadata_json = Column(JSONB, nullable=True)
    access_level = Column(String(32), nullable=False, server_default="internal_only")
    display_policy = Column(String(32), nullable=False, server_default="internal_only")
    rights_status = Column(String(32), nullable=False, server_default="unknown")
    contains_sensitive_media = Column(Boolean, nullable=False, server_default=false())
    contains_watermark = Column(Boolean, nullable=False, server_default=false())
    contains_identifiable_person = Column(Boolean, nullable=False, server_default=false())
    contains_identifiable_vehicle = Column(Boolean, nullable=False, server_default=false())

    __table_args__ = (
        ForeignKeyConstraint(
            ["route_version_id", "route_book_id"],
            ["route_versions.id", "route_versions.route_book_id"],
            name="fk_evidence_items_route_version_book",
        ),
        CheckConstraint(
            "evidence_type IN ('route_version_geometry', 'verified_segment_geometry', "
            "'internal_structured_metric', 'platform_metric', 'elevation_profile_image', "
            "'ugc_text', 'web_page_text', 'model_inference', 'human_observation', "
            "'human_review_decision')",
            name="ck_evidence_items_evidence_type",
        ),
        CheckConstraint("fidelity_tier BETWEEN 1 AND 5", name="ck_evidence_items_fidelity_tier"),
        CheckConstraint(
            "access_level IN ('internal_only', 'reviewer', 'admin')",
            name="ck_evidence_items_access_level",
        ),
        CheckConstraint(
            "display_policy IN ('internal_only', 'summarize_only', 'display_allowed')",
            name="ck_evidence_items_display_policy",
        ),
        CheckConstraint(
            "rights_status IN ('unknown', 'allowed', 'forbidden', 'licensed', 'self_owned')",
            name="ck_evidence_items_rights_status",
        ),
        Index("idx_evidence_items_first_run", "first_judgment_run_id"),
        Index("idx_evidence_items_research_run", "research_run_id"),
        Index("idx_evidence_items_type", "evidence_type"),
        Index("idx_evidence_items_fidelity", "fidelity_tier"),
        Index("idx_evidence_items_route_version", "route_version_id"),
        Index("idx_evidence_items_route_book", "route_book_id"),
        Index("idx_evidence_items_segment", "segment_id"),
        Index("idx_evidence_items_content_hash", "content_hash"),
        Index("idx_evidence_items_display_policy", "display_policy"),
        Index("idx_evidence_items_rights_status", "rights_status"),
    )


class JudgmentRunEvidence(Base):
    """判断证据连接表——说明一条证据在某轮判断里是支持、反驳还是无法对质。"""

    __tablename__ = "judgment_run_evidence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    judgment_run_id = Column(Integer, ForeignKey("judgment_runs.id", ondelete="CASCADE"), nullable=False)
    evidence_item_id = Column(Integer, ForeignKey("evidence_items.id", ondelete="CASCADE"), nullable=False)
    evidence_role = Column(String(32), nullable=False)
    assessment_result = Column(String(32), nullable=False)
    weight = Column(Numeric(5, 4), nullable=True)
    anchor_evidence_item_id = Column(Integer, ForeignKey("evidence_items.id", ondelete="SET NULL"), nullable=True)
    assessment_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "evidence_role IN ('primary_input', 'primary_physical_basis', 'supporting', "
            "'contradicting', 'background', 'weak_signal', 'comparison_target')",
            name="ck_judgment_run_evidence_role",
        ),
        CheckConstraint(
            "assessment_result IN ('input', 'supports', 'contradicts', 'neutral', "
            "'unverifiable', 'insufficient')",
            name="ck_judgment_run_evidence_result",
        ),
        CheckConstraint(
            "weight IS NULL OR (weight >= 0 AND weight <= 1)",
            name="ck_judgment_run_evidence_weight_range",
        ),
        UniqueConstraint(
            "judgment_run_id",
            "evidence_item_id",
            "evidence_role",
            name="uq_judgment_run_evidence_role",
        ),
        Index("idx_judgment_run_evidence_run", "judgment_run_id"),
        Index("idx_judgment_run_evidence_item", "evidence_item_id"),
        Index("idx_judgment_run_evidence_result", "assessment_result"),
        Index("idx_judgment_run_evidence_anchor", "anchor_evidence_item_id"),
    )


class SegmentGeometrySource(Base):
    """赛段几何来源表——记录一条正式 segment 的线条从哪份真实材料裁出来。"""

    __tablename__ = "segment_geometry_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    segment_id = Column(Integer, ForeignKey("segments.id"), nullable=False)
    source_type = Column(String(32), nullable=False)
    source_activity_id = Column(Integer, ForeignKey("activities.id", ondelete="SET NULL"), nullable=True)
    source_file_id = Column(String(512), nullable=True)
    source_url = Column(Text, nullable=True)
    source_start_index = Column(Integer, nullable=True)
    source_end_index = Column(Integer, nullable=True)
    source_start_time = Column(DateTime(timezone=True), nullable=True)
    source_end_time = Column(DateTime(timezone=True), nullable=True)
    original_coordinate_system = Column(String(16), nullable=True)
    geometry_hash = Column(String(64), nullable=False)
    source_content_hash = Column(String(64), nullable=True)
    normalization_version = Column(String(64), nullable=False)
    quality_status = Column(String(16), nullable=False)
    quality_metrics_json = Column(JSONB, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "source_type IN ('activity_clip', 'gpx_upload', 'fit_upload', 'admin_import')",
            name="ck_segment_geometry_sources_source_type",
        ),
        CheckConstraint(
            "quality_status IN ('verified', 'needs_review', 'rejected', 'deprecated')",
            name="ck_segment_geometry_sources_quality_status",
        ),
        CheckConstraint(
            "original_coordinate_system IS NULL OR "
            "original_coordinate_system IN ('wgs84', 'gcj02', 'unknown')",
            name="ck_segment_geometry_sources_coordinate_system",
        ),
        CheckConstraint(
            "source_start_index IS NULL OR source_end_index IS NULL "
            "OR source_start_index < source_end_index",
            name="ck_segment_geometry_sources_index_order",
        ),
        CheckConstraint(
            "("
            "source_type = 'activity_clip' "
            "AND source_content_hash IS NOT NULL"
            ") OR ("
            "source_type IN ('gpx_upload', 'fit_upload', 'admin_import') "
            "AND ("
            "source_file_id IS NOT NULL "
            "OR source_url IS NOT NULL "
            "OR source_content_hash IS NOT NULL"
            ")"
            ")",
            name="ck_segment_geometry_sources_material_pointer",
        ),
        UniqueConstraint("id", "segment_id", name="uq_segment_geometry_sources_id_segment"),
        UniqueConstraint(
            "id",
            "segment_id",
            "geometry_hash",
            name="uq_segment_geometry_sources_id_segment_geometry_hash",
        ),
        Index("idx_segment_geometry_sources_segment", "segment_id"),
        Index("idx_segment_geometry_sources_source_type", "source_type"),
        Index("idx_segment_geometry_sources_activity", "source_activity_id"),
        Index("idx_segment_geometry_sources_file", "source_file_id"),
        Index("idx_segment_geometry_sources_geometry_hash", "geometry_hash"),
        Index("idx_segment_geometry_sources_quality", "quality_status"),
    )


class RouteCognitionSegment(Base):
    """路线认知 segment 白名单——只有审过的正式 segment 才能进入后续路线认知。"""

    __tablename__ = "route_cognition_segments"

    segment_id = Column(Integer, ForeignKey("segments.id"), primary_key=True)
    primary_geometry_source_id = Column(Integer, nullable=True)
    review_basis = Column(String(32), nullable=False)
    eligibility_status = Column(String(16), nullable=False)
    geometry_hash = Column(String(64), nullable=False)
    normalization_version = Column(String(64), nullable=False)
    accepted_judgment_run_id = Column(Integer, ForeignKey("judgment_runs.id"), nullable=False)
    reviewed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=False)
    review_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["primary_geometry_source_id", "segment_id"],
            ["segment_geometry_sources.id", "segment_geometry_sources.segment_id"],
            name="fk_route_cognition_segments_primary_source_segment",
        ),
        ForeignKeyConstraint(
            ["primary_geometry_source_id", "segment_id", "geometry_hash"],
            [
                "segment_geometry_sources.id",
                "segment_geometry_sources.segment_id",
                "segment_geometry_sources.geometry_hash",
            ],
            name="fk_route_cognition_segments_primary_source_geometry_hash",
        ),
        CheckConstraint(
            "review_basis IN ('provenance_verified', 'legacy_reviewed')",
            name="ck_route_cognition_segments_review_basis",
        ),
        CheckConstraint(
            "eligibility_status IN ('active', 'suspended', 'deprecated')",
            name="ck_route_cognition_segments_eligibility_status",
        ),
        CheckConstraint(
            "accepted_judgment_run_id IS NOT NULL "
            "AND geometry_hash IS NOT NULL "
            "AND normalization_version IS NOT NULL "
            "AND reviewed_at IS NOT NULL",
            name="ck_route_cognition_segments_required_review_fields",
        ),
        CheckConstraint(
            "("
            "review_basis = 'provenance_verified' "
            "AND primary_geometry_source_id IS NOT NULL"
            ") OR ("
            "review_basis = 'legacy_reviewed' "
            "AND primary_geometry_source_id IS NULL"
            ")",
            name="ck_route_cognition_segments_review_basis_source",
        ),
        UniqueConstraint(
            "primary_geometry_source_id",
            name="uq_route_cognition_segments_primary_source",
        ),
        Index("idx_route_cognition_segments_eligibility", "eligibility_status"),
        Index("idx_route_cognition_segments_review_basis", "review_basis"),
        Index("idx_route_cognition_segments_judgment", "accepted_judgment_run_id"),
        Index("idx_route_cognition_segments_reviewed_by", "reviewed_by"),
        Index("idx_route_cognition_segments_geometry_hash", "geometry_hash"),
    )
