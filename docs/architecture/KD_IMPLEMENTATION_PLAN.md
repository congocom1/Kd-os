# KD — Implementation Plan (from Phase 0 evidence)

Anchored to `KD_MASTER_SPEC.md` §20 and the Phase 0 audit. Small, testable
stages; each stage ships with tests and a commit. Nothing here assumes an
uninstalled dependency.

## Phase 1 — Stabilization (next up, in priority order)

1. **Commit-review the parallel-editor tree changes** (ui.py, reactor_widget,
   llm_router, memory_manager, arc-reactor-bundle) — review, run the suite,
   commit or revert deliberately. Blocks everything else.
2. **Fix the shutdown race** (`ui.py:7105` set_state → deleted MainWindow):
   guard emitters behind `_closed` (pattern already exists in JarvisUI).
3. **Audio tooling gap:** install `pulseaudio-utils` (pactl) or gate those
   actions on its presence with a spoken explanation (already the pattern for
   Wayland limits).
4. **Startup reliability:** cold-boot timing evidence — measure action/plugin
   discovery time in the PyInstaller bundle (observed slow: minutes under
   xvfb); profile and cut.
5. **VRAM-aware model router:** cap resident model size at ~5 GB on Hermes
   (audit evidence), prefer qwen3.5:4b / qwen3-vl:4b / embeddings; make
   providers/llm_router.py enforce it with a config override.
6. Acceptance checkpoint: §21 first five criteria demonstrably green.

## Phase 2 — Shared runtime

7. Typed service contracts for the five managed services (kronos, awesome-llm,
   data-analyst, knowledge-rag, GEV): one `ServiceContract` dataclass in
   core/app_manager.py (port, health path, start cmd, venv) replacing per-app
   ad-hoc methods.
8. Unified health endpoint surfaced in the HUD (right-rail status block reads
   real AppManager state).
9. Structured JSON logging for actions (extend core/outcome.py; logs stay local).

## Phase 3 — Multi-language (only after 1–2 land)

10. Install toolchains (needs owner approval — apt installs):
    `gnat`, `gprbuild`, `sbcl`.
11. **First Ada/SPARK component:** the authorization/risk classifier as a
    policy library with C ABI, called from core/confirm.py — small, formal,
    exactly the spec's intent. Prove the boundary works; expand later.
12. **First Lisp component:** symbolic plan-validation service over a socket,
    used by core/unified_agent routing. Parallel-validated against the
    existing keyword router.

## Phase 4 — HUD/UI (design decision required first)

13. Owner decision: keep JARVIS Orange identity (shipping) vs §6.2 cyan tokens.
14. Then: design tokens module, command-center screen real-data wiring,
    emergency-stop control (hooks into core/os.py shutdown), memory explorer
    on top of memory/long_term.json.

## Phase 5–6 — Autonomy + hardening

15. Approval workflow already exists (core/confirm.py) — extend to agent task
    queues with execution logs.
16. Docker Compose stack exists at repo root — validate `docker compose up`
    as the single startup command; add healthchecks for the new services.

## Open decisions for the owner

- **D1 (blocks Phase 4):** orange JARVIS identity vs §6.2 cyan design tokens.
- **D2 (blocks Phase 3):** approve apt installation of gnat/gprbuild/sbcl.
- **D3:** the parallel editor's uncommitted changes — keep them (they look
  intentional) or have me review-and-commit them as a unit?
