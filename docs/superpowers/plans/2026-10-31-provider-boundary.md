# Provider boundary and prompt migration

Continue in ml. Preserve current request messages exactly while moving them to
a versioned prompts module. Define a JSON-provider protocol, select the existing
GigaChat implementation via PM_ML_PROVIDER (default gigachat), and retain
transport.request_document as a compatibility boundary. No new external service
or credentials, no fallback, no live calls. Unknown providers fail explicitly.
Adding a second provider requires selecting its API, implementing the protocol
and running targeted compatibility/quality checks; an arbitrary new key alone
cannot select or authenticate a different service.

- [x] RED: prompt hashes, provider dispatch, unsupported provider handling.
- [x] Extract prompt v1 and GigaChat adapter without semantic changes.
- [x] Run focused ML tests and lint; document configuration and limitations.

Verification: 26 focused tests passed on Python 3.13; Ruff passed. No live
provider calls. Changes are in the ml working tree; the running deployment
still uses the previously built image until the next explicit rebuild.

Prompt v2 remains a draft in the shared outputs and is not activated by this
refactor. Provider-neutral business logic retains validation, scope and IDs.
