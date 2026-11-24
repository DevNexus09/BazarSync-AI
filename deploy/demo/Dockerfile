# BazarSync AI public demo backend image (API and Celery worker). Works on x86_64 and ARM.
# Build context is the repo root (copied to the server); only backend/ and the constraints file enter the image.
FROM python:3.14.4-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/home/app/app \
    PATH=/home/app/.local/bin:$PATH \
    HF_HOME=/home/app/.cache/huggingface

RUN apt-get update \
    && apt-get install --no-install-recommends -y libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 app
USER app
WORKDIR /home/app/app

COPY --chown=app backend/requirements.txt ./requirements.txt
COPY --chown=app deploy/demo/constraints.txt ./constraints.txt
# CPU-only torch: no GPU here, and it is several GB smaller. Constraints pin the tested dev versions.
RUN python -m pip install --user --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt -c constraints.txt

# Bake the RAG embedding model into the image so restarts never re-download 2 GB.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3', device='cpu')"

COPY --chown=app backend/ ./

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
