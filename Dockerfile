FROM alpine:latest

RUN apk --update add jq curl
COPY entrypoint.sh .

ENTRYPOINT ["/bin/sh", "entrypoint.sh"]
