"""Integration tests for authentication endpoints."""


def test_register_success(client):
    resp = client.post(
        "/api/auth/register",
        json={"username": "newuser_reg01", "password": "password123"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "newuser_reg01"
    assert "id" in data


def test_register_username_too_short(client):
    resp = client.post(
        "/api/auth/register",
        json={"username": "ab", "password": "password123"},
    )
    assert resp.status_code == 422


def test_register_password_too_short(client):
    resp = client.post(
        "/api/auth/register",
        json={"username": "validuser01", "password": "12345"},
    )
    assert resp.status_code == 422


def test_register_duplicate_username(client):
    client.post("/api/auth/register", json={"username": "dupuser01", "password": "pass123456"})
    resp = client.post("/api/auth/register", json={"username": "dupuser01", "password": "pass123456"})
    assert resp.status_code == 400
    assert "已存在" in resp.json()["detail"]


def test_login_success(client):
    client.post("/api/auth/register", json={"username": "loginok01", "password": "password123"})
    resp = client.post("/api/auth/login", json={"username": "loginok01", "password": "password123"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client):
    client.post("/api/auth/register", json={"username": "wrongpw01", "password": "correct123"})
    resp = client.post("/api/auth/login", json={"username": "wrongpw01", "password": "wrong"})
    assert resp.status_code == 401


def test_login_nonexistent_user(client):
    resp = client.post("/api/auth/login", json={"username": "ghost_user_xyz", "password": "anything"})
    assert resp.status_code == 401


def test_protected_endpoint_without_token(client):
    resp = client.get("/api/chat/conversations")
    assert resp.status_code == 403


def test_protected_endpoint_with_invalid_token(client):
    resp = client.get(
        "/api/chat/conversations",
        headers={"Authorization": "Bearer invalid.token.here"},
    )
    assert resp.status_code == 401
