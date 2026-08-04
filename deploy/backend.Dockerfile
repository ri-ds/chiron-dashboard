# syntax=docker/dockerfile:1
# Chiron backend — Django + DRF (test_project). Dev/demo image.
# Build context is ./is4r-chiron-develop (see docker-compose.yml).
#
# Two databases are in play:
#   * Django metadata  -> SQLite (test_project/db.sqlite3, baked in as a snapshot)
#   * Chiron warehouse -> Postgres (the `db` service; connection string via env)
# This image seeds NO data. `migrate` only creates/updates the SQLite *schema*.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1) Python deps first for better layer caching. Everything in base.txt ships as
#    a manylinux wheel (django, drf, psycopg2-binary, SQLAlchemy, pandas, ...),
#    so no compiler/toolchain is needed on the slim image.
COPY requirements/ /app/requirements/
RUN pip install -r requirements/base.txt

# 2) The chiron package + the Django project. settings.py does sys.path.append("..")
#    so with the working dir at /app/test_project, /app is on sys.path and
#    `import chiron` resolves to /app/chiron — exactly like the host-local layout.
#    (The heavy .venv lives at the repo root and is intentionally not copied.)
COPY chiron/ /app/chiron/
COPY test_project/ /app/test_project/

WORKDIR /app/test_project
EXPOSE 8000

# migrate = SQLite metadata schema only (idempotent on the baked snapshot, and
# loads NO data). Then start the dev server bound to all interfaces.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec python manage.py runserver 0.0.0.0:8000 --noreload"]
