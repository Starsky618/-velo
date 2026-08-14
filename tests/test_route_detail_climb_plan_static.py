"""公共路线详情页的 ClimbPlan 展示合同。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PAGE_DIR = ROOT / "miniprogram" / "pages" / "route-detail"


def test_public_route_detail_replaces_fake_whole_route_grade_with_climb_composition():
    js = (PAGE_DIR / "route-detail.js").read_text(encoding="utf-8")
    wxml = (PAGE_DIR / "route-detail.wxml").read_text(encoding="utf-8")
    wxss = (PAGE_DIR / "route-detail.wxss").read_text(encoding="utf-8")

    assert "climbPlanUi.buildView(guide.climb_plan, guide.rider_climb_plan)" in js
    assert "c / (d * 1000)" not in js
    assert "k: '显著爬坡'" in js
    assert "这条路线由哪些坡组成" in wxml
    assert "item.shapeLabels" in wxml
    assert ".climb-plan-card" in wxss


def test_public_route_stats_and_climb_cards_share_the_normalized_plan():
    script = f"""
      global.Page = function () {{}};
      global.wx = {{}};
      const page = require({json.dumps(str(PAGE_DIR / 'route-detail.js'))});
      const guide = {{
        distance: 52.3,
        climb: 920,
        climb_plan: {{
          algorithm_version: 'velo_climb_plan_v1',
          source: {{ confidence: 'terrain_estimate' }},
          composition: {{ climb_count: 2, sequence_label: 'Cat 2 + Cat 3', boundary_status: 'stable' }},
          climbs: [{{
            order: 1,
            category: '2',
            category_status: 'candidate',
            shape_label: '末段墙',
            shape_labels: ['末段墙'],
            start_distance_m: 10000,
            end_distance_m: 15000,
            length_m: 5000,
            average_grade_pct: 6.5,
            elevation_gain_m: 330,
            max_sustained_grade_pct: {{ '500m': 12.1 }}
          }}]
        }}
      }};
      console.log(JSON.stringify({{
        stats: page.buildStats(guide),
        view: page.buildClimbPlanView(guide.climb_plan, null)
      }}));
    """
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    assert [item["k"] for item in payload["stats"]] == ["距离", "爬升", "显著爬坡"]
    assert payload["view"]["sequence"] == "Cat 2 + Cat 3"
    assert payload["view"]["climbs"][0]["shape"] == "末段墙"
    assert payload["view"]["climbs"][0]["candidate"] is True


def test_climb_plan_ui_shows_actual_capped_power_range_and_multi_climb_boundary():
    utility = ROOT / "miniprogram" / "utils" / "climb-plan.js"
    script = f"""
      const ui = require({json.dumps(str(utility))});
      const plan = {{
        algorithm_version: 'velo_climb_plan_v1',
        source: {{}},
        composition: {{ sequence_label: 'Cat 2 + Cat 3', boundary_status: 'stable' }},
        climbs: []
      }};
      const rider = {{
        status: 'estimated',
        multi_climb_context: {{ status: 'pdc_cumulative_duration_no_recovery_credit' }},
        scenarios: [{{
          key: 'steady', label: '持续推进',
          target_power_w: 240, target_w_per_kg: 3.43,
          target_power_range_w: [240, 265],
          target_w_per_kg_range: [3.43, 3.79],
          estimated_climbing_time_min: 62,
          estimated_climbing_time_range_min: [57, 70],
          climbs: [
            {{ order: 1, target_power_w: 265 }},
            {{ order: 2, target_power_w: 240 }}
          ]
        }}]
      }};
      process.stdout.write(JSON.stringify(ui.buildView(plan, rider)));
    """
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    view = json.loads(completed.stdout)
    assert view["riderScenarios"][0]["power"] == "240–265W"
    assert view["riderScenarios"][0]["powerPerKg"] == "3.43–3.79W/kg"
    assert view["riderScenarios"][0]["climbTargets"] == "第1坡 265W · 第2坡 240W"
    assert "累计爬坡时长" in view["riderContextLine"]
    assert "CP/W′" in view["riderContextLine"]

    for page in ("route-book-detail", "route-detail", "route-draw"):
        wxml = (
            ROOT / "miniprogram" / "pages" / page / f"{page}.wxml"
        ).read_text(encoding="utf-8")
        assert "climbPlanView.riderContextLine" in wxml
