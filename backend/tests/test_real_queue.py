import os
import subprocess
import sys
import time
from datetime import timedelta
from uuid import UUID

from conftest import generate, headers, register
from fastapi.testclient import TestClient

from app import worker
from app.db.models import Job, utcnow
from app.main import create_app


def test_real_celery_redis_recovery_and_revision(database, monkeypatch, tmp_path):
    """Проверяет настоящий prefork-воркер, доставку Redis и PostgreSQL без eager-режима."""
    log_path = tmp_path / "celery-integration.log"
    monkeypatch.setenv("PM_FIXTURE_DELAY", "3")
    processes = []
    with open(log_path, "w") as log:
        try:
            for queue in ("celery", "pm.maintenance"):
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "celery",
                            "-A",
                            "app.worker:celery",
                            "worker",
                            "--concurrency=1",
                            "--loglevel=WARNING",
                            "--without-gossip",
                            "--without-mingle",
                            f"--queues={queue}",
                            f"--hostname={queue}-test@%h",
                        ],
                        stdout=log,
                        stderr=log,
                        env=os.environ.copy(),
                    )
                )
            with TestClient(create_app()) as client:
                _, token = register(client)
                real_publish = worker.execute_job.apply_async

                def unavailable(*args, **kwargs):
                    raise OSError("Simulated broker failure after commit")

                monkeypatch.setattr(worker.execute_job, "apply_async", unavailable)
                accepted = generate(client, token).json()
                assert client.get(accepted["status_url"]).json()["status"] == "queued"
                monkeypatch.setattr(worker.execute_job, "apply_async", real_publish)
                with database() as db, db.begin():
                    # Разрешаем повторную отправку сохранённого задания без ожидания интервала.
                    db.get(Job, UUID(accepted["job_id"])).dispatched_at = None
                # Сама задача восстановления тоже доставляется через Redis, как при запуске Beat.
                worker.maintenance.delay()

                # Обслуживание выполняется независимо от занятого ML-воркера.
                deadline = time.monotonic() + 20
                while client.get(accepted["status_url"]).json()["status"] != "running":
                    assert time.monotonic() < deadline, f"Worker did not start; inspect {log_path}"
                    time.sleep(0.05)
                monkeypatch.setattr(worker.execute_job, "apply_async", unavailable)
                expired = generate(client, token, "expire-during-ml").json()
                monkeypatch.setattr(worker.execute_job, "apply_async", real_publish)
                with database() as db, db.begin():
                    db.get(Job, UUID(expired["job_id"])).deadline_at = utcnow() - timedelta(
                        seconds=1
                    )
                worker.maintenance.delay()
                deadline = time.monotonic() + 2
                while client.get(expired["status_url"]).json()["status"] != "timed_out":
                    assert time.monotonic() < deadline, "Maintenance was blocked by ML"
                    time.sleep(0.05)
                assert client.get(accepted["status_url"]).json()["status"] == "running"

                def await_result(job):
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        result = client.get(job["status_url"]).json()
                        if result["status"] not in {"queued", "running"}:
                            assert result["status"] == "succeeded", result
                            return
                        time.sleep(0.1)
                    raise AssertionError(f"Real worker did not finish; inspect {log_path}")

                await_result(accepted)
                current = client.get(f"/api/v1/presentations/{accepted['presentation_id']}").json()
                revision = client.post(
                    f"/api/v1/presentations/{accepted['presentation_id']}/revisions",
                    json={
                        "instruction": "Тестовая команда",
                        "base_document_token": current["document_token"],
                        "target_slide_numbers": [3],
                    },
                    headers=headers(token, "real-revision"),
                ).json()
                await_result(revision)
                updated = client.get(f"/api/v1/presentations/{accepted['presentation_id']}").json()
                assert updated["document_token"] != current["document_token"]
                assert updated["document"]["slides"][1] == current["document"]["slides"][1]
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
