FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AURAFI_API_HOST=0.0.0.0

WORKDIR /app

RUN groupadd --system aurafi && useradd --system --gid aurafi --home-dir /app aurafi \
    && mkdir -p /data && chown aurafi:aurafi /data

# Only the managed-PostgreSQL path needs a driver; the SQLite/in-memory path
# stays zero-dependency (see database/postgres/repository.py's lazy import).
RUN pip install --no-cache-dir "psycopg[binary]==3.2.13"

COPY --chown=aurafi:aurafi contracts ./contracts
COPY --chown=aurafi:aurafi database ./database
COPY --chown=aurafi:aurafi services ./services

USER aurafi
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import json,os,urllib.request; p=os.environ.get('AURAFI_API_PORT') or os.environ.get('PORT') or '8000'; r=urllib.request.urlopen('http://127.0.0.1:'+p+'/health', timeout=3); assert r.status == 200 and json.load(r)['status'] == 'ok'"

CMD ["python", "-m", "services.api.cli"]
