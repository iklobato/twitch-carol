# Shared image for api and workers (different entrypoints per compose service).
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg build-essential cmake postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependency layer first: code edits must not retrigger the llama.cpp build.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt

COPY alembic.ini ./
COPY core/ core/
COPY apps/__init__.py apps/__init__.py
COPY apps/api/ apps/api/
# The API serves the /howto page (App Platform static sites can't do
# extensionless URLs); apps/web is not in this image, so ship just that file.
COPY apps/web/public/howto.html apps/api/howto.html
COPY workers/ workers/
COPY migrations/ migrations/
COPY scripts/ scripts/
RUN pip install --no-cache-dir --no-deps .

EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
