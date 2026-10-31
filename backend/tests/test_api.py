from datetime import timedelta
from uuid import UUID

from conftest import generate, headers, register
from sqlalchemy import select

from app.db.models import Job, Session, User, utcnow
from app.worker import execute_job, maintenance, publish_result


def read(client, accepted):
    return client.get(f"/api/v1/presentations/{accepted['presentation_id']}").json()


def execute(client, accepted):
    execute_job.run(accepted["job_id"])
    return client.get(f"/api/v1/jobs/{accepted['job_id']}").json()


def test_auth_csrf_hashes_rotation_logout(client, database):
    pre = client.get("/api/v1/auth/csrf")
    assert pre.headers["cache-control"] == "no-store"
    old_cookie = client.cookies.get("pm-dev-session")
    user, token = register(client)
    assert old_cookie != client.cookies.get("pm-dev-session")
    assert client.get("/api/v1/auth/me").json()["user"] == user
    assert generate(client, "wrong").status_code == 403
    assert (
        client.post(
            "/api/v1/presentations",
            json={},
            headers={**headers(token), "Origin": "https://evil.test"},
        ).status_code
        == 403
    )
    with database() as db:
        saved = db.get(User, UUID(user["id"]))
        assert saved.password_hash.startswith("$argon2id$")
        assert db.scalar(select(Session.token_hash)) != client.cookies.get("pm-dev-session")
    response = client.post("/api/v1/auth/logout", headers=headers(token))
    assert response.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.set("pm-dev-session", old_cookie)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_expired_idle_session(client, database):
    register(client)
    with database() as db, db.begin():
        session = db.scalar(select(Session).where(Session.user_id.is_not(None)))
        session.last_seen_at = utcnow() - timedelta(hours=25)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_generic_error_and_case_policy(client):
    _, token = register(client, "Example")
    client.post("/api/v1/auth/logout", headers=headers(token))
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    bodies = []
    for login in ["unknown", "example"]:
        response = client.post(
            "/api/v1/auth/login",
            json={"login": login, "password": "wrong password long"},
            headers=headers(token),
        )
        assert response.status_code == 401
        bodies.append(response.json()["error"])
    assert bodies[0] == bodies[1]
    response = client.post(
        "/api/v1/auth/login",
        json={"login": "EXAMPLE", "password": "correct horse battery staple"},
        headers=headers(token),
    )
    assert response.status_code == 200


def test_generation_and_idempotency(client, database):
    _, token = register(client)
    response = generate(client, token)
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert read(client, accepted)["document"] is None
    assert generate(client, token).json() == accepted
    assert generate(client, token, slideCount=9).status_code == 409
    assert execute(client, accepted)["status"] == "succeeded"
    current = read(client, accepted)
    assert current["slide_count"] == 6 and current["requested_slide_count"] == 8
    # Повторная доставка не должна повторно вызывать ML или применять результат.
    execute_job.run(accepted["job_id"])
    assert read(client, accepted) == current
    with database() as db:
        job = db.get(Job, UUID(accepted["job_id"]))
        assert job.input_snapshot == {}
        assert not hasattr(job, "output_document")
    assert generate(client, token).json() == accepted


def test_user_isolation(client):
    _, token = register(client, "first")
    accepted = generate(client, token).json()
    client.cookies.clear()
    register(client, "second")
    assert client.get(f"/api/v1/presentations/{accepted['presentation_id']}").status_code == 404
    assert client.get(f"/api/v1/jobs/{accepted['job_id']}").status_code == 404


