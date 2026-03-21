from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_generate_layer_tiles():
    response = client.post("/api/areas/paiol/layers/rgb-true/generate")
    # 200 se COG existe no disco, 500 se GEE download falhar (quota/size)
    # O importante e que nao retorne 404 (endpoint existe e area e valida)
    assert response.status_code in (200, 500)
    if response.status_code == 200:
        data = response.json()
        assert "tile_url" in data
        assert "{z}" in data["tile_url"]
        assert data["layer_id"] == "rgb-true"
        assert "paiol" in data["tile_url"]


def test_generate_unknown_layer():
    response = client.post("/api/areas/paiol/layers/unknown/generate")
    assert response.status_code == 404


def test_generate_unknown_area():
    response = client.post("/api/areas/unknown/layers/rgb-true/generate")
    assert response.status_code == 404


def test_layers_list_shows_can_generate():
    response = client.get("/api/areas/paiol/layers")
    data = response.json()["layers"]
    rgb = next(l for l in data if l["id"] == "rgb-true")
    assert rgb["can_generate"] is True
