# Shared image for the agent worker and the dashboard.
FROM python:3.11-slim

WORKDIR /app

# ffmpeg: audio decode for the TTS/STT pipeline; procps: pgrep for the agent healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg curl procps \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the Silero VAD model so the worker starts fast and offline.
RUN python -m livekit.agents download-files || true

COPY . .

# Overridden per service in docker-compose.yml.
CMD ["python", "agent.py", "start"]
