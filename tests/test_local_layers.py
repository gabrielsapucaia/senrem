import numpy as np
import os
import pytest
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS
from fastapi.testclient import TestClient


def test_layers_list_includes_local():
    from backend.main import app
    client = TestClient(app)
    resp = client.get("/api/layers")
    assert resp.status_code == 200
    layers = resp.json()
    local_layers = [l for l in layers if l["source"] == "local"]
    assert len(local_layers) >= 6
    layer_ids = [l["id"] for l in local_layers]
    assert "crosta-feox" in layer_ids
    assert "crosta-oh" in layer_ids
    assert "ninomiya-aloh" in layer_ids


def test_local_layer_available_when_cog_exists(tmp_path):
    """Se o COG existe no cache, available=True."""
    from backend.api.layers import _check_local_available
    cog_path = str(tmp_path / "crosta-feox.tif")
    # Sem arquivo -> False
    assert _check_local_available("crosta-feox", str(tmp_path)) is False
    # Com arquivo -> True
    data = np.random.rand(1, 10, 10).astype(np.float32)
    transform = from_bounds(-47.4, -11.9, -46.9, -11.5, 10, 10)
    with rasterio.open(
        cog_path, "w", driver="GTiff",
        height=10, width=10, count=1, dtype="float32",
        crs=CRS.from_epsg(4326), transform=transform,
    ) as dst:
        dst.write(data)
    assert _check_local_available("crosta-feox", str(tmp_path)) is True
