FROM python:3.12-slim

# Node.js — the Claude Agent SDK drives the Claude Code CLI, which runs on Node.
# Install the CLI globally so it's on PATH regardless of the SDK's bundling.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get purge -y curl && apt-get autoremove -y \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Flask endpoint for Alexa skill (proxied via nginx on the host).
EXPOSE 8080

CMD ["python", "main.py"]
