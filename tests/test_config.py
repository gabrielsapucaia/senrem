from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_get_config():
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert data["center"]["lat"] == -11.699153
    assert data["center"]["lon"] == -47.155531
    assert data["radius_km"] == 25.0
    assert data["name"] == "Natividade-Almas Greenstone Belt"


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
