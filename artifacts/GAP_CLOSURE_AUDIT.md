# KD Release Engineering — Gap Closure Audit (Complete)

Date: 2026-11-16
Checkout: /home/hermes/.cline/worktrees/ec023/Mark-LVI-main
Team-agent infrastructure: UNAVAILABLE (authentication failures on all runs)
Execution mode: Direct (this agent performed all audits)

## Summary

Five audit artifacts were produced under artifacts/:
- voice_pipeline_audit.json
- action_scheduler_audit.json
- frontend_command_center_audit.json
- ops_release_audit.json
- security_audit.json

All five files validated as parseable JSON.

## Findings by area

### A — Voice pipeline (B, C partially)
- All stages exist individually: wake word (openwakeword), VAD (faster-whisper vad_filter), STT (WhisperSTT/VoskSTT), speaker ID (SpectralSpeakerEmbedder), LLM (engine_pipeline), action dispatch (50 TOOL actions), TTS (Kokoro/EdgeTTS/ElevenLabs).
- MISSING: end-to-end pipeline orchestrator, interruption/barge-in, text fallback.
- Dependencies: openwakeword✓ faster_whisper✓ piper✓ sounddevice✓ onnxruntime✓(CPU). Missing: pyannote✗ speechbrain✗ onnxruntime-gpu✗.
- Local models: Ollama reachable, 15 models incl. qwen3.5:4b.

### B — Actions / scheduler / connectors (E)
- 50 actions with TOOL dicts discovered.
- NONE carry permission, side-effect metadata, timeout, or auditable-result fields.
- NO scheduler exists (no cron, recurring, dedupe, missed-run, timezone).
- 2 connector interfaces: google_connector.py, current_time.py.
- NO universal approval boundary.

### C — Frontend command center (E partially)
- Screens present: voice assistant, conversation history, command palette, command center.
- Missing: unified search, workflows/approvals, security events, settings, diagnostics.
- Telemetry endpoints /api/telemetry and /ws/telemetry exist on backend but NOT wired into frontend dashboard.js.
- No voice state machine, no mic indicator, no keyboard nav, no WS reconnect.

### D — Ops / release (F partially)
- ./kd entrypoint: setup/start/doctor/check/deps all functional.
- health-check.sh, deploy.sh, make_process_telemetry.py all present and runnable.
- Full pytest: 178 passed, 2 failed (optional deps: trimesh, sentence_transformers), 1 skipped.
- pyproject.toml configures black/flake8/mypy but not yet executed.
- 22 unpinned deps in requirements.txt; 8 duplicate constraints in pyproject.toml.
- NO systemd user service unit.

### E — Security / privacy (F partially)
- Speaker enrollment: exists, re-enroll, delete, no raw audio retention, enrolled/unknown/uncertain.
- Missing: embeddings encrypted at rest, voice authorization boundary, cloud consent by data category, keyring integration, action permission enforcement.
- Dashboard: loopback default ✓, LAN opt-in ✓, origin checks on all WS endpoints ✓.
- Keys never logged ✓; keys not in keyring ✗.

## Remaining gaps (A-F)

| Area | Gap | Severity |
|------|-----|----------|
| B | Pipeline orchestrator (wake→VAD→STT→speaker→LLM→TTS) | High |
| B | Interruption / barge-in | High |
| B | Text fallback | Medium |
| E | Scheduler (recurring, dedupe, missed-run, timezone) | High |
| E | Approval boundary (action+args, confirmation) | High |
| E | Connector credential management | Medium |
| E | Unified search, workflows, approvals UI | High |
| E | Security events, settings, diagnostics UI | Medium |
| F | Telemetry wired into frontend | High |
| F | Encrypted speaker embeddings at rest | High |
| F | Voice authorization boundary | High |
| F | Cloud consent by data category | Medium |
| F | Keyring integration | Medium |
| F | Action permission enforcement | High |
| F | systemd user service | Medium |
| F | Dependency pinning (22 unpinned) | Medium |
| F | Lint/typecheck execution | Low |

## Artifacts

- artifacts/voice_pipeline_audit.json
- artifacts/action_scheduler_audit.json
- artifacts/frontend_command_center_audit.json
- artifacts/ops_release_audit.json
- artifacts/security_audit.json
- artifacts/operation_gate.json (existing, updated)
- artifacts/provenance.json (existing, updated)

## Next step

Implementation work can now begin on the highest-severity gaps, starting with the pipeline orchestrator and approval boundary. Each gap maps to specific files enumerated in the audit artifacts.
