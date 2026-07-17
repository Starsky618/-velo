import numpy as np
from PIL import Image
import pytest


def test_glo30_tile_id_and_public_url_are_deterministic():
    from app.elevation.dem_client import (
        GLO30_DATASET_ID,
        GLO30_GRID_REGISTRATION,
        GLO30_VERTICAL_DATUM,
        _tile_id,
        _tile_key,
        _tile_url,
    )

    assert GLO30_DATASET_ID == "COP-DEM_GLO-30-DGED"
    assert GLO30_VERTICAL_DATUM == "EGM2008 (EPSG:3855)"
    assert GLO30_GRID_REGISTRATION == "RasterPixelIsPoint"
    assert _tile_id(37, 112) == "Copernicus_DSM_COG_10_N37_00_E112_00_DEM"
    assert _tile_id(-4, -73) == "Copernicus_DSM_COG_10_S04_00_W073_00_DEM"
    assert _tile_key(37.5, 112.5) == (37, 112)
    assert _tile_key(37.0, 112.0) == (36, 112)
    assert _tile_key(0.0, 112.0) == (-1, 112)
    assert _tile_key(-3.0, -72.5) == (-4, -73)
    assert _tile_url("https://example.test", 37, 112) == (
        "https://example.test/Copernicus_DSM_COG_10_N37_00_E112_00_DEM/"
        "Copernicus_DSM_COG_10_N37_00_E112_00_DEM.tif"
    )


def test_glo30_bilinear_sampling_matches_experiment_pixel_semantics():
    from app.elevation.dem_client import _sample_tile

    tile = np.asarray([[0.0, 10.0], [20.0, 30.0]], dtype=np.float32)

    assert _sample_tile(tile, south=0, west=0, lat=0.75, lon=0.25) == 15.0


def test_glo30_query_reads_cached_float_tiff_without_network(tmp_path, monkeypatch):
    from app.elevation import dem_client

    tile_id = dem_client._tile_id(37, 112)
    tile = np.arange(16, dtype=np.float32).reshape(4, 4)
    Image.fromarray(tile, mode="F").save(tmp_path / f"{tile_id}.tif")
    monkeypatch.setenv("GLO30_CACHE_DIR", str(tmp_path))
    dem_client._load_tile.cache_clear()

    values = dem_client.query_elevations(
        [(37.875, 112.125), (37.625, 112.375), (float("nan"), 112.0)]
    )

    assert values == [2.5, 7.5, None]
    dem_client._load_tile.cache_clear()


def test_glo30_download_is_atomic(tmp_path, monkeypatch):
    from app.elevation import dem_client

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            return iter((b"tile-", b"bytes"))

    monkeypatch.setattr(dem_client.httpx, "stream", lambda *_args, **_kwargs: FakeResponse())
    destination = tmp_path / "tile.tif"

    dem_client._download_tile("https://example.test/tile.tif", destination)

    assert destination.read_bytes() == b"tile-bytes"
    assert list(tmp_path.glob("*.part-*")) == []


def test_glo30_corrupt_cache_is_replaced_and_revalidated_once(tmp_path, monkeypatch):
    from app.elevation import dem_client

    tile_id = dem_client._tile_id(37, 112)
    destination = tmp_path / f"{tile_id}.tif"
    destination.write_bytes(b"not-a-tiff")
    downloads = []

    def fake_download(url, path):
        downloads.append(url)
        Image.fromarray(np.arange(16, dtype=np.float32).reshape(4, 4), mode="F").save(path)

    monkeypatch.setattr(dem_client, "_download_tile", fake_download)
    monkeypatch.setenv("GLO30_CACHE_DIR", str(tmp_path))
    dem_client._load_tile.cache_clear()

    values = dem_client.query_elevations([(37.875, 112.125)])

    assert values == [2.5]
    assert len(downloads) == 1
    with Image.open(destination) as recovered:
        assert recovered.size == (4, 4)
    dem_client._load_tile.cache_clear()


def test_glo30_corrupt_redownload_is_not_retried_or_left_cached(tmp_path, monkeypatch):
    from app.elevation import dem_client

    tile_id = dem_client._tile_id(37, 112)
    destination = tmp_path / f"{tile_id}.tif"
    destination.write_bytes(b"first-corrupt-tiff")
    downloads = []

    def fake_download(url, path):
        downloads.append(url)
        path.write_bytes(b"second-corrupt-tiff")

    monkeypatch.setattr(dem_client, "_download_tile", fake_download)
    monkeypatch.setenv("GLO30_CACHE_DIR", str(tmp_path))
    dem_client._load_tile.cache_clear()

    with pytest.raises(dem_client.DEMServiceError, match="重新下载修复失败"):
        dem_client.query_elevations([(37.875, 112.125)])

    assert len(downloads) == 1
    assert not destination.exists()
    dem_client._load_tile.cache_clear()
