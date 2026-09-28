FROM python:3.12-slim

RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optional extra root CAs (certs/*.pem, gitignored): appended to certifi's bundle so requests can
# verify music.youtube.com behind a TLS-intercepting proxy. Empty folder = plain certifi bundle.
COPY certs/ ./certs/
RUN { cat "$(python -m certifi)"; cat certs/*.pem 2>/dev/null || true; } > /app/ca-bundle.pem
ENV REQUESTS_CA_BUNDLE=/app/ca-bundle.pem

COPY app ./app

USER appuser

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" || exit 1

EXPOSE 8000

CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "-b", "0.0.0.0:8000", "app.main:app"]
