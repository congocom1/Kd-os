# KD — Phase 0 Audit: evidence-backed inventory (2026-10-28)

Evidence collected live from Hermes and this repository. Every claim has a
command behind it; where something is untested it says so.

## Hardware — Hermes

| Item | Evidence |
|---|---|
| GPU | NVIDIA GeForce **RTX 5050 Laptop, 8151 MiB VRAM**, 358 MiB in use, driver 595.99.02 (`nvidia-smi`) |
| CUDA toolkit | **nvcc MISSING** — driver present, no toolkit. cuDNN arrives via pip `nvidia-*` wheels (Piper/ONNX path in `launch.sh`) |
| RAM | 30 GiB total, 15 GiB available (`free -h`) |
| CPU | Intel Core 7 240H, 16 threads (`lscpu`) |
| OS | Ubuntu 26.04.1 LTS (`lsb_release`) |

## Inference backends

- **Ollama: active** (`systemctl is-active ollama` → active). 11 models installed:
  qwen3.5 (0.8b / 2b / 4b / 27b / 35b), qwen3-embedding:0.6b, embeddinggemma,
  gemma3:4b, deepseek-r1:8b, granite4:3b, qwen3-vl:4b (`ollama list`).
- ⚠️ **VRAM reality check (spec §10):** qwen3.5:27b/35b (17–22 GB) cannot fit in
  8 GB VRAM; they run CPU/CPU+GPU-offload. The resident-size-safe set on Hermes
  is ≤ ~5 GB quantized (2b/4b class + embeddings + qwen3-vl:4b for vision).
- Gemini Live cloud path: configured and working (the running app uses it).

## Toolchains

| Tool | Status |
|---|---|
| gcc/g++ | 15.2.0 ✓ |
| Rust | 1.99.1 ✓ |
| Node/npm | v24.22.1 / 11.19.1 ✓ |
| Docker + Compose | 29.9.2 / v5.6.1 ✓ (one unrelated container running: freellmapi) |
| **GNAT (Ada/SPARK)** | **MISSING** — needed for Phase 3 trusted control plane |
| **SBCL (Common Lisp)** | **MISSING** — needed for Phase 3 symbolic engine |
| Blender | /snap/bin/blender ✓ (used for the reactor export) |

## Repository — current state (this tree)

- **Tests: 71/71 pass** (`pytest tests -q`).
- 55 actions + 15 plugins discovered; skills: 15 (8 vendored + 7 awesome-llm).
- Services: God's Eye View (:4174) **up 200**, phone dashboard (:8000) **up 200**;
  kronos (:7861), awesome-llm (:7862), data-analyst (:7863), knowledge-rag (:7864)
  are **down-by-design** (start on demand via AppManager / action auto-start).
- **Audio control gap:** `pactl` missing — volume actions that shell out to
  pactl degrade (documented in install notes; pulseaudio-utils not installed).
- **Known defect (from `jarvis.log`):** shutdown race —
  `RuntimeError: wrapped C/C++ object of type MainWindow has been deleted`
  from `ui.py:7105 set_state` after window close. Non-fatal but noisy; belongs
  to Phase 1 stabilization.
- ⚠️ **Uncommitted parallel work in tree:** ui.py, core/reactor_widget.py,
  memory/memory_manager.py, providers/llm_router.py, MANIFEST.in modified plus
  new arc-reactor-bundle/ and assembled OBJ files — produced by a second,
  concurrently-running tool. Not yet committed; needs review before Phase 1.
- Release artifacts: installable bundle + tarballs (`release/`, v1.2.2 latest),
  PyInstaller build verified booting headless (47 actions, 0 errors).

## Map to spec §19 target structure

The repo is a single Python package (core/, actions/, plugins/, providers/,
dashboard/, memory/) plus apps/ (gods-eye-view Node, kronos PyTorch,
awesome-llm FastAPI, data-analyst, knowledge-rag) and awesome-llm-apps-main/
(skills). The spec's services/packages/infrastructure split is a **target**,
not current state — migration must be incremental per §20 Phase 2–3.

## Design-token conflict (flagged, needs owner decision)

Spec §6.2 mandates cyan/ice-blue tokens (#00D9FF family) and an original
identity. The currently shipping UI is the owner-requested **JARVIS Orange**
(#ff9500) movie-homage with an orb centerpiece. These conflict. Current
decision stands (orange, owner-chosen, live on screen) unless the owner
redirects to the §6.2 token set.
