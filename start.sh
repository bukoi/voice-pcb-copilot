#!/usr/bin/env bash
set -e

# Ensure Python can find modules in both root and backend folders
export PYTHONPATH="${PYTHONPATH}:$(pwd)/backend:$(pwd)"

# Start the LiveKit voice agent after a 3-second delay so Uvicorn binds the port instantly
(sleep 3 && python backend/agent.py start) &

# Start the FastAPI HTTP server immediately on the assigned PORT
exec uvicorn backend.livekit_token:app --host 0.0.0.0 --port "${PORT:-10000}"
