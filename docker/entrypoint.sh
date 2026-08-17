#!/bin/sh
set -eu

# Bind mounts retain host ownership and replace the image's pre-owned folders.
# Preserve the host owner, grant the shared group access, then run the app as
# the unprivileged Playwright user (which belongs to `users`).
chgrp -R users /app/data /app/logs
chmod -R g+rwX /app/data /app/logs

cd /app/backend
exec setpriv --reuid=pwuser --regid=pwuser --init-groups \
  sh -c 'if command -v Xvfb >/dev/null 2>&1; then Xvfb :99 -screen 0 1280x900x24 >/tmp/xvfb.log 2>&1 & export DISPLAY=:99; command -v x11vnc >/dev/null 2>&1 && x11vnc -display :99 -localhost -forever -rfbport 5900 >/tmp/x11vnc.log 2>&1 & command -v websockify >/dev/null 2>&1 && websockify --web=/usr/share/novnc 6080 localhost:5900 >/tmp/websockify.log 2>&1 & fi; alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000'
