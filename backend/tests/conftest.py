"""Shared test fixtures.

These tests do NOT require a running MySQL server or Ollama. The database
layer is stubbed per-test via monkeypatch; ``token_required``'s student
lookup is stubbed by the ``auth_headers`` fixture.
"""

import os
import sys

import jwt as pyjwt
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-0123456789")

FAKE_STUDENT = {
    "id": 1,
    "student_id": "STU001",
    "name": "Test User",
    "email": "test@university.edu",
}


@pytest.fixture
def app():
    from app import app as flask_app

    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers(monkeypatch):
    """Return an Authorization header whose token resolves to FAKE_STUDENT.

    The DB lookup inside ``middleware.token_required`` is stubbed so no
    database is touched.
    """
    monkeypatch.setattr(
        "middleware.execute_query",
        lambda *args, **kwargs: dict(FAKE_STUDENT),
    )
    from config import Config

    token = pyjwt.encode(
        {"student_id": FAKE_STUDENT["id"]}, Config.SECRET_KEY, algorithm="HS256"
    )
    return {"Authorization": f"Bearer {token}"}
