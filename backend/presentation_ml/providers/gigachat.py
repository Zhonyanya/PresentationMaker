"""Lazy official SDK transport. Never logs payloads, responses or credentials."""

import json
import os

from app.core.errors import AppError
from app.ml.errors import PUBLIC_ERRORS, ProviderFailure


def _provider_error(code):
    return AppError(502, code, PUBLIC_ERRORS[code])


def _request_document(*, system, payload, schema, timeout):
    # Import inside invocation: readiness must not initialize the model or SDK.
    import httpx
    from gigachat import GigaChat
    from gigachat.exceptions import LengthFinishReasonError, ResponseError

    credentials = os.getenv("GIGACHAT_CREDENTIALS", "").strip()
    model = os.getenv("GIGACHAT_MODEL", "").strip()
    if not credentials or not model:
        raise RuntimeError("GigaChat credentials and model must be configured")
    options = dict(credentials=credentials, model=model,
                   scope=os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
                   base_url="https://api.giga.chat/v1", timeout=timeout,
                   verify_ssl_certs=True, max_retries=0)
    if os.getenv("GIGACHAT_CA_BUNDLE"):
        options["ca_bundle_file"] = os.environ["GIGACHAT_CA_BUNDLE"]
    # No application-level retries: a second generation can incur extra cost.
    try:
        with GigaChat(**options) as client:
            response = client.chat({
                "model": model, "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                "temperature": 0.2, "stream": False,
                "response_format": {"type": "json_schema", "schema": schema, "strict": True},
            })
    except httpx.TimeoutException:
        raise _provider_error("ML_PROVIDER_TIMEOUT") from None
    except httpx.TransportError:
        raise ProviderFailure("ML_PROVIDER_UNAVAILABLE", "transport") from None
    except LengthFinishReasonError:
        raise _provider_error("ML_PROVIDER_INCOMPLETE") from None
    except ResponseError as exc:
        if exc.status_code in (408, 504):
            code = "ML_PROVIDER_TIMEOUT"
        elif exc.status_code == 429:
            code = "ML_PROVIDER_BUSY"
        elif exc.status_code >= 500:
            raise ProviderFailure("ML_PROVIDER_UNAVAILABLE", "upstream_5xx") from None
        else:
            raise ProviderFailure("ML_PROVIDER_REJECTED", "upstream_4xx") from None
        raise _provider_error(code) from None
    choice = response.choices[0] if response.choices else None
    if choice and choice.finish_reason == "blacklist":
        raise ProviderFailure("ML_PROVIDER_REJECTED", "blacklist")
    if choice is None or choice.finish_reason != "stop":
        raise _provider_error("ML_PROVIDER_INCOMPLETE")
    content = choice.message.content
    if not isinstance(content, str) or len(content.encode()) > 8_000_000:
        raise ValueError("Invalid GigaChat document size")
    return json.loads(content)


class GigaChatProvider:
    def complete_json(self, *, system, payload, schema, timeout):
        return _request_document(system=system, payload=payload, schema=schema, timeout=timeout)
