import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture
def http():
    # Проверяемые маршруты не требуют запуска ресурсов API и доступных PostgreSQL/Redis.
    client = TestClient(create_app())
    yield client
    client.close()


@pytest.mark.parametrize("origin", ["http://localhost:5173", "https://evil.test"])
def test_cors_preflight_only_allows_explicit_origin_and_required_headers(http, origin):
    response = http.options(
        "/api/v1/presentations",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-csrf-token,idempotency-key",
        },
    )
    if origin == "http://localhost:5173":
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["access-control-allow-credentials"] == "true"
        allowed = response.headers["access-control-allow-headers"].lower()
        assert all(name in allowed for name in ("content-type", "x-csrf-token", "idempotency-key"))
    else:
        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("status", [404, 413, 500])
def test_errors_keep_public_envelope_cors_and_no_store(http, status, caplog):
    if status == 500:
        # FastAPI находится внутри оболочек CORS и ограничения тела запроса.
        app = http.app.app.app

        @app.get("/test-error")
        async def broken():
            raise RuntimeError("private database password and report")

        response = http.get("/test-error", headers={"Origin": "http://localhost:5173"})
    elif status == 413:
        response = http.post(
            "/api/v1/presentations", content=b"x" * (get_settings().max_http_bytes + 1),
            headers={"Origin": "http://localhost:5173"},
        )
    else:
        response = http.get("/missing", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == status
    payload = response.json()
    assert set(payload) == {"error", "request_id"}
    assert set(payload["error"]) == {"code", "message"}
    assert payload["request_id"] == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "private database" not in response.text + caplog.text


def test_liveness_is_independent_of_external_services_and_has_security_headers(http):
    response = http.get("/api/v1/health/live")
    assert response.status_code == 200 and response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "strict-transport-security" not in response.headers
