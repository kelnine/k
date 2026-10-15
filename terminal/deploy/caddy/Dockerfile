# syntax=docker/dockerfile:1.7
# The edge proxy with the dashboard baked in: the single-page app is built with
# Node, then served by Caddy from /srv/dashboard. Build context: terminal/
#
#   docker build -f deploy/caddy/Dockerfile -t kterminal-caddy terminal
#
# (docker compose builds it as the `caddy` service.)

ARG NODE_VERSION=22
ARG CADDY_VERSION=2

# ── build: type-check and bundle the dashboard (npm ci from the lock file) ──────
FROM node:${NODE_VERSION}-alpine AS dashboard
WORKDIR /src
COPY dashboard/package.json dashboard/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY dashboard/ ./
RUN npm run build

# ── runtime: Caddy, its configuration and the static files — nothing else ────
FROM caddy:${CADDY_VERSION}-alpine
COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=dashboard /src/dist /srv/dashboard
# Not validated here: provisioning would write a local CA key into an image layer.
# CI validates the configuration in a throw-away container instead.
