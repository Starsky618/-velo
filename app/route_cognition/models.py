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
    text,
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
        UniqueConstraint("id", "run_type", name="uq_judgment_runs_id_run_type"),
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


class ConceptNode(Base):
    """语义概念表——给“FTP 测试、网红桥、碎石风险”这类概念发身份证。

    它只保存概念本体和审核来源，不保存路线、segment 或 collection 关系；
    未来关系必须走候选和人工审核后再进入具体关系表，避免把 metadata_json 当知识仓库。
    """

    __tablename__ = "concept_nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    slug = Column(String(128), nullable=False)
    node_type = Column(String(32), nullable=False)
    scope_type = Column(String(16), nullable=False, server_default="global")
    scope_value = Column(String(128), nullable=False, server_default="global")
    city = Column(String(64), nullable=True)
    region = Column(String(128), nullable=True)
    visibility = Column(String(16), nullable=False, server_default="private")
    publish_status = Column(String(16), nullable=False, server_default="draft")
    summary = Column(Text, nullable=True)
    description_md = Column(Text, nullable=True)
    cover_url = Column(Text, nullable=True)
    geom = Column(Geometry("GEOMETRY", srid=4326, spatial_index=False), nullable=True)
    center_lat = Column(Numeric(9, 6), nullable=True)
    center_lon = Column(Numeric(9, 6), nullable=True)
    source = Column(String(16), nullable=False, server_default="manual")
    source_ref = Column(Text, nullable=True)
    confidence = Column(Numeric(5, 4), nullable=True)
    metadata_json = Column(JSONB, nullable=True)
    source_judgment_run_id = Column(Integer, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", name="fk_concept_nodes_created_by", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["source_judgment_run_id"],
            ["judgment_runs.id"],
            name="fk_concept_nodes_source_judgment_run",
        ),
        CheckConstraint("length(btrim(name)) > 0", name="ck_concept_nodes_name_nonempty"),
        CheckConstraint(
            "slug ~ '^[a-z0-9][a-z0-9_-]{1,127}$'",
            name="ck_concept_nodes_slug_format",
        ),
        CheckConstraint(
            "node_type IN ('practice_type', 'landmark', 'road_condition', 'safety_risk', "
            "'event', 'local_term', 'place', 'training_theme', 'other')",
            name="ck_concept_nodes_node_type",
        ),
        CheckConstraint(
            "scope_type IN ('global', 'city', 'region')",
            name="ck_concept_nodes_scope_type",
        ),
        CheckConstraint(
            "(scope_type = 'global' AND scope_value = 'global') OR "
            "(scope_type = 'city' AND scope_value <> 'global') OR "
            "(scope_type = 'region' AND scope_value <> 'global')",
            name="ck_concept_nodes_scope_rule",
        ),
        CheckConstraint(
            "visibility IN ('private', 'unlisted', 'public')",
            name="ck_concept_nodes_visibility",
        ),
        CheckConstraint(
            "publish_status IN ('draft', 'published', 'archived')",
            name="ck_concept_nodes_publish_status",
        ),
        CheckConstraint("source IN ('manual', 'imported')", name="ck_concept_nodes_source"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_concept_nodes_confidence_range",
        ),
        CheckConstraint(
            "center_lat IS NULL OR (center_lat >= -90 AND center_lat <= 90)",
            name="ck_concept_nodes_center_lat_range",
        ),
        CheckConstraint(
            "center_lon IS NULL OR (center_lon >= -180 AND center_lon <= 180)",
            name="ck_concept_nodes_center_lon_range",
        ),
        CheckConstraint(
            "(center_lat IS NULL AND center_lon IS NULL) OR "
            "(center_lat IS NOT NULL AND center_lon IS NOT NULL)",
            name="ck_concept_nodes_center_pair",
        ),
        CheckConstraint(
            "visibility <> 'public' OR publish_status = 'published'",
            name="ck_concept_nodes_publication_state",
        ),
        CheckConstraint(
            "publish_status <> 'published' OR source_judgment_run_id IS NOT NULL",
            name="ck_concept_nodes_published_judgment",
        ),
        CheckConstraint(
            "source <> 'imported' OR source_ref IS NOT NULL OR source_judgment_run_id IS NOT NULL",
            name="ck_concept_nodes_import_source_ref",
        ),
        CheckConstraint(
            "geom IS NULL OR ("
            "ST_IsValid(geom) "
            "AND upper(replace(GeometryType(geom), 'ST_', '')) IN "
            "('POINT', 'MULTIPOINT', 'LINESTRING', 'MULTILINESTRING', 'POLYGON', 'MULTIPOLYGON')"
            ")",
            name="ck_concept_nodes_geom_valid_type",
        ),
        UniqueConstraint(
            "scope_type",
            "scope_value",
            "node_type",
            "slug",
            name="uq_concept_nodes_scope_type_scope_value_node_type_slug",
        ),
        Index("idx_concept_nodes_scope", "scope_type", "scope_value"),
        Index("idx_concept_nodes_type", "node_type"),
        Index("idx_concept_nodes_slug", "slug"),
        Index("idx_concept_nodes_visibility_status", "visibility", "publish_status"),
        Index("idx_concept_nodes_source_judgment", "source_judgment_run_id"),
        Index("idx_concept_nodes_created_by", "created_by"),
        Index("idx_concept_nodes_geom", "geom", postgresql_using="gist"),
    )


