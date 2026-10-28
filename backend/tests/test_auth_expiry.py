from datetime import timedelta
from uuid import UUID

import pytest
from conftest import headers, register
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.db.models import Job, Presentation, Session, utcnow
from app.main import create_app

IDENTIFIER = "11111111-1111-4111-8111-111111111111"
PROTECTED_POSTS = [
    ("/presentations", {"text": "Доклад " * 30, "slideCount": 8}),
    (
        f"/presentations/{IDENTIFIER}/generations",
        {"text": "Доклад " * 30, "slideCount": 8},
    ),
    (
        f"/presentations/{IDENTIFIER}/revisions",
        {"instruction": "Сократи текст", "base_document_token": "document"},
    ),
    ("/auth/logout", {}),
]


@pytest.mark.parametrize(("path", "body"), PROTECTED_POSTS)
def test_protected_posts_without_session_return_auth_required(path, body):
    # Отказ должен произойти до обращения к БД, Redis или ML, без запуска ресурсов API.
    http = TestClient(create_app())
    try:
        response = http.post(f"/api/v1{path}", json=body, headers=headers("missing-session"))
    finally:
        http.close()
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


@pytest.mark.parametrize("path", ["/auth/login", "/auth/register"])
def test_pre_authentication_posts_still_require_csrf(path):
    http = TestClient(create_app())
    try:
        response = http.post(
            f"/api/v1{path}",
            json={"login": "tester", "password": "correct horse battery staple"},
            headers=headers("missing-session"),
        )
    finally:
        http.close()
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_REJECTED"


@pytest.mark.parametrize(("path", "body"), PROTECTED_POSTS)
@pytest.mark.parametrize("state", ["absolute", "idle", "revoked", "preliminary"])
def test_expired_or_unauthenticated_session_cannot_hide_as_csrf_failure(
    client, database, state, path, body
):
    if state == "preliminary":
        token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    else:
        user, token = register(client)
        with database() as db, db.begin():
            session = db.scalar(select(Session).where(Session.user_id == UUID(user["id"])))
            if state == "absolute":
                session.expires_at = utcnow() - timedelta(seconds=1)
            elif state == "idle":
                session.last_seen_at = utcnow() - timedelta(hours=25)
            else:
                db.execute(delete(Session).where(Session.id == session.id))

    response = client.post(f"/api/v1{path}", json=body, headers=headers(token))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert response.headers["cache-control"] == "no-store"
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 0
        assert db.scalar(select(func.count()).select_from(Presentation)) == 0


@pytest.mark.parametrize(("path", "body"), PROTECTED_POSTS)
@pytest.mark.parametrize("invalid", ["csrf", "origin"])
def test_live_authenticated_posts_still_enforce_csrf_and_origin(client, invalid, path, body):
    _, token = register(client)
    request_headers = headers("wrong-token" if invalid == "csrf" else token)
    if invalid == "origin":
        request_headers["Origin"] = "https://evil.test"
    response = client.post(f"/api/v1{path}", json=body, headers=request_headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == (
        "CSRF_REJECTED" if invalid == "csrf" else "ORIGIN_REJECTED"
    )
