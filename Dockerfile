FROM python:3.12-slim

ARG AIOS_APP_ROOT
ARG UV_VERSION=0.12.19
ARG K6_VERSION=2.3.0
ARG SYFT_VERSION=1.52.0
ARG GRYPE_VERSION=0.119.0
RUN test -n "$AIOS_APP_ROOT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AIOS_APP_ROOT=$AIOS_APP_ROOT

WORKDIR $AIOS_APP_ROOT

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl docker-cli git \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}" \
    && curl -fsSL "https://github.com/grafana/k6/releases/download/v${K6_VERSION}/k6-v${K6_VERSION}-linux-amd64.tar.gz" -o /tmp/k6.tar.gz \
    && tar -xzf /tmp/k6.tar.gz -C /tmp \
    && install "/tmp/k6-v${K6_VERSION}-linux-amd64/k6" /usr/local/bin/k6 \
    && curl -fsSL "https://github.com/anchore/syft/releases/download/v${SYFT_VERSION}/syft_${SYFT_VERSION}_linux_amd64.tar.gz" -o /tmp/syft.tar.gz \
    && tar -xzf /tmp/syft.tar.gz -C /tmp syft \
    && install /tmp/syft /usr/local/bin/syft \
    && curl -fsSL "https://github.com/anchore/grype/releases/download/v${GRYPE_VERSION}/grype_${GRYPE_VERSION}_linux_amd64.tar.gz" -o /tmp/grype.tar.gz \
    && tar -xzf /tmp/grype.tar.gz -C /tmp grype \
    && install /tmp/grype /usr/local/bin/grype \
    && rm -rf /tmp/k6.tar.gz /tmp/k6-v${K6_VERSION}-linux-amd64 /tmp/syft.tar.gz /tmp/grype.tar.gz /tmp/syft /tmp/grype

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir .

COPY contracts ./contracts
COPY migrations ./migrations
COPY scripts ./scripts

CMD ["world-runtime"]
