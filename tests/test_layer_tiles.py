from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_generate_layer_tiles():
    response = client.post("/api/layers/rgb-true/generate")
    assert response.status_code == 200
    data = response.json()
    assert "tile_url" in data
    assert "{z}" in data["tile_url"]
    assert data["layer_id"] == "rgb-true"


def test_generate_unknown_layer():
    response = client.post("/api/layers/unknown/generate")
    assert response.status_code == 404


def test_layers_list_shows_can_generate():
    response = client.get("/api/layers")
    data = response.json()
    rgb = next(l for l in data if l["id"] == "rgb-true")
    assert rgb["can_generate"] is True