class RouteConceptCandidate(Base):
    """路线-概念候选表——先把“这条路线像什么”放进待审队列。

    它只保存 route 与 concept 的关系候选，不是正式关系；以后正式 link 必须引用已接受候选。
    """

    __tablename__ = "route_concept_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    route_book_id = Column(Integer, nullable=False)
    route_version_id = Column(Integer, nullable=False)
    route_line_hash = Column(String(64), nullable=False)
    concept_node_id = Column(Integer, nullable=False)
    relation_type = Column(String(32), nullable=False)
    proposer_kind = Column(String(16), nullable=False)
    candidate_status = Column(String(16), nullable=False)
    created_by_judgment_run_id = Column(Integer, nullable=False)
    latest_judgment_run_id = Column(Integer, nullable=False)
    accepted_by_judgment_run_id = Column(Integer, nullable=True)
    latest_confidence = Column(Numeric(5, 4), nullable=True)
    latest_confidence_state = Column(String(32), nullable=False)
    latest_evidence_summary_json = Column(JSONB, nullable=True)
    latest_missing_data_summary_json = Column(JSONB, nullable=True)
    latest_contradiction_summary_json = Column(JSONB, nullable=True)
    reason_summary = Column(Text, nullable=True)
    metadata_json = Column(JSONB, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", name="fk_route_concept_candidates_created_by", ondelete="SET NULL"), nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id", name="fk_route_concept_candidates_reviewed_by", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(["route_book_id"], ["route_books.id"], name="fk_route_concept_candidates_route_book"),
        ForeignKeyConstraint(
            ["route_version_id", "route_book_id"],
            ["route_versions.id", "route_versions.route_book_id"],
            name="fk_route_concept_candidates_route_version_book",
        ),
        ForeignKeyConstraint(["concept_node_id"], ["concept_nodes.id"], name="fk_route_concept_candidates_concept_node"),
        ForeignKeyConstraint(
            ["created_by_judgment_run_id"],
            ["judgment_runs.id"],
            name="fk_route_concept_candidates_created_by_judgment_run",
        ),
        ForeignKeyConstraint(
            ["latest_judgment_run_id"],
            ["judgment_runs.id"],
            name="fk_route_concept_candidates_latest_judgment_run",
        ),
        ForeignKeyConstraint(
            ["accepted_by_judgment_run_id"],
            ["judgment_runs.id"],
            name="fk_route_concept_candidates_accepted_by_judgment_run",
        ),
        CheckConstraint(
            "relation_type IN ('suitable_for', 'passes_near', 'has_feature', 'has_risk', "
            "'part_of_event', 'story_reference', 'training_theme', 'local_name', 'associated_with')",
            name="ck_route_concept_candidates_relation_type",
        ),
        CheckConstraint(
            "proposer_kind IN ('algorithm', 'agent', 'human', 'imported')",
            name="ck_route_concept_candidates_proposer_kind",
        ),
        CheckConstraint(
            "candidate_status IN ('proposed', 'needs_review', 'accepted', 'rejected', "
            "'withdrawn', 'superseded', 'stale', 'inconclusive')",
            name="ck_route_concept_candidates_candidate_status",
        ),
        CheckConstraint(
            "latest_confidence IS NULL OR (latest_confidence >= 0 AND latest_confidence <= 1)",
            name="ck_route_concept_candidates_latest_confidence_range",
        ),
        CheckConstraint(
            "latest_confidence_state IN ('raw', 'proposed', 'challenged', 'stable', "
            "'human_accepted', 'stale', 'inconclusive')",
            name="ck_route_concept_candidates_latest_confidence_state",
        ),
        CheckConstraint(
            "((candidate_status = 'accepted' AND accepted_by_judgment_run_id IS NOT NULL "
            "AND reviewed_at IS NOT NULL) OR "
            "(candidate_status <> 'accepted' AND accepted_by_judgment_run_id IS NULL))",
            name="ck_route_concept_candidates_acceptance_gate",
        ),
        UniqueConstraint(
            "route_book_id",
            "route_version_id",
            "concept_node_id",
            "relation_type",
            "created_by_judgment_run_id",
            name="uq_route_concept_candidates_idempotency",
        ),
        UniqueConstraint("id", "accepted_by_judgment_run_id", name="uq_route_concept_candidates_formal_gate"),
        UniqueConstraint(
            "id",
            "accepted_by_judgment_run_id",
            "route_book_id",
            "route_version_id",
            "route_line_hash",
            "concept_node_id",
            "relation_type",
            name="uq_route_concept_candidates_wide_formal_gate",
        ),
        Index("idx_route_concept_candidates_route_book", "route_book_id"),
        Index("idx_route_concept_candidates_route_version", "route_version_id"),
        Index("idx_route_concept_candidates_concept_node", "concept_node_id"),
        Index("idx_route_concept_candidates_status", "candidate_status"),
        Index("idx_route_concept_candidates_relation_type", "relation_type"),
        Index("idx_route_concept_candidates_created_by_run", "created_by_judgment_run_id"),
        Index("idx_route_concept_candidates_latest_run", "latest_judgment_run_id"),
        Index("idx_route_concept_candidates_accepted_run", "accepted_by_judgment_run_id"),
        Index("idx_route_concept_candidates_created_by", "created_by"),
        Index("idx_route_concept_candidates_reviewed_by", "reviewed_by"),
        Index(
            "uq_route_concept_candidates_open_candidate",
            "route_book_id",
            "route_version_id",
            "concept_node_id",
            "relation_type",
            unique=True,
            postgresql_where=text("candidate_status IN ('proposed', 'needs_review')"),
        ),
    )


