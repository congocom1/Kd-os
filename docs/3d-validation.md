# 3D and UI follow-up — October 28, 2026

## Verified environment

- Python 3.14.9, torch 2.14.1+cu130; torch CUDA is available.
- trimesh 5.2.0, Open3D 0.20.0, fvcore 0.1.5.post20221221, iopath 0.1.10.
- No `nvcc` on PATH. Native PyTorch3D was absent at the start of this audit.
- The original native build failed because setup requested C++17 while this
  torch installation requires C++20. The later `at::symint::sizes` errors do
  not establish blanket incompatibility with all PyTorch 2.14+ installations.
- Local `pytorch3d-main/setup.py` now requests C++20. Build results and exit
  codes are captured in `/tmp/mark-lvi-validation/`; do not infer installation
  success from source files or from importing the compatibility module.
- The C++20 CPU wheel attempt reached 27 compiled objects but exceeded its
  600-second limit (exit 124). It did not produce an installed native backend.
  Logs are also copied to `logs/3d-validation` in the project. A longer build
  and compiled-operation smoke test remain necessary; CUDA additionally
  requires a matching development toolkit.

## Explicit backend contract

`core.geometry_backend.sample_mesh(..., backend='compat'|'native')` offers a
shared sampling entry point. `VisualDisplayManager.sample_model_surface` uses
it for workshop geometry. Native selection checks the compiled `_C` extension
and raises an actionable error rather than silently falling back.

The compatibility module is not PyTorch3D. It has property-based containers,
xyzw quaternions and column-vector SE(3) matrices. Tensor sampling and matrix
transforms support autograd; trimesh/Open3D paths explicitly detach and run on
CPU. It does not provide a differentiable rasterizer. The SE(3) logarithm
rejects rotations at pi, where its principal-axis extraction is ambiguous.
The desktop continues to render with its existing OpenGL renderer.

## Gestures

Tracking defaults OFF. Enabling initializes the camera and reports synchronous
failure through the checkbox. Worker callbacks use a Qt signal to dispatch on
the GUI thread; the active Reactor or Workshop widget receives the event.
Closing MainWindow stops tracking. The pairing overlay no longer accesses a
controller it does not own. Workshop now implements rotate/zoom/pan/reset.
Tests mock camera/tracker initialization rather than loading real MediaPipe.
Physical gesture recognition still requires a user camera acceptance test.
Webcam gestures in the web frontend are not implemented.

## Frontend preservation

`frontend/public` contains the server-compatible app/login pages and offline
assets. Clean Vite builds copy these into `dashboard/static`. The server mounts
`/static` and keeps the authenticated dashboard at `/`. The JARVIS-inspired
redesign is available as separate build output, not as the default dashboard:
its telemetry/command/WebSocket protocols still need server integration.
Face recognition in the visual landing page is not authentication and now
redirects to server pairing at `/login`.

## Validation

Run from `/home/hermes/Downloads/Mark-LVI-main`:

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -v
cd /home/hermes/Downloads/Mark-LVI-main/frontend && npm run build
```

The audit's regression run passed 107 tests with one display-dependent skip.
The HUD layout file is included, not excluded. CPU/CUDA sampling, normals,
batch transforms, zero-angle gradients, SE(3) coupling, OBJ I/O, gesture
lifecycle, backend selection, static routes and build preservation are covered.
This does not establish end-to-end camera or browser interaction correctness.