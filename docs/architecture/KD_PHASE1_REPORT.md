# KD — Phase 1 Report (2026-10-28)

Per spec §22: what changed, which files, why, what tests ran, what remains.

## 1. Parallel-editor tree changes reviewed and committed (commit 41f5db2)

- **Files:** ui.py, core/reactor_widget.py, memory/memory_manager.py,
  providers/llm_router.py, MANIFEST.in, core/diagnostics.py,
  arc-reactor-bundle/, assets/models/arc_reactor_assembled.*,
  scripts/export_reactor_bundle.py
- **Why:** a second tool had uncommitted work in the tree; leaving it
  uncommitted risked losing it (twice happened this week via history rewrites).
- **Review verdicts:** atomic memory writes (fsync + os.replace) — kept;
  router empty-fleet guard — kept; assembled reactor with real material
  colors + orbit controls — kept; bottom metrics strip replacing the left
  rail — kept (better than the hidden-rail draft it replaced).
- **Tests:** 71/71 pass; headless boot clean (0 tracebacks).

## 2. Shutdown race fixed (commit b9441df)

- **File:** ui.py (`JarvisUI.set_state` / `write_log`, new `_win_alive()`).
- **Why:** jarvis.log showed `RuntimeError: wrapped C/C++ object of type
  MainWindow has been deleted` — the `is None` guard can't see a deleted C++
  widget under WA_DeleteOnClose.
- **Evidence:** headless boot + shutdown — 0 RuntimeError, "shutdown
  complete" present; suite green.

## 3. pactl gap gated (commit 99b2347)

- **File:** actions/computer_settings.py
- **Why:** `pactl` is not installed on Hermes; volume actions died with a raw
  FileNotFoundError read out loud.
- **Now:** explicit availability gate with an instructive message
  ("install pulseaudio-utils and it just works"). Verified live on Hermes:
  `status=failed ... reason="volume control needs 'pactl'..."`.
- **Note:** installing pulseaudio-utils needs the owner's sudo — not done
  (spec rule 13).

## 4. Cold-boot evidence (commit 6a911f3)

- Source-tree action+plugin discovery: **0.29s**.
- Frozen bundle cold boot to full discovery: **~90s** (PyInstaller PYZ import
  cost, mostly first-boot/OS-cache).
- The apparent >200s "frozen hang" during measurement was **duplicate test
  instances** left by my own timing rig thrashing the CPU — test-harness
  artifact, not a product defect. EGL warnings silenced via
  `OpenGL.platform.egl` hiddenimport (that import set had been lost in an
  earlier history-rewrite reset; re-applied and committed).
- **Open follow-up (Phase 2):** profile per-module import cost in the bundle
  and lazy-load the heaviest (cv2/playwright) where the loaders allow.

## 5. VRAM-aware model router (commits 7177f61 + ee0cbec)

- **Files:** providers/llm_router.py, tests/test_llm_router_vram.py
- **What:** per-model resident-size estimate (explicit `size_gb` or parsed
  from the name), NVIDIA VRAM detection via pynvml, budget = 85% of total
  (Hermes: 7.3 GB of 8.5 GB). Fitting models always outrank CPU-offload ones;
  oversized models stay available as fallback; unknown sizes unpenalized;
  `vram_budget_gb: 0` disables.
- **Tests:** +4 (estimation, preference, overflow fallback, disabled budget).
  One test initially failed (explicit-0 override bug) — fixed before close.

## Acceptance checkpoint (spec §21, items 1–5)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Starts reliably | ✅ | headless boots clean, source + bundle |
| 2 | Mic capture + ASR | ⚠️ partial | audio stack loads, device picker exists; no headless way to prove capture — needs a live mic check by the owner |
| 3 | Local LLM inference | ✅ | qwen3.5:2b answered via Ollama /v1/chat/completions |
| 4 | GPU acceleration verified where configured | ✅ | `ollama ps`: qwen3.5:2b resident 100% GPU (7.0 GB) |
| 5 | Memory survives restart | ✅ | long_term.json + now-atomic writes (P1.1) |

## Remaining / risks

- Phase 1 items complete except live-mic verification (needs the owner's voice).
- D1 (orange vs cyan design tokens) and D2 (apt install gnat/gprbuild/sbcl)
  still open with the owner.