class SegmentConceptCandidate(Base):
    """赛段-概念候选表——只允许已进路线认知白名单的 segment 提交概念关系候选。"""

    __tablename__ = "segment_concept_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    segment_id = Column(Integer, nullable=False)
    segment_geometry_hash = Column(String(64), nullable=False)
    concept_node_id = Column(Integer, nullable=False)
    relation_type = Column(String(32), nullable=False)
    proposer_kind = Column(String(16), nullable=False)
    candidate_status = Column(String(16), nullable=False)
    created_by_judgment_run_id = Column(Integer, nullable=False)
    latest_judgment_run_id = Column(Integer, nullable=False)
    accepted_by_judgment_run_id = Column(Integer, nullable=True)
    latest_confidence = Column(Numeric(5, 4), nullable=True)
    latest_confidence_state = Column(String(32), nullable=False)
    latest_evidence_summary_json = Column(JSONB, nullable=True)
    latest_missing_data_summary_json = Column(JSONB, nullable=True)
    latest_contradiction_summary_json = Column(JSONB, nullable=True)
    reason_summary = Column(Text, nullable=True)
    metadata_json = Column(JSONB, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", name="fk_segment_concept_candidates_created_by", ondelete="SET NULL"), nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id", name="fk_segment_concept_candidates_reviewed_by", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(["segment_id"], ["route_cognition_segments.segment_id"], name="fk_segment_concept_candidates_segment"),
        ForeignKeyConstraint(["concept_node_id"], ["concept_nodes.id"], name="fk_segment_concept_candidates_concept_node"),
        ForeignKeyConstraint(
            ["created_by_judgment_run_id"],
            ["judgment_runs.id"],
            name="fk_segment_concept_candidates_created_by_judgment_run",
        ),
        ForeignKeyConstraint(
            ["latest_judgment_run_id"],
            ["judgment_runs.id"],
            name="fk_segment_concept_candidates_latest_judgment_run",
        ),
        ForeignKeyConstraint(
            ["accepted_by_judgment_run_id"],
            ["judgment_runs.id"],
            name="fk_segment_concept_candidates_accepted_by_judgment_run",
        ),
        CheckConstraint(
            "relation_type IN ('suitable_for', 'passes_near', 'has_feature', 'has_risk', "
            "'part_of_event', 'story_reference', 'training_theme', 'local_name', 'associated_with')",
            name="ck_segment_concept_candidates_relation_type",
        ),
        CheckConstraint(
            "proposer_kind IN ('algorithm', 'agent', 'human', 'imported')",
            name="ck_segment_concept_candidates_proposer_kind",
        ),
        CheckConstraint(
            "candidate_status IN ('proposed', 'needs_review', 'accepted', 'rejected', "
            "'withdrawn', 'superseded', 'stale', 'inconclusive')",
            name="ck_segment_concept_candidates_candidate_status",
        ),
        CheckConstraint(
            "latest_confidence IS NULL OR (latest_confidence >= 0 AND latest_confidence <= 1)",
            name="ck_segment_concept_candidates_latest_confidence_range",
        ),
        CheckConstraint(
            "latest_confidence_state IN ('raw', 'proposed', 'challenged', 'stable', "
            "'human_accepted', 'stale', 'inconclusive')",
            name="ck_segment_concept_candidates_latest_confidence_state",
        ),
        CheckConstraint(
            "((candidate_status = 'accepted' AND accepted_by_judgment_run_id IS NOT NULL "
            "AND reviewed_at IS NOT NULL) OR "
            "(candidate_status <> 'accepted' AND accepted_by_judgment_run_id IS NULL))",
            name="ck_segment_concept_candidates_acceptance_gate",
        ),
        UniqueConstraint(
            "segment_id",
            "concept_node_id",
            "relation_type",
            "created_by_judgment_run_id",
            name="uq_segment_concept_candidates_idempotency",
        ),
        UniqueConstraint("id", "accepted_by_judgment_run_id", name="uq_segment_concept_candidates_formal_gate"),
        UniqueConstraint(
            "id",
            "accepted_by_judgment_run_id",
            "segment_id",
            "segment_geometry_hash",
            "concept_node_id",
            "relation_type",
            name="uq_segment_concept_candidates_wide_formal_gate",
        ),
        Index("idx_segment_concept_candidates_segment", "segment_id"),
        Index("idx_segment_concept_candidates_concept_node", "concept_node_id"),
        Index("idx_segment_concept_candidates_status", "candidate_status"),
        Index("idx_segment_concept_candidates_relation_type", "relation_type"),
        Index("idx_segment_concept_candidates_created_by_run", "created_by_judgment_run_id"),
        Index("idx_segment_concept_candidates_latest_run", "latest_judgment_run_id"),
        Index("idx_segment_concept_candidates_accepted_run", "accepted_by_judgment_run_id"),
        Index("idx_segment_concept_candidates_created_by", "created_by"),
        Index("idx_segment_concept_candidates_reviewed_by", "reviewed_by"),
        Index(
            "uq_segment_concept_candidates_open_candidate",
            "segment_id",
            "concept_node_id",
            "relation_type",
            unique=True,
            postgresql_where=text("candidate_status IN ('proposed', 'needs_review')"),
        ),
    )


