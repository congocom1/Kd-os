#!/usr/bin/env bash
# Restore desktop-session settings missing from IDE/agent terminals.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

# Prefer conda python3 (has all deps); fall back to .venv then system python3.
if [[ -x "${CONDA_PREFIX:-/home/hermes/miniconda3}/bin/python3" ]]; then
    python_bin="${JARVIS_PYTHON:-${CONDA_PREFIX:-/home/hermes/miniconda3}/bin/python3}"
elif [[ -x "$PWD/.venv/bin/python" ]]; then
    python_bin="${JARVIS_PYTHON:-$PWD/.venv/bin/python}"
else
    python_bin="${JARVIS_PYTHON:-python3}"
fi
# --- Conda/xcb library path for Qt platform plugins ---
# PyQt6's xcb plugin needs libxcb-cursor, libxcb-icccm, etc. from conda.
if [[ -d "${CONDA_PREFIX:-/home/hermes/miniconda3}/lib" ]]; then
    export LD_LIBRARY_PATH="${CONDA_PREFIX:-/home/hermes/miniconda3}/lib:${LD_LIBRARY_PATH:-}"
fi
# Ask PyQt's runtime distribution where its plugins actually live. The
# bindings and PyQt6-Qt6 runtime can be installed in different site-packages
# directories, so importing PyQt6 alone does not reliably reveal the path.
_plugin_root="$("$python_bin" - <<'PY' 2>/dev/null || true
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
    _pyqt6_dir="$("$python_bin" -c 'import PyQt6; print(PyQt6.__path__[-1])' 2>/dev/null || true)"
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

# Track children we start. Never stop a globe server owned by another launcher.
auth_copy=""
child=""
gev_pid=""
cleanup() {
    local pid
    for pid in "$child" "$gev_pid"; do
        if [[ -n "$pid" ]]; then
            kill -TERM "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
    done
    [[ -z "$auth_copy" ]] || rm -f -- "$auth_copy"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

start_gev() {
    [[ "${KD_START_GEV_DEV:-0}" == "1" ]] || return 0
    if curl --noproxy '*' --fail --silent --max-time 2 -o /dev/null http://127.0.0.1:4174/; then
        return 0
    fi
    local logfile
    if ! logfile=$(mktemp "${TMPDIR:-/tmp}/kd-gev.XXXXXXXX"); then
        echo '[JARVIS] Could not create the optional globe log.' >&2
        return 0
    fi
    # No readiness polling on the desktop startup path. Only this run owns
    # the new server, and it must not retain the ./kd launch lock (fd 9).
    bash apps/gods-eye-view/launch-jarvis.sh >"$logfile" 2>&1 9>&- &
    gev_pid=$!
    echo "[JARVIS] Starting God's Eye View on port 4174 (log: $logfile)"
}

run_app() {
    start_gev
    local status=0
    "$@" &
    child=$!
    wait "$child" || status=$?
    child=""
    return "$status"
}

if [[ "${1:-}" == "--virtual-display" ]]; then
    shift
    command -v xvfb-run >/dev/null || {
        echo "Virtual display requires xvfb-run and xauth." >&2
        exit 1
    }
    echo "[JARVIS] Starting an isolated virtual display (not your visible desktop)."
    run_app xvfb-run -a -s '-screen 0 1920x1080x24 -nolisten tcp' \
        env QT_QPA_PLATFORM=xcb "$python_bin" -u main.py "$@"
    exit
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
run_app "$python_bin" -u main.py "$@"
