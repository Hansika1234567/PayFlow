import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_health_check_returns_healthy():
    """Verify that /api/v1/health returns 200 OK and database connectivity is healthy."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"
    assert "version" in data
    assert "timestamp" in data

def test_openapi_schema_accessible():
    """Verify that Swagger OpenAPI documentation schema is generated properly."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert data["info"]["title"] == "PayFlow API"
