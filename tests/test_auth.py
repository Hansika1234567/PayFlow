import uuid
import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_user_registration_and_automatic_wallet_provisioning():
    """Test user registration returns 201, JWT token, and auto-provisioned wallet with $1000."""
    uid = uuid.uuid4().hex[:6]
    payload = {
        "email": f"alice_{uid}@example.com",
        "username": f"alice_{uid}",
        "password": "Password123!",
        "full_name": "Alice Tester"
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == payload["email"]
    assert data["user"]["username"] == payload["username"]
    
    # Verify wallet was auto-provisioned with 100,000 cents ($1,000.00)
    assert data["user"]["wallet"] is not None
    assert data["user"]["wallet"]["balance_cents"] == 100000
    assert data["user"]["wallet"]["balance_dollars"] == 1000.0
    assert data["user"]["wallet"]["currency"] == "USD"
    assert data["user"]["wallet"]["status"] == "ACTIVE"

def test_duplicate_registration_fails():
    """Test that registering with duplicate email or username returns 400 Bad Request."""
    uid = uuid.uuid4().hex[:6]
    payload = {
        "email": f"dup_{uid}@example.com",
        "username": f"dup_{uid}",
        "password": "Password123!",
        "full_name": "Duplicate Tester"
    }
    # First registration passes
    res1 = client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    # Second registration with same email fails
    dup_email_payload = {
        "email": payload["email"],
        "username": f"other_{uid}",
        "password": "Password123!",
        "full_name": "Other Name"
    }
    res2 = client.post("/api/v1/auth/register", json=dup_email_payload)
    assert res2.status_code == 400
    assert "already exists" in res2.json()["detail"]

def test_user_login_success():
    """Test login with username and password returns valid JWT token."""
    uid = uuid.uuid4().hex[:6]
    reg_payload = {
        "email": f"login_{uid}@example.com",
        "username": f"login_{uid}",
        "password": "Password123!",
        "full_name": "Login Tester"
    }
    client.post("/api/v1/auth/register", json=reg_payload)

    login_payload = {
        "email_or_username": f"login_{uid}",
        "password": "Password123!"
    }
    response = client.post("/api/v1/auth/login", json=login_payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["user"]["username"] == f"login_{uid}"

def test_user_login_invalid_password():
    """Test login with incorrect password returns 401 Unauthorized."""
    uid = uuid.uuid4().hex[:6]
    reg_payload = {
        "email": f"badpwd_{uid}@example.com",
        "username": f"badpwd_{uid}",
        "password": "Password123!",
        "full_name": "Bad Pwd Tester"
    }
    client.post("/api/v1/auth/register", json=reg_payload)

    login_payload = {
        "email_or_username": f"badpwd_{uid}",
        "password": "WrongPassword999!"
    }
    response = client.post("/api/v1/auth/login", json=login_payload)
    assert response.status_code == 401
    assert "Incorrect" in response.json()["detail"]

def test_protected_me_endpoint():
    """Test accessing /api/v1/auth/me with Bearer token."""
    uid = uuid.uuid4().hex[:6]
    reg_payload = {
        "email": f"me_{uid}@example.com",
        "username": f"me_{uid}",
        "password": "Password123!",
        "full_name": "Me Tester"
    }
    reg_res = client.post("/api/v1/auth/register", json=reg_payload)
    token = reg_res.json()["access_token"]

    # Call /me with valid token
    headers = {"Authorization": f"Bearer {token}"}
    me_res = client.get("/api/v1/auth/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["username"] == f"me_{uid}"

    # Call /me with no token -> 401
    me_res_no_auth = client.get("/api/v1/auth/me")
    assert me_res_no_auth.status_code == 401

    # Call /me with invalid token -> 401
    me_res_invalid = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid.fake.token"})
    assert me_res_invalid.status_code == 401

def test_production_secret_enforcement(monkeypatch):
    """
    Priority 5 Test:
    Verifies that the Settings model rejects insecure fallback secrets when ENVIRONMENT=production.
    """
    from backend.config import Settings
    from pydantic import ValidationError

    # In production with default secret -> Must raise ValidationError
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "payflow-dev-secret-key-change-in-production-2026")
    with pytest.raises(ValidationError) as exc:
        Settings()
    assert "FATAL SECURITY VIOLATION" in str(exc.value)

    # In production with strong 256-bit secret -> Must succeed
    monkeypatch.setenv("SECRET_KEY", "a" * 64)
    prod_settings = Settings()
    assert prod_settings.SECRET_KEY == "a" * 64

def test_cors_configuration():
    """
    Priority 5 Test:
    Verifies that CORS origins are properly loaded from settings and responded to preflight requests.
    """
    from backend.config import settings
    assert len(settings.ALLOWED_CORS_ORIGINS) >= 1
    
    # Test preflight OPTIONS request
    res = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET"
        }
    )
    assert res.status_code == 200
    assert "access-control-allow-origin" in res.headers

