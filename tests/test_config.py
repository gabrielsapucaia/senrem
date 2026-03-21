from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_get_config():
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert "center" in data
    assert "areas" in data
    assert "default_area" in data
    assert "paiol" in data["areas"]
    assert "engegold" in data["areas"]
    assert "principe" in data["areas"]
    paiol = data["areas"]["paiol"]
    assert paiol["center"]["lat"] == -11.699153
    assert paiol["center"]["lon"] == -47.155531


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
