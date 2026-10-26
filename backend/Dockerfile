FROM python:3.12-slim

WORKDIR /app

# Dependencies first: this layer only rebuilds when requirements.txt changes,
# which keeps an edit-and-rerun loop to a couple of seconds.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY windsight ./windsight
COPY tests ./tests

ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s \
  CMD python -c "import httpx,sys; sys.exit(0 if httpx.get('http://localhost:8000/api/health').status_code==200 else 1)"

CMD ["uvicorn", "windsight.api:app", "--host", "0.0.0.0", "--port", "8000"]
