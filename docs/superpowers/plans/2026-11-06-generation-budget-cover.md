# Generation budget and cover implementation plan

**Goal:** Include cover and closing in the requested slide budget and give the cover the document's subject.

**Architecture:** Keep the public generate/revise interface and content prompt versions. Add a generation wire prompt, constrain the provider schema for all source lengths, then validate the final normalized count. Preserve the existing short-source packing; never truncate content or retry inference automatically. Normalize only the generated cover title; scoped revisions stay unchanged.

**Tech stack:** Python, Pydantic/JSON Schema, pytest, GigaChat SDK, Docker Compose.

- [x] Add regressions for 3/7/8-slide budgets, normalization overflow, explicit/inferred cover titles, and single-call failure.
- [x] Observe the regressions fail without contacting the provider: six generation failures; separate cache regression also failed before its fix.
- [x] Implement schema budget, generation instructions, final validation and cover title alignment.
- [x] Run ML tests and review diff; document behavior and limitations: 88 passed, independent review completed, cache fingerprints updated.
- [x] Rebuild backend once; update API/worker only when no job is active; verify health and deployed code hashes.

Validation: no live inference performed. Model quality, actual output count and cover composition still need one sequential user acceptance run in Edge. More-than-requested output is rejected rather than truncated or retried; fewer slides remain allowed for insufficient source material.

## Follow-up: missing closing response

User acceptance then failed with INVALID_ML_RESPONSE. One explicit sequential synthetic cafeteria-seven diagnostic attempt saved raw output privately outside Git: 7 slides, title + section + five bullets, no closing. Normalization added closing as eighth and budget validation rejected it.

Added ordered-partition recovery for long-source overflow. Adjacent internal slides may be grouped verbatim into text within 800 UTF-16 units and 10,000 note units, preserving all headings/labels and note order. Cover, closing and standalone slides remain intact. No valid partition means rejection, not truncation or retry. A review caught greedy shortest-pair dead ends; regression [600,190,190,600] failed first, then passed after DP partitioning.

Final validation: 93 tests passed; independent review had no remaining blockers. Saved candidate replayed with network disabled, yielding exactly 7 with all content fragments preserved; native frontend PPTX export and rendered cover/merged/closing slides checked. API/worker updated with idle queue, health OK and deployed/source hashes matched. No further paid calls; diagnostic raw data remains outside repository. This supersedes the earlier validation note for the follow-up only.

Ruling: Work in the existing ml checkout to update the already configured local test stand. No branch switching, push, or changes to secrets. Short sources may still yield fewer slides, as required by the existing contract. Minimal-word mode is a separate follow-up.
