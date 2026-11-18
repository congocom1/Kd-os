# KD release engineering progress — November 15, 2026

## Status: partial implementation; NOT production-ready

Requested primary checkout `/home/hermes/Downloads/Mark-LVI-main` is absent.
Actual checkout: `/home/hermes/.cline/worktrees/ec023/Mark-LVI-main`.
Its `.git` points into the absent primary checkout. Git status/diff cannot be
verified. No Git metadata, user configuration, model directory, or personal
memory migration was intentionally changed by this implementation.

## Commands

From a desktop terminal:

```sh
cd /home/hermes/.cline/worktrees/ec023/Mark-LVI-main
./kd doctor                 # read-only package, hardware and Ollama inventory
./kd start                  # existing desktop app through its native launcher
./kd check                  # full Python suite (two known baseline failures)
```

For a fresh environment, `./kd setup` creates `.venv` and installs existing
`requirements.txt`. This setup path was NOT run or verified from a clean host;
Python dependencies remain bounded ranges, not a reproducible lock. Do not run
it over an environment you need to preserve. `KD_PYTHON` overrides the interpreter;
`JARVIS_PYTHON` remains a compatibility fallback. Launch selection otherwise prefers
the repository `.venv`, then `python3`.

Frontend: `npm --prefix frontend ci --ignore-scripts`,
`npm --prefix frontend test`, and `npm --prefix frontend run build`.
The normal build replaces dashboard static assets: stop the application first.
Verification instead used `-- --outDir /tmp/kd-release-audit/frontend-dist`.

Stop the existing app normally before starting the updated one. The new launch
lock prevents duplicate `./kd start` invocations, not legacy `python main.py`
instances. No second desktop instance was started for this work.

## Implemented

- `core/camera.py`: process-local reference-counted camera leases, used by the
  desktop preview, gesture controller, and vision snapshot. Last close releases
  the handle; failed opens release immediately. No frame storage or transfer.
- Preview no longer starts duplicate workers and releases its lease in `finally`.
- Loopback dashboard listeners by default. LAN binding needs both `KD_BIND_HOST`
  and `KD_ALLOW_LAN=1`; existing TLS/pairing authentication remains required.
- Browser WebSocket origins must match Host on all three endpoints. Originless
  native clients still need pairing tokens. This is not a complete Host/session
  security audit.
- KD setup/start/doctor/check entrypoint and frontend protocol test command.
- Optional God's Eye Vite dev server is no longer auto-started by the launcher.
  Explicit development-only opt-in: `KD_START_GEV_DEV=1`.

Preserved PyQt desktop, Python provider pipeline, FastAPI dashboard, and existing
Vite UI rather than replacing them with a parallel React application. Legacy
identifiers/data remain compatible. No new cloud provider or remote device added.

## Evidence

Files under `docs/evidence/kd-hardening/` contain observed logs, not readiness claims.

- Baseline: two failures (missing trimesh, missing sentence_transformers), one
  native PyTorch3D skip. Final full suite before the last two boundary tests:
  178 passed, 2 failed, 1 skipped; final rerun recorded separately.
- Synthetic ownership and dashboard tests exercise no physical microphone/camera.
- Frontend protocol: 3 passed. Production build: succeeds with Vite 5.4.21.
- npm audit reports esbuild moderate and Vite high advisories. No forced update.
- Host: Ubuntu 26.04.1, RTX 5050 Laptop GPU, 8151 MiB, driver 595.99.02.
- Local Ollama inventory includes requested chat, coding, vision and embedding
  candidates. No model download or saved model selection changed.
- Synthetic streaming qwen3.5:4b request, requested context 4096, output limit 16:
  first text 8.552s then 5.266s. Both requests completed. `/api/ps` returned no
  resident models afterward, so GPU placement and warm residency are UNVERIFIED.
- faster-whisper and Piper distributions exist; only CPU ONNX Runtime distribution
  reported. Driver presence is not CUDA/cuDNN backend verification.

## A–F gates still open

A: Primary checkout/Git repair; actual updated desktop launch and GUI journey.
B: Offline microphone → VAD → transcript → local response → spoken audio;
French/English voices; interruption/mute/device-removal behavior; cold/warm speech
latencies; bounded GPU queue shared by STT/chat/vision/embeddings. Current camera
leases serialize native reads and may block on a driver; no hard timeout or
cross-process frame broker. Detection probes and legacy trackers are not shared.
C: Encrypted opt-in speaker profiles; enrolled/unknown/uncertain validation;
durable conversation CRUD; authorized hybrid search; embedding deletion;
backup/restore in an isolated environment. Existing memory/profile modules are
not evidence these requirements are satisfied.
D: Live telemetry freshness and queue UI; authorized Wayland portal capture;
physical camera tracking and desktop window/OCR checks.
E: Universal typed action/argument-bound approvals, isolated coding worker,
timezone-aware scoped schedules and deduplication; connector credential checks;
complete command-center journeys. No connector sends were performed.
F: Category-specific cloud consent enforcement across ALL existing providers,
keyring migration, health/readiness contracts, systemd deployment, request bounds,
dependency remediation, pinned Python lock, full lint/type checks and browser QA.

No internet disconnection test was performed. No microphone recording or speaker
enrollment was performed. No personal-data backup restoration was claimed. The
existing app may still use cloud providers configured before this work; the new
launcher does not enforce offline mode. Do not treat it as a privacy boundary.

## Rollback and data safety

Pre-edit copies of modified existing code are in
`/tmp/kd-release-audit/before/` (temporary; preserve privately if needed).
Compare each against the current file before restoring, since other edits may
have occurred. New files: `kd`, `core/camera.py`, camera lease/boundary tests,
this report, and evidence. Revert consumer imports before removing camera.py.
Restore frontend/package.json if removing its test command. `npm ci` rebuilt
frontend node_modules from the existing lockfile. No data migration was applied;
there is no data downgrade step. Test-suite side effects were not proven absent.

Future data migration must first stop writers, create a private snapshot (SQLite
online backup where applicable), verify a restore to a temporary directory, and
record a rollback procedure before changing the live schema.