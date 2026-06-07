from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200


def test_create_and_get_item():
    r = client.post("/api/v1/items/", json={"name": "Widget", "description": "A test widget"})
    assert r.status_code == 201
    item = r.json()
    assert item["name"] == "Widget"

    r2 = client.get(f"/api/v1/items/{item['id']}")
    assert r2.status_code == 200
    assert r2.json()["name"] == "Widget"


def test_delete_item():
    r = client.post("/api/v1/items/", json={"name": "ToDelete"})
    item_id = r.json()["id"]

    r2 = client.delete(f"/api/v1/items/{item_id}")
    assert r2.status_code == 204

    r3 = client.get(f"/api/v1/items/{item_id}")
    assert r3.status_code == 404
