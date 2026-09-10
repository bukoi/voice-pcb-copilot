import { useEffect, useMemo, useRef, useState } from "react";
import { Room, RoomEvent } from "livekit-client";
import { BOARD, COMPONENTS, TEST_POINTS, ALL_IDS } from "./board-data";
import { LOGIN_ENDPOINT, TOKEN_ENDPOINT, UPLOAD_ENDPOINT, LIVEKIT_URL } from "./config";
import "./App.css";

const MENTION_TIMEOUT_MS = 3500;

function App() {
  // Auth state
  const [authToken, setAuthToken] = useState(() => localStorage.getItem("pcb_auth_token") || "");
  const [authUser, setAuthUser] = useState(() => localStorage.getItem("pcb_auth_user") || "");
  const [loginId, setLoginId] = useState("");
  const [loginPass, setLoginPass] = useState("");
  const [loginError, setLoginError] = useState(null);
  const [isLoggingIn, setIsLoggingIn] = useState(false);

  // App state
  const [phase, setPhase] = useState("idle"); // idle | connecting | live
  const [error, setError] = useState(null);
  const [entries, setEntries] = useState([]); // finalized transcript lines
  const [liveText, setLiveText] = useState("");
  const [mentioned, setMentioned] = useState(new Set());
  const [roomName, setRoomName] = useState(null); // set when connected

  // Upload state
  const [schFile, setSchFile] = useState(null);
  const [pcbFile, setPcbFile] = useState(null);
  const [uploadStatus, setUploadStatus] = useState(null); // null | "uploading" | "done" | "error"
  const schInputRef = useRef(null);
  const pcbInputRef = useRef(null);

  const roomRef = useRef(null);
  const audioElsRef = useRef([]);
  const mentionTimerRef = useRef(null);
  const transcriptRef = useRef(null);
  const nextIdRef = useRef(0);

  const mentionPattern = useMemo(
    () => new RegExp(`\\b(${ALL_IDS.join("|")})\\b`, "gi"),
    []
  );

  const flagMentions = (text) => {
    const found = text.match(mentionPattern);
    if (!found || found.length === 0) return;
    const ids = new Set(found.map((m) => m.toUpperCase()));
    setMentioned(ids);
    clearTimeout(mentionTimerRef.current);
    mentionTimerRef.current = setTimeout(() => setMentioned(new Set()), MENTION_TIMEOUT_MS);
  };

  useEffect(() => {
    if (transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
    }
  }, [entries, liveText]);

  useEffect(() => () => clearTimeout(mentionTimerRef.current), []);

  const handleLogin = async (e) => {
    e.preventDefault();
    if (!loginId.trim() || !loginPass.trim()) {
      setLoginError("Please enter both ID and password.");
      return;
    }

    setLoginError(null);
    setIsLoggingIn(true);

    try {
      const res = await fetch(LOGIN_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: loginId.trim(), password: loginPass.trim() }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Invalid User ID or Password.");
      }

      const data = await res.json();
      localStorage.setItem("pcb_auth_token", data.token);
      localStorage.setItem("pcb_auth_user", data.username);
      setAuthToken(data.token);
      setAuthUser(data.username);
      setLoginPass("");
    } catch (err) {
      setLoginError(err.message || "Failed to authenticate with backend.");
    } finally {
      setIsLoggingIn(false);
    }
  };

  const handleLogout = async () => {
    await disconnect();
    localStorage.removeItem("pcb_auth_token");
    localStorage.removeItem("pcb_auth_user");
    setAuthToken("");
    setAuthUser("");
    setLoginError(null);
  };

  const cleanupAudio = () => {
    audioElsRef.current.forEach((el) => el.remove());
    audioElsRef.current = [];
  };

  const disconnect = async () => {
    await roomRef.current?.disconnect();
    setRoomName(null);
    setUploadStatus(null);
    setSchFile(null);
    setPcbFile(null);
  };

  const connect = async () => {
    setError(null);
    setPhase("connecting");
    try {
      const response = await fetch(TOKEN_ENDPOINT, {
        headers: {
          Authorization: `Bearer ${authToken}`,
        },
      });

      if (response.status === 401) {
        handleLogout();
        throw new Error("Session expired. Please log in again.");
      }

      if (!response.ok) {
        throw new Error(`Token server responded with ${response.status}`);
      }
      const data = await response.json();

      const room = new Room();
      roomRef.current = room;

      room.on(RoomEvent.Disconnected, () => {
        setPhase("idle");
        cleanupAudio();
        setRoomName(null);
      });

      room.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === "audio") {
          const audioElement = track.attach();
          audioElsRef.current.push(audioElement);
          document.body.appendChild(audioElement);
        }
      });

      room.registerTextStreamHandler("lk.live-partial", async (reader) => {
        let text = "";
        for await (const chunk of reader) text = chunk;
        setLiveText(text);
        flagMentions(text);
      });

      room.registerTextStreamHandler("lk.final-transcript", async (reader) => {
        let text = "";
        for await (const chunk of reader) text = chunk;
        setEntries((prev) => [
          ...prev,
          { id: nextIdRef.current++, text, ts: new Date(), isUser: true },
        ]);
        setLiveText("");
        flagMentions(text);
      });

      // Agent's spoken reply text — sent back from agent_speech_committed
      room.registerTextStreamHandler("lk.agent-response", async (reader) => {
        let text = "";
        for await (const chunk of reader) text = chunk;
        if (text) {
          setEntries((prev) => [
            ...prev,
            { id: nextIdRef.current++, text, ts: new Date(), isAgent: true },
          ]);
        }
      });

      await room.connect(LIVEKIT_URL, data.token);
      await room.localParticipant.setMicrophoneEnabled(true);
      setRoomName(room.name);
      setPhase("live");
    } catch (err) {
      console.error("Connection failed:", err);
      setError(
        err.message === "Failed to fetch"
          ? "Can't reach the backend server -- check if the backend service is running."
          : err.message || "Connection failed."
      );
      setPhase("idle");
      roomRef.current = null;
    }
  };

  const handleConnectClick = () => {
    if (phase === "live") disconnect();
    else if (phase === "idle") connect();
  };

  // -----------------------------------------------------------------------
  // Board file upload
  // -----------------------------------------------------------------------
  const handleUpload = async () => {
    if (!schFile && !pcbFile) return;
    if (!roomRef.current || phase !== "live") {
      setError("Connect first before uploading a board file.");
      return;
    }

    setUploadStatus("uploading");
    try {
      const form = new FormData();
      form.append("room_name", roomRef.current.name);
      if (schFile) form.append("sch_file", schFile);
      if (pcbFile) form.append("pcb_file", pcbFile);

      const res = await fetch(UPLOAD_ENDPOINT, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${authToken}`,
        },
        body: form,
      });

      if (res.status === 401) {
        handleLogout();
        throw new Error("Session expired. Please log in again.");
      }

      if (!res.ok) {
        const detail = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(detail.detail || res.statusText);
      }
      const { sch_path, pcb_path } = await res.json();

      // Notify the agent via the LiveKit data channel so it calls load_board_file
      const payload = JSON.stringify({ sch_path, pcb_path });
      await roomRef.current.localParticipant.publishData(
        new TextEncoder().encode(payload),
        { topic: "lk.board-upload", reliable: true }
      );

      setUploadStatus("done");
    } catch (err) {
      console.error("Upload failed:", err);
      setError(`Upload failed: ${err.message}`);
      setUploadStatus("error");
    }
  };

  // Render Login Modal if not authenticated
  if (!authToken) {
    return (
      <div className="login-wrapper">
        <div className="login-card">
          <div className="login-chip-icon">
            <span className="chip-pin pin-l" />
            <span className="chip-pin pin-r" />
            <div className="chip-core">⚡</div>
          </div>
          <h1 className="login-title">Voice PCB Copilot</h1>
          <p className="login-subtitle">Secured Hardware Debugging Terminal</p>

          <form className="login-form" onSubmit={handleLogin}>
            {loginError && (
              <div className="login-error-alert" role="alert">
                <span>{loginError}</span>
              </div>
            )}

            <div className="form-group">
              <label htmlFor="user-id">User ID</label>
              <input
                id="user-id"
                type="text"
                value={loginId}
                placeholder="Enter ID (e.g. Sudarshan)"
                autoComplete="username"
                autoFocus
                onChange={(e) => setLoginId(e.target.value)}
                disabled={isLoggingIn}
              />
            </div>

            <div className="form-group">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                value={loginPass}
                placeholder="••••••"
                autoComplete="current-password"
                onChange={(e) => setLoginPass(e.target.value)}
                disabled={isLoggingIn}
              />
            </div>

            <button
              type="submit"
              className="login-submit-btn"
              disabled={isLoggingIn}
            >
              {isLoggingIn ? "Authenticating\u2026" : "Unlock Terminal"}
            </button>
          </form>

          <div className="login-footer">
            <span className="auth-hint">Authorized Access Only</span>
          </div>
        </div>
      </div>
    );
  }

  const buttonLabel = { idle: "Connect", connecting: "Connecting\u2026", live: "Listening" }[phase];
  const statusLabel = {
    idle: "Not connected",
    connecting: "Opening voice channel\u2026",
    live: "Mic live — describe what you're testing",
  }[phase];

  const uploadLabel =
    uploadStatus === "uploading" ? "Uploading\u2026"
    : uploadStatus === "done"     ? "Board loaded \u2713"
    : "Upload board";

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <div className="header-title-row">
            <h1>Voice PCB Copilot</h1>
            <div className="user-badge">
              <span className="user-dot" />
              <span className="user-name">{authUser || "Sudarshan"}</span>
              <button
                type="button"
                className="logout-btn"
                onClick={handleLogout}
                title="Log out"
              >
                Log out
              </button>
            </div>
          </div>
          <p className="board-desc">
            {BOARD.name} — {BOARD.description}
          </p>
        </div>

        <div className="header-actions">
          {/* ---- Board upload panel ---- */}
          <div className="upload-panel">
            <p className="upload-label">Upload KiCad files</p>
            <div className="upload-row">
              {/* Hidden file inputs */}
              <input
                ref={schInputRef}
                type="file"
                accept=".kicad_sch"
                style={{ display: "none" }}
                onChange={(e) => { setSchFile(e.target.files[0] || null); setUploadStatus(null); }}
              />
              <input
                ref={pcbInputRef}
                type="file"
                accept=".kicad_pcb"
                style={{ display: "none" }}
                onChange={(e) => { setPcbFile(e.target.files[0] || null); setUploadStatus(null); }}
              />

              <button
                type="button"
                className={`file-pick-btn${schFile ? " has-file" : ""}`}
                onClick={() => schInputRef.current?.click()}
                title="Pick .kicad_sch schematic file"
              >
                {schFile ? schFile.name : ".kicad_sch"}
              </button>

              <button
                type="button"
                className={`file-pick-btn${pcbFile ? " has-file" : ""}`}
                onClick={() => pcbInputRef.current?.click()}
                title="Pick .kicad_pcb board file"
              >
                {pcbFile ? pcbFile.name : ".kicad_pcb"}
              </button>

              <button
                type="button"
                id="upload-board-btn"
                className={`upload-btn${uploadStatus === "done" ? " is-done" : ""}`}
                onClick={handleUpload}
                disabled={
                  (!schFile && !pcbFile) ||
                  uploadStatus === "uploading" ||
                  uploadStatus === "done"
                }
              >
                {uploadLabel}
              </button>
            </div>
          </div>

          <button
            type="button"
            id="connect-btn"
            className={`connect-btn${phase === "live" ? " is-live" : ""}`}
            onClick={handleConnectClick}
            disabled={phase === "connecting"}
          >
            <span className="dot" />
            {buttonLabel}
          </button>
        </div>
      </header>

      {error && (
        <div className="error-banner" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)} aria-label="Dismiss">
            &times;
          </button>
        </div>
      )}

      <div className="app-main">
        <aside className="board-ref">
          <p className="panel-title">Board reference</p>

          <div className="ref-group">
            {COMPONENTS.map((c) => (
              <div key={c.id} className={`ref-row${mentioned.has(c.id) ? " is-mentioned" : ""}`}>
                <span className="ref-id">{c.id}</span>
                <span className="ref-detail">
                  <span className="part">{c.part}</span>
                  <span className="role">{c.role}</span>
                </span>
              </div>
            ))}
          </div>

          <p className="panel-title">Test points</p>
          <div className="ref-group">
            {TEST_POINTS.map((t) => (
              <div key={t.id} className={`ref-row${mentioned.has(t.id) ? " is-mentioned" : ""}`}>
                <span className="ref-id">{t.id}</span>
                <span className="ref-detail">
                  <span className="part">{t.location}</span>
                </span>
                <span className="expected">{t.expected}</span>
              </div>
            ))}
          </div>
        </aside>

        <section className="console">
          <p className="panel-title">Debug session</p>
          <p className={`status-line${phase === "live" ? " live" : ""}`}>
            <span className="dot" />
            {statusLabel}
          </p>

          <div className="transcript" ref={transcriptRef}>
            {entries.length === 0 && !liveText && (
              <p className="empty-state">
                Press Connect, then talk through what you're probing — e.g.
                "what's the expected voltage at TP3?"
              </p>
            )}
            {entries.map((entry) => (
              <p
                className={`transcript-line${entry.isAgent ? " agent-line" : ""}${entry.isUser ? " user-line" : ""}`}
                key={entry.id}
              >
                <span className="ts">{entry.ts.toLocaleTimeString([], { hour12: false })}</span>
                {entry.isAgent && <span className="speaker-tag agent-tag">Agent</span>}
                {entry.isUser && <span className="speaker-tag user-tag">You</span>}
                {entry.text}
              </p>
            ))}
            {liveText && (
              <p className="transcript-line live-partial">{liveText}</p>
            )}
          </div>
        </section>
      </div>

      <footer className="edge-connector">
        <div className="pins" aria-hidden="true">
          {Array.from({ length: 14 }).map((_, i) => (
            <span key={i} />
          ))}
        </div>
        <p className="stack">{"LiveKit \u2192 Deepgram STT \u2192 Groq LLM \u2192 Rime TTS"}</p>
      </footer>
    </div>
  );
}

export default App;