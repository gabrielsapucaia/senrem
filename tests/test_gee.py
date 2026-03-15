import pytest
from backend.services.gee import GEEService


@pytest.fixture(scope="module")
def gee():
    return GEEService()


def test_gee_initializes(gee):
    assert gee.ee is not None


def test_study_area_geometry(gee):
    bbox = gee.get_study_area_bbox()
    assert "type" in bbox
    assert bbox["type"] == "Polygon"


def test_get_tile_url_rgb_true(gee):
    result = gee.get_layer_tiles("rgb-true")
    assert "tile_url" in result
    assert "{z}" in result["tile_url"]
    assert "name" in result