def test_revision_conflict_atomicity_and_snapshot(client, database, monkeypatch):
    _, token = register(client)
    accepted = generate(client, token).json()
    execute(client, accepted)
    old = read(client, accepted)
    path = f"/api/v1/presentations/{accepted['presentation_id']}/revisions"
    body = {
        "instruction": "Сократи текст",
        "base_document_token": old["document_token"],
        "target_slide_numbers": [3],
    }
    assert (
        client.post(
            path, json={**body, "base_document_token": "stale"}, headers=headers(token, "stale")
        ).status_code
        == 409
    )
    assert (
        client.post(
            path, json={**body, "target_slide_numbers": [70]}, headers=headers(token, "bad-target")
        ).status_code
        == 422
    )
    revision = client.post(path, json=body, headers=headers(token, "revise")).json()
    # Принятый ранее запрос распознаётся до проверок активного задания и токена базы.
    assert client.post(path, json=body, headers=headers(token, "revise")).json() == revision
    assert client.post(path, json=body, headers=headers(token, "busy")).status_code == 409
    assert read(client, accepted)["document"] == old["document"]
    with database() as db:
        snapshot = db.get(Job, UUID(revision["job_id"])).input_snapshot
        assert snapshot["document"] == old["document"]
        assert snapshot["target_slide_ids"] == [old["document"]["slides"][2]["id"]]
        assert snapshot["text"] == "Доклад " * 29 + "Доклад"
        assert snapshot["slideCount"] == 8
    assert execute(client, revision)["status"] == "succeeded"
    new = read(client, accepted)
    assert new["document_token"] != old["document_token"]
    assert new["document"]["slides"][1] == old["document"]["slides"][1]
    assert new["document"]["slides"][2]["id"] == old["document"]["slides"][2]["id"]
    body["base_document_token"] = new["document_token"]
    failed = client.post(path, json=body, headers=headers(token, "failure")).json()
    monkeypatch.setenv("PM_FIXTURE_FAILURE", "true")
    assert execute(client, failed)["status"] == "failed"
    after = read(client, accepted)
    assert after["document"] == new["document"] and after["document_token"] == new["document_token"]


def test_deadline_and_late_result(client, database, document):
    _, token = register(client)
    accepted = generate(client, token).json()
    with database() as db, db.begin():
        job = db.get(Job, UUID(accepted["job_id"]))
        job.status, job.phase, job.attempt_token = "running", "ml", "attempt"
        job.heartbeat_at = utcnow()
        job.deadline_at = utcnow() - timedelta(seconds=1)
    assert not publish_result(UUID(accepted["job_id"]), "attempt", document)
    assert read(client, accepted)["document"] is None
    assert client.get(accepted["status_url"]).json()["status"] == "timed_out"


def test_worker_loss_no_automatic_paid_retry(client, database, document):
    _, token = register(client)
    accepted = generate(client, token).json()
    with database() as db, db.begin():
        job = db.get(Job, UUID(accepted["job_id"]))
        job.status, job.phase, job.attempt_token = "running", "ml", "attempt"
        job.heartbeat_at = utcnow() - timedelta(minutes=10)
    maintenance.run()
    assert client.get(accepted["status_url"]).json()["error"]["code"] == "WORKER_LOST"
    assert not publish_result(UUID(accepted["job_id"]), "attempt", document)
    execute_job.run(accepted["job_id"])
    assert read(client, accepted)["document"] is None


def test_validation_body_limit_and_private_errors(client):
    _, token = register(client)
    response = generate(client, token, text="private secret short")
    assert response.status_code == 422
    assert "private secret" not in response.text
    assert generate(client, token, slideCount=None).status_code == 422
    response = client.post(
        "/api/v1/presentations", content=b"x" * 2_000_001, headers=headers(token)
    )
    assert response.status_code == 413


def test_no_deferred_routes(client):
    routes = client.get("/openapi.json").json()["paths"]
    # Список и удаление — часть контракта: пользователь управляет своими данными
    assert set(routes["/api/v1/presentations"]) == {"get", "post"}
    assert "delete" in routes["/api/v1/presentations/{identifier}"]
    assert "delete" in routes["/api/v1/auth/me"]
    assert not any(
        word in path
        for path in routes
        for word in ["versions", "assets", "preview", "export", "history"]
    )
