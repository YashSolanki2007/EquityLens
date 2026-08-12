FROM python:3.12-slim

WORKDIR /srv

COPY services/api/pyproject.toml services/api/pyproject.toml
RUN pip install --no-cache-dir -e services/api

COPY services/api services/api
COPY data data
COPY scripts scripts

WORKDIR /srv/services/api
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
