import { useEffect, useMemo, useRef, useState } from "react";
import { Room, RoomEvent } from "livekit-client";
import { BOARD, COMPONENTS, TEST_POINTS, ALL_IDS } from "./board-data";
import "./App.css";

const TOKEN_ENDPOINT = "http://127.0.0.1:8000/token";
const LIVEKIT_URL = "wss://pcb-design-jdags579.livekit.cloud";
const MENTION_TIMEOUT_MS = 3500;

function App() {
  const [phase, setPhase] = useState("idle");
  const [error, setError] = useState(null);
  const [entries, setEntries] = useState([]);
  const [liveText, setLiveText] = useState("");
  const [mentioned, setMentioned] = useState(new Set());
  const [agentSpeaking, setAgentSpeaking] = useState(false);

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

  const cleanupAudio = () => {
    audioElsRef.current.forEach((el) => el.remove());
    audioElsRef.current = [];
  };

  const disconnect = async () => {
    await roomRef.current?.disconnect();
  };

  const connect = async () => {
    setError(null);
    setPhase("connecting");
    try {
      const response = await fetch(TOKEN_ENDPOINT);
      if (!response.ok) {
        throw new Error(`Token server responded with ${response.status}`);
      }
      const data = await response.json();

      const room = new Room();
      roomRef.current = room;

      room.on(RoomEvent.Disconnected, () => {
        setPhase("idle");
        setAgentSpeaking(false);
        cleanupAudio();
      });

      room.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === "audio") {
          const audioElement = track.attach();
          audioElsRef.current.push(audioElement);
          document.body.appendChild(audioElement);
        }
      });

      room.on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
        const localId = room.localParticipant.identity;
        const agentIsSpeaking = speakers.some((p) => p.identity !== localId);
        setAgentSpeaking(agentIsSpeaking);
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
          { id: nextIdRef.current++, text, ts: new Date() },
        ]);
        setLiveText("");
        flagMentions(text);
      });

      await room.connect(LIVEKIT_URL, data.token);
      await room.localParticipant.setMicrophoneEnabled(true);
      setPhase("live");
    } catch (err) {
      console.error("Connection failed:", err);
      setError(
        err.message === "Failed to fetch"
          ? "Can't reach the token server -- is the backend running on port 8000?"
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

  const buttonLabel = { idle: "Connect", connecting: "Connecting\u2026", live: "Listening" }[phase];
  const statusLabel = agentSpeaking
    ? "Agent speaking\u2026"
    : {
        idle: "Not connected",
        connecting: "Opening voice channel\u2026",
        live: "Mic live -- describe what you're testing",
      }[phase];

  return (
    <div className={`app-shell${agentSpeaking ? " agent-speaking" : ""}`}>
      <div className="aura-field" aria-hidden="true">
        <div className="aura-ring ring-1" />
        <div className="aura-ring ring-2" />
        <div className="aura-ring ring-3" />
      </div>

      <header className="app-header">
        <div className="brand">
          <div className={`brand-orb${phase === "live" ? " is-live" : ""}${agentSpeaking ? " is-speaking" : ""}`} />
          <div>
            <h1>Voice PCB Copilot</h1>
            <p className="board-desc">
              {BOARD.name} &mdash; {BOARD.description}
            </p>
          </div>
        </div>
        <button
          type="button"
          className={`connect-btn${phase === "live" ? " is-live" : ""}`}
          onClick={handleConnectClick}
          disabled={phase === "connecting"}
        >
          <span className="dot" />
          {buttonLabel}
        </button>
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
          <p className={`status-line${phase === "live" ? " live" : ""}${agentSpeaking ? " speaking" : ""}`}>
            <span className="dot" />
            {statusLabel}
          </p>

          <div className="transcript" ref={transcriptRef}>
            {entries.length === 0 && !liveText && (
              <p className="empty-state">
                Press Connect, then talk through what you're probing &mdash; e.g.
                "what's the expected voltage at TP3?"
              </p>
            )}
            {entries.map((entry) => (
              <div className="chat-row user" key={entry.id}>
                <span className="chat-avatar user-avatar">You</span>
                <div className="chat-bubble user-bubble">
                  <span className="ts">{entry.ts.toLocaleTimeString([], { hour12: false })}</span>
                  {entry.text}
                </div>
              </div>
            ))}
            {liveText && (
              <div className="chat-row user is-live">
                <span className="chat-avatar user-avatar">You</span>
                <div className="chat-bubble user-bubble live-partial">{liveText}</div>
              </div>
            )}
            {agentSpeaking && (
              <div className="chat-row agent">
                <span className="chat-avatar agent-avatar">AI</span>
                <div className="chat-bubble agent-bubble speaking-indicator">
                  <span className="bar" />
                  <span className="bar" />
                  <span className="bar" />
                  <span className="bar" />
                </div>
              </div>
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