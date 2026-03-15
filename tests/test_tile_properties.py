import numpy as np
import os
import pytest
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS
from fastapi.testclient import TestClient

from backend.main import app, tile_service

client = TestClient(app)


@pytest.fixture(autouse=True)
def register_test_cog(tmp_path, monkeypatch):
    """Cria um COG temporario e registra no tile_service."""
    cog_path = str(tmp_path / "test-layer.tif")
    data = np.random.rand(1, 256, 256).astype(np.float32)
    transform = from_bounds(-47.4, -11.9, -46.9, -11.5, 256, 256)
    with rasterio.open(
        cog_path, "w", driver="GTiff",
        height=256, width=256, count=1, dtype="float32",
        crs=CRS.from_epsg(4326), transform=transform,
    ) as dst:
        dst.write(data)
    tile_service.register_cog("test-layer", cog_path)
    yield
    if "test-layer" in tile_service._cog_registry:
        del tile_service._cog_registry["test-layer"]
        if "test-layer" in tile_service._stats:
            del tile_service._stats["test-layer"]


def test_tile_with_colormap_param():
    resp = client.get("/api/tiles/test-layer/8/94/136.png?colormap=magma")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"


def test_tile_with_vmin_vmax_params():
    resp = client.get("/api/tiles/test-layer/8/94/136.png?vmin=0.1&vmax=0.9")
    assert resp.status_code == 200


def test_tile_stats_endpoint():
    resp = client.get("/api/tiles/test-layer/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "p2" in data
    assert "p98" in data
    assert data["p2"] < data["p98"]


def test_tile_stats_unknown_layer():
    resp = client.get("/api/tiles/unknown-layer/stats")
    assert resp.status_code == 404
