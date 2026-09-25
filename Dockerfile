FROM python:3.12-slim

ARG AIOS_APP_ROOT
RUN test -n "$AIOS_APP_ROOT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AIOS_APP_ROOT=$AIOS_APP_ROOT

WORKDIR $AIOS_APP_ROOT

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl docker.io git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir .

COPY contracts ./contracts
COPY migrations ./migrations
COPY scripts ./scripts

CMD ["world-runtime"]
