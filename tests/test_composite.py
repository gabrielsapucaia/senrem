import numpy as np
import os
import pytest
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS

from backend.services.processing import ProcessingService


@pytest.fixture
def processing_service(tmp_path):
    return ProcessingService(output_dir=str(tmp_path))


@pytest.fixture
def sample_scenes(tmp_path):
    """Cria 3 cenas simuladas com 4 bandas cada."""
    transform = from_bounds(-47.4, -11.9, -46.9, -11.5, 50, 50)
    crs = CRS.from_epsg(4326)
    paths = []
    np.random.seed(42)
    for i in range(3):
        path = str(tmp_path / f"scene_{i}.tif")
        data = np.random.rand(4, 50, 50).astype(np.float32) + 0.1 + i * 0.1
        with rasterio.open(
            path, "w", driver="GTiff",
            height=50, width=50, count=4, dtype="float32",
            crs=crs, transform=transform,
        ) as dst:
            dst.write(data)
        paths.append(path)
    return paths


def test_build_composite_median(processing_service, sample_scenes, tmp_path):
    output_path = str(tmp_path / "composite.tif")
    processing_service.build_composite(
        scene_paths=sample_scenes,
        output_path=output_path,
        bands=[1, 2, 3, 4],
    )
    assert os.path.exists(output_path)
    with rasterio.open(output_path) as src:
        assert src.count == 4
        assert src.width == 50
        assert src.height == 50
        data = src.read()
        assert data.shape == (4, 50, 50)
        assert np.all(np.isfinite(data))


def test_composite_is_median(processing_service, sample_scenes, tmp_path):
    """Verifica que o composite e realmente a mediana."""
    output_path = str(tmp_path / "composite.tif")
    processing_service.build_composite(
        scene_paths=sample_scenes,
        output_path=output_path,
        bands=[1],
    )
    # Ler cenas originais e calcular mediana manualmente
    arrays = []
    for path in sample_scenes:
        with rasterio.open(path) as src:
            arrays.append(src.read(1))
    expected_median = np.median(arrays, axis=0)

    with rasterio.open(output_path) as src:
        actual = src.read(1)
    np.testing.assert_array_almost_equal(actual, expected_median, decimal=5)