class CollectionConceptCandidate(Base):
    """路线专题-概念候选表——给 collection 和 concept 的关系先排队审查。"""

    __tablename__ = "collection_concept_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    collection_id = Column(Integer, nullable=False)
    concept_node_id = Column(Integer, nullable=False)
    relation_type = Column(String(32), nullable=False)
    proposer_kind = Column(String(16), nullable=False)
    candidate_status = Column(String(16), nullable=False)
    created_by_judgment_run_id = Column(Integer, nullable=False)
    latest_judgment_run_id = Column(Integer, nullable=False)
    accepted_by_judgment_run_id = Column(Integer, nullable=True)
    latest_confidence = Column(Numeric(5, 4), nullable=True)
    latest_confidence_state = Column(String(32), nullable=False)
    latest_evidence_summary_json = Column(JSONB, nullable=True)
    latest_missing_data_summary_json = Column(JSONB, nullable=True)
    latest_contradiction_summary_json = Column(JSONB, nullable=True)
    reason_summary = Column(Text, nullable=True)
    metadata_json = Column(JSONB, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", name="fk_collection_concept_candidates_created_by", ondelete="SET NULL"), nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id", name="fk_collection_concept_candidates_reviewed_by", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(["collection_id"], ["route_collections.id"], name="fk_collection_concept_candidates_collection"),
        ForeignKeyConstraint(["concept_node_id"], ["concept_nodes.id"], name="fk_collection_concept_candidates_concept_node"),
        ForeignKeyConstraint(
            ["created_by_judgment_run_id"],
            ["judgment_runs.id"],
            name="fk_collection_concept_candidates_created_by_judgment_run",
        ),
        ForeignKeyConstraint(
            ["latest_judgment_run_id"],
            ["judgment_runs.id"],
            name="fk_collection_concept_candidates_latest_judgment_run",
        ),
        ForeignKeyConstraint(
            ["accepted_by_judgment_run_id"],
            ["judgment_runs.id"],
            name="fk_collection_concept_candidates_accepted_by_judgment_run",
        ),
        CheckConstraint(
            "relation_type IN ('suitable_for', 'passes_near', 'has_feature', 'has_risk', "
            "'part_of_event', 'story_reference', 'training_theme', 'local_name', 'associated_with')",
            name="ck_collection_concept_candidates_relation_type",
        ),
        CheckConstraint(
            "proposer_kind IN ('algorithm', 'agent', 'human', 'imported')",
            name="ck_collection_concept_candidates_proposer_kind",
        ),
        CheckConstraint(
            "candidate_status IN ('proposed', 'needs_review', 'accepted', 'rejected', "
            "'withdrawn', 'superseded', 'stale', 'inconclusive')",
            name="ck_collection_concept_candidates_candidate_status",
        ),
        CheckConstraint(
            "latest_confidence IS NULL OR (latest_confidence >= 0 AND latest_confidence <= 1)",
            name="ck_collection_concept_candidates_latest_confidence_range",
        ),
        CheckConstraint(
            "latest_confidence_state IN ('raw', 'proposed', 'challenged', 'stable', "
            "'human_accepted', 'stale', 'inconclusive')",
            name="ck_collection_concept_candidates_latest_confidence_state",
        ),
        CheckConstraint(
            "((candidate_status = 'accepted' AND accepted_by_judgment_run_id IS NOT NULL "
            "AND reviewed_at IS NOT NULL) OR "
            "(candidate_status <> 'accepted' AND accepted_by_judgment_run_id IS NULL))",
            name="ck_collection_concept_candidates_acceptance_gate",
        ),
        UniqueConstraint(
            "collection_id",
            "concept_node_id",
            "relation_type",
            "created_by_judgment_run_id",
            name="uq_collection_concept_candidates_idempotency",
        ),
        UniqueConstraint("id", "accepted_by_judgment_run_id", name="uq_collection_concept_candidates_formal_gate"),
        UniqueConstraint(
            "id",
            "accepted_by_judgment_run_id",
            "collection_id",
            "concept_node_id",
            "relation_type",
            name="uq_collection_concept_candidates_wide_formal_gate",
        ),
        Index("idx_collection_concept_candidates_collection", "collection_id"),
        Index("idx_collection_concept_candidates_concept_node", "concept_node_id"),
        Index("idx_collection_concept_candidates_status", "candidate_status"),
        Index("idx_collection_concept_candidates_relation_type", "relation_type"),
        Index("idx_collection_concept_candidates_created_by_run", "created_by_judgment_run_id"),
        Index("idx_collection_concept_candidates_latest_run", "latest_judgment_run_id"),
        Index("idx_collection_concept_candidates_accepted_run", "accepted_by_judgment_run_id"),
        Index("idx_collection_concept_candidates_created_by", "created_by"),
        Index("idx_collection_concept_candidates_reviewed_by", "reviewed_by"),
        Index(
            "uq_collection_concept_candidates_open_candidate",
            "collection_id",
            "concept_node_id",
            "relation_type",
            unique=True,
            postgresql_where=text("candidate_status IN ('proposed', 'needs_review')"),
        ),
    )


