FROM python:3.13-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && rm -rf /var/lib/apt/lists/*

# Install dependencies first — these layers are cached until deps change
COPY services/gateway/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefix=/install -r requirements.txt

COPY core/ /build/core/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install hatchling && \
    pip install --prefix=/install /build/core/


FROM python:3.13-slim

LABEL org.opencontainers.image.source="https://github.com/BitModerator/bitmod"
LABEL org.opencontainers.image.description="BitMod API Gateway"
LABEL org.opencontainers.image.licenses="Proprietary"

RUN groupadd --gid 1000 bitmod && \
    useradd --uid 1000 --gid bitmod --shell /bin/sh --create-home bitmod

COPY --from=builder /install /usr/local

WORKDIR /app
COPY services/gateway/app ./app
COPY bitmod.yaml ./bitmod.yaml

RUN mkdir -p /app/data && chown -R bitmod:bitmod /app
USER bitmod

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
