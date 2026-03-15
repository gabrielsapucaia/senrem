import os
import pytest

from backend.services.aster import AsterService, BAND_SUFFIXES
from backend.config import settings


def test_aster_service_init(tmp_path):
    service = AsterService(
        data_dir=str(tmp_path),
        username="test",
        password="test",
    )
    assert service.data_dir == str(tmp_path)


def test_build_aoi_geojson():
    service = AsterService(data_dir="/tmp", username="", password="")
    geojson = service.build_aoi_geojson(
        center_lon=-47.155531,
        center_lat=-11.699153,
        radius_km=25.0,
    )
    assert geojson["type"] == "Polygon"
    assert len(geojson["coordinates"][0]) >= 32


def test_get_bbox():
    service = AsterService(data_dir="/tmp", username="", password="")
    bbox = service._get_bbox(-47.155531, -11.699153, 25.0)
    parts = bbox.split(",")
    assert len(parts) == 4
    lon_min, lat_min, lon_max, lat_max = [float(p) for p in parts]
    assert lon_min < -47.155531 < lon_max
    assert lat_min < -11.699153 < lat_max


def test_band_suffixes():
    assert len(BAND_SUFFIXES["AST_07XT"]) == 9
    assert len(BAND_SUFFIXES["AST_05"]) == 5
    assert "SRF_VNIR_B01" in BAND_SUFFIXES["AST_07XT"]
    assert "Emissivity_B10" in BAND_SUFFIXES["AST_05"]


def test_cache_dir_structure(tmp_path):
    service = AsterService(data_dir=str(tmp_path), username="", password="")
    service.ensure_dirs()
    assert os.path.isdir(os.path.join(str(tmp_path), "aster", "raw"))
    assert os.path.isdir(os.path.join(str(tmp_path), "aster", "composite"))
    assert os.path.isdir(os.path.join(str(tmp_path), "processed"))