class RouteConceptLink(Base):
    """路线-概念正式关系表——只保存已经被人工 review 盖章的 route 与 concept 关系。"""

    __tablename__ = "route_concept_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    route_book_id = Column(Integer, nullable=False)
    route_version_id = Column(Integer, nullable=False)
    route_line_hash = Column(String(64), nullable=False)
    concept_node_id = Column(Integer, nullable=False)
    relation_type = Column(String(32), nullable=False)
    link_status = Column(String(16), nullable=False, server_default="active")
    source_kind = Column(String(32), nullable=False)
    accepted_judgment_run_id = Column(Integer, nullable=False)
    accepted_judgment_run_type = Column(String(32), nullable=False, server_default="human_review")
    source_route_concept_candidate_id = Column(Integer, nullable=True)
    display_priority = Column(Integer, nullable=True)
    reason_summary = Column(Text, nullable=True)
    metadata_json = Column(JSONB, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", name="fk_route_concept_links_created_by", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(["route_book_id"], ["route_books.id"], name="fk_route_concept_links_route_book"),
        ForeignKeyConstraint(
            ["route_version_id", "route_book_id"],
            ["route_versions.id", "route_versions.route_book_id"],
            name="fk_route_concept_links_route_version_book",
        ),
        ForeignKeyConstraint(["concept_node_id"], ["concept_nodes.id"], name="fk_route_concept_links_concept_node"),
        ForeignKeyConstraint(
            ["accepted_judgment_run_id", "accepted_judgment_run_type"],
            ["judgment_runs.id", "judgment_runs.run_type"],
            name="fk_route_concept_links_accepted_judgment_run",
        ),
        ForeignKeyConstraint(
            [
                "source_route_concept_candidate_id",
                "accepted_judgment_run_id",
                "route_book_id",
                "route_version_id",
                "route_line_hash",
                "concept_node_id",
                "relation_type",
            ],
            [
                "route_concept_candidates.id",
                "route_concept_candidates.accepted_by_judgment_run_id",
                "route_concept_candidates.route_book_id",
                "route_concept_candidates.route_version_id",
                "route_concept_candidates.route_line_hash",
                "route_concept_candidates.concept_node_id",
                "route_concept_candidates.relation_type",
            ],
            name="fk_route_concept_links_source_candidate_wide",
        ),
        CheckConstraint(
            "relation_type IN ('suitable_for', 'passes_near', 'has_feature', 'has_risk', "
            "'part_of_event', 'story_reference', 'training_theme', 'local_name', 'associated_with')",
            name="ck_route_concept_links_relation_type",
        ),
        CheckConstraint(
            "link_status IN ('active', 'deprecated', 'superseded')",
            name="ck_route_concept_links_link_status",
        ),
        CheckConstraint(
            "source_kind IN ('candidate_accepted', 'manual_curated', 'legacy_import')",
            name="ck_route_concept_links_source_kind",
        ),
        CheckConstraint(
            "accepted_judgment_run_type = 'human_review'",
            name="ck_route_concept_links_accepted_judgment_run_type",
        ),
        CheckConstraint(
            "((source_kind = 'candidate_accepted' AND source_route_concept_candidate_id IS NOT NULL) OR "
            "(source_kind IN ('manual_curated', 'legacy_import') AND source_route_concept_candidate_id IS NULL))",
            name="ck_route_concept_links_source_gate",
        ),
        UniqueConstraint("source_route_concept_candidate_id", name="uq_route_concept_links_source_candidate"),
        Index("idx_route_concept_links_route_book_id", "route_book_id"),
        Index("idx_route_concept_links_route_version_id", "route_version_id"),
        Index("idx_route_concept_links_concept_node", "concept_node_id"),
        Index("idx_route_concept_links_relation_type", "relation_type"),
        Index("idx_route_concept_links_status", "link_status"),
        Index("idx_route_concept_links_source_kind", "source_kind"),
        Index("idx_route_concept_links_accepted_judgment", "accepted_judgment_run_id"),
        Index("idx_route_concept_links_source_candidate", "source_route_concept_candidate_id"),
        Index("idx_route_concept_links_created_by", "created_by"),
        Index(
            "uq_route_concept_links_active",
            "route_book_id",
            "route_version_id",
            "concept_node_id",
            "relation_type",
            unique=True,
            postgresql_where=text("link_status = 'active'"),
        ),
    )


class SegmentConceptLink(Base):
    """赛段-概念正式关系表——segment 必须先进入路线认知白名单才能建立正式概念关系。"""

    __tablename__ = "segment_concept_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    segment_id = Column(Integer, nullable=False)
    segment_geometry_hash = Column(String(64), nullable=False)
    concept_node_id = Column(Integer, nullable=False)
    relation_type = Column(String(32), nullable=False)
    link_status = Column(String(16), nullable=False, server_default="active")
    source_kind = Column(String(32), nullable=False)
    accepted_judgment_run_id = Column(Integer, nullable=False)
    accepted_judgment_run_type = Column(String(32), nullable=False, server_default="human_review")
    source_segment_concept_candidate_id = Column(Integer, nullable=True)
    display_priority = Column(Integer, nullable=True)
    reason_summary = Column(Text, nullable=True)
    metadata_json = Column(JSONB, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", name="fk_segment_concept_links_created_by", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(["segment_id"], ["route_cognition_segments.segment_id"], name="fk_segment_concept_links_segment"),
        ForeignKeyConstraint(["concept_node_id"], ["concept_nodes.id"], name="fk_segment_concept_links_concept_node"),
        ForeignKeyConstraint(
            ["accepted_judgment_run_id", "accepted_judgment_run_type"],
            ["judgment_runs.id", "judgment_runs.run_type"],
            name="fk_segment_concept_links_accepted_judgment_run",
        ),
        ForeignKeyConstraint(
            [
                "source_segment_concept_candidate_id",
                "accepted_judgment_run_id",
                "segment_id",
                "segment_geometry_hash",
                "concept_node_id",
                "relation_type",
            ],
            [
                "segment_concept_candidates.id",
                "segment_concept_candidates.accepted_by_judgment_run_id",
                "segment_concept_candidates.segment_id",
                "segment_concept_candidates.segment_geometry_hash",
                "segment_concept_candidates.concept_node_id",
                "segment_concept_candidates.relation_type",
            ],
            name="fk_segment_concept_links_source_candidate_wide",
        ),
        CheckConstraint(
            "relation_type IN ('suitable_for', 'passes_near', 'has_feature', 'has_risk', "
            "'part_of_event', 'story_reference', 'training_theme', 'local_name', 'associated_with')",
            name="ck_segment_concept_links_relation_type",
        ),
        CheckConstraint(
            "link_status IN ('active', 'deprecated', 'superseded')",
            name="ck_segment_concept_links_link_status",
        ),
        CheckConstraint(
            "source_kind IN ('candidate_accepted', 'manual_curated', 'legacy_import')",
            name="ck_segment_concept_links_source_kind",
        ),
        CheckConstraint(
            "accepted_judgment_run_type = 'human_review'",
            name="ck_segment_concept_links_accepted_judgment_run_type",
        ),
        CheckConstraint(
            "((source_kind = 'candidate_accepted' AND source_segment_concept_candidate_id IS NOT NULL) OR "
            "(source_kind IN ('manual_curated', 'legacy_import') AND source_segment_concept_candidate_id IS NULL))",
            name="ck_segment_concept_links_source_gate",
        ),
        UniqueConstraint("source_segment_concept_candidate_id", name="uq_segment_concept_links_source_candidate"),
        Index("idx_segment_concept_links_segment_id", "segment_id"),
        Index("idx_segment_concept_links_concept_node", "concept_node_id"),
        Index("idx_segment_concept_links_relation_type", "relation_type"),
        Index("idx_segment_concept_links_status", "link_status"),
        Index("idx_segment_concept_links_source_kind", "source_kind"),
        Index("idx_segment_concept_links_accepted_judgment", "accepted_judgment_run_id"),
        Index("idx_segment_concept_links_source_candidate", "source_segment_concept_candidate_id"),
        Index("idx_segment_concept_links_created_by", "created_by"),
        Index(
            "uq_segment_concept_links_active",
            "segment_id",
            "concept_node_id",
            "relation_type",
            unique=True,
            postgresql_where=text("link_status = 'active'"),
        ),
    )


