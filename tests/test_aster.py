import os
import pytest

from backend.services.aster import AsterService
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


def test_get_task_payload():
    service = AsterService(data_dir="/tmp", username="", password="")
    aoi = service.build_aoi_geojson(-47.155531, -11.699153, 25.0)
    payload = service.build_task_payload(
        task_name="test",
        product="AST_07XT",
        aoi=aoi,
        start_date="2000-01-01",
        end_date="2008-12-31",
    )
    assert payload["task_name"] == "test"
    assert payload["task_type"] == "area"
    assert len(payload["params"]["dates"]) == 1


def test_cache_dir_structure(tmp_path):
    service = AsterService(data_dir=str(tmp_path), username="", password="")
    service.ensure_dirs()
    assert os.path.isdir(os.path.join(str(tmp_path), "aster", "raw"))
    assert os.path.isdir(os.path.join(str(tmp_path), "aster", "composite"))
    assert os.path.isdir(os.path.join(str(tmp_path), "processed"))
