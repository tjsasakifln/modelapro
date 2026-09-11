import json

from fastapi.testclient import TestClient

from backend.api import app, reset_runtime
from tests.c10_pipeline.doubles import install_labeled_runtime
from tests.c10_pipeline.fixtures import market_csv_bytes

client = TestClient(app)


class TestAPI:
    def test_health_check(self):
        reset_runtime()
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    def test_upload_endpoint(self):
        install_labeled_runtime()
        try:
            files = {"file": ("test.csv", market_csv_bytes("API"), "text/csv")}
            data = {"degree": 1, "target_col": "preco"}
            response = client.post("/upload", files=files, data=data)
            assert response.status_code == 202
            body = response.json()
            assert "job_id" in body
            assert "Processing started" in body["message"]
            result = client.get(f"/jobs/{body['job_id']}/result")
            assert result.status_code == 200
            assert result.json()["schema_version"] == "MP/1"
        finally:
            reset_runtime()

    def test_upload_invalid_degree_is_4xx(self):
        install_labeled_runtime()
        try:
            files = {"file": ("test.csv", market_csv_bytes("API"), "text/csv")}
            data = {"degree": 9, "target_col": "preco"}
            response = client.post("/upload", files=files, data=data)
            assert response.status_code == 400
            detail = response.json().get("detail", response.json())
            issues = detail.get("issues") if isinstance(detail, dict) else []
            assert any(i["code"] == "DEGREE_OUT_OF_RANGE" for i in issues)
        finally:
            reset_runtime()
