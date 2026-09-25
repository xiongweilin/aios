FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl docker.io git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir .

COPY config ./config
COPY contracts ./contracts
COPY migrations ./migrations
COPY scripts ./scripts
COPY deploy ./deploy

RUN mkdir -p /var/lib/aios

CMD ["world-runtime"]
