# GigaChat ML integration

`backend/presentation_ml` implements `generate` and `revise` from ML_CONTRACT.md.
At most one structured-output request is made per operation. Explicit unsupported
slide-structure commands can be refused locally without any provider request. There is no automatic
regeneration or paid fallback. SDK generation retries are explicitly disabled.
Importing the package does not import the SDK or initialize a client.

## Provider boundary and prompts

`presentation_ml/prompts.py` holds versioned shared and operation-specific
instructions (default `PM_ML_PROMPT_VERSION=v1`). The migration preserves the exact earlier
system messages; their hashes are checked offline. The more detailed v2 templates
are in `presentation_ml/prompt_templates`. Set `PM_ML_PROMPT_VERSION=v2` in the
worker environment to opt in. v2 passed one live short-report generation in
5.41 seconds, retaining the source facts and caveat. A targeted v2 revision then
passed in 12.03 seconds: only the explicitly requested heading changed, with
the entire rest of the document compared for exact equality. These are two
synthetic smoke cases, not a complete quality comparison. v1 remains the default.
Experimental v3 and its measured limitations are described at the end of this guide.

`transport.request_document` dispatches through the JsonProvider protocol in
`presentation_ml/providers`. `PM_ML_PROVIDER=gigachat` selects the only currently
implemented adapter (and is the default when unset). Its SDK, credentials and
TLS handling live in `providers/gigachat.py`. Unknown provider names fail with
NotImplementedError; there is no silent fallback or credential forwarding.
To support another service, implement `complete_json(system, payload, schema,
timeout)` and add its explicit selection in get_provider. Validate its schema
support and a small quality sample before claiming interchangeability.
Backend/frontend and the generate/revise contract remain provider-independent.
Hugging Face integration is deferred by user request; no HF client or keys are used.

Changing the key of the same service usually changes only its secret. Changing
the service also changes the provider/model profile and may require different
authorization or endpoint settings. Docker environment changes require worker
recreation. Do not use a GigaChat authorization key as another provider's key.

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
worker through the opt-in Compose override and its ignored env_file, and set PM_ML_ADAPTER/module
and PM_ML_MODULE on api too for readiness. The API needs the module available,
but does not need the provider credential for its import-only readiness probe.
Keep one ML worker with concurrency=1; do not run other requests against the
same personal account concurrently. Separate deployments need a shared limiter.

## Revision behavior

For revision-wire-v2 the model returns an internal object with required status
and document fields. Applied edits use {"status":"applied","document":<full document>};
refusals use {"status":"unsupported","document":null}. The module unwraps and
validates the full candidate document and its
ordered IDs. For explicit targets, only selected slide objects are copied into
a deep copy of the original snapshot; its title and other slides remain unchanged.
This also applies when all slide numbers are explicitly selected. With no target
lists, the model may revise content and the document title, preserving structure.
The original input object is never mutated. Unsupported structural operations
are represented internally by the unsupported status and raised as NotImplementedError.
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
identity. Unambiguous supported-language slide-structure commands are rejected locally before
provider work. The conservative guard handles explicit Russian/English imperatives,
excludes tested negated/quoted phrases and does not classify arbitrary language.
Other unsupported-command detection depends on the model and
requires adversarial live examples. Do not claim production readiness from
offline tests. The module reserves ten seconds before the backend deadline.
If time remains but is insufficient for this reserve, it declines the call as a
normal generation failure (GENERATION_FAILED), rather than declaring the backend
deadline expired early. The backend owns the actual JOB_TIMED_OUT transition.

Official reference: https://developers.sber.ru/docs/ru/gigachat/guides/structured-output

## Economical quality checks

Five explicitly synthetic cases are in `backend/tests/fixtures/ml_quality_cases.json`:
three existing fictional frontend reports, one short report with caveats, and one
Unicode/untrusted-quote case. These are not five real-report acceptance documents.

From backend, with GigaChat variables already in the process environment:

```bash
# Offline analysis only; no provider calls.
uv run --locked python -m tools.ml_acceptance --output /private/results
# Explicitly select the case(s) for live calls; calls are sequential.
uv run --locked python -m tools.ml_acceptance --live --case short-caveats --output /private/results
```

The CLI requires explicit case selection for live mode. Saved successful documents
are reused for later analysis. Failed or interrupted attempts block implicit
retries: choose a new output directory deliberately if another paid attempt is
needed. Results contain generated content; keep them private and outside Git.
Expected text anchors, exact repetition, and long-text indicators only guide
review. They neither prove factual fidelity nor guarantee PowerPoint fit.
New live results record provider, model, scope, prompt version and prompt hash. A live
run cannot reuse a cached result from a different generation profile; use a new
result directory for an intentional comparison. Old results can still be reviewed
offline with their original metadata (or explicitly unrecorded legacy metadata).

On 2026-10-31 only two live baseline cases were attempted. The short-report case
had a ConnectError and was not retried. The Unicode/untrusted-quote case returned
five valid slides, retained the numbers 24/18/6 and the exam-results caveat, and
did not execute the embedded instruction. It quoted 999% as explicitly unreliable;
the automatic forbidden-fragment flag was therefore reviewed as contextual,
not evidence of instruction execution. Broader quality acceptance remains open.

A later single attempt on year-results failed with ConnectError after 82.98 s;
it was not retried. Unauthenticated DNS/TCP/TLS probes then succeeded for both
the OAuth host and api.giga.chat (expected HTTP 405 and 401 respectively).
This establishes connectivity at probe time, not the cause of the earlier
intermittent failures. The baseline now records exception cause class names and
a TLS-verification flag without exception messages, payloads or credentials.
Do not confuse ConnectError with an HTTP authentication rejection: the SDK uses
the authorization key to acquire the short-lived access token automatically.

