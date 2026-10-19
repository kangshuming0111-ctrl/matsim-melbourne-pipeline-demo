# Explaining the P2 AI extension

## English introduction

I added a local language-model interface to the simulation analysis. The model interprets a question into a typed read-only plan. SQL and Python compute values, and every numeric result carries its unit, denominator, run IDs and source hashes. A second model step organizes bounded, evidence-backed explanations.

The first development evaluation showed why valid JSON is not enough: the model omitted seeds and changed units or comparison scope. I added deterministic binding for explicit parameters and retained the raw plan and corrections. I then froze the implementation before evaluating reserved questions.

I report the guarded system separately from the deterministic baseline, including failures, fallbacks, latency and cost scope. Local inference has no API fee, but hardware and electricity are not free. This is a bounded analyst interface, not unrestricted causal reasoning.

## Ten follow-up questions

1. Why typed tools instead of generated SQL? Show Plan, the query allowlist and read-only connection.
2. Why is JSON validation insufficient? Show an actual failed response with a wrong seed, unit or scope.
3. Does the score represent the raw model? No. Explain parameter binding, deterministic arithmetic, required claims, fallback and correction counts.
4. Does AI outperform the baseline? Only claim this if measured results support it. This small suite may show no accuracy gain; the model adds routing/organization within a bounded system.
5. How are invented numbers/causes prevented? Facts are calculated outside the model; placeholders and reviewed claim IDs are validated. This sacrifices unrestricted prose and breadth.
6. Is the holdout independent? Reserved before tuning, but a small same-author internal suite, not an external benchmark. Reusing it after fixes is not unseen testing.
7. What happens if the model fails? A labelled deterministic fallback; unavailable data is never replaced by guesses.
8. Can it run a new road experiment? No. It reads and explains reviewed results only.
9. What cost/latency are measured? End-to-end per-question timings and p50/p95, also separating model calls from pre-model refusals. API fee is zero locally; energy/hardware are unpriced.
10. What comes next? Independently authored paraphrases, explicit conversational context, stronger ambiguity handling and another model comparison. These remain future work.

Use actual evaluation scores. Do not claim fine-tuning, independent simulator authorship, production reliability, baseline superiority or a proved causal detour mechanism. Implementation was AI-assisted.