class CollectionConceptLink(Base):
    """路线专题-概念正式关系表——collection 与 concept 的正式关系档案。"""

    __tablename__ = "collection_concept_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    collection_id = Column(Integer, nullable=False)
    concept_node_id = Column(Integer, nullable=False)
    relation_type = Column(String(32), nullable=False)
    link_status = Column(String(16), nullable=False, server_default="active")
    source_kind = Column(String(32), nullable=False)
    accepted_judgment_run_id = Column(Integer, nullable=False)
    accepted_judgment_run_type = Column(String(32), nullable=False, server_default="human_review")
    source_collection_concept_candidate_id = Column(Integer, nullable=True)
    display_priority = Column(Integer, nullable=True)
    reason_summary = Column(Text, nullable=True)
    metadata_json = Column(JSONB, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", name="fk_collection_concept_links_created_by", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(["collection_id"], ["route_collections.id"], name="fk_collection_concept_links_collection"),
        ForeignKeyConstraint(["concept_node_id"], ["concept_nodes.id"], name="fk_collection_concept_links_concept_node"),
        ForeignKeyConstraint(
            ["accepted_judgment_run_id", "accepted_judgment_run_type"],
            ["judgment_runs.id", "judgment_runs.run_type"],
            name="fk_collection_concept_links_accepted_judgment_run",
        ),
        ForeignKeyConstraint(
            [
                "source_collection_concept_candidate_id",
                "accepted_judgment_run_id",
                "collection_id",
                "concept_node_id",
                "relation_type",
            ],
            [
                "collection_concept_candidates.id",
                "collection_concept_candidates.accepted_by_judgment_run_id",
                "collection_concept_candidates.collection_id",
                "collection_concept_candidates.concept_node_id",
                "collection_concept_candidates.relation_type",
            ],
            name="fk_collection_concept_links_source_candidate_wide",
        ),
        CheckConstraint(
            "relation_type IN ('suitable_for', 'passes_near', 'has_feature', 'has_risk', "
            "'part_of_event', 'story_reference', 'training_theme', 'local_name', 'associated_with')",
            name="ck_collection_concept_links_relation_type",
        ),
        CheckConstraint(
            "link_status IN ('active', 'deprecated', 'superseded')",
            name="ck_collection_concept_links_link_status",
        ),
        CheckConstraint(
            "source_kind IN ('candidate_accepted', 'manual_curated', 'legacy_import')",
            name="ck_collection_concept_links_source_kind",
        ),
        CheckConstraint(
            "accepted_judgment_run_type = 'human_review'",
            name="ck_collection_concept_links_accepted_judgment_run_type",
        ),
        CheckConstraint(
            "((source_kind = 'candidate_accepted' AND source_collection_concept_candidate_id IS NOT NULL) OR "
            "(source_kind IN ('manual_curated', 'legacy_import') AND source_collection_concept_candidate_id IS NULL))",
            name="ck_collection_concept_links_source_gate",
        ),
        UniqueConstraint("source_collection_concept_candidate_id", name="uq_collection_concept_links_source_candidate"),
        Index("idx_collection_concept_links_collection_id", "collection_id"),
        Index("idx_collection_concept_links_concept_node", "concept_node_id"),
        Index("idx_collection_concept_links_relation_type", "relation_type"),
        Index("idx_collection_concept_links_status", "link_status"),
        Index("idx_collection_concept_links_source_kind", "source_kind"),
        Index("idx_collection_concept_links_accepted_judgment", "accepted_judgment_run_id"),
        Index("idx_collection_concept_links_source_candidate", "source_collection_concept_candidate_id"),
        Index("idx_collection_concept_links_created_by", "created_by"),
        Index(
            "uq_collection_concept_links_active",
            "collection_id",
            "concept_node_id",
            "relation_type",
            unique=True,
            postgresql_where=text("link_status = 'active'"),
        ),
    )


