# /autoplan Review Record — GLOBE_INTEGRATION.md

Run: autoplan-mark-lvi-20261026-134124
Plan: /home/hermes/Downloads/Mark-LVI-main/GLOBE_INTEGRATION.md
Phases: CEO (ran), Design (skipped — no UI scope), DX (ran), Eng (ran)
Outside coverage: Codex unavailable (not authenticated)

## CEO Review — Summary

- High: No defined user scenario or success metric; JARVIS being able to "open the globe" is not a user outcome.
- High: Unvalidated premises — users need a 3D globe, license/compliance clean, MCP bridge is right pattern, local loopback is acceptable.
- High: Stabilization numbers (8,586 tests passed) conflated with unvalidated rendering, voice, live feeds, persistent tab control.
- Critical: Voice-driven interaction and persistent tab control are expected but explicitly not built/validated.
- High: Cesium pinned to 1.138.0 creates future debt.
- High: No fallback when globe service unavailable.
- Recommendation: Ship behind a feature flag; require user scenario, compliance sign-off, validation checklist, and fallback design before GA.

## DX Review — Summary

- Error Messages score capped at 4/10 (Critical CAP4): browser launch is unverified and has no non-interactive alternative.
- High: port-occupied, missing dependencies, bridge unreachable, and call-validation paths lack stable codes, recovery bounds, and non-interactive fixes.
- Medium: no concrete hello-world example; `call` accepts raw JSON string; no launcher port override; no escape hatches for browser auto-launch / action discovery; upstream test failures not tracked.
- Recommendation: Add `--no-browser` / env escape hatches, stable error codes with recovery commands, and copy-paste examples.

## Eng Review — Summary

- Critical: `mcp_bridge.mcp_call` uses 3-second read timeout instead of 60; `test_globe.py` is missing despite validation instructions.
- High: three MCP transports duplicated; hardcoded ports/paths; `_start_server` deadlocks on full pipes; `_stop_server` uses unsafe `pkill`; implementation scope exceeds documented plan.
- High: `globe_panels.py` embeds user input into HTML without escaping.
- Medium: process/lifecycle races, broad exception catching, voice patterns hijacking non-globe queries, weather command using placeholder coordinates.
- Recommendation: Centralize transport in `mcp_bridge.py`, add JARVIS-side tests, PID-based lifecycle, input escaping, and scope clarity.

## Cross-Phase Themes

1. **Validation gaps** — all three phases flagged that upstream globe tests do not prove the JARVIS integration works.
2. **Hardcoded local assumptions** — loopback port, local checkout path, and browser launch are treated as production-ready defaults.
3. **Missing error contract** — DX and Eng both found no stable error codes or recovery instructions for failure paths.
4. **Scope/expectation mismatch** — CEO and Eng both noted voice/persistent-tab features are expected but unimplemented.

## Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|----------------|-----------|-----------|----------|
| 1 | CEO | Treat as SELECTIVE EXPANSION, recommend feature-flagged PoC | Mechanical | P1 completeness | Plan lacks user/compliance validation before GA | None |
| 2 | DX | Add `--no-browser` and stable error codes | Mechanical | P5 explicit + P1 | Error paths currently block headless/CI usage | None |
| 3 | Eng | Centralize transport in mcp_bridge.py and add tests | Mechanical | P4 DRY + P1 | Three transports and missing tests are root causes | None |

## Implementation Tasks (aggregated)

- [ ] CEO-1 — Define a concrete user scenario and success metric for the globe integration.
- [ ] CEO-2 — Produce a license/compliance matrix for globe assets (Nepal imagery, ALPR data, etc.).
- [ ] CEO-3 — Create a validation checklist covering rendering, voice, live feeds, and persistent tab control.
- [ ] CEO-4 — Design a degraded-mode response when the globe service is unavailable.
- [ ] DX-1 — Add `launch-jarvis.sh --no-browser` / `GLOBE_NO_BROWSER=1` escape hatch.
- [ ] DX-2 — Assign stable error codes and recovery commands for port-occupied, missing deps, bridge unreachable, and call-validation failures.
- [ ] DX-3 — Add a copy-paste hello-world example for `list` / `call`.
- [ ] DX-4 — Allow `GLOBE_PORT` override and auto-propagate to `JARVIS_GLOBE_URL`.
- [ ] ENG-1 — Fix `mcp_bridge.py` timeout to use full `(3, 60)` tuple.
- [ ] ENG-2 — Replace `pkill` with PID-tracked termination.
- [ ] ENG-3 — Centralize JSON-RPC transport in `mcp_bridge.py`; remove duplication from `globe_panels.py`.
- [ ] ENG-4 — Add `test_globe.py` covering actions, lifecycle, error paths, and `JARVIS_GLOBE_URL`.
- [ ] ENG-5 — Escape `tool_name` in `globe_panels.py` HTML output.
- [ ] ENG-6 — Decide scope of `globe_panels.py`, `globe_voice.py`, and `launches.py`; document or remove out-of-scope files.
