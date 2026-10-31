# GigaChat ML: first implementation

`backend/presentation_ml` implements `generate` and `revise` from ML_CONTRACT.md.
One structured-output request is made per operation. There is no automatic
regeneration or paid fallback. SDK generation retries are explicitly disabled.
Importing the package does not import the SDK or initialize a client.

## Configuration

Set these in the ML worker environment (not frontend VITE variables):

```dotenv
GIGACHAT_CREDENTIALS=<authorization key from the project settings>
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=<exact available model ID; verify before selecting>
GIGACHAT_CA_BUNDLE=/path/inside/container/trusted-ca-bundle.pem
PM_ML_ADAPTER=module
PM_ML_MODULE=presentation_ml
```

The authorization key is not a 30-minute access token. The SDK exchanges it
and manages access-token refresh. Never commit the key or include it in logs.
CA_BUNDLE is optional if the required trust chain is already installed. Keep
TLS verification enabled; obtain certificates through the official provider.
Host paths are not container paths: mount the bundle read-only when needed.

The existing compose.yaml intentionally remains a fixture deployment.
Use the checked-in opt-in override for local GigaChat:

```bash
docker compose -f compose.yaml -f compose.gigachat.yaml build api
docker compose -f compose.yaml -f compose.gigachat.yaml up --no-build -d --wait
```

`backend/.env` supplies the credential, scope and model to worker only.
The public root certificate from the provider's official documentation is in
`backend/certs/gigachat-root.crt`, mounted read-only. Update this public file
when the provider changes its certificate chain. Never place secrets in it.
API uses the module for readiness but does not receive provider credentials.

Creating backend/.env alone does NOT pass credentials to Compose containers.
For the opt-in ML deployment, rebuild the backend image, pass the variables to
worker through an ignored Compose override/env_file, and set PM_ML_ADAPTER/module
and PM_ML_MODULE on api too for readiness. The API needs the module available,
but does not need the provider credential for its import-only readiness probe.
Keep one ML worker with concurrency=1; do not run other requests against the
same personal account concurrently. Separate deployments need a shared limiter.

## Revision behavior

The model returns a full candidate document. The module validates its schema and
ordered IDs. For explicit targets, only selected slide objects are copied into
a deep copy of the original snapshot; its title and other slides remain unchanged.
This also applies when all slide numbers are explicitly selected. With no target
lists, the model may revise content and the document title, preserving structure.
The original input object is never mutated. Unsupported structural operations
are represented internally by {"unsupported":true} and raised as NotImplementedError.
This internal response is never returned as a presentation document.

For generation, if the candidate starts with a content slide, the module inserts
a title slide using document.title; if it lacks a closing slide, it appends a
plain closing slide. Content slides are retained, and the final full document
still passes strict backend validation. The final count may therefore exceed
the requested count. Revision never adds these structural slides.

## Live integration verification (2026-10-31)

GigaChat-3-Ultra, personal scope, verified TLS: direct generation and targeted
revision succeeded. A real browser completed registration, generation via the
job queue, revision of slide 2, and PPTX download. Unselected slides, document
title and ordered IDs were compared before/after and preserved. The exported
PPTX contained nine slides. Backend tests: 254 passed, 128 integration tests
skipped without separate test databases; Ruff passed. This synthetic smoke does
not replace the five-report semantic acceptance test. Repetition and unsupported
inferences remain quality risks.

## Verification and limits

```bash
cd backend
uv run --locked pytest -q tests/test_presentation_ml.py
uv run --locked ruff check app tests presentation_ml
```

Tests substitute the provider boundary; no real credentials are needed.
Live acceptance must verify authentication, exact model ID, JSON Schema support
(including unions/references), TLS, refusals, latency/cost and five real reports.
The one-call baseline cannot mechanically prove factual fidelity or semantic
identity. Unsupported-command detection currently depends on the model and
requires adversarial live examples. Do not claim production readiness from
offline tests. The module reserves ten seconds before the backend deadline.
If time remains but is insufficient for this reserve, it declines the call as a
normal generation failure (GENERATION_FAILED), rather than declaring the backend
deadline expired early. The backend owns the actual JOB_TIMED_OUT transition.

Official reference: https://developers.sber.ru/docs/ru/gigachat/guides/structured-output
