# syntax = docker/dockerfile:1.6

FROM python:3.8-slim

ENV PYTHONDONTWRITEBYTECODE 1
WORKDIR /app

RUN apt-get update -y && apt-get install --no-install-recommends -y curl python3-pip nodejs npm && pip3 install requests bs4 lxml

COPY sq-job.py .

CMD ["python3", "sq-job.py"]
