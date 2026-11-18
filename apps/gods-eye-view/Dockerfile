# ── God's Eye View Production Dockerfile ──────────────────────────────────
# GEV requires Node >=24.14 per package.json engines.
FROM node:24-bookworm-slim

WORKDIR /app

# curl is used by the HEALTHCHECK; git may be needed for some npm deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy everything (including package.json and source) for build.
COPY . .

# Install dependencies and build the production bundle.
RUN npm ci && npm run build

EXPOSE 4174

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:4174/ || exit 1

# Use preview mode for a static, production-ready server.
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "4174"]
