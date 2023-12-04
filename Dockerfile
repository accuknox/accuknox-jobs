FROM docker.io/nginx

RUN apt update -y \
    && apt upgrade -y \
    && apt install -y curl jq

COPY entrypoint.sh .

ENTRYPOINT ["/bin/bash", "entrypoint.sh"]