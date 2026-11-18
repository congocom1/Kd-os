# KD OS

KD OS (JARVIS) is a Python/PyQt desktop assistant with a paired web dashboard. The repository also includes the optional God's Eye View globe and separate Kronos and knowledge workspaces.

## Desktop quick start

Use Python 3.11 or newer. On Linux, install your distribution's Qt/OpenGL and PortAudio runtime libraries first. The Bash launcher needs a local X display, or `xvfb-run` and `xauth` for an isolated `--virtual-display` session.

```sh
./kd doctor           # Read-only inventory; works before setup
./kd setup            # Install runtime dependencies in .venv
./kd start            # Run from a desktop terminal
```

For development, use `./kd setup --dev` and `./kd check`. Pytest options are forwarded, for example `./kd check -k telemetry`. The standard tests do not need model downloads, a camera, or a microphone. Tests for optional Torch and wake-word runtimes skip when those packages are missing. Qt tests still need the OS libraries even when run offscreen.

KD uses the headless OpenCV wheel because Qt handles display. Use a fresh virtual environment when upgrading from an install with `opencv-python`: the GUI and headless wheels both provide `cv2` and should not be installed together.

## Optional JavaScript components

Use Node 24.14+ (on the 24 line) or Node 26. Reinstall from the lockfiles rather than relying on the dependency files in the checkout.

```sh
# God's Eye View (root workspace)
PUPPETEER_SKIP_DOWNLOAD=true npm ci
npm run build:gev
npm run test:gev
apps/gods-eye-view/launch-jarvis.sh    # http://127.0.0.1:4174

# Paired dashboard assets (separate lockfile)
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build       # replaces dashboard/static; stop KD first
```

For an isolated dashboard build, append `-- --outDir /absolute/path/to/test-output`. Set `KD_START_GEV_DEV=1` before `./kd start` to start the optional loopback globe without blocking desktop startup. The launcher stops only the globe instance it started.

## Local operation

- The dashboard binds to loopback by default. Remote access requires explicit opt-in and pairing; do not publish a configured instance to the open internet.
- Set secrets in the environment or `config/api_keys.json`; use `config/api_keys.example.json` as a reference. Keep private backups outside the checkout. If a key was committed before, remove it from use and rotate it; deleting a file does not remove Git history.
- Connected dashboard tabs share one on-demand telemetry probe per sampling window. `last_updated` is the time of that sample, not the time a cached response was sent. No clients means no periodic sampling.

See [development notes](docs/DEVELOPMENT.md) and [globe integration](GLOBE_INTEGRATION.md) for more detail.
