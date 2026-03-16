"""Testes do servico CPRM — download WFS e processamento de GeoJSON."""

import json
import os
from unittest.mock import patch, MagicMock

import pytest

from backend.services.cprm import (
    CPRMService,
    ERA_COLORS,
    SIGLA_COLORS,
    DEFAULT_ERA_COLOR,
    GEOLOGY_LAYER,
    OCCURRENCES_LAYER,
)

BBOX = (-47.38, -11.93, -46.93, -11.47)


def _make_geology_response():
    """Cria resposta WFS fake de geologia."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                "properties": {
                    "sigla": "NP3na",
                    "nome_unidade": "Grupo Natividade",
                    "era_max": "Neoproterozóico",
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[1, 1], [2, 1], [2, 2], [1, 1]]]},
                "properties": {
                    "sigla": "PP2ri",
                    "nome_unidade": "Formacao Riachao",
                    "era_max": "Paleoproterozóico",
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[2, 2], [3, 2], [3, 3], [2, 2]]]},
                "properties": {
                    "sigla": "NP3na",
                    "nome_unidade": "Grupo Natividade",
                    "era_max": "Mesozóico",
                },
            },
        ],
    }


def _make_occurrences_response():
    """Cria resposta WFS fake de ocorrencias."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-47.1, -11.7]},
                "properties": {"substancia": "Ouro", "nome": "Garimpo X"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-47.2, -11.8]},
                "properties": {"substancia": "Quartzo", "nome": "Ocorrencia Y"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-47.15, -11.75]},
                "properties": {"substancia": "Au", "nome": "Garimpo Z"},
            },
        ],
    }


@pytest.fixture
def service(tmp_path):
    return CPRMService(vectors_dir=str(tmp_path), bbox=BBOX)


def test_init(service, tmp_path):
    assert service.vectors_dir == str(tmp_path)
    assert service.bbox == BBOX


def test_geojson_path(service, tmp_path):
    path = service._geojson_path("geology-litho")
    assert path == os.path.join(str(tmp_path), "geology-litho.geojson")


def test_has_cache_false(service):
    assert service.has_cache("geology-litho") is False


def test_get_layer_none(service):
    assert service.get_layer("geology-litho") is None


@patch("backend.services.cprm.requests.get")
def test_download_geology(mock_get, service, tmp_path):
    mock_resp = MagicMock()
    mock_resp.json.return_value = _make_geology_response()
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    result = service.download_geology()

    assert "geology-litho" in result
    assert "geology-age" in result

    # Litho: 3 features com color
    litho = result["geology-litho"]
    assert len(litho["features"]) == 3
    for f in litho["features"]:
        assert "color" in f["properties"]
        assert f["properties"]["color"].startswith("#")

    # Mesma sigla deve ter mesma cor
    colors_np3na = [
        f["properties"]["color"]
        for f in litho["features"]
        if f["properties"]["sigla"] == "NP3na"
    ]
    assert len(colors_np3na) == 2
    assert colors_np3na[0] == colors_np3na[1]

    # Age: cores por era
    age = result["geology-age"]
    assert len(age["features"]) == 3
    era_colors_found = [f["properties"]["color"] for f in age["features"]]
    assert ERA_COLORS["Neoproterozóico"] in era_colors_found
    assert ERA_COLORS["Paleoproterozóico"] in era_colors_found
    assert ERA_COLORS["Mesozóico"] in era_colors_found


@patch("backend.services.cprm.requests.get")
def test_download_geology_saves_files(mock_get, service, tmp_path):
    mock_resp = MagicMock()
    mock_resp.json.return_value = _make_geology_response()
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    service.download_geology()

    assert os.path.exists(os.path.join(str(tmp_path), "geology-litho.geojson"))
    assert os.path.exists(os.path.join(str(tmp_path), "geology-age.geojson"))
    assert service.has_cache("geology-litho")
    assert service.has_cache("geology-age")


