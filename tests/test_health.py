from fastapi.testclient import TestClient

from app.main import app


def test_healthz_is_public_and_reports_liveness():
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
