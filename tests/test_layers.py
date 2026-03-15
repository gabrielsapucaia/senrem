from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_list_layers():
    response = client.get("/api/layers")
    assert response.status_code == 200
    resp = response.json()
    assert "layers" in resp
    data = resp["layers"]
    assert isinstance(data, list)
    assert len(data) > 0
    layer = data[0]
    assert "id" in layer
    assert "name" in layer
    assert "available" in layer
    assert "category" in layer
    assert "can_generate" in layer


def test_layers_have_categories():
    response = client.get("/api/layers")
    data = response.json()["layers"]
    categories = {l["category"] for l in data}
    assert "spectral" in categories
    assert "terrain" in categories


def test_gee_layers_can_generate():
    response = client.get("/api/layers")
    data = response.json()["layers"]
    rgb = next(l for l in data if l["id"] == "rgb-true")
    assert rgb["can_generate"] is True
