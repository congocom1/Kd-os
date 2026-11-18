# JARVIS / KD — ZERO-REGRESSION DEVELOPMENT PROTOCOL

> Governing process protocol provided by the owner (Michel Buki) on 2026-10-28.
> Verbatim below. This file + `KD_MASTER_SPEC.md` together govern the program:
> the master spec says WHAT to build; this protocol says HOW to change things.
>
> Path note: the protocol references `/home/hermes/Ultron`; the actual working
> repository is `/home/hermes/Downloads/Mark-LVI-main` (branch `ml-engine`).
> `/home/hermes/Ultron` does not exist on Hermes (verified 2026-10-28).

## CRITICAL DIRECTIVE: DO NOT BREAK EXISTING CODE

Primary responsibility: preserve every working feature while introducing new
capabilities. Project: KD (Jarvis). Workstation: Hermes, Ubuntu 26.04,
NVIDIA RTX 5050 (8 GB), Ollama inference.

## 1. NON-DESTRUCTIVE DEVELOPMENT RULES

1. Never delete existing working functionality.
2. Never overwrite working modules without understanding their dependencies.
3. Never replace the current architecture merely because a newer technology is available.
4. Never rename existing directories, APIs, environment variables, database tables, or public interfaces without a verified migration plan.
5. Never remove existing models, integrations, skills, plugins, or configurations without explicit authorization.
6. Never change the current AI provider or model-routing behavior without compatibility testing.
7. Never modify production configurations directly without approval.
8. Never perform destructive database migrations.
9. Never force-push or rewrite Git history.
10. Never deploy untested changes.

All new functionality must be backward-compatible wherever technically feasible.
If a requested feature conflicts with an existing implementation, document the
conflict and propose the smallest safe change.

## 2. BASELINE AUDIT BEFORE CHANGES

Before modifying any code: inspect structure, services, dependencies, branch,
working tree, uncommitted changes, Docker configs, Ollama integrations, voice
pipeline, memory implementation, desktop control, HUD, API contracts,
security/auth boundaries. Run existing tests/lint/builds and record results.
Do not interpret an existing failure as a regression introduced by the upgrade.
Produce a baseline report of what works, what fails, what is unverified.

## 3. GIT SAFETY PROTOCOL

Preserve the working tree (including uncommitted/untracked files); create a
recoverable backup; record the commit SHA; use a dedicated feature branch;
avoid modifying main directly; small logically separated commits; review every
diff; never force-push; never merge without verification and approval. Do not
automatically stash, reset, clean, or discard existing changes.

## 4. ADD FEATURES THROUGH EXTENSIONS

Prefer new modules over replacing existing ones (suggested boundaries:
core/realtime_context, core/speaker_identity, core/event_engine,
core/proactive_intelligence, services/*, memory/speaker_profiles,
ui/hud, security/voice_verification, tests/regression). Suggested paths only —
inspect the repository first. Use adapters to existing implementations.

## 5. FEATURE FLAGS

Every major new subsystem gets independent activation and rollback, defaulting
to disabled until validated (KD_REALTIME_CONTEXT_ENABLED,
KD_SPEAKER_IDENTITY_ENABLED, KD_DYNAMIC_WINDOWS_ENABLED,
KD_PROACTIVE_INTELLIGENCE_ENABLED, KD_HOLOGRAPHIC_HUD_ENABLED,
KD_AUTONOMOUS_ACTIONS_ENABLED). One flag must never disable unrelated
functionality.

## 6. PRESERVE THE EXISTING AI BRAIN

Do not replace the current Ollama integration. Preserve installed models,
selection logic, provider configs, local endpoints, conversation behavior,
voice commands, memory data, tool integrations. New capabilities through
compatible interfaces. No automatic large-model downloads or exceeding GPU
resources.

## 7. DATABASE AND MEMORY SAFETY

Identify schema, create and verify a restorable backup, design additive
migrations, test against a copy of the data, preserve conversations/profiles,
verify compatibility with older records, document rollback. Never silently
delete, reset, or overwrite existing memory.

## 8. UI AND WINDOW MANAGEMENT SAFETY

Preserve the current interface; holographic HUD components incrementally;
no replacing navigation/routes/layouts/controls without approval; dynamic
windows as an optional subsystem; the desktop agent cannot interfere with
applications outside granted permissions.

## 9. CONTINUOUS REGRESSION TESTING

After every meaningful change: unit + integration tests, voice commands,
Ollama connectivity, model routing, memory persistence, API endpoints, Docker
health, HUD functionality, new errors, compare to baseline. On regression:
stop, identify the commit, revert/disable safely, restore, verify, report.
Never claim zero regressions without test evidence.

## 10. SAFE ROLLOUT STRATEGY

Stage 1 audit/backup → Stage 2 additive infrastructure (event bus, context
engine) → Stage 3 speaker recognition (adapter into the speech pipeline) →
Stage 4 real-time awareness (isolated services) → Stage 5 window management
(permission-controlled) → Stage 6 HUD enhancement (floating windows, live
dashboards, keep current UI) → Stage 7 autonomous workflows (planning,
approvals, verified execution) → Stage 8 integration testing →
Stage 9 controlled activation (one subsystem at a time) →
Stage 10 production readiness (regression, security, recovery, performance).

## 11. MANDATORY STOP CONDITIONS

Stop and request guidance if: user data may be lost; a migration cannot be
reversed; the working tree cannot be preserved; breaking interface changes;
secrets/permissions exposed; a critical feature fails regression; destructive
changes required; implementation exceeds hardware resources. Never conceal
these or bypass safety checks.

## 12. FINAL ACCEPTANCE CRITERIA

Acceptable only when: verified functionality stays operational; user data
preserved; Ollama integrations functional; existing voice commands work; new
speaker recognition works; real-time monitoring works; dynamic window control
works within permissions; HUD enhancements don't break navigation; autonomous
workflows respect approval boundaries; regression tests pass; rollback and
recovery verified; changes documented and reviewable.

## FINAL INSTRUCTION

**EXTEND. DO NOT REBUILD. PRESERVE. DO NOT REPLACE. TEST. DO NOT ASSUME.
REQUEST APPROVAL. DO NOT FORCE CHANGES.**

Treat the current KD codebase as the source of truth.
