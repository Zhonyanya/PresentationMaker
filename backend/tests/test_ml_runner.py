import copy
import io
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.errors import AppError
from app.db.models import utcnow
from app.ml import runner
from app.worker import call_ml


@pytest.fixture
def run_ml(monkeypatch):
    """Exercise the runner protocol without arming a timer in the pytest process."""
    timer = Mock()
    monkeypatch.setattr(
        runner, "signal", SimpleNamespace(signal=Mock(), setitimer=timer, SIGALRM=14, ITIMER_REAL=0)
    )

    def run(invoke, *, kind="generate", inputs=None):
        request = {
            "kind": kind,
            "inputs": {"deadline": (utcnow() + timedelta(minutes=1)).isoformat(), **(inputs or {})},
        }
        output = io.StringIO()
        monkeypatch.setattr(runner.sys, "stdin", io.StringIO(json.dumps(request)))
        monkeypatch.setattr(runner.sys, "stdout", output)
        monkeypatch.setattr(runner, "get_adapter", lambda: SimpleNamespace(invoke=invoke))
        runner.main()
        return output.getvalue()

    return run, timer


def test_runner_normalizes_json_and_keeps_ml_stdout_out_of_protocol(run_ml, document):
    run, timer = run_ml
    document["slides"][0].pop("id")

    def invoke(kind, inputs):
        assert kind == "generate" and inputs["slideCount"] == 12
        print("private report and model diagnostics")
        return json.dumps(document, ensure_ascii=False)

    output = run(invoke, inputs={"slideCount": 12})
    assert "private report" not in output
    result = json.loads(output)["document"]
    assert result["title"] == document["title"]
    assert len({slide["id"] for slide in result["slides"]}) == len(result["slides"])
    assert timer.call_args_list[0].args[1] > 0
    assert timer.call_args_list[-1].args == (runner.signal.ITIMER_REAL, 0)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        *[(AppError(503, code, "private exception"), code) for code in runner.PUBLIC_ERRORS],
        (AppError(500, "INTERNAL_SECRET", "private exception"), "GENERATION_FAILED"),
        (ValueError("private exception"), "INVALID_ML_RESPONSE"),
        (TypeError("private exception"), "INVALID_ML_RESPONSE"),
        (KeyError("private exception"), "INVALID_ML_RESPONSE"),
        (RuntimeError("private exception"), "GENERATION_FAILED"),
    ],
)
def test_runner_errors_are_public_and_timer_is_disarmed(run_ml, error, code):
    run, timer = run_ml

    def invoke(*args):
        raise error

    output = run(invoke)
    reply = json.loads(output)
    reply.pop("diagnostic", None)
    assert reply == {
        "error": {"code": code, "message": runner.PUBLIC_ERRORS[code]}
    }
    assert "private" not in output and "INTERNAL_SECRET" not in output
    assert timer.call_args_list[-1].args == (runner.signal.ITIMER_REAL, 0)


@pytest.mark.parametrize(
    ("adapter_result", "diagnostic"),
    [
        (json.JSONDecodeError("private parser detail", "private model response", 0),
         "adapter_invalid_json"),
        ({"slides": [], "private field": "private model response"}, "document_schema"),
    ],
)
def test_runner_reports_only_a_safe_validation_reason(run_ml, adapter_result, diagnostic):
    run, _ = run_ml

    def invoke(*args):
        if isinstance(adapter_result, Exception):
            raise adapter_result
        return adapter_result

    output = run(invoke)
    assert json.loads(output)["diagnostic"] == diagnostic
    assert "private" not in output


def test_runner_expired_deadline_never_calls_ml(run_ml):
    run, timer = run_ml
    invoke = Mock(side_effect=AssertionError("Expired work reached ML"))
    assert run(invoke, inputs={"deadline": (utcnow() - timedelta(seconds=1)).isoformat()}) == ""
    invoke.assert_not_called()
    timer.assert_not_called()


@pytest.mark.parametrize("outside_scope", [False, True])
def test_runner_validates_revision_scope(run_ml, document, outside_scope):
    run, _ = run_ml
    revised = copy.deepcopy(document)
    revised["slides"][2 if not outside_scope else 1]["notes"] = "Changed"
    output = json.loads(run(
        lambda *args: revised,
        kind="revise",
        inputs={"document": document, "target_slide_ids": [document["slides"][2]["id"]]},
    ))
    if outside_scope:
        assert output["error"]["code"] == "INVALID_ML_RESPONSE"
    else:
        assert output == {"document": revised}


