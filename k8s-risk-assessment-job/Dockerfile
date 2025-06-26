FROM alpine:3.22.0 AS downloader
RUN apk add --no-cache ca-certificates curl
ENV KUBESCAPE_VERSION=v3.0.8
ARG ARCH=""
RUN curl \
    -L "https://github.com/kubescape/kubescape/releases/download/${KUBESCAPE_VERSION}/kubescape${ARCH}-ubuntu-latest" \
    -o /usr/local/bin/kubescape
RUN chmod +x /usr/local/bin/kubescape

FROM alpine:3.22.0 AS runner
RUN apk add --no-cache ca-certificates
COPY --from=downloader /usr/local/bin/kubescape /usr/local/bin/kubescape
RUN mkdir -p /opt/kubescape/artifacts && \
    kubescape download artifacts --output /opt/kubescape/artifacts && \
    kubescape download framework clusterscan --output /opt/kubescape/artifacts/clusterscan.json
RUN adduser --disabled-password --no-create-home kubescape
RUN mkdir -p /data && chown kubescape:kubescape /data
USER kubescape
ENTRYPOINT ["/usr/local/bin/kubescape"]