An explicitly requested retry of year-results later succeeded in 15.65 seconds
with eight slides. Numeric anchors and the age qualifier (>49) were retained.
Manual review found a semantic repetition of school internet connectivity on
slides 2 and 6 despite no exact-string repetition flag. This demonstrates the
limits of the offline indicators. No additional model judge was called.

## Synthetic acceptance update (2026-11-01)

A paired year-results comparison used identical source/title/requested count (8),
with the existing v1 result reused. v2 returned eight valid slides in 10.33 s
(v1: 15.65 s). Both retained the numeric anchors and >49 age qualifier.
v2 repeated both school internet and the 96% platform adoption on slides 2 and 6;
v1 repeated internet only. v2 also omitted the explicit points unit after +3.4
and used a less specific title-slide heading. This single sample does not show
v2 superiority or establish relative latency/cost. v1 remains the default.
The legacy v1 result has no recorded prompt hash; model aliases can change.

A substantive v1 revision of that saved document succeeded in 8.44 s:
slide 4 changed from bullets to a text paragraph under 450 characters while
retaining the rural subject shortages, age >49 and 46 Zemsky Teacher recruits.
The input object, document title, ordered IDs, count and every unselected slide
were checked for exact preservation. Content was also read manually.

The resulting document was loaded into the running frontend through intercepted
synthetic read responses, then exported using the existing download dialog.
This export check made no ML calls and did not exercise backend job publication.
The eight-slide editable PPTX opened and converted to PDF in LibreOffice;
all eight rendered pages were visually reviewed with no obvious clipping.
At this checkpoint PowerPoint-specific behavior and a fresh full user-path timing
were unverified; see the later end-to-end result below.

One earlier v2 attempt failed after 83.23 s with ConnectError / SSLEOFError.
Subsequent unauthenticated TLS probes and an SDK get_models call (0.78 s)
succeeded with the current credential/certificate. The later generation also
succeeded, but the intermittent connection failure has no established root cause.
TLS stays enabled; there are no automatic paid retries.

The user explicitly deferred real reports for this session. Five-real-report
semantic acceptance remains outstanding; synthetic checks are not production
acceptance. Saved outputs and local handoff notes stay outside committed files.

## Revision protocol and latest acceptance

The former bare-document/unsupported root union failed a live delete command:
the candidate deleted or moved a slide. Validation protected the stored document
but classified it as INVALID_ML_RESPONSE. Revision-wire-v2 adds mandatory root
status/document fields and exact snapshot count constraints. That alone did not
make the model reliably refuse structure changes. `capabilities.py` therefore
refuses explicit Russian/English slide add/delete/move imperatives before calling
the provider. Tested negated/quoted phrases and slide-title/body content edits
still reach the model. This is a conservative fast path, not a general language
classifier. Unknown formulations still depend on model interpretation and strict
result invariants; no universal unsupported-command detection is claimed.

A fresh real browser path with v1 content prompts and revision-wire-v2 passed
registration, generation, substantive paragraph revision, and export in 24.38 s.
It produced nine slides. IDs, order, count, document title and every unselected
slide were compared exactly. A separate API job for deleting slide 4 failed with
ML_CAPABILITY_UNAVAILABLE and preserved the stored document and token. It did
not invoke the provider. The nine exported slides were rendered in LibreOffice
and visually reviewed; no obvious clipping was found. However, manual content
review found an invented feedback-collection action in the generated v1 deck.
The successful transport path is not a semantic acceptance result.

### Experimental v3 (opt in)

Set `PM_ML_PROMPT_VERSION=v3` on the worker to opt in and recreate the worker.
v1 remains the default; v2 and v3 are experimental. v3 builds on v2 instructions
and adds `prompt_templates/v3-generate.txt`. For source text shorter than 1000
Python Unicode code points, its target is min(requested slideCount, 4), including
title/closing. The limit is sent in the payload and schema and checked after
normalization. An over-budget candidate is rejected, never truncated or retried.
This heuristic can compress unusually information-dense short texts, so review
fidelity rather than assuming length alone establishes quality.

On the exact 404-character synthetic source that exposed v1's invented feedback
action, v3 plus the short-source budget returned four slides in 4.71 s. Manual
review retained 12 students, 5 interviews, 3 prototypes, 8/12 self-report and its
non-causal caveat, input/reminder problems, the four-week plans and unknown
funding. The invented action and earlier repetitions were absent. A substantive
v3 revision changed slide 2 from bullets to a paragraph in 5.21 s, preserving
all invariants and facts (8/12 was written in words). The four-slide result was
exported through the real frontend using saved synthetic responses, opened in
LibreOffice and visually reviewed without obvious clipping.

A longer year-results v3 check returned eight slides in 9.74 s with numeric
anchors and >49 preserved and no duplicate internet/platform facts. It shortened
some qualifiers (e.g. compensation for young specialists became compensation
without the beneficiary qualifier). This limits semantic acceptance and is why
v3 is not promoted as a generally superior default. The initial prompt-only v3
attempt returned seven slides, motivating the code-enforced short-source budget.
The generation-policy identifier in acceptance metadata prevents silently reusing
that older result under the changed policy.

Latest targeted offline checks: 57 passed; Ruff passed. Independent focused review
found two issues (final count after normalization and English content-command
false refusals); both were reproduced and fixed with tests. Tests make no paid
calls. SDK connection failures remain intermittent with no established root cause.
Five-real-report acceptance is explicitly deferred by the user. Microsoft
PowerPoint-specific rendering and production deployment remain separate gates.
