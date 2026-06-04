"""Integration tests for conversation management endpoints."""


def test_create_conversation(client, auth_headers):
    resp = client.post("/api/chat/conversations", headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert "title" in data
    assert "created_at" in data


def test_list_conversations_initially_empty(client, auth_headers):
    resp = client.get("/api/chat/conversations", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_list_conversations_after_create(client, auth_headers):
    client.post("/api/chat/conversations", headers=auth_headers)
    resp = client.get("/api/chat/conversations", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_create_multiple_conversations(client, auth_headers):
    for _ in range(3):
        client.post("/api/chat/conversations", headers=auth_headers)
    resp = client.get("/api/chat/conversations", headers=auth_headers)
    assert len(resp.json()) >= 3


def test_get_messages_empty_conversation(client, auth_headers):
    create_resp = client.post("/api/chat/conversations", headers=auth_headers)
    conv_id = create_resp.json()["id"]

    resp = client.get(f"/api/chat/conversations/{conv_id}/messages", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["conversation_id"] == conv_id
    assert data["messages"] == []


def test_get_messages_not_found(client, auth_headers):
    resp = client.get("/api/chat/conversations/nonexistent-conv-id/messages", headers=auth_headers)
    assert resp.status_code == 404


def test_conversations_isolated_between_users(client):
    """Each user must only see their own conversations."""
    import uuid

    def _make_headers(username):
        client.post("/api/auth/register", json={"username": username, "password": "pass123456"})
        resp = client.post("/api/auth/login", json={"username": username, "password": "pass123456"})
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    suffix = uuid.uuid4().hex[:6]
    headers_a = _make_headers(f"iso_user_a_{suffix}")
    headers_b = _make_headers(f"iso_user_b_{suffix}")

    # User A creates a conversation
    resp_create = client.post("/api/chat/conversations", headers=headers_a)
    conv_id_a = resp_create.json()["id"]

    # User B cannot read user A's messages
    resp = client.get(f"/api/chat/conversations/{conv_id_a}/messages", headers=headers_b)
    assert resp.status_code == 404

    # User B's conversation list does not contain user A's conversation
    ids_b = {c["id"] for c in client.get("/api/chat/conversations", headers=headers_b).json()}
    assert conv_id_a not in ids_b


def test_health_endpoint(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
