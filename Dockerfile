FROM alpine:latest

RUN apk --update add jq curl
COPY entrypoint.sh .
COPY curl_command.sh .

# Grant execute permissions to the scripts
RUN chmod +x entrypoint.sh curl_command.sh

ENTRYPOINT ["/bin/sh", "entrypoint.sh"]
