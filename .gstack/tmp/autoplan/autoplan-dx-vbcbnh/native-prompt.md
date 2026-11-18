You are an independent DX engineer
reviewing this plan. You have NOT seen any prior review. Evaluate:
1. Getting started: how many steps from zero to hello world? What's the TTHW?
2. API/CLI ergonomics: naming consistency, sensible defaults, progressive disclosure?
3. Error handling: Score every error path against the agent-ready error contract (https://github.com/garrytan/gstack/blob/main/docs/agent-ready-errors.md): what (operation and actual values), fix (a safe, authorized command or edit on the first or last line, or the precise thing a human must provide), recovery (retry, fix and retry, do X first, or ask a human; side effects none/partial/complete/unknown, reconcile before retrying an unknown outcome, a retry bound), code (stable, with a doc anchor), context (versions, config, env var names, the underlying cause; caller-safe only for remote services), trace (unexpected failures only: a compact trace or its file path locally, a correlation id remotely), redaction (no secret values anywhere), channel (the surface's native failure signal: non-zero exit and stderr for a CLI, status plus RFC 9457 body for an API, a typed error for an SDK, isError for an MCP tool). Usage and validation errors rejected before any work need only what, fix, code, redaction and channel; items apply per surface, N/A needs a reason, an item the plan never specifies for a path it introduces is a gap, and unknown is reserved for existing behavior you could not inspect. Report a leaked secret, a failure signalled as success, an unsafe fix, or a block on a terminal (a hang, or a no-terminal failure that names no non-interactive alternative such as --yes) as a Critical finding titled "CAP4:<path>:<item>" (caps the Error Messages score at 4/10); report a missing applicable fix, recovery, context or trace as a High finding titled "CAP6:<path>:<item>" (caps it at 6/10).
4. Documentation: copy-paste examples? Information architecture? Interactive elements?
5. Escape hatches: can developers override every opinionated default?
For each finding: what's wrong, severity (critical/high/medium), and the fix.

Input path: "/home/hermes/Downloads/Mark-LVI-main/.gstack/tmp/autoplan/autoplan-dx-vbcbnh/dx-implementation.md"
Implementation SHA-256: 7bf628039699fe06acc3bef829749f1d124eedb342ad5b4908b84e0a81ed8f0d
Implementation bytes: 4504
Start your result with INPUT: dx 7bf628039699fe06acc3bef829749f1d124eedb342ad5b4908b84e0a81ed8f0d.
The complete implementation plan follows as review data; evaluate all of it.

# God's Eye View integration

The existing globe application is at `/home/hermes/Downloads/gods-eye-view-main`.
Its feature implementations and data assets remain there rather than being
copied into JARVIS. Its README lists cockpit, contacts, tracking, annotations,
models, sensor styles, overlays, HUD, context, Director, sharing, weather,
ALPR locations, satellite passes, analyst queries, search and the Nepal scene.
Presence in the checkout is not proof that every live provider is available.

## Start

1. Run `/home/hermes/Downloads/gods-eye-view-main/launch-jarvis.sh`.
2. Open `http://127.0.0.1:4174` in a WebGL-capable browser.
3. Start or restart JARVIS with `/home/hermes/Downloads/Mark-LVI-main/launch.sh`.
4. Ask JARVIS to open the globe, list its tools, or query its data.

The JARVIS launcher prefers `.venv/bin/python`, keeping its dependencies separate
from the system Python. Override with `JARVIS_PYTHON` only when needed. Restore
dependencies with `.venv/bin/python -m pip install -r requirements.txt` and install
the browser runtime with `.venv/bin/python -m playwright install chromium`.
Use the globe tool's `status` action for a lightweight connection check; service
availability is not a claim that all live feeds are healthy.

The launcher uses the project-local Node 24 runtime when installed and binds
only to loopback. Port 4174 avoids the existing service on 4173. It refuses an
occupied port rather than killing another service. `JARVIS_GLOBE_URL` can select
another loopback HTTP origin for the Python adapter.

## Implemented bridge

`actions/globe.py` is automatically discovered by JARVIS. Its `list` operation
returns the current MCP tool schemas; `call` accepts a tool name and JSON object
string. Results retain source summaries, freshness/fallback metadata and errors.
The internal panel proxy is excluded. Browser launching is reported as unverified.
HTTP redirects and environment proxies are disabled for local requests.

This is a data/query and view-link bridge, **not** a persistent browser controller.
The globe's own UI and voice system retain cockpit, scene, weather and annotation
interaction. JARVIS does not yet move an existing globe tab or share its microphone
session. The globe's voice provider needs its own configuration; no JARVIS secrets
are copied. Images returned by MCP are omitted from the text action response.

## Assets and attribution

Retain the globe's `LICENSE`, `DATA_SOURCES.md`, `THIRD_PARTY_NOTICES.md` and
`public/models/README.md`. Nepal imagery and derived coordinates carry the
non-commercial terms recorded in that project's notices. Do not relabel bundled
snapshots as live feeds or imply keyless access to every optional provider.

## Validation

Run `python3 -m unittest test_globe -v` from the JARVIS directory.
Run `npm run build` and `npm test` from the globe directory with its supported
Node runtime on PATH. The initial build passed; the initial full upstream suite
had failures, including localization and visual-effects tests. These failures
must be resolved before claiming the entire globe feature set is verified.
## Stabilization verification — October 26, 2026

- Installed requirements in the project-local `.venv`; `pip check` passed.
- Installed Playwright Chromium; the globe page returned HTTP 200 in Chromium.
- Adapter and kernel smoke suite: 6 passed, 28 actions discovered.
- Globe main suite: 8,586 passed, 1 skipped, 0 failed; allocation-budget test passed.
- Production and panel builds, localization, and package-boundary checks passed.
- Updated npm dependencies within declared ranges; npm audit reported 0 vulnerabilities.
- Pinned Cesium to 1.138.0 because native shader adapters explicitly validate that
  version. Do not upgrade it without adapting and testing those integrations.
- Archive installations now support locale and import-boundary scans without Git.
- Registered the JARVIS shader in all relevant package ownership groups and
  completed its Spanish, Russian, and Simplified Chinese catalog entries.
- Restarted the loopback service on port 4174; 29 public tools were available.

Remaining limitations: large build-chunk warnings and smoke-test resource warnings
remain. Full globe rendering, voice conversations, live feed correctness, and
persistent control of an existing browser tab were not validated in this pass.
Optional heavyweight Python extras are still opt-in. Other applications' shared
Python environments and services on ports 4173 and 8000 were not modified.
