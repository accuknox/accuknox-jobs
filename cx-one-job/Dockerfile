# syntax = docker/dockerfile:1.6

FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE 1
 
WORKDIR /app

# Update package list and install git
RUN apk add --no-cache python3 py3-pip \
    && pip install requests==2.31.0

COPY checkmarx_job.py .

CMD ["python3", "checkmarx_job.py"]
