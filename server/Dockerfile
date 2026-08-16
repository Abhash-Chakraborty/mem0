FROM python:3.12-slim

WORKDIR /app

# pg_dump / pg_restore / psql back the /backups endpoints. Without them the API
# still runs, but backups report themselves unavailable - which is the one
# failure mode this instance cannot afford to discover during an incident.
RUN apt-get update \
  && apt-get install -y --no-install-recommends postgresql-client \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# mem0's v3 entity extraction (which feeds the /graph endpoint's entity store)
# needs the en_core_web_sm spaCy model. Bake it in so extraction works
# offline and deterministically instead of downloading it at runtime.
RUN pip install --no-cache-dir -r requirements.txt \
  && python -m spacy download en_core_web_sm

COPY . .

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

CMD ["sh", "-c", "python scripts/ensure_app_db.py && alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000"]
