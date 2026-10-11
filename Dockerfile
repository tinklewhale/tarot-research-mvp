FROM node:20-bookworm-slim

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-pip bash tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g n8n

COPY requirements.txt /tmp/requirements.txt
RUN python3 -m venv /home/node/venv \
    && /home/node/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /home/node/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
    && mkdir -p /home/node/.n8n /workspace \
    && chown -R node:node /home/node /workspace

ENV PATH="/home/node/venv/bin:${PATH}"

USER node
WORKDIR /workspace
