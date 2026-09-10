🎙️ Voice PCB Copilot

A hands-free, voice-first AI copilot for debugging PCBs — built for the moment your hands are full of a multimeter probe and a soldering iron, and typing just isn't an option.

Python FastAPI LiveKit Agents License

📖 Overview

Debugging a printed circuit board is a two-handed job — one hand on the probe, one hand on the board — which leaves zero hands free to search a datasheet, log a voltage reading, or look up what a mystery IC does. Voice PCB Copilot solves that problem by turning your voice into the interface.

Instead of putting down your tools to type into a search bar, you simply talk to the copilot the way you'd talk to a lab partner: "What's this SOIC-8 chip near the power input?", "I'm reading 3.3 volts across R12, is that expected?", "Pull up the datasheet for the LM358." The copilot listens, reasons, looks things up, and talks back — in real time, completely hands-free.

🧩 The Problem It Solves
Both hands are occupied. Probing a live board with a multimeter or oscilloscope while also typing on a laptop isn't realistic.
Component identification is slow. Squinting at a tiny SMD part marking and cross-referencing it against a datasheet mid-debug breaks your flow.
Measurements get lost. Voltage/current/resistance readings taken during a debug session are rarely logged anywhere useful.
Context-switching kills focus. Alt-tabbing between a schematic, a datasheet PDF, and a search engine while your probe is still on the board is how mistakes happen.

Voice PCB Copilot keeps your hands on the hardware and your eyes on the board, while an AI copilot handles the lookup, logging, and reasoning in the background through natural conversation.

