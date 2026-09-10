// Centralized Configuration for Frontend

export const BACKEND_URL = (
  import.meta.env.VITE_BACKEND_URL || "https://voice-pcb-copilot.onrender.com"
).replace(/\/$/, "");

export const LIVEKIT_URL =
  import.meta.env.VITE_LIVEKIT_URL || "wss://pcb-design-jdags579.livekit.cloud";

export const LOGIN_ENDPOINT = `${BACKEND_URL}/login`;
export const TOKEN_ENDPOINT = `${BACKEND_URL}/token`;
export const UPLOAD_ENDPOINT = `${BACKEND_URL}/upload-board`;
export const AUTH_VERIFY_ENDPOINT = `${BACKEND_URL}/auth/verify`;

export default {
  BACKEND_URL,
  LIVEKIT_URL,
  LOGIN_ENDPOINT,
  TOKEN_ENDPOINT,
  UPLOAD_ENDPOINT,
  AUTH_VERIFY_ENDPOINT,
};
