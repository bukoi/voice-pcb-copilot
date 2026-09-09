import os
import uuid
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from livekit import api

load_dotenv()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/token")
def get_token():
    room_name = f"pcb-copilot-{uuid.uuid4().hex[:8]}"
    identity = "user"

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
# is the HTTP server (uvicorn on port 8000).  The LiveKit agent process
# is separate and communicates via the LiveKit room data channel.
# ---------------------------------------------------------------------------
from file_receiver import router as upload_router  # noqa: E402
app.include_router(upload_router)