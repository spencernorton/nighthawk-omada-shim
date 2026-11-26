FROM python:3.13-slim

ARG VERSION=0.9.1
ARG REVISION=unknown

LABEL org.opencontainers.image.title="Nighthawk Omada Shim" \
      org.opencontainers.image.description="Connect stock-firmware Netgear Nighthawk access points to a TP-Link Omada controller over ECSP" \
      org.opencontainers.image.source="https://github.com/spencernorton/nighthawk-omada-shim" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Agent state (adoption credentials provisioned by the controller) must
# survive container recreation: mount a volume at /state.
ENV OMADA_STATE_FILE=/state/agent-state.json
VOLUME ["/state"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD ["python", "-m", "open_omada_device_agent", "--healthcheck"]

ENTRYPOINT ["python", "-m", "open_omada_device_agent"]
