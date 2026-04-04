FROM python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "echo '=== ENV CHECK ===' && if [ -z \"$DATABASE_URL\" ]; then echo 'DATABASE_URL: EMPTY - using default'; else echo 'DATABASE_URL: SET'; fi && alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
