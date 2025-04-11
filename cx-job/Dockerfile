# syntax = docker/dockerfile:1.6

FROM python:3.8-slim

ENV PYTHONDONTWRITEBYTECODE 1

WORKDIR /app

# Update package list and install git
RUN apt-get update -y \
    && apt-get install --no-install-recommends -y python3-pip \
    && pip install requests==2.31.0 && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
    && rm -rf /var/lib/apt/lists/* 

COPY checkmarx_job.py .

CMD ["python3", "checkmarx_job.py"]
