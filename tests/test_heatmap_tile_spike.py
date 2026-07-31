from __future__ import annotations

from io import BytesIO
import importlib.util
from pathlib import Path

from PIL import Image, ImageDraw


_SPIKE_ROOT = Path(__file__).resolve().parents[1] / "experiments" / "heatmap-tile-spike"
_SPEC = importlib.util.spec_from_file_location("heatmap_tile_spike_serve", _SPIKE_ROOT / "serve.py")
assert _SPEC is not None and _SPEC.loader is not None
serve = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(serve)


def test_parse_tile_path_accepts_only_versioned_bounded_png_tiles():
    assert serve.parse_tile_path(
        "/live-tiles/g11-deadbeef/18/213000/101300.png?cache=1"
    ) == ("live-tiles", "g11-deadbeef", 18, 213000, 101300)
    assert serve.parse_tile_path(
        "/fallback-tiles/../../18/213000/101300.png"
    ) is None
    assert serve.parse_tile_path(
        "/live-tiles/g11-deadbeef/18/999999/101300.png"
    ) is None


def test_parent_fallback_crops_the_requested_child_quadrant(tmp_path):
    parent = serve.tile_path(tmp_path, "g11-test", 14, 100, 200)
    parent.parent.mkdir(parents=True)
    image = Image.new("RGBA", (256, 256), (255, 0, 0, 255))
    ImageDraw.Draw(image).rectangle((128, 0, 255, 127), fill=(0, 0, 255, 255))
    image.save(parent)

    payload = serve.render_parent_fallback(
        tmp_path,
        "g11-test",
        15,
        201,
        400,
        min_zoom=11,
    )

    assert payload is not None
    with Image.open(BytesIO(payload)) as child:
        assert child.size == (256, 256)
        assert child.getpixel((128, 128))[:3] == (0, 0, 255)


def test_parent_fallback_keeps_overzoomed_line_near_original_width(tmp_path):
    parent = serve.tile_path(tmp_path, "g11-test", 15, 10, 20)
    parent.parent.mkdir(parents=True)
    image = Image.new("RGBA", (512, 512), (255, 0, 0, 0))
    ImageDraw.Draw(image).line((100, 0, 100, 511), fill=(255, 0, 0, 255), width=3)
    image.save(parent)

    payload = serve.render_parent_fallback(
        tmp_path,
        "g11-test",
        18,
        81,
        160,
        min_zoom=11,
    )

    assert payload is not None
    with Image.open(BytesIO(payload)) as child:
        alpha_bounds = child.getchannel("A").getbbox()
        assert alpha_bounds is not None
        assert alpha_bounds[2] - alpha_bounds[0] <= 6


def test_spike_uses_stable_parent_and_lazy_detail_layers():
    source = (_SPIKE_ROOT / "app.js").read_text(encoding="utf-8")

    assert "fallback-tiles/" in source
    assert "live-tiles/" in source
    assert "fallbackHeatLayer" in source
    assert "detailHeatLayer" in source
    assert "fallbackHeatLayer.setVisible(heatVisible)" in source
    assert "detailHeatLayer.setVisible(heatVisible)" in source
