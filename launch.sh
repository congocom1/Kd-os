#!/usr/bin/env bash
# Restore desktop-session settings missing from IDE/agent terminals.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

# --- Conda/xcb library path for Qt platform plugins ---
# PyQt6's xcb plugin needs libxcb-cursor, libxcb-icccm, etc. from conda.
if [[ -d "${CONDA_PREFIX:-/home/hermes/miniconda3}/lib" ]]; then
    export LD_LIBRARY_PATH="${CONDA_PREFIX:-/home/hermes/miniconda3}/lib:${LD_LIBRARY_PATH:-}"
fi
# Ask PyQt's runtime distribution where its plugins actually live. The
# bindings and PyQt6-Qt6 runtime can be installed in different site-packages
# directories, so importing PyQt6 alone does not reliably reveal the path.
_plugin_root="$(python3 - <<'PY' 2>/dev/null || true
from pathlib import Path
try:
    import importlib.metadata
    dist = importlib.metadata.distribution("PyQt6-Qt6")
    for entry in dist.files or ():
        path = Path(str(entry))
        if "plugins" in path.parts:
            index = len(path.parts) - 1 - path.parts[::-1].index("plugins")
            print(dist.locate_file(path.parents[index]) / "plugins")
            break
except Exception:
    pass
PY
)"
if [[ -z "$_plugin_root" ]]; then
    _pyqt6_dir="$(python3 -c 'import PyQt6; print(PyQt6.__path__[-1])' 2>/dev/null || true)"
    _plugin_root="${_pyqt6_dir:+${_pyqt6_dir}/Qt6/plugins}"
fi
[[ -z "$_plugin_root" ]] || export QT_PLUGIN_PATH="${_plugin_root}:${QT_PLUGIN_PATH:-}"

# --- QtWebEngine paths (process binary, resources, locales) ---
export QTWEBENGINEPROCESS_PATH="${QTWEBENGINEPROCESS_PATH:-${CONDA_PREFIX:-/home/hermes/miniconda3}/lib/qt6/QtWebEngineProcess}"
export QTWEBENGINE_RESOURCES_PATH="${QTWEBENGINE_RESOURCES_PATH:-${CONDA_PREFIX:-/home/hermes/miniconda3}/share/qt6/resources}"
_locales="${CONDA_PREFIX:-/home/hermes/miniconda3}/share/qt6/translations/qtwebengine_locales"
[[ -d "$_locales" ]] && export QTWEBENGINE_LOCALES_PATH="$_locales"

# --- CUDA/cuDNN library path for GPU acceleration ---
# Required for ONNX Runtime CUDAExecutionProvider with cuDNN support (Piper TTS).
# Derived from the repo's own .venv when cuDNN is installed there; otherwise
# honor a caller-provided CUDNN_LIB_DIR.
cudnn_dir="${CUDNN_LIB_DIR:-}"
if [[ -z "$cudnn_dir" ]]; then
    for candidate in "$PWD"/.venv/lib/python*/site-packages/nvidia/cudnn/lib; do
        if [[ -d "$candidate" ]]; then
            cudnn_dir="$candidate"
            break
        fi
    done
fi
if [[ -n "$cudnn_dir" ]]; then
    export LD_LIBRARY_PATH="$cudnn_dir:${LD_LIBRARY_PATH:-}"
fi

# --- Start God's Eye View server if not already running ---
if [[ "${KD_START_GEV_DEV:-0}" == "1" ]] && ! curl --noproxy '*' -sS --max-time 2 -o /dev/null -w '%{http_code}' http://127.0.0.1:4174/ 2>/dev/null | grep -q '200'; then
    echo "[JARVIS] Starting God's Eye View server..."
    # Change to the God's Eye View app directory and start the Vite server
    cd "$(dirname -- "${BASH_SOURCE[0]}")/apps/gods-eye-view"
    # Use .jarvis-runtime node if available, otherwise system node
    if [[ -x ".jarvis-runtime/node_modules/node/bin/node" ]]; then
        export PATH="$PWD/.jarvis-runtime/node_modules/node/bin:$PATH"
    fi
    # Start vite in background, redirect output
    node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4174 --strictPort > /tmp/gev-server.log 2>&1 &
    GEV_PID=$!
    echo "GEV_PID=$GEV_PID" >> /tmp/jarvis-environment.txt
    # Wait for server to be ready
    for i in $(seq 1 30); do
        if curl --noproxy '*' -sS --max-time 2 -o /dev/null -w '%{http_code}' http://127.0.0.1:4174/ 2>/dev/null | grep -q '200'; then
            echo "[JARVIS] God's Eye View server ready on port 4174"
            break
        fi
        sleep 0.5
    done
    # Return to Mark-LVI-main
    cd -
