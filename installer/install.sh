#!/usr/bin/env bash
# JARVIS — Linux installer.
# Installs the app bundle into ~/.local/share/mark-lvi, registers a desktop
# entry with icon, and sets executable permissions. No root required.
set -euo pipefail

PREFIX="${MARK_LVI_PREFIX:-$HOME/.local/share/mark-lvi}"
APPS_DIR="$HOME/.local/share/applications"
SRC="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/mark-lvi"

if [[ ! -f "$SRC/mark-lvi" ]]; then
    echo "✗ Cannot find the app bundle next to this installer ($SRC/mark-lvi)." >&2
    echo "  Run this script from the unpacked release archive." >&2
    exit 1
fi

echo "▶ Installing JARVIS to $PREFIX"
mkdir -p "$PREFIX"
cp -a "$SRC/." "$PREFIX/"
chmod +x "$PREFIX/mark-lvi"

echo "▶ Registering desktop entry"
mkdir -p "$APPS_DIR"cat > "$APPS_DIR/mark-lvi.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=JARVIS
Comment=JARVIS-style personal AI assistant
Exec=$PREFIX/mark-lvi
Icon=$PREFIX/config/jarvis.png
Terminal=false
Categories=Utility;AudioVideo;Office;
Keywords=jarvis;assistant;voice;ai;
StartupNotify=true
EOF
chmod 644 "$APPS_DIR/mark-lvi.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" || true

# Knowledge services (data analyst, knowledge RAG) ship as source + pinned
# requirements; each gets its own venv here. Non-fatal if it fails — the core
# assistant works without them and the action reports what's missing.
for svc in data-analyst knowledge-rag; do
    req="$PREFIX/apps/$svc/requirements.txt"
    venv="$PREFIX/apps/$svc/.venv"
    if [[ -f "$req" && ! -x "$venv/bin/python" ]]; then
        pybin="$(command -v python3.12 || command -v python3 || true)"
        if [[ -n "$pybin" ]]; then
            echo "▶ Setting up $svc service venv (one time, may take a minute)…"
            "$pybin" -m venv "$venv" && \
                "$venv/bin/pip" install -q -r "$req" || \
                echo "⚠  $svc setup failed — the assistant will say so if you use it."
        fi
    fi
done

cat <<EOF

✓ JARVIS installed.

  Launch:      search "JARVIS" in your app menu, or run:
                 $PREFIX/mark-lvi
  Uninstall:   $PREFIX/uninstall.sh

First launch:
  • The setup screen will ask for a free Gemini API key
    (or configure a fully local engine from ⚙ → ENGINE & PROVIDERS).
  • Your settings live in $PREFIX/config/api_keys.json — never shared.

Permissions & optional system tools:
  • Microphone/speakers: required for voice. On PipeWire/PulseAudio no extra
    setup is needed; if the mic list is empty, check your desktop's audio
    permissions for terminal apps.
  • Voice-controlled OS actions use native tools; install the ones you want:
      sudo apt install pulseaudio-utils brightnessctl xdg-utils at
  • Display: full computer control needs an X11 session. On Wayland, typing /
    clicking / screen capture are unavailable (the app says so at startup).
  • Browser automation needs Playwright browsers, one time, from a terminal:
      python3 -m pip install playwright && python3 -m playwright install chromium
EOF
