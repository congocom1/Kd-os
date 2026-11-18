# ── Mark-LVI JARVIS Production Dockerfile ─────────────────────────────────
# Builds a containerized, headless-ready JARVIS with virtual display support.
#
# Build:
#   docker build -t mark-lvi/jarvis:latest .
#
# Run as part of the full stack:
#   docker compose up -d
#
# The HUD dashboard is exposed on port 7860. GEV/Kronos are reached via
# the docker-compose service names (gods-eye-view, kronos) by default.
# ──────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DISPLAY=:99
ENV QT_QPA_PLATFORM=xcb

# Install system dependencies for PyQt6, audio, browser automation, and a
# virtual display so the HUD can run headless.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    wget \
    ca-certificates \
    libgl1 \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libfontconfig1 \
    libice6 \
    libx11-6 \
    libegl1 \
    libxkbcommon0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-shm0 \
    libxcb-xfixes0 \
    libxcb-xinerama0 \
    libxcb-xkb1 \
    libxi6 \
    libxrandr2 \
    libxtst6 \
    libfreetype6 \
    libharfbuzz0b \
    libgdk-pixbuf2.0-0 \
    libdbus-1-3 \
    libpulse0 \
    pulseaudio-utils \
    xvfb \
    xauth \
    xdg-utils \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Use tini for proper signal handling and zombie reaping.
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency manifests first for layer caching.
COPY requirements.txt pyproject.toml install.py ./
COPY apps/kronos/requirements.txt ./apps/kronos/requirements.txt

# Install Python dependencies.
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r apps/kronos/requirements.txt

# Install Playwright browsers for web automation.
RUN python -m playwright install chromium firefox || true

# Copy the whole monorepo. .dockerignore excludes node_modules, build outputs,
# and runtime data so the image stays focused on the runtime.
COPY . .

# Ensure the package metadata is available for editable-like imports.
RUN pip install --no-cache-dir -e .

# Expose dashboard / HUD ports.
EXPOSE 7860 8000 8001

# Health check against the HUD dashboard.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/', timeout=5)" || exit 1

# Start Xvfb, then JARVIS. tini handles signals cleanly.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "-c", "Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp & sleep 2 && python main.py"]