class RouteSegment(Base):
    """路线成员段表——记录一版路线由哪些正式 segment 或人工线段拼成。

    它像路线图纸旁边的“装配清单”：说明第几段用哪个白名单 segment 或哪条人工线；
    真正的路线几何仍以 `route_versions.reference_line_snapshot` 为准，这里不能反向改路线图纸。
    """

    __tablename__ = "route_segments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    route_book_id = Column(Integer, nullable=False)
    route_version_id = Column(Integer, nullable=False)
    route_line_hash = Column(String(64), nullable=False)
    seq = Column(Integer, nullable=False)
    component_type = Column(String(32), nullable=False)
    segment_id = Column(Integer, nullable=True)
    segment_geometry_hash = Column(String(64), nullable=True)
    component_geometry = Column(Geometry("GEOMETRY", srid=4326, spatial_index=False), nullable=False)
    component_geometry_hash = Column(String(64), nullable=False)
    direction = Column(String(16), nullable=True)
    start_fraction = Column(Numeric(8, 7), nullable=True)
    end_fraction = Column(Numeric(8, 7), nullable=True)
    membership_status = Column(String(16), nullable=False, server_default="active")
    source_kind = Column(String(32), nullable=False)
    source_ref = Column(Text, nullable=True)
    accepted_judgment_run_id = Column(Integer, nullable=False)
    accepted_judgment_run_type = Column(String(32), nullable=False, server_default="human_review")
    display_priority = Column(Integer, nullable=True)
    reason_summary = Column(Text, nullable=True)
    metadata_json = Column(JSONB, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", name="fk_route_segments_created_by", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(["route_book_id"], ["route_books.id"], name="fk_route_segments_route_book"),
        ForeignKeyConstraint(
            ["route_version_id", "route_book_id"],
            ["route_versions.id", "route_versions.route_book_id"],
            name="fk_route_segments_route_version_book",
        ),
        ForeignKeyConstraint(["segment_id"], ["route_cognition_segments.segment_id"], name="fk_route_segments_segment"),
        ForeignKeyConstraint(
            ["segment_id", "segment_geometry_hash"],
            ["route_cognition_segments.segment_id", "route_cognition_segments.geometry_hash"],
            name="fk_route_segments_segment_hash",
        ),
        ForeignKeyConstraint(
            ["accepted_judgment_run_id", "accepted_judgment_run_type"],
            ["judgment_runs.id", "judgment_runs.run_type"],
            name="fk_route_segments_accepted_judgment_run",
        ),
        CheckConstraint("seq >= 1", name="ck_route_segments_seq_positive"),
        CheckConstraint(
            "component_type IN ('segment_clip', 'custom_geometry')",
            name="ck_route_segments_component_type",
        ),
        CheckConstraint(
            "membership_status IN ('active', 'deprecated', 'superseded')",
            name="ck_route_segments_membership_status",
        ),
        CheckConstraint(
            "source_kind IN ('manual_curated', 'legacy_import')",
            name="ck_route_segments_source_kind",
        ),
        CheckConstraint(
            "accepted_judgment_run_type = 'human_review'",
            name="ck_route_segments_accepted_judgment_run_type",
        ),
        CheckConstraint(
            "source_kind <> 'legacy_import' OR source_ref IS NOT NULL OR reason_summary IS NOT NULL",
            name="ck_route_segments_legacy_source",
        ),
        CheckConstraint(
            "display_priority IS NULL OR (display_priority >= 0 AND display_priority <= 100)",
            name="ck_route_segments_display_priority_range",
        ),
        CheckConstraint(
            "((component_type = 'segment_clip' "
            "AND segment_id IS NOT NULL "
            "AND segment_geometry_hash IS NOT NULL "
            "AND component_geometry IS NOT NULL "
            "AND component_geometry_hash IS NOT NULL "
            "AND direction IN ('forward', 'reverse')) "
            "OR (component_type = 'custom_geometry' "
            "AND segment_id IS NULL "
            "AND segment_geometry_hash IS NULL "
            "AND component_geometry IS NOT NULL "
            "AND component_geometry_hash IS NOT NULL "
            "AND direction IS NULL))",
            name="ck_route_segments_component_contract",
        ),
        CheckConstraint(
            "((start_fraction IS NULL AND end_fraction IS NULL) OR "
            "(component_type = 'segment_clip' "
            "AND start_fraction IS NOT NULL "
            "AND end_fraction IS NOT NULL "
            "AND start_fraction >= 0 "
            "AND end_fraction <= 1 "
            "AND start_fraction < end_fraction))",
            name="ck_route_segments_fraction_range",
        ),
        CheckConstraint(
            "ST_IsValid(component_geometry) "
            "AND upper(replace(GeometryType(component_geometry), 'ST_', '')) IN "
            "('LINESTRING', 'MULTILINESTRING')",
            name="ck_route_segments_component_geometry_valid_type",
        ),
        Index("idx_route_segments_route_version", "route_version_id"),
        Index("idx_route_segments_segment", "segment_id"),
        Index("idx_route_segments_status", "membership_status"),
        Index("idx_route_segments_accepted_judgment", "accepted_judgment_run_id"),
        Index("idx_route_segments_geom", "component_geometry", postgresql_using="gist"),
        Index(
            "uq_route_segments_active_seq",
            "route_book_id",
            "route_version_id",
            "seq",
            unique=True,
            postgresql_where=text("membership_status = 'active'"),
        ),
    )


class CollectionRoute(Base):
    """路线专题-路线成员表——记录 collection 正式收录哪些路线。"""

    __tablename__ = "collection_routes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    collection_id = Column(Integer, nullable=False)
    route_book_id = Column(Integer, nullable=False)
    reviewed_route_version_id = Column(Integer, nullable=False)
    reviewed_route_line_hash = Column(String(64), nullable=False)
    role = Column(String(32), nullable=False)
    seq = Column(Integer, nullable=True)
    importance = Column(Integer, nullable=True)
    membership_status = Column(String(16), nullable=False, server_default="active")
    source_kind = Column(String(32), nullable=False)
    source_ref = Column(Text, nullable=True)
    accepted_judgment_run_id = Column(Integer, nullable=False)
    accepted_judgment_run_type = Column(String(32), nullable=False, server_default="human_review")
    display_priority = Column(Integer, nullable=True)
    reason_summary = Column(Text, nullable=True)
    metadata_json = Column(JSONB, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", name="fk_collection_routes_created_by", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(["collection_id"], ["route_collections.id"], name="fk_collection_routes_collection"),
        ForeignKeyConstraint(["route_book_id"], ["route_books.id"], name="fk_collection_routes_route_book"),
        ForeignKeyConstraint(
            ["reviewed_route_version_id", "route_book_id"],
            ["route_versions.id", "route_versions.route_book_id"],
            name="fk_collection_routes_route_version_book",
        ),
        ForeignKeyConstraint(
            ["accepted_judgment_run_id", "accepted_judgment_run_type"],
            ["judgment_runs.id", "judgment_runs.run_type"],
            name="fk_collection_routes_accepted_judgment_run",
        ),
        CheckConstraint(
            "role IN ('primary', 'featured', 'alternate', 'connector', 'reference', 'supporting')",
            name="ck_collection_routes_role",
        ),
        CheckConstraint(
            "membership_status IN ('active', 'deprecated', 'superseded')",
            name="ck_collection_routes_membership_status",
        ),
        CheckConstraint(
            "source_kind IN ('manual_curated', 'legacy_import')",
            name="ck_collection_routes_source_kind",
        ),
        CheckConstraint(
            "accepted_judgment_run_type = 'human_review'",
            name="ck_collection_routes_accepted_judgment_run_type",
        ),
        CheckConstraint(
            "source_kind <> 'legacy_import' OR source_ref IS NOT NULL OR reason_summary IS NOT NULL",
            name="ck_collection_routes_legacy_source",
        ),
        CheckConstraint("seq IS NULL OR seq >= 1", name="ck_collection_routes_seq_positive"),
        CheckConstraint(
            "importance IS NULL OR (importance >= 0 AND importance <= 100)",
            name="ck_collection_routes_importance_range",
        ),
        CheckConstraint(
            "display_priority IS NULL OR (display_priority >= 0 AND display_priority <= 100)",
            name="ck_collection_routes_display_priority_range",
        ),
        Index("idx_collection_routes_collection", "collection_id"),
        Index("idx_collection_routes_route_book", "route_book_id"),
        Index("idx_collection_routes_reviewed_route_version", "reviewed_route_version_id"),
        Index("idx_collection_routes_status", "membership_status"),
        Index("idx_collection_routes_accepted_judgment", "accepted_judgment_run_id"),
        Index(
            "uq_collection_routes_active_route",
            "collection_id",
            "route_book_id",
            unique=True,
            postgresql_where=text("membership_status = 'active'"),
        ),
        Index(
            "uq_collection_routes_active_seq",
            "collection_id",
            "seq",
            unique=True,
            postgresql_where=text("membership_status = 'active' AND seq IS NOT NULL"),
        ),
    )


