# syntax=docker/dockerfile:1
# Chiron control dashboard (the front door) + the tool CLIs it runs.
# Build context is the repo root (see docker-compose.yml).
#
# The backend + UI SOURCE are NOT copied into this image — they are bind-mounted
# read-only at runtime so the validator/scanners always see the live code.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# git: the Import tab can clone a data repo straight into the shared folder.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Tool sources + the dashboard itself. The root .dockerignore keeps the host
# venvs, node_modules, and the is4r-* source trees out of the build context.
COPY chiron-validator/      /app/chiron-validator/
COPY chiron-benchmark/      /app/chiron-benchmark/
COPY chiron-scanners/       /app/chiron-scanners/
COPY chiron-data-validator/ /app/chiron-data-validator/
COPY rdcrn-catalog-checker/ /app/rdcrn-catalog-checker/

# Recreate each tool's virtualenv at the SAME relative path the dashboard's
# config.py already expects (<tool>/.venv; the data-validator uses venv/). Using
# EDITABLE installs keeps the code in place, so each tool's sibling data dirs
# (chiron-validator/specs, results/, reports/) resolve via __file__ exactly as
# they do on the host — and the console entry points land in .venv/bin.
RUN set -eux; \
    for t in chiron-validator chiron-benchmark chiron-scanners; do \
        python -m venv "/app/$t/.venv"; \
        "/app/$t/.venv/bin/pip" install -e "/app/$t"; \
    done; \
    python -m venv /app/chiron-data-validator/venv; \
    /app/chiron-data-validator/venv/bin/pip install -r /app/chiron-data-validator/requirements.txt

# The RDCRN checker drives a REAL browser against the live deployment (the login
# page it exercises is JavaScript-built, and the SAML handoff runs through
# auto-submitting forms — neither survives a plain HTTP client). Chromium plus its
# system libraries is therefore a genuine runtime dependency, not a convenience.
# Its own venv at <tool>/.venv keeps the layout config.py already expects.
RUN set -eux; \
    python -m venv /app/rdcrn-catalog-checker/.venv; \
    /app/rdcrn-catalog-checker/.venv/bin/pip install \
        -r /app/rdcrn-catalog-checker/requirements.txt; \
    /app/rdcrn-catalog-checker/.venv/bin/playwright install --with-deps chromium

# Dashboard code last, so editing the dashboard (e.g. static/) doesn't bust the
# tool-install layer above. Then its runtime deps (flask, gunicorn) + the Docker
# SDK it uses to control the other containers through the mounted socket.
COPY chiron-dashboard/      /app/chiron-dashboard/
RUN pip install -r /app/chiron-dashboard/requirements.txt "docker>=7,<8"

# Ensure the runtime data/log dir exists (the named volume initializes from it).
RUN mkdir -p /app/chiron-dashboard/data/logs

WORKDIR /app/chiron-dashboard
EXPOSE 8787

# One worker so the in-memory process/job state is a single source of truth;
# threads serve the concurrent pollers. --chdir puts the `dashboard` package on
# the import path.
CMD ["gunicorn", "-w", "1", "--threads", "8", "-b", "0.0.0.0:8787", \
     "--timeout", "300", "--chdir", "/app/chiron-dashboard", "dashboard:create_app()"]
