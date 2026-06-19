FROM python:3.11-slim

# Non-root user
RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app

# Install dependencies into system Python (no venv cross-stage copy)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY alembic.ini .
COPY alembic/ ./alembic/
COPY app/ ./app/

# Shared volume mount point
RUN mkdir -p /app/uploaded_csvs && chown app:app /app/uploaded_csvs

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
