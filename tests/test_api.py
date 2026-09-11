import pytest
from fastapi.testclient import TestClient
from backend.api import app

client = TestClient(app)

class TestAPI:
    def test_health_check(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}
        
    def test_upload_endpoint(self):
        # Mock file
        file_content = b"col1,col2\n1,2\n3,4\n5,6\n7,8\n9,10\n11,12\n13,14\n15,16\n17,18\n19,20\n21,22\n23,24\n25,26\n27,28\n29,30"
        files = {"file": ("test.csv", file_content, "text/csv")}
        data = {"degree": 1, "target_col": "col2"}
        
        response = client.post("/upload", files=files, data=data)
        assert response.status_code == 200
        assert "Processing started" in response.json()["message"]