✨ Key Features
🎤 Hands-free voice conversation — talk naturally, no wake-word gymnastics or rigid commands required.
🔍 Component identification — describe a part (markings, package type, location on the board) and get an ID plus a plain-language explanation of what it does.
📄 Datasheet retrieval — ask for pinouts, voltage ratings, or key specs and have them read back to you on the spot.
📊 Measurement tracking — call out readings as you take them ("12 volts at test point 3") and have the copilot keep a running log for you.
🛠️ Guided troubleshooting — describe symptoms (won't power on, chip getting hot, no output signal) and get a conversational, step-by-step debugging path.
⚡ Real-time, low-latency dialogue — built on a streaming voice pipeline so the back-and-forth feels like talking to a person, not a chatbot with a mic bolted on.
🎯 Who It's For
Hardware engineers doing bring-up and debug on the bench.
Electronics students learning to read boards and troubleshoot circuits who want a patient, always-available voice tutor.
Makers and hobbyists repairing or reverse-engineering boards without a shelf full of datasheets.
Repair technicians who need quick answers while their hands are on the device under test.
🏗️ Architecture
   Microphone                                  Speaker
       │                                           ▲
       ▼                                           │
┌────────────────────────────────────────────────────────┐
│                    LiveKit Realtime Session              │
│  ┌───────────┐   ┌───────────────┐   ┌────────────────┐  │
│  │  Deepgram │──▶│  Groq / OpenAI │──▶│   Rime (TTS)   │  │
│  │  (STT)    │   │  (LLM reasoning)│   │  (Voice out)   │  │
│  └───────────┘   └───────┬────────┘   └────────────────┘  │
│                          │ tool calls                     │
└──────────────────────────┼────────────────────────────────┘
                            ▼
                 ┌─────────────────────┐
                 │   FastAPI Backend    │
                 │  Agent orchestration │
                 │  Datasheet / part    │
                 │  lookup (Tavily)     │
                 │  Measurement logging │
                 └─────────────────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │      Frontend        │
                 │  Session UI / live   │
                 │  transcript & logs   │
                 └─────────────────────┘

The voice pipeline listens continuously, transcribes speech, reasons about the request (calling out to tools like web/datasheet search when it needs facts), and speaks the answer back — all within a single low-latency LiveKit session.

🛠️ Tech Stack

Backend & Agent Orchestration

FastAPI — API layer and session orchestration
LiveKit Agents — real-time, streaming voice-agent framework that ties STT → LLM → TTS together
Uvicorn — ASGI server
Pydantic — data validation for structured tool calls (measurements, component lookups, etc.)

Voice Pipeline & Rime Configuration

- **Text-to-Speech**: **Rime Labs** (`livekit-plugins-rime`)
  - **Model ID**: `coda` (fast conversational TTS)
  - **Speaker**: `lyra` (natural tone)
  - **Language**: `en`
  - **Transport**: WebSocket streaming (`use_websocket=True`)
  - **Segment Mode**: `immediate` (instant time-to-first-audio)
  - **Audio Format**: 24kHz Opus/WebRTC
- **Speech-to-Text**: Deepgram (`nova-3`, `livekit-plugins-deepgram`)
- **LLM Reasoning**: Groq (`openai/gpt-oss-120b`, `livekit-plugins-groq`)
- **Turn Detection / Flow**: Multilingual turn-detector for natural, interruption-aware dialogue

Knowledge & Retrieval

- **RAG Vector Database**: Qdrant Cloud + Sentence Transformers (`all-MiniLM-L6-v2`)
- **Web & Datasheet Search**: Tavily (`tavily-python`) — real-time web search for datasheets and pinouts
- **Hardware Parsers**: Custom KiCad S-expression parser (`sexpdata`) for `.kicad_sch` & `.kicad_pcb` files

Frontend

Web client (see /frontend) providing the session UI, live transcript, and measurement/history view

Observability

OpenTelemetry — tracing and metrics export for the agent pipeline
📂 Project Structure
voice-pcb-copilot/
├── backend/          # FastAPI app + LiveKit voice agent, tool logic
├── frontend/          # Web client for the voice session
├── requirements.txt   # Python dependencies
├── .env.example        # Required environment variables (API keys, LiveKit config)
└── Readme.md
🚀 Getting Started
Prerequisites
Python 3.10+
A LiveKit account/server (cloud or self-hosted)
API keys for the voice pipeline: Deepgram (STT), Groq and/or OpenAI (LLM), Rime (TTS)
A Tavily API key for datasheet/web lookups
Node.js (for running /frontend)
Backend Setup
bash
git clone https://github.com/kuldeepsingh102006-stack/voice-pcb-copilot.git
cd voice-pcb-copilot

python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Fill in your LiveKit, Deepgram, Groq/OpenAI, Rime, and Tavily API keys in .env

cd backend
python agent.py start         # or the equivalent entrypoint in /backend
Frontend Setup
bash
cd frontend
npm install
npm run dev

Then open the frontend in your browser, join a session, and start talking to the copilot.

🧪 Testing with Sample KiCad Files

We include real-world test hardware files in `backend/kicad_files_to_test/`:
- `CM5_MINIMA_3.kicad_sch` (Raspberry Pi Compute Module 5 Minima carrier schematic)
- `CM5_MINIMA_3.kicad_pcb` (Raspberry Pi Compute Module 5 Minima carrier layout)

**To test dynamic board loading in the web UI:**
1. Connect to the voice session in the browser.
2. In the **Upload KiCad files** header panel, pick the `.kicad_sch` and/or `.kicad_pcb` files from `backend/kicad_files_to_test/`.
3. Click **Upload board**.
4. The copilot will parse the board dynamically, acknowledge the component count via Rime speech, and update its context so you can immediately ask about its specific components and nets.

💬 Example Interactions
- "What's this 8-pin chip labeled 'LM358' near the op-amp section?"
- "I'm probing test point 2 and getting 0 volts, what should that be reading?"
- "Log 4.98 volts at the regulator output."
- "What components are on this board?" (after uploading the sample files)
- "The board powers on but the LED isn't lighting, walk me through what to check."
🗺️ Roadmap Ideas
Persistent session history so past debug sessions and logged measurements can be revisited
Image/vision support for pointing a camera at a component instead of describing it verbally
Offline/local-inference mode for bench use without internet access
Multi-turn schematic awareness (uploading a schematic the copilot can reference during the conversation)
🤝 Contributing

Contributions, issues, and feature requests are welcome. Feel free to open an issue or submit a PR.

📄 License

This project is open source. Add your preferred license (e.g., MIT) here.

Built for the moment your hands are full and your questions can't wait.
