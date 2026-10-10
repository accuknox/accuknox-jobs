FROM alpine:3.23 AS downloader
RUN apk add --no-cache ca-certificates curl
ARG KUBESCAPE_VERSION=4.0.15
ARG TARGETARCH
RUN set -eux; \
    ARCH="${TARGETARCH:-}"; \
    if [ -z "$ARCH" ]; then \
      case "$(uname -m)" in \
        x86_64)  ARCH=amd64 ;; \
        aarch64) ARCH=arm64 ;; \
        *) echo "unsupported arch: $(uname -m)"; exit 1 ;; \
      esac; \
    fi; \
    curl -fsSL \
      "https://github.com/kubescape/kubescape/releases/download/v${KUBESCAPE_VERSION}/kubescape_${KUBESCAPE_VERSION}_linux_${ARCH}" \
      -o /usr/local/bin/kubescape; \
    chmod +x /usr/local/bin/kubescape

FROM alpine:3.23 AS runner
RUN apk add --no-cache ca-certificates python3 py3-ijson
RUN python3 -c 'import ijson, sqlite3'
COPY --from=downloader /usr/local/bin/kubescape /usr/local/bin/kubescape
RUN mkdir -p /opt/kubescape/artifacts && \
    kubescape download artifacts --output /opt/kubescape/artifacts && \
    kubescape download framework clusterscan --output /opt/kubescape/artifacts/clusterscan.json
RUN adduser --disabled-password --no-create-home kubescape
RUN mkdir -p /data && chown kubescape:kubescape /data
COPY scripts/scan-resources.py /usr/local/bin/scan-resources.py
COPY scripts/merge-frameworks.py /usr/local/bin/merge-frameworks.py
USER kubescape
#ENTRYPOINT ["/usr/local/bin/kubescape"]
