from __future__ import annotations

from copy import deepcopy

from app.route_cognition.transit_paths import canonical_sha256
from scripts.analyze_xishan_route_heat import _route_hard_failures


def _with_hash(payload: dict, field: str) -> dict:
    payload[field] = canonical_sha256(payload)
    return payload


def _inputs() -> tuple[dict, dict, dict, dict, dict, dict]:
    geometry_hash = "a" * 64
    exit_port = {
        "module_key": "taiyuan_xishan_hengling",
        "port_key": "full-ascent:upper-observation-boundary-exit",
        "port_sha256": "b" * 64,
        "reference_source_geometry_hash": geometry_hash,
    }
    ascent = {"blockers": [], "traversal_ports": [{"exit": exit_port}]}
    mountain = _with_hash({"module_key": "taiyuan_xishan_hengling"}, "run_sha256")
    transit = _with_hash(
        {
            "transit_key": "hengling-upper-to-taohuagou-huaketou",
            "research_verdict": "connection_candidate",
            "from": {
                "module_key": exit_port["module_key"],
                "port_key": exit_port["port_key"],
                "module_port_sha256": exit_port["port_sha256"],
                "lonlat": [112.4, 38.0],
            },
            "to": {
                "source_observation_id": 6,
                "source_geometry_hash": "c" * 64,
                "lonlat": [112.3, 37.8],
            },
        },
        "result_sha256",
    )
    source_slice = _with_hash({"observations": []}, "slice_sha256")
    hengling = {
        "source_geometry_hash": geometry_hash,
        "source_geometry_lonlat": [[112.5, 38.0], [112.4, 38.0]],
    }
    taohuagou = {
        "source_geometry_hash": "c" * 64,
        "source_geometry_lonlat": [[112.3, 37.8], [112.2, 37.7]],
    }
    return mountain, transit, source_slice, ascent, hengling, taohuagou


def test_route_hard_gate_accepts_exact_bound_inputs() -> None:
    assert _route_hard_failures(*_inputs()) == ()


def test_route_hard_gate_rejects_wrong_connection_even_with_new_self_hash() -> None:
    inputs = list(_inputs())
    transit = deepcopy(inputs[1])
    transit["from"]["lonlat"] = [0.0, 0.0]
    transit.pop("result_sha256")
    inputs[1] = _with_hash(transit, "result_sha256")
    assert "full_ascent_exit_not_joined_to_transit" in _route_hard_failures(*inputs)


def test_route_hard_gate_rejects_wrong_transit_identity_and_verdict() -> None:
    inputs = list(_inputs())
    transit = deepcopy(inputs[1])
    transit["transit_key"] = "wrong-path"
    transit["research_verdict"] = "blocked"
    transit.pop("result_sha256")
    inputs[1] = _with_hash(transit, "result_sha256")
    failures = _route_hard_failures(*inputs)
    assert "unexpected_transit_path" in failures
    assert "transit_not_connection_candidate" in failures
