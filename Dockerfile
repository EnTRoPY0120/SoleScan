# syntax=docker/dockerfile:1.7
FROM node:24-bookworm-slim AS frontend-build
WORKDIR /build/frontend
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM frontend-build AS frontend-test
RUN pnpm test && pnpm check

FROM mcr.microsoft.com/playwright/python:v1.62.0-noble AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY backend/requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt
COPY --chown=pwuser:pwuser backend/ /app/backend/
COPY --from=frontend-build --chown=pwuser:pwuser /build/frontend/build/ /app/frontend/build/
COPY --chown=pwuser:pwuser docker/entrypoint.sh /app/docker/entrypoint.sh
RUN chmod +x /app/docker/entrypoint.sh && mkdir -p /app/data /app/logs && chown -R pwuser:pwuser /app/data /app/logs
# The entrypoint starts as root only long enough to make bind-mounted runtime
# directories writable by the shared `users` group, then drops to pwuser.
USER root
EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]

FROM runtime AS test
USER root
COPY backend/requirements-dev.txt /tmp/requirements-dev.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements-dev.txt
COPY --from=frontend-test /build/frontend/package.json /tmp/frontend-tests-passed
USER pwuser
ENTRYPOINT []
CMD ["sh", "-c", "cd /app/backend && pytest"]
