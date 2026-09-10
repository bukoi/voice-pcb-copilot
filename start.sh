#!/usr/bin/env bash
set -e

# Ensure Python can find modules in both root and backend folders
export PYTHONPATH="${PYTHONPATH}:$(pwd)/backend:$(pwd)"

# Start the LiveKit voice agent background process
python backend/agent.py start &

# Start the FastAPI HTTP & auth server
exec uvicorn backend.livekit_token:app --host 0.0.0.0 --port ${PORT:-8000}

