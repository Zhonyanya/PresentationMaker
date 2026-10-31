"""Пользователь видит и удаляет свои данные: презентации и аккаунт целиком."""

from uuid import UUID

from conftest import generate, headers, register
from sqlalchemy import select

from app.db.models import Job, Presentation, Session, User
from app.worker import execute_job


def created(client, token, key="del-job"):
    accepted = generate(client, token, key).json()
    execute_job.run(accepted["job_id"])
    return accepted["presentation_id"]


def test_list_and_delete_presentation_wipes_content(client, database):
    _, token = register(client, "deleter")
    identifier = created(client, token)
    listed = client.get("/api/v1/presentations").json()["presentations"]
    assert [p["presentation_id"] for p in listed] == [identifier]
    assert listed[0]["title"] and listed[0]["slide_count"] and not listed[0]["active"]
    assert "source_text" not in listed[0] and "document" not in listed[0]

    response = client.delete(f"/api/v1/presentations/{identifier}", headers=headers(token))
    assert response.status_code == 204
    assert client.get(f"/api/v1/presentations/{identifier}").status_code == 404
    assert client.get("/api/v1/presentations").json()["presentations"] == []
    with database() as db:
        row = db.get(Presentation, UUID(identifier))
        assert row.source_text == "" and row.document is None and row.deleted_at is not None
    # Повторное удаление и правка удалённой — как у несуществующей
    again = client.delete(f"/api/v1/presentations/{identifier}", headers=headers(token))
    assert again.status_code == 404


def test_delete_is_refused_while_job_is_active(client, database):
    _, token = register(client, "busy-deleter")
    identifier = generate(client, token, "busy").json()["presentation_id"]
    response = client.delete(f"/api/v1/presentations/{identifier}", headers=headers(token))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JOB_ALREADY_ACTIVE"


def test_delete_account_requires_password_and_removes_everything(client, database):
    user, token = register(client, "leaver")
    created(client, token)
    wrong = client.request(
        "DELETE", "/api/v1/auth/me", json={"password": "not my password"}, headers=headers(token)
    )
    assert wrong.status_code == 403
    assert wrong.json()["error"]["code"] == "INVALID_PASSWORD"

    response = client.request(
        "DELETE",
        "/api/v1/auth/me",
        json={"password": "correct horse battery staple"},
        headers=headers(token),
    )
    assert response.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    owner = UUID(user["id"])
    with database() as db:
        assert db.get(User, owner) is None
        for model, column in [(Presentation, Presentation.owner_id), (Job, Job.owner_id)]:
            assert db.scalar(select(model).where(column == owner)) is None
        assert db.scalar(select(Session).where(Session.user_id == owner)) is None
