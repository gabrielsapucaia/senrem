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
def sample_raster_data():
    """Simula um stack de bandas ASTER (4 bandas, 100x100 pixels)."""
    np.random.seed(42)
    return np.random.rand(4, 100, 100).astype(np.float32) + 0.1


@pytest.fixture
def sample_raster_file(tmp_path, sample_raster_data):
    """Cria um raster multi-banda de teste."""
    path = str(tmp_path / "input.tif")
    transform = from_bounds(-47.4, -11.9, -46.9, -11.5, 100, 100)
    with rasterio.open(
        path, "w", driver="GTiff",
        height=100, width=100, count=4, dtype="float32",
        crs=CRS.from_epsg(4326), transform=transform,
    ) as dst:
        dst.write(sample_raster_data)
    return path


def test_processing_service_init(processing_service):
    assert processing_service is not None


def test_pca(processing_service, sample_raster_data):
    """PCA deve retornar n_components componentes."""
    components, loadings, explained = processing_service.run_pca(
        sample_raster_data, n_components=3
    )
    assert components.shape == (3, 100, 100)
    assert loadings.shape == (3, 4)
    assert len(explained) == 3
    # Com n_components < n_bands, soma < 1.0; verificar que cada valor e positivo
    assert all(e > 0 for e in explained)
    assert sum(explained) <= 1.0


def test_crosta_select_component(processing_service, sample_raster_data):
    """Crosta deve selecionar a CP com maior peso na banda alvo."""
    components, loadings, _ = processing_service.run_pca(
        sample_raster_data, n_components=3
    )
    selected = processing_service.select_crosta_component(
        components, loadings, target_band=2, contrast_band=0
    )
    assert selected.shape == (100, 100)


def test_band_ratio(processing_service, sample_raster_data):
    """Ratio de duas bandas."""
    ratio = processing_service.compute_ratio(
        sample_raster_data[0], sample_raster_data[1]
    )
    assert ratio.shape == (100, 100)
    expected = sample_raster_data[0] / sample_raster_data[1]
    np.testing.assert_array_almost_equal(ratio, expected, decimal=5)


def test_ninomiya_aloh(processing_service, sample_raster_data):
    """AlOH index = B7 / (B6 * B8), simulado com bandas 0,1,2."""
    result = processing_service.ninomiya_aloh(
        b6=sample_raster_data[0],
        b7=sample_raster_data[1],
        b8=sample_raster_data[2],
    )
    assert result.shape == (100, 100)
    expected = sample_raster_data[1] / (sample_raster_data[0] * sample_raster_data[2])
    np.testing.assert_array_almost_equal(result, expected, decimal=5)


def test_save_as_cog(processing_service, sample_raster_data, tmp_path):
    """Salvar array como COG."""
    output_path = str(tmp_path / "output.tif")
    transform = from_bounds(-47.4, -11.9, -46.9, -11.5, 100, 100)
    crs = CRS.from_epsg(4326)
    processing_service.save_as_cog(
        sample_raster_data[0], output_path, transform=transform, crs=crs
    )
    assert os.path.exists(output_path)
    with rasterio.open(output_path) as src:
        assert src.count == 1
        assert src.width == 100
        assert src.height == 100
