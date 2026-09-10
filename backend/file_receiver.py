"""
FastAPI endpoint that accepts KiCad file uploads from the frontend.

The frontend POSTs one or both KiCad files together with the LiveKit
room name.  This endpoint saves them to backend/tmp/ and returns the
saved paths so the agent can parse them via load_board_file.

Mount this alongside the existing token endpoint, or run it standalone
on the same port.  The existing livekit_token.py already uses FastAPI,
so we just add these routes to the same app instance — see agent.py for
how they're wired together.

Endpoints
---------
POST /upload-board
    Form fields:
        room_name  : str              — LiveKit room name for this session
        sch_file   : UploadFile | None  — .kicad_sch file (optional)
        pcb_file   : UploadFile | None  — .kicad_pcb file (optional)

    Response JSON:
        {
          "sch_path": "/abs/path/to/tmp/<room>_board.kicad_sch" | null,
          "pcb_path": "/abs/path/to/tmp/<room>_board.kicad_pcb" | null
        }

DELETE /upload-board/{room_name}
    Cleans up tmp files for a session (call on disconnect).
"""

import re
from pathlib import Path
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

router = APIRouter()

_TMP_DIR = Path(__file__).parent / "tmp"


def _safe_room_name(room_name: str) -> str:
    """Strip any characters that shouldn't appear in a filename."""
    return re.sub(r"[^\w\-]", "_", room_name)[:64]


def _ensure_tmp():
    _TMP_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/upload-board")
async def upload_board(
    room_name: str = Form(...),
    sch_file: UploadFile | None = File(default=None),
    pcb_file: UploadFile | None = File(default=None),
):
    """Accept .kicad_sch and/or .kicad_pcb uploads for a LiveKit session."""
    if not sch_file and not pcb_file:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one of sch_file or pcb_file.",
        )

    _ensure_tmp()
    safe = _safe_room_name(room_name)
    result = {"sch_path": None, "pcb_path": None}

    if sch_file:
        # Validate extension
        if not (sch_file.filename or "").endswith(".kicad_sch"):
            raise HTTPException(
                status_code=400,
                detail=f"sch_file must be a .kicad_sch file, got: {sch_file.filename}",
            )
        dest = _TMP_DIR / f"{safe}_board.kicad_sch"
        dest.write_bytes(await sch_file.read())
        result["sch_path"] = str(dest.resolve())

    if pcb_file:
        if not (pcb_file.filename or "").endswith(".kicad_pcb"):
            raise HTTPException(
                status_code=400,
                detail=f"pcb_file must be a .kicad_pcb file, got: {pcb_file.filename}",
            )
        dest = _TMP_DIR / f"{safe}_board.kicad_pcb"
        dest.write_bytes(await pcb_file.read())
        result["pcb_path"] = str(dest.resolve())

    return JSONResponse(content=result)


@router.delete("/upload-board/{room_name}")
async def cleanup_board(room_name: str):
    """Remove tmp files for a session (call when the room disconnects)."""
    safe = _safe_room_name(room_name)
    removed = []
    for ext in (".kicad_sch", ".kicad_pcb"):
        path = _TMP_DIR / f"{safe}_board{ext}"
        if path.exists():
            path.unlink()
            removed.append(path.name)
    return {"removed": removed}
