import os

# Must be set before any project module is imported so pydantic-settings
# and load_dotenv() both pick up test values instead of production secrets.
os.environ.setdefault("DOUBAO_API_KEY", "test-api-key")
os.environ.setdefault("DOUBAO_BASE_URL", "https://test.api.local/v1")
os.environ.setdefault("DOUBAO_MODEL", "test-model")
os.environ.setdefault("EMBEDDING_MODEL", "text-embedding-v3")
os.environ.setdefault("EMBEDDING_API_KEY", "test-embedding-key")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32-chars-minimum!!")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db.models import Base
from backend.core.dependencies import get_db

_ENGINE = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
_Session = sessionmaker(autocommit=False, autoflush=False, bind=_ENGINE)
Base.metadata.create_all(bind=_ENGINE)


def _override_db():
    db = _Session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="session")
def client():
    from backend.main import app
    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client):
    username = f"u_{uuid.uuid4().hex[:8]}"
    client.post("/api/auth/register", json={"username": username, "password": "testpass123"})
    resp = client.post("/api/auth/login", json={"username": username, "password": "testpass123"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
