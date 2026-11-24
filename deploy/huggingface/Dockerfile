# BazarSync AI public demo backend for a Hugging Face Docker Space (free CPU tier).
# Build context is the Space repo, which holds a copy of backend/ plus this file and start.sh.
FROM python:3.14.4-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/home/user/app \
    PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/.cache/huggingface

RUN apt-get update \
    && apt-get install --no-install-recommends -y redis-server libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Spaces run containers as uid 1000.
RUN useradd -m -u 1000 user
USER user
WORKDIR /home/user/app

COPY --chown=user requirements.txt ./requirements.txt
# CPU-only torch keeps the image GBs smaller; the Space has no GPU.
RUN python -m pip install --user --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY --chown=user . ./

EXPOSE 7860
CMD ["sh", "start.sh"]
