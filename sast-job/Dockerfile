# syntax = docker/dockerfile:1.6

FROM python:3.9-slim

ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# Install Node.js and Python dependencies
RUN apt-get update && apt-get install --no-install-recommends -y \
    nodejs \
    npm \
    && pip install aiohttp==3.8.5 tqdm==4.65.0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY sq-job.py .

CMD ["python3", "sq-job.py"]
