# GigaChat ML Implementation Plan

> Execute inline with superpowers:executing-plans, using test-driven-development.

**Goal:** Implement the ML_CONTRACT.md interface without live provider calls during development.

**Architecture:** One structured-output request per generation. Revision asks for a full
document with immutable IDs, then copies only explicitly targeted slides into a deep
copy of the original snapshot. Validate the entire provider response before merging.
Unsupported structural commands return an explicit capability error.

**Tech stack:** Python 3.13, official GigaChat Python SDK, existing Pydantic validators.

**Spec:** ML_CONTRACT.md plus the agreed single-request generation approach.

## Constraints
- No paid calls, credentials or changes to the running fixture deployment.
- Import must be side-effect free; SDK initialization is lazy.
- Preserve revision identities/order and untouched slides; never mutate inputs.
- Deadline reserves 10 seconds for validation/publication. No automatic generation retries.
- TLS verification remains enabled; configurable CA bundle.
- One ML worker with concurrency=1 for the personal account; other clients share its quota.
- Work in the existing checkout to avoid creating further project directories; preserve .idea.

## Tasks
- [x] Write failing tests for generation, scoped/global revision, invalid identities,
  unsupported operations, expired deadlines, malformed provider responses.
- [x] Implement presentation_ml package with prompts and lazy SDK transport.
- [x] Add SDK dependency and Docker copy; document opt-in deployment and certificates.
- [x] Run ML tests, existing unit suite and Ruff; review diff.

## Review focus
Emoji use UTF-16 limits; explicit all-slides selection still freezes document title;
provider refusals/truncation are errors; no retries conceal extra cost; missing SDK/key
does not break module import. Real semantic quality and provider schema compatibility
require later live acceptance tests.

## Verification ledger
- Python 3.13/Linux container, initial implementation: 245 passed, 128 skipped.
- Subsequent SDK retry/schema changes and additional transport tests: 14 passed
  on the bundled Python 3.12 fallback; Ruff passes. This is supplementary evidence,
  not a replacement for the supported-runtime run.
- Docker daemon disappeared while Docker Desktop Installer was running. Final
  supported-runtime tests and rebuilt-image readiness are pending its recovery.
- Live GigaChat calls intentionally deferred until the user supplies credentials.
- Existing .idea files were preserved; no commits or remote writes performed.
- Review ruling: keep the backend's existing public exception mapping. Insufficient
  positive budget is RuntimeError/GENERATION_FAILED; only an actually elapsed
  deadline is TimeoutError. A regression test distinguishes the two cases.
- After reboot: final Python 3.13/Linux suite 252 passed, 128 integration tests
  skipped without separate test PostgreSQL/Redis; full backend Ruff passed.
- Live acceptance fixes: revision schema requires IDs; generation adds missing
  structural title/closing slides without discarding model content. Both have
  regression tests. Final suite: 254 passed, 128 skipped; full Ruff passed.
- Opt-in compose.gigachat.yaml deployed locally. Key only in worker, public CA
  mounted read-only. Synthetic UI generation, scoped revision and PPTX export
  passed; temporary diagnostic module removed by worker recreation.