@patch("backend.services.cprm.requests.get")
def test_download_occurrences(mock_get, service):
    mock_resp = MagicMock()
    mock_resp.json.return_value = _make_occurrences_response()
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    result = service.download_occurrences()

    assert len(result["features"]) == 3

    # Ouro features
    gold = [f for f in result["features"] if f["properties"]["color"] == "#ffd700"]
    assert len(gold) == 2  # "Ouro" e "Au"
    for f in gold:
        assert f["properties"]["radius"] == 8

    # Outros
    other = [f for f in result["features"] if f["properties"]["color"] == "#aaaaaa"]
    assert len(other) == 1
    assert other[0]["properties"]["radius"] == 5


@patch("backend.services.cprm.requests.get")
def test_download_occurrences_saves_file(mock_get, service, tmp_path):
    mock_resp = MagicMock()
    mock_resp.json.return_value = _make_occurrences_response()
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    service.download_occurrences()

    assert os.path.exists(os.path.join(str(tmp_path), "mineral-occurrences.geojson"))
    assert service.has_cache("mineral-occurrences")


@patch("backend.services.cprm.requests.get")
def test_download_all(mock_get, service):
    mock_resp = MagicMock()
    # download_all chama geology (1 request) + occurrences (1 request)
    mock_resp.json.side_effect = [
        _make_geology_response(),
        _make_occurrences_response(),
    ]
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    result = service.download_all()

    assert "geology-litho" in result
    assert "geology-age" in result
    assert "mineral-occurrences" in result


@patch("backend.services.cprm.requests.get")
def test_get_layer_from_cache(mock_get, service):
    mock_resp = MagicMock()
    mock_resp.json.return_value = _make_occurrences_response()
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    service.download_occurrences()

    # Deve retornar do cache sem ler disco
    result = service.get_layer("mineral-occurrences")
    assert result is not None
    assert len(result["features"]) == 3


@patch("backend.services.cprm.requests.get")
def test_get_layer_from_disk(mock_get, service, tmp_path):
    mock_resp = MagicMock()
    mock_resp.json.return_value = _make_occurrences_response()
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    service.download_occurrences()

    # Novo service (sem cache em memoria) deve ler do disco
    service2 = CPRMService(vectors_dir=str(tmp_path), bbox=BBOX)
    result = service2.get_layer("mineral-occurrences")
    assert result is not None
    assert len(result["features"]) == 3


def test_era_colors_dict():
    """Verifica que ERA_COLORS tem as eras esperadas."""
    assert "Paleoproterozóico" in ERA_COLORS
    assert "Neoproterozóico" in ERA_COLORS
    assert "Mesozóico" in ERA_COLORS
    assert DEFAULT_ERA_COLOR == "#7f7f7f"


@patch("backend.services.cprm.requests.get")
def test_unknown_era_gets_default_color(mock_get, service):
    """Era desconhecida recebe cor default."""
    data = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            "properties": {"sigla": "XX", "era_max": "EraInventada"},
        }],
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = data
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    result = service.download_geology()
    age_feat = result["geology-age"]["features"][0]
    assert age_feat["properties"]["color"] == DEFAULT_ERA_COLOR


@patch("backend.services.cprm.requests.get")
def test_wfs_request_params(mock_get, service):
    """Verifica que os parametros WFS estao corretos."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"type": "FeatureCollection", "features": []}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    service._wfs_get_features(GEOLOGY_LAYER)

    call_args = mock_get.call_args
    params = call_args.kwargs.get("params") or call_args[1].get("params")
    assert params["service"] == "WFS"
    assert params["version"] == "2.0.0"
    assert params["typeName"] == GEOLOGY_LAYER
    assert params["outputFormat"] == "application/json"
    assert params["srsName"] == "EPSG:4326"
    # bbox no formato lat,lon,lat,lon (WFS 2.0)
    assert "-11.93" in params["bbox"]
    assert "-47.38" in params["bbox"]
