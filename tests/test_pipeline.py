import pytest

from backend.services.pipeline import AsterPipeline


def test_pipeline_init(tmp_path):
    pipeline = AsterPipeline(
        data_dir=str(tmp_path),
        earthdata_username="test",
        earthdata_password="test",
        center_lon=-47.155531,
        center_lat=-11.699153,
        radius_km=25.0,
    )
    assert pipeline is not None


def test_pipeline_get_available_products(tmp_path):
    pipeline = AsterPipeline(
        data_dir=str(tmp_path),
        earthdata_username="",
        earthdata_password="",
        center_lon=-47.155531,
        center_lat=-11.699153,
        radius_km=25.0,
    )
    products = pipeline.get_required_products()
    assert "AST_07XT" in products
    assert "AST_08" in products


def test_pipeline_layer_to_product_mapping(tmp_path):
    pipeline = AsterPipeline(
        data_dir=str(tmp_path),
        earthdata_username="",
        earthdata_password="",
        center_lon=-47.155531,
        center_lat=-11.699153,
        radius_km=25.0,
    )
    assert pipeline.get_product_for_layer("crosta-feox") == "AST_07XT"
    assert pipeline.get_product_for_layer("crosta-oh") == "AST_07XT"
    assert pipeline.get_product_for_layer("pca-tir") == "AST_08"
    assert pipeline.get_product_for_layer("ninomiya-aloh") == "AST_07XT"
