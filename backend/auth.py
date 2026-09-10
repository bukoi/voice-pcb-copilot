import os
import time
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

AUTH_USERNAME = os.getenv("AUTH_USERNAME", "Sudarshan")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "842684")
AUTH_SECRET = os.getenv("AUTH_SECRET_KEY", "pcb-copilot-secret-auth-key-2026")
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRE_SECONDS = 7 * 24 * 60 * 60  # 7 days

security = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str
    password: str


def authenticate_user(req: LoginRequest) -> bool:
    return req.username == AUTH_USERNAME and req.password == AUTH_PASSWORD


def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + TOKEN_EXPIRE_SECONDS,
    }
    return jwt.encode(payload, AUTH_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> str:
    try:
        payload = jwt.decode(token, AUTH_SECRET, algorithms=[JWT_ALGORITHM])
        username = payload.get("sub")
        if not username or username != AUTH_USERNAME:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token.",
            )
        return username
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid token.",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in with valid credentials.",
        )
    return verify_token(credentials.credentials)
