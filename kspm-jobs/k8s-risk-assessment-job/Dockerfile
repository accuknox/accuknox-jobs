FROM alpine:3.23 AS downloader
RUN apk add --no-cache ca-certificates curl bash
ENV KUBESCAPE_VERSION=4.0.15
RUN curl -fsSL https://raw.githubusercontent.com/kubescape/kubescape/master/install.sh | /bin/bash -s -- -v v${KUBESCAPE_VERSION}
RUN KS="$(command -v kubescape || find / -name kubescape -type f -perm -u+x -not -path '/proc/*' 2>/dev/null | head -n1)" \
    && [ -n "$KS" ] \
    && { [ "$KS" = /usr/local/bin/kubescape ] || cp "$KS" /usr/local/bin/kubescape; } \
    && /usr/local/bin/kubescape version
RUN chmod +x /usr/local/bin/kubescape

FROM alpine:3.23 AS runner
RUN apk add --no-cache ca-certificates python3 py3-ijson bash kubectl time
RUN python3 -c 'import ijson, sqlite3'
COPY --from=downloader /usr/local/bin/kubescape /usr/local/bin/kubescape
RUN mkdir -p /opt/kubescape/artifacts && \
    kubescape download artifacts --output /opt/kubescape/artifacts
RUN adduser --disabled-password --no-create-home kubescape
RUN mkdir -p /data && chown kubescape:kubescape /data
COPY scripts/scan-control-namespaces.py /usr/local/bin/scan-control-namespaces.py
COPY scripts/scan-namespace-dumps.py scripts/scan-per-namespace.sh /usr/local/bin/
USER kubescape
#ENTRYPOINT ["/usr/local/bin/kubescape"]
