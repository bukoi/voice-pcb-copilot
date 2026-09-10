import os
import sys
import uuid
from pathlib import Path

# Add backend directory to sys.path so local imports work from any working directory
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from livekit import api

from auth import LoginRequest, authenticate_user, create_token, get_current_user

load_dotenv()

app = FastAPI(title="Voice PCB Copilot Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/login")
def login(req: LoginRequest):
    if not authenticate_user(req):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid ID or password.",
        )
    token = create_token(req.username)
    return {
        "success": True,
        "token": token,
        "username": req.username,
    }


@app.get("/auth/verify")
def verify_auth(username: str = Depends(get_current_user)):
    return {"authenticated": True, "username": username}


@app.get("/token")
def get_token(username: str = Depends(get_current_user)):
    room_name = f"pcb-copilot-{uuid.uuid4().hex[:8]}"
    identity = username or "user"

    token = (
        api.AccessToken(
            os.getenv("LIVEKIT_API_KEY"),
            os.getenv("LIVEKIT_API_SECRET"),
        )
        .with_identity(identity)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
            )
        )
        .with_room_config(
            api.RoomConfiguration(
                agents=[
                    api.RoomAgentDispatch(
                        agent_name="pcb-copilot"
                    )
                ]
            )
        )
    )

    return {
        "token": token.to_jwt(),
        "room": room_name,
    }


# ---------------------------------------------------------------------------
# KiCad file upload endpoints — registered here because this FastAPI app
# is the HTTP server (uvicorn on port 8000). Protected by get_current_user.
# ---------------------------------------------------------------------------
from file_receiver import router as upload_router  # noqa: E402
app.include_router(upload_router, dependencies=[Depends(get_current_user)])