import numpy as np
import os
import pytest
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS

from backend.services.tiles import TileService


@pytest.fixture
def sample_cog(tmp_path):
    """Cria um COG de teste com dados sinteticos."""
    path = str(tmp_path / "test.tif")
    data = np.random.rand(1, 256, 256).astype(np.float32)
    transform = from_bounds(-47.4, -11.9, -46.9, -11.5, 256, 256)
    with rasterio.open(
        path, "w", driver="GTiff",
        height=256, width=256, count=1, dtype="float32",
        crs=CRS.from_epsg(4326), transform=transform,
    ) as dst:
        dst.write(data)
    return path


def test_tile_service_init():
    service = TileService(processed_dir="/tmp/nonexistent")
    assert service.processed_dir == "/tmp/nonexistent"


def test_get_tile_from_cog(sample_cog):
    service = TileService(processed_dir=os.path.dirname(sample_cog))
    layer_id = "test"
    # Registrar o COG manualmente
    service.register_cog(layer_id, sample_cog)
    tile_bytes = service.get_tile(layer_id, z=10, x=377, y=545)
    assert tile_bytes is not None
    assert len(tile_bytes) > 0


def test_get_tile_unknown_layer():
    service = TileService(processed_dir="/tmp")
    with pytest.raises(ValueError, match="nao registrada"):
        service.get_tile("unknown", z=10, x=300, y=500)
