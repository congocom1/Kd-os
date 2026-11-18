# KD stabilization — October 28, 2026

## Local inference smoke test

Queried loopback Ollama with proxies/redirects disabled. Checked /api/ps first:
no models were resident, so the test did not displace an existing workload.
Confirmed qwen3.5:0.8b was already installed. No model download occurred.

Request: /api/generate, prompt `Reply with exactly the word READY.`, streaming
disabled, thinking disabled, temperature 0, context 2048, output limit 16,
keep_alive 15 seconds, client timeout 90 seconds.

Observed:
- Completed response: `READY`
- End-to-end time including subsequent residency query: 3.292 seconds
- Ollama load_duration: 3,086,131,135 ns
- eval_count: 2; eval_duration: 62,778,000 ns
- /api/ps size_vram: 4,038,391,232 bytes for the tested model

This verifies one local generation and server-reported GPU residency. It is not
a sustained throughput benchmark, proof of all-GPU computation, tool-calling
evaluation, or voice latency measurement. No saved provider settings changed.
The short keep-alive requests automatic release; unloading was not separately
verified. HTTP timeouts are not server-side cancellation guarantees.

## Changes and isolated verification

- Fixed providers/llm_router.py: select(escalate=True) now returns None when no
  higher-tier candidate exists instead of indexing an empty list.
- Added tests for capability filtering, failed-model exclusion, single retry,
  confirmation refusal without UI, cancellation, expiry and single execution.
- Added a two-process memory save/load test using a temporary path, never the
  user's actual memory store.

These confirmation tests cover existing behavior, not full authorization coverage.
Concurrent request replacement, action-bound approval IDs, signed approvals and
universal dispatch enforcement still need design and adversarial tests.

## Remaining gates

Live microphone capture was not requested or activated. Speech recognition,
synthesis, acoustic echo handling, provider cancellation, memory concurrency,
container recovery and backup restoration remain unverified. Existing router
default inventory and sticky escalation behavior remain follow-up work. No
deployment, elevated commands, package installation or security-policy changes.

Rollback: selectively revert the router's empty-candidate return change and
remove this stage's test/document additions if necessary. Do not reset unrelated
HUD, diagnostic or memory changes.