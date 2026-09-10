#!/usr/bin/env bash
set -e

# Unbuffer python logs so all agent activity streams to Render logs in real time
export PYTHONUNBUFFERED=1
export PYTHONPATH="${PYTHONPATH}:$(pwd)/backend:$(pwd)"

# Start the LiveKit voice agent worker in background with direct stdout/stderr logging
python -u backend/agent.py start &

# Start the FastAPI HTTP server on Render's assigned PORT
exec uvicorn backend.livekit_token:app --host 0.0.0.0 --port "${PORT:-10000}"
