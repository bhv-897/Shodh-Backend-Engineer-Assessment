"""Integration tests use the configured real MySQL 8 database."""
import os
import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture
def client():
    if "mysql" not in os.getenv("DATABASE_URL", "").lower():
        pytest.skip("Integration suite requires a real MySQL 8 DATABASE_URL")
    return TestClient(app)
