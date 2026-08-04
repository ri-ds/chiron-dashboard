# Local-only overrides (not part of the tracked repo). See settings.py's
# `from .settings_custom import *` at the bottom.
#
# Everything here applies to BOTH host-local dev and the docker-compose stack.
# Anything specific to the containerized stack is gated behind the CHIRON_IN_DOCKER
# environment variable, so a plain `manage.py runserver` on your machine behaves
# exactly as it did before.

import os

# The React UI dev server (vite) runs on a different origin/port than this Django
# server. Vite's proxy forwards requests here without preserving the original Host
# header, so Django's CSRF Origin check needs an explicit allowlist entry or every
# POST (e.g. login) gets a 403.
CSRF_TRUSTED_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

# --- docker-compose stack only (host-local runs skip this entire block) ------
if os.environ.get("CHIRON_IN_DOCKER"):
    # Requests arrive through the compose network and the UI's nginx with assorted
    # Host headers (api, localhost, ...). Dev/demo only — never enable "*" in prod.
    ALLOWED_HOSTS = ["*"]

    # Point the Chiron warehouse at the `db` service instead of localhost. Overridable
    # via the same env var so the connection string lives in one place (compose).
    CHIRON_SQL_ALCHEMY_CONNECTION_STRING = os.environ.get(
        "CHIRON_SQL_ALCHEMY_CONNECTION_STRING",
        "postgresql://postgres:postgres@db:5432/chiron",
    )

    # Extra trusted origins may be supplied comma-separated via the environment
    # (compose passes the UI/API origins here).
    _extra = os.environ.get("CSRF_TRUSTED_ORIGINS", "")
    CSRF_TRUSTED_ORIGINS = CSRF_TRUSTED_ORIGINS + [
        o.strip() for o in _extra.split(",") if o.strip()
    ]
