# God's Eye View shares one dependency layer between preview and local dev.
FROM node:24-bookworm-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends curl git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN chown node:node /app
USER node

# Puppeteer is used by browser QA, not by the build or runtime.
COPY --chown=node:node package.json package-lock.json ./
RUN PUPPETEER_SKIP_DOWNLOAD=true npm ci
COPY --chown=node:node . .

ENV HOST=0.0.0.0
ENV PORT=4174
EXPOSE 4174
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/" || exit 1

# Used by the main KD Compose stack. The preview also runs provider middleware.
FROM base AS production
RUN npm run build
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "4174", "--strictPort"]

# Used by standalone Compose with a bind-mounted source checkout. An explicit
# host UID may differ from the image user, but still needs to write Vite's cache.
FROM base AS development
RUN mkdir -p node_modules/.vite && chmod a+w node_modules node_modules/.vite
CMD ["node", "scripts/docker-start.mjs"]
