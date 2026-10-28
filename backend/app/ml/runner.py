"""One isolated ML invocation; parent enforces the remaining wall-clock budget."""

import contextlib
import json
import os
import signal
import sys
from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.errors import AppError
from app.ml.adapter import get_adapter
from app.presentations.schemas import normalize_document, validate_revision

PUBLIC_ERRORS = {
    "ML_UNAVAILABLE": "ML-модуль недоступен.",
    "ML_CAPABILITY_UNAVAILABLE": "ML не поддерживает эту операцию.",
    "INVALID_ML_RESPONSE": "ML вернул документ неверного формата.",
    "GENERATION_FAILED": "Ошибка выполнения ML.",
}


def main():
    request = json.load(sys.stdin)
    # Independent deadline also applies if the Celery child dies and cannot reap us.
    deadline = datetime.fromisoformat(request["inputs"]["deadline"])
    remaining = (deadline - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        return

    def expire(*_):
        os.killpg(os.getpgrp(), signal.SIGKILL)

    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, remaining)
    try:
        # ML stdout must not corrupt protocol or expose private content in application logs.
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink):
            result = get_adapter().invoke(request["kind"], request["inputs"])
        document = normalize_document(
            result, generation=request["kind"] == "generate", max_bytes=get_settings().max_ml_bytes
        )
        if request["kind"] == "revise":
            validate_revision(
                request["inputs"]["document"], document, request["inputs"].get("target_slide_ids")
            )
        reply = {"document": document}
    except AppError as exc:
        code = exc.code if exc.code in PUBLIC_ERRORS else "GENERATION_FAILED"
        reply = {"error": {"code": code, "message": PUBLIC_ERRORS[code]}}
    except (ValueError, TypeError, KeyError):
        reply = {
            "error": {
                "code": "INVALID_ML_RESPONSE",
                "message": "ML вернул документ неверного формата.",
            }
        }
    except Exception:
        reply = {"error": {"code": "GENERATION_FAILED", "message": "Ошибка выполнения ML."}}
    json.dump(reply, sys.stdout, ensure_ascii=False)
    signal.setitimer(signal.ITIMER_REAL, 0)


if __name__ == "__main__":
    main()
