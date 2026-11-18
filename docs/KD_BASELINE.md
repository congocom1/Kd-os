# KD migration: Phase 0 baseline and execution plan

Observed October 28, 2026. This is a partial repository audit, not a security
certification or production-readiness claim. Existing uncommitted HUD/reactor
changes have been preserved. No services were deployed or packages installed.

## Evidence-backed inventory

| Area | Evidence | Status / gap |
| --- | --- | --- |
| Host | Local OS probe: Ubuntu 26.04.1 LTS; 16 logical CPUs; 32,797,839,360 bytes RAM | Detected, not load-tested |
| GPU | nvidia-smi: RTX 5050 Laptop, 8151 MiB, driver 595.99.02 | Driver query works; inference not verified |
| Python | Repository venv: 3.14.9 | Existing tests executable |
| Native tools | gcc/g++ found; nvcc, cmake, gnat, gnatprove, sbcl absent on PATH | No native migration or formal verification claimed |
| Inference | Loopback Ollama /api/tags returned 15 models | Inventory works; generation, VRAM residency and throughput untested |
| Audio | main.py capture path; providers/engine_pipeline.py, stt_whisper.py, tts_piper.py | Existing STT/LLM/TTS pipeline; live capture and speech untested |
| Packages | faster-whisper 1.2.1, Piper 1.8.0, sounddevice 0.5.6, both ONNX distributions 1.31.0 | Installed metadata only; GPU provider compatibility unverified; torch absent |
| Desktop | ui.py, core/reactor_widget.py | PyQt6 HUD and interactive reactor; no React replacement implemented |
| Dashboard | dashboard/server.py | FastAPI, authentication checks, TLS-related code; full authorization review pending |
| Memory | memory/memory_manager.py | JSON categories, timestamps, retrieval; no PostgreSQL/pgvector service established by this audit |
| Tools | core/action_loader.py, plugin_loader.py, confirm.py | Existing tool dispatch and UI confirmation; not a universal out-of-process policy boundary |
| Routing | providers/llm_router.py | Configured capability/cost tiers; no verified VRAM-aware admission control |
| Containers | docker-compose.yml | Existing JARVIS, globe, Kronos and speech topology, not the proposed KD services |

Ollama inventory included local coding, embedding, vision-named and general models.
Names are not capability verification. Run the diagnostic command for the actual
inventory; it neither pulls nor loads models. Large installed models must not be
assumed to fit the GPU.

## Current architecture

```text
PyQt HUD <-> main.py orchestration <-> selected conversation engine
                                |       |-- cloud/live provider
                                |       `-- STT -> LLM -> TTS pipeline
                                |-- actions/plugins/skills
                                |-- JSON memory
                                `-- FastAPI dashboard
```

## Findings requiring follow-up

1. Memory used direct overwrite: an interrupted save could truncate the store.
   This stage adds same-directory temporary writes, fsync, and atomic replacement.
   Failure-injection tests preserve the previous file. This does NOT resolve
   multi-process lost updates or guarantee directory durability after power loss.
2. Router defaults list models absent from the observed inventory. Saved provider
   settings were intentionally not read or modified; actual selection is unknown.
3. Dashboard code binds all interfaces; Compose publishes host ports without a
   loopback address. Verify intended LAN pairing, auth, TLS and firewall rules
   before any deployment. Public exposure has NOT been measured.
4. Compose requires globe, Kronos and authenticated legacy speech image health
   before JARVIS starts. Startup independence and real health endpoints need tests.
5. launch.sh starts the globe before display validation; child cleanup needs review.
6. Both CPU and GPU ONNX packages are installed. Test actual provider loading in
   isolation before making GPU defaults; package presence is insufficient.
7. Confirmation is in-process and covers selected actions. Ada must not become a
   cosmetic wrapper around bypassable execution paths.

## ADR-001: incremental compatibility-first migration (accepted for this stage)

Keep existing launchers, config names, JSON stores, provider APIs, PyQt UI and Git
history. Introduce KD-facing adapters and versioned contracts alongside them.
Do not rename the installed jarvis entry point or move user data in Phase 0.

Target boundaries: UI -> authenticated gateway -> orchestrator -> authorization
adapter -> scoped executor -> verifier. Model, audio, memory and symbolic services
communicate through explicit versioned contracts. Every executable action must
cross authorization at dispatch, not merely during planning.

## ADR-002: evidence before language migration (proposed)

Python stays the working implementation. Add Ada/SPARK only after the toolchain
is available and a narrow authorization state machine has a tested Python
contract, differential tests and fail-closed behavior. Lisp planning should return
plans, never invoke tools. Introduce C/C++ only for a measured hot path, with
sanitizers and a comparable baseline. No new framework dependency in this stage.

## Ordered implementation plan and gates

1. **Stabilize:** subprocess restart tests for memory; synthetic EN/FR audio
   fixtures; device-failure tests; local model generation/cancellation test using
   one approved installed model; provider failure and fallback tests. Capture
   latency distributions before selecting budgets. Live mic/camera remains opt-in.
2. **Security baseline:** enumerate every executable tool and sensitive dashboard
   route; test denial, expiry, replay, scope and cancellation. Specify signed
   approval claims and use an established implementation. No custom cryptography.
3. **Runtime contracts:** versioned task IDs, actor/scope, deadline, correlation ID,
   approval reference, cancellation and result evidence; health must distinguish
   unavailable, degraded, ready and untested. Add adapters to existing providers.
4. **Memory migration:** additive provenance/retention schema, export/import,
   encrypted backups, restore drill, then optional PostgreSQL/pgvector dual-read
   validation. Never delete the JSON source until cutover is explicitly approved.
5. **Native/symbolic services:** toolchain setup by approval; isolated contracts,
   benchmarks, differential tests and per-service rollback flags.
6. **KD interface:** connect real runtime events and telemetry first. Add design
   tokens, reduced-motion mode and accessible controls, then screens individually.
   Keep native desktop available until feature parity. No fake activity metrics.
7. **Deployment:** loopback-first Compose profiles, non-root services, scoped
   mounts, verified probes, secret handling, restart and backup restoration drills.

## Diagnostic operation

From the repository root:

```bash
/home/hermes/Downloads/Mark-LVI-main/.venv/bin/python -m core.diagnostics
QT_QPA_PLATFORM=offscreen /home/hermes/Downloads/Mark-LVI-main/.venv/bin/python -m pytest tests -q
```

The diagnostic emits versioned JSON, queries only loopback Ollama with redirects
and proxies disabled, and uses a bounded nvidia-smi query. It does not read secret
config, capture devices, load models, start containers or claim readiness.
Its exit status indicates command execution, not acceptance of production gates.
Review model names and host metadata before sharing reports externally.

## Rollback and recovery

No data format migration occurred. Memory tests write only temporary fixtures.
Keep a secure backup of configuration and memory before later migration steps.
To roll back this stage, selectively revert only the atomic-save hunk in
memory/memory_manager.py and remove the new diagnostic/test/document files after
review. Do not reset the working tree: it contains unrelated ongoing HUD work.
Backup restoration and full power-loss recovery are not yet verified.

## Production readiness

**Not production-ready against the KD acceptance criteria.** Voice, GPU inference,
authorization completeness, container recovery, full UI workflows, restored backups,
security scanning and performance budgets remain unverified. No Ada/Lisp/C++ KD
services, new React screens, distributed runtime or formal proofs were delivered
in this stage. This document is the starting architecture/migration decision record,
not a claim that all requested deliverables are complete.