fi

# --- Rest of original launch.sh ---

# Prefer conda python3 (has all deps); fall back to .venv then system python3.
if [[ -x "${CONDA_PREFIX:-/home/hermes/miniconda3}/bin/python3" ]]; then
    python_bin="${JARVIS_PYTHON:-${CONDA_PREFIX:-/home/hermes/miniconda3}/bin/python3}"
elif [[ -x "$PWD/.venv/bin/python" ]]; then
    python_bin="${JARVIS_PYTHON:-$PWD/.venv/bin/python}"
else
    python_bin="${JARVIS_PYTHON:-python3}"
fi
if [[ "${1:-}" == "--virtual-display" ]]; then
    shift
    command -v xvfb-run >/dev/null || {
        echo "Virtual display requires xvfb-run and xauth." >&2
        exit 1
    }
    echo "[JARVIS] Starting an isolated virtual display (not your visible desktop)."
    exec xvfb-run -a -s '-screen 0 1920x1080x24 -nolisten tcp' \
        env QT_QPA_PLATFORM=xcb "$python_bin" -u main.py "$@"
fi

runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [[ -d "$runtime" && -O "$runtime" ]]; then
    export XDG_RUNTIME_DIR="$runtime"
fi

if [[ -z "${DISPLAY:-}" ]]; then
    command -v xdpyinfo >/dev/null || {
        echo "Set DISPLAY from your desktop session, or use --virtual-display." >&2
        exit 1
    }
    # Probe local displays with the current user's existing Xwayland credentials.
    shopt -s nullglob
    auth_files=("$runtime"/.mutter-Xwaylandauth.*)
    [[ ! -f "$HOME/.Xauthority" ]] || auth_files+=("$HOME/.Xauthority")
    [[ -z "${XAUTHORITY:-}" ]] || auth_files=("$XAUTHORITY" "${auth_files[@]}")
    for display in :0 :1; do
        for auth in "${auth_files[@]}"; do
            [[ -f "$auth" && -O "$auth" ]] || continue
            if timeout 3 env DISPLAY="$display" XAUTHORITY="$auth" xdpyinfo >/dev/null 2>&1; then
                export DISPLAY="$display" XAUTHORITY="$auth"
                break 2
            fi
        done
    done
fi

if [[ -z "${DISPLAY:-}" ]]; then
    echo "No accessible local X display. Run from a desktop terminal or use --virtual-display." >&2
    exit 1
fi

echo "[JARVIS] Using desktop display $DISPLAY"
export QT_QPA_PLATFORM=xcb

# python-xlib does not match Mutter's empty display-number auth entries.
# Make a private, display-specific copy; never modify the session's authority.
auth_copy=""
child=""
cleanup() {
    if [[ -n "$child" ]]; then
        kill -TERM "$child" 2>/dev/null || true
        wait "$child" 2>/dev/null || true
    fi
    [[ -z "$auth_copy" ]] || rm -f -- "$auth_copy"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
if [[ -n "${XAUTHORITY:-}" && -r "$XAUTHORITY" ]]; then
    auth_copy=$(mktemp "${XDG_RUNTIME_DIR:-/tmp}/jarvis-xauth.XXXXXXXX")
    "$python_bin" - "$auth_copy" <<'PY'
import os
import struct
import sys
from Xlib.xauth import Xauthority

number = os.environ["DISPLAY"].rsplit(":", 1)[1].split(".", 1)[0].encode()
with open(sys.argv[1], "wb") as target:
    for family, address, display, name, cookie in Xauthority().entries:
        target.write(struct.pack("!H", family))
        for value in (address, display or number, name, cookie):
            target.write(struct.pack("!H", len(value)))
            target.write(value)
PY
    export XAUTHORITY="$auth_copy"
fi
"$python_bin" -u main.py "$@" &
child=$!
wait "$child"
child=""