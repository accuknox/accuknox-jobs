FROM alpine:3.23 AS downloader
RUN apk add --no-cache ca-certificates curl
ENV KUBESCAPE_VERSION=4.0.11
ARG ARCH=""
RUN curl \
    -L "https://github.com/kubescape/kubescape/releases/download/v${KUBESCAPE_VERSION}/kubescape_${KUBESCAPE_VERSION}_linux_${ARCH}" \
    -o /usr/local/bin/kubescape
RUN chmod +x /usr/local/bin/kubescape

FROM alpine:3.23 AS runner
RUN apk add --no-cache ca-certificates
COPY --from=downloader /usr/local/bin/kubescape /usr/local/bin/kubescape
RUN mkdir -p /opt/kubescape/artifacts && \
    kubescape download artifacts --output /opt/kubescape/artifacts && \
    kubescape download framework clusterscan --output /opt/kubescape/artifacts/clusterscan.json
RUN adduser --disabled-password --no-create-home kubescape
RUN mkdir -p /data && chown kubescape:kubescape /data
USER kubescape
#ENTRYPOINT ["/usr/local/bin/kubescape"]
