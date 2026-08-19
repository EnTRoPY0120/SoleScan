#!/bin/sh
set -eu

# Bind mounts retain host ownership and replace the image's pre-owned folders.
chgrp -R users /app/data /app/logs
chmod -R g+rwX /app/data /app/logs

exec setpriv --reuid=pwuser --regid=pwuser --init-groups /app/docker/run-app.sh
