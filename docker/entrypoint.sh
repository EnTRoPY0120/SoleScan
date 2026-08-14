#!/bin/sh
set -eu

# Bind mounts retain host ownership and replace the image's pre-owned folders.
# Preserve the host owner, grant the shared group access, then run the app as
# the unprivileged Playwright user (which belongs to `users`).
chgrp -R users /app/data /app/logs
chmod -R g+rwX /app/data /app/logs

cd /app/backend
exec setpriv --reuid=pwuser --regid=pwuser --init-groups \
  sh -c 'alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000'
