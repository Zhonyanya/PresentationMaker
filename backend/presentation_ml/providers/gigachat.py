"""Lazy official SDK transport. Never logs payloads, responses or credentials."""

import json
import os


def _request_document(*, system, payload, schema, timeout):
    # Import inside invocation: readiness must not initialize the model or SDK.
    from gigachat import GigaChat

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
    with GigaChat(**options) as client:
        response = client.chat({
            "model": model, "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "temperature": 0.2, "stream": False,
            "response_format": {"type": "json_schema", "schema": schema, "strict": True},
        })
    if not response.choices or response.choices[0].finish_reason != "stop":
        raise RuntimeError("GigaChat returned an incomplete or refused response")
    content = response.choices[0].message.content
    if not isinstance(content, str) or len(content.encode()) > 8_000_000:
        raise ValueError("Invalid GigaChat document size")
    return json.loads(content)


class GigaChatProvider:
    def complete_json(self, *, system, payload, schema, timeout):
        return _request_document(system=system, payload=payload, schema=schema, timeout=timeout)
