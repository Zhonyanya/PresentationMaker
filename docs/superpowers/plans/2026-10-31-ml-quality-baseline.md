# ML quality baseline

Continue on branch ml. Reuse the three explicitly fictional frontend examples,
add two synthetic edge cases, and run sequential one-call generations. This is
a regression baseline, not acceptance on five real reports.

- [x] Tests: missing fact anchors, repeated visible content, notes excluded.
- [x] CLI: explicit --live, per-case documents, cache to avoid paid repeats,
  structural validation and review indicators; never log documents or secrets.
- [x] Two targeted cases per user's economy preference; three remain unrun.
- [x] Record limitations and next fixes. No automatic live retries or LLM judges.

Ruling: only two live calls; short-caveats failed with ConnectError (no retry),
Unicode case succeeded. Model treated the malicious quotation as untrusted;
the literal 999 flag is contextual, not an injection failure. Real-report
acceptance and a successful short-report baseline remain outstanding.

Exact text anchors are review hints, not an entailment metric: paraphrases may
be flagged despite correctness and hallucinations may pass them.