@pytest.mark.parametrize("change", ["content", "rename", "replace_all", "move", "insert", "delete"])
def test_runner_enforces_revision_identity_without_explicit_targets(run_ml, document, change):
    run, _ = run_ml
    before = copy.deepcopy(document)
    revised = copy.deepcopy(document)
    slides = revised["slides"]
    if change == "content":
        slides[2]["body"] = "Changed body"
    elif change == "rename":
        slides[2]["id"] = "replacement-id"
    elif change == "replace_all":
        for index, slide in enumerate(slides):
            slide["id"] = f"replacement-{index}"
    elif change == "move":
        slides.insert(4, slides.pop(2))
    elif change == "insert":
        slides.append({**slides[2], "id": "new-slide"})
    else:
        slides.pop(2)
    output = json.loads(run(lambda *args: revised, kind="revise", inputs={"document": document}))
    if change == "content":
        assert output == {"document": revised}
    else:
        assert output == {
            "error": {
                "code": "INVALID_ML_RESPONSE",
                "message": runner.PUBLIC_ERRORS["INVALID_ML_RESPONSE"],
            }
        }
        assert "document" not in output
    assert document == before


@pytest.mark.parametrize(
    "outcome", ["success", "nonzero", "expired", "unknown", "invalid_json", "diagnostic", "private",
                "provider_transport", "provider_private"]
)
def test_parent_protocol_checks_reply_and_always_reaps_process(monkeypatch, document, outcome, caplog):
    from app import worker

    process = Mock(pid=12345, returncode=1 if outcome in {"nonzero", "expired"} else 0)
    start = Mock(return_value=process)
    reply = {"error": {"code": "PRIVATE_ERROR"}} if outcome == "unknown" else {"document": document}
    if outcome in {"diagnostic", "private"}:
        reply = {
            "error": {"code": "INVALID_ML_RESPONSE"},
            "diagnostic": "adapter_schema" if outcome == "diagnostic" else "private model data",
        }
    if outcome.startswith("provider_"):
        reply = {
            "error": {"code": "ML_PROVIDER_UNAVAILABLE"},
            "diagnostic": "transport" if outcome == "provider_transport" else "private model data",
        }
    exchange = Mock(return_value=b"{" if outcome == "invalid_json" else json.dumps(reply).encode())
    kill = Mock()
    monkeypatch.setattr(worker.subprocess, "Popen", start)
    monkeypatch.setattr(worker, "exchange", exchange)
    monkeypatch.setattr(worker.os, "killpg", kill, raising=False)
    monkeypatch.setattr(worker, "signal", SimpleNamespace(SIGKILL=9))
    deadline = utcnow() + timedelta(seconds=-1 if outcome == "expired" else 60)
    if outcome == "success":
        assert call_ml("job", "attempt", "generate", {"slideCount": 8}, deadline) == document
    elif outcome in {"unknown", "invalid_json"}:
        with pytest.raises(ValueError):
            call_ml("job", "attempt", "generate", {}, deadline)
    elif outcome == "expired":
        with pytest.raises(TimeoutError):
            call_ml("job", "attempt", "generate", {}, deadline)
    elif outcome in {"diagnostic", "private"}:
        with pytest.raises(AppError) as exc:
            call_ml("job", "attempt", "generate", {}, deadline)
        assert exc.value.code == "INVALID_ML_RESPONSE"
        expected = "adapter_schema" if outcome == "diagnostic" else "unspecified"
        assert f"ml_invalid_response job_id=job reason={expected}" in caplog.text
        assert "private model data" not in caplog.text
    else:
        with pytest.raises(AppError) as exc:
            call_ml("job", "attempt", "generate", {}, deadline)
        if outcome.startswith("provider_"):
            assert exc.value.code == "ML_PROVIDER_UNAVAILABLE"
            reason = "transport" if outcome == "provider_transport" else "unspecified"
            assert f"code=ML_PROVIDER_UNAVAILABLE reason={reason}" in caplog.text
            assert "private model data" not in caplog.text
        else:
            assert exc.value.code == "GENERATION_FAILED"
    assert start.call_args.kwargs["start_new_session"] is True
    payload = json.loads(exchange.call_args.args[1])
    assert payload["inputs"]["job_id"] == "job"
    assert payload["inputs"]["deadline"] == deadline.isoformat()
    kill.assert_called_once_with(process.pid, worker.signal.SIGKILL)
    process.stdin.close.assert_called_once()
    process.stdout.close.assert_called_once()
    process.wait.assert_called_once()
