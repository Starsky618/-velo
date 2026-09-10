"""The public demo must use the same GLO profile algorithm, without a DB write."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.website.router import ElevationPreviewRequest
from app.website import router as module


def test_rejects_outside_region_excessive_distance_and_invalid_points():
    for points in [[], [[0, 0], [0.1, 0.1]], [[112.4, 37.9]] * 2,
                   [[112.4, 37.9], [112.5, 37.8]] * 100,
                   [[112.4, 37.9]] * 2001, [[float('nan'), 37.9], [112.5, 37.9]]]:
        with pytest.raises(ValueError):
            ElevationPreviewRequest(points=points)


def test_public_profile_uses_real_processing_and_preserves_point_order(monkeypatch):
    monkeypatch.setattr(module, 'check_rate_limit_by_ip', lambda *a, **k: None)
    queries = []
    def elevations(points, **kwargs):
        queries.append((points, kwargs))
        return [800 + i * 2 for i in range(len(points))]
    monkeypatch.setattr(module, 'query_elevations', elevations)
    points = [[112.44, 37.98], [112.43, 37.985], [112.42, 37.99]]
    with TestClient(app) as client:
        response = client.post('/api/website/elevation-preview', json={'points': points})
    assert response.status_code == 200
    data = response.json()
    assert data['source'] == 'Copernicus GLO-30'
    assert data['method'] == 'glo30_meaningful_ascent_v1'
    assert len(data['elevations_m']) == len(points)
    assert data['climb_m'] > 0
    assert data['profile'][0][0] == 0
    assert queries[0][0][0] == (37.98, 112.44)  # DEM receives lat/lon.
    assert queries[0][1]['timeout_seconds'] == 20


def test_failure_and_rate_limit_do_not_return_fabricated_heights(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(module, 'check_rate_limit_by_ip', lambda *a, **k: None)
    monkeypatch.setattr(module, 'query_elevations', lambda points, **kwargs: [None] * len(points))
    payload = {'points': [[112.44, 37.98], [112.43, 37.985]]}
    with TestClient(app) as client:
        assert client.post('/api/website/elevation-preview', json=payload).status_code == 503
        monkeypatch.setattr(module, 'check_rate_limit_by_ip', lambda *a, **k: (_ for _ in ()).throw(HTTPException(429)))
        assert client.post('/api/website/elevation-preview', json=payload).status_code == 429


def test_busy_slots_are_bounded_and_released(monkeypatch):
    monkeypatch.setattr(module, 'check_rate_limit_by_ip', lambda *a, **k: None)
    assert module._slots.acquire(False)
    assert module._slots.acquire(False)
    try:
        with TestClient(app) as client:
            response = client.post('/api/website/elevation-preview', json={'points': [[112.44, 37.98], [112.43, 37.985]]})
        assert response.status_code == 503
    finally:
        module._slots.release()
        module._slots.release()