class CollectionSegment(Base):
    """路线专题-segment 成员表——collection 只能收录已经进入白名单的正式 segment。"""

    __tablename__ = "collection_segments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    collection_id = Column(Integer, nullable=False)
    segment_id = Column(Integer, nullable=False)
    segment_geometry_hash = Column(String(64), nullable=False)
    role = Column(String(32), nullable=False)
    seq = Column(Integer, nullable=True)
    importance = Column(Integer, nullable=True)
    membership_status = Column(String(16), nullable=False, server_default="active")
    source_kind = Column(String(32), nullable=False)
    source_ref = Column(Text, nullable=True)
    accepted_judgment_run_id = Column(Integer, nullable=False)
    accepted_judgment_run_type = Column(String(32), nullable=False, server_default="human_review")
    display_priority = Column(Integer, nullable=True)
    reason_summary = Column(Text, nullable=True)
    metadata_json = Column(JSONB, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", name="fk_collection_segments_created_by", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(["collection_id"], ["route_collections.id"], name="fk_collection_segments_collection"),
        ForeignKeyConstraint(["segment_id"], ["route_cognition_segments.segment_id"], name="fk_collection_segments_segment"),
        ForeignKeyConstraint(
            ["segment_id", "segment_geometry_hash"],
            ["route_cognition_segments.segment_id", "route_cognition_segments.geometry_hash"],
            name="fk_collection_segments_segment_hash",
        ),
        ForeignKeyConstraint(
            ["accepted_judgment_run_id", "accepted_judgment_run_type"],
            ["judgment_runs.id", "judgment_runs.run_type"],
            name="fk_collection_segments_accepted_judgment_run",
        ),
        CheckConstraint(
            "role IN ('core', 'connector', 'landmark', 'risk_area', 'training_interval', 'supporting')",
            name="ck_collection_segments_role",
        ),
        CheckConstraint(
            "membership_status IN ('active', 'deprecated', 'superseded')",
            name="ck_collection_segments_membership_status",
        ),
        CheckConstraint(
            "source_kind IN ('manual_curated', 'legacy_import')",
            name="ck_collection_segments_source_kind",
        ),
        CheckConstraint(
            "accepted_judgment_run_type = 'human_review'",
            name="ck_collection_segments_accepted_judgment_run_type",
        ),
        CheckConstraint(
            "source_kind <> 'legacy_import' OR source_ref IS NOT NULL OR reason_summary IS NOT NULL",
            name="ck_collection_segments_legacy_source",
        ),
        CheckConstraint("seq IS NULL OR seq >= 1", name="ck_collection_segments_seq_positive"),
        CheckConstraint(
            "importance IS NULL OR (importance >= 0 AND importance <= 100)",
            name="ck_collection_segments_importance_range",
        ),
        CheckConstraint(
            "display_priority IS NULL OR (display_priority >= 0 AND display_priority <= 100)",
            name="ck_collection_segments_display_priority_range",
        ),
        Index("idx_collection_segments_collection", "collection_id"),
        Index("idx_collection_segments_segment", "segment_id"),
        Index("idx_collection_segments_status", "membership_status"),
        Index("idx_collection_segments_accepted_judgment", "accepted_judgment_run_id"),
        Index(
            "uq_collection_segments_active_segment",
            "collection_id",
            "segment_id",
            unique=True,
            postgresql_where=text("membership_status = 'active'"),
        ),
        Index(
            "uq_collection_segments_active_seq",
            "collection_id",
            "seq",
            unique=True,
            postgresql_where=text("membership_status = 'active' AND seq IS NOT NULL"),
        ),
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
        UniqueConstraint(
            "segment_id",
            "geometry_hash",
            name="uq_route_cognition_segments_segment_geometry_hash",
        ),
        Index("idx_route_cognition_segments_eligibility", "eligibility_status"),
        Index("idx_route_cognition_segments_review_basis", "review_basis"),
        Index("idx_route_cognition_segments_judgment", "accepted_judgment_run_id"),
        Index("idx_route_cognition_segments_reviewed_by", "reviewed_by"),
        Index("idx_route_cognition_segments_geometry_hash", "geometry_hash"),
    )
