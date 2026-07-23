FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV AKDB_HOST=0.0.0.0
ENV AKDB_PORT=8787
ENV AKDB_DATA_ROOT=/data

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md* /app/
COPY docs /app/docs
COPY architectural_knowledge_db /app/architectural_knowledge_db

RUN pip install --no-cache-dir ".[postgres]"

EXPOSE 8787
VOLUME ["/data", "/sources"]

CMD ["uvicorn", "architectural_knowledge_db.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8787"]
