# GigaChat prompt v2, opt-in

User deferred other providers. Implemented separate v2 common/generate/revise
templates and PM_ML_PROMPT_VERSION selection; v1 remains default and its exact
pre-refactor messages are hash-checked. No HF adapter or dependency was added.

Focused tests: 29 passed initially. Review added a regression test for scope
changes in acceptance-cache profiles; source/model/scope/prompt are distinct
from a credential and no keys are recorded. Live run: one short synthetic
generation, 5.41 seconds, five slides, source facts and caveats retained.
A subsequent live v2 revision passed in 12.03 seconds: exact requested heading
replacement, all other fields unchanged, input snapshot not mutated. This is
not a broad v1/v2 comparison or acceptance on real reports.

Rebuilt API/worker in ml; readiness module is healthy, active prompt remains v1.
To opt in later, add PM_ML_PROMPT_VERSION=v2 to backend/.env and recreate worker
with compose.yaml + compose.gigachat.yaml. No automatic provider fallback.

Review ruling: the proposed 'v1 changed' finding was checked against committed
HEAD: the two questioned instructions were already present before extraction.
No rollback of those instructions was needed.
