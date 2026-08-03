"""Fail-closed repository for grounded route traversals.

The repository deliberately accepts only recorded traversal objects.  It does
not derive geometry, names, metrics, access, closure state, or provenance from
content prose.  Records missing any grounding field stay visible in
``diagnostics`` but never enter planning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class EvidenceRef:
    evidence_ref: str
    status: str
    source_object_ref: str


@dataclass(frozen=True)
class GroundedMetric:
    value: float
    calculation_source_ref: str


@dataclass(frozen=True)
class Traversal:
    traversal_ref: str
    role: str
    composition_ref: str
    display_name: str
    path_ref: str
    start_anchor_ref: str
    end_anchor_ref: str
    source_object_ref: str
    revision_ref: str
    bicycle_access: str
    bicycle_access_evidence_ref: str
    closure_status: str
    closure_evidence_ref: str
    urban_exposure: str
    evidence: tuple[EvidenceRef, ...]
    distance_km: GroundedMetric
    climb_m: GroundedMetric
    estimated_minutes: GroundedMetric
    risk: str


class GroundedWorldRepository:
    """Read-only adapter that exposes only fully grounded Traversals."""

    REQUIRED_METRICS = ("distance_km", "climb_m", "estimated_minutes")
    ALLOWED_ROLES = {"access", "core", "return"}

    def __init__(self, world: Mapping[str, Any]):
        self.world = world
        self.diagnostics: dict[str, tuple[str, ...]] = {}

    def list_traversals(self) -> list[Traversal]:
        traversals: list[Traversal] = []
        self.diagnostics = {}
        for index, record in enumerate(self.world.get("traversals", [])):
            record_ref = str(record.get("traversal_ref") or f"record:{index}")
            errors = self._record_errors(record)
            if errors:
                self.diagnostics[record_ref] = tuple(errors)
                continue
            traversal = self._to_traversal(record)
            runtime_errors = self.eligibility_errors(traversal)
            if runtime_errors:
                self.diagnostics[record_ref] = tuple(runtime_errors)
                continue
            traversals.append(traversal)
        return traversals

    def get_traversal(self, traversal_ref: str) -> Traversal | None:
        return next(
            (
                traversal
                for traversal in self.list_traversals()
                if traversal.traversal_ref == traversal_ref
            ),
            None,
        )

    def eligibility_errors(self, traversal: Traversal) -> list[str]:
        errors: list[str] = []
        if traversal.role not in self.ALLOWED_ROLES:
            errors.append("unsupported traversal role")
        if traversal.bicycle_access != "permitted":
            errors.append("bicycle access is not permitted")
        if traversal.closure_status != "clear":
            errors.append("closure state is not clear")
        if not traversal.evidence or any(
            evidence.status != "accepted" for evidence in traversal.evidence
        ):
            errors.append("accepted evidence is required")
        accepted_evidence_refs = {
            evidence.evidence_ref
            for evidence in traversal.evidence
            if evidence.status == "accepted"
        }
        if traversal.bicycle_access_evidence_ref not in accepted_evidence_refs:
            errors.append("bicycle access fact requires accepted evidence")
        if traversal.closure_evidence_ref not in accepted_evidence_refs:
            errors.append("closure fact requires accepted evidence")
        if any(
            evidence.source_object_ref != traversal.source_object_ref
            for evidence in traversal.evidence
        ):
            errors.append("evidence does not trace to the traversal source object")
        if not traversal.revision_ref:
            errors.append("revision is required")
        current_revision = self.world.get("current_revisions", {}).get(
            traversal.source_object_ref
        )
        if current_revision != traversal.revision_ref:
            errors.append("revision is not current")
        for metric_name in self.REQUIRED_METRICS:
            metric = getattr(traversal, metric_name)
            if not metric.calculation_source_ref:
                errors.append(f"{metric_name} calculation source is required")
        if not traversal.start_anchor_ref or not traversal.end_anchor_ref:
            errors.append("both traversal anchors are required")
        if not traversal.path_ref:
            errors.append("recorded path ref is required")
        if not traversal.source_object_ref:
            errors.append("source object ref is required")
        return errors

    def _record_errors(self, record: Mapping[str, Any]) -> list[str]:
        errors: list[str] = []
        required_text = (
            "traversal_ref",
            "role",
            "composition_ref",
            "display_name",
            "path_ref",
            "start_anchor_ref",
            "end_anchor_ref",
            "source_object_ref",
            "revision_ref",
            "bicycle_access",
            "bicycle_access_evidence_ref",
            "closure_status",
            "closure_evidence_ref",
            "urban_exposure",
        )
        for field_name in required_text:
            if not isinstance(record.get(field_name), str) or not record[field_name]:
                errors.append(f"{field_name} is required")

        evidence = record.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append("accepted evidence is required")
        else:
            for item in evidence:
                if not isinstance(item, Mapping):
                    errors.append("evidence record is invalid")
                    continue
                if item.get("status") != "accepted":
                    errors.append("accepted evidence is required")
                if not item.get("evidence_ref") or not item.get("source_object_ref"):
                    errors.append("evidence provenance is required")

        metrics = record.get("metrics")
        if not isinstance(metrics, Mapping):
            errors.append("grounded metrics are required")
        else:
            for metric_name in self.REQUIRED_METRICS:
                metric = metrics.get(metric_name)
                if not isinstance(metric, Mapping):
                    errors.append(f"{metric_name} is required")
                    continue
                if not isinstance(metric.get("value"), (int, float)):
                    errors.append(f"{metric_name} value is required")
                if not metric.get("calculation_source_ref"):
                    errors.append(f"{metric_name} calculation source is required")
        return errors

    @staticmethod
    def _to_traversal(record: Mapping[str, Any]) -> Traversal:
        metrics = record["metrics"]
        return Traversal(
            traversal_ref=record["traversal_ref"],
            role=record["role"],
            composition_ref=record["composition_ref"],
            display_name=record["display_name"],
            path_ref=record["path_ref"],
            start_anchor_ref=record["start_anchor_ref"],
            end_anchor_ref=record["end_anchor_ref"],
            source_object_ref=record["source_object_ref"],
            revision_ref=record["revision_ref"],
            bicycle_access=record["bicycle_access"],
            bicycle_access_evidence_ref=record["bicycle_access_evidence_ref"],
            closure_status=record["closure_status"],
            closure_evidence_ref=record["closure_evidence_ref"],
            urban_exposure=record["urban_exposure"],
            evidence=tuple(
                EvidenceRef(
                    evidence_ref=item["evidence_ref"],
                    status=item["status"],
                    source_object_ref=item["source_object_ref"],
                )
                for item in record["evidence"]
            ),
            distance_km=GroundedMetric(**metrics["distance_km"]),
            climb_m=GroundedMetric(**metrics["climb_m"]),
            estimated_minutes=GroundedMetric(**metrics["estimated_minutes"]),
            risk=str(record.get("risk") or "未记录额外风险"),
        )
