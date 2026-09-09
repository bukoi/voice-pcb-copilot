import asyncio
import json
from dotenv import load_dotenv

load_dotenv()

from livekit import agents
from livekit.agents import AgentServer, Agent, AgentSession, TurnHandlingOptions, room_io
from livekit.plugins import deepgram, groq, rime
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from pcb_tools import (
    search_debugging_knowledge,
    get_component,
    get_test_point,
    record_measurement,
    get_measurement,
    search_component_info,
    load_board_file,
    list_components,
)

server = AgentServer()



# ---------------------------------------------------------------------------
# Voice session
# ---------------------------------------------------------------------------

_ALL_TOOLS = [
    search_debugging_knowledge,
    get_component,
    get_test_point,
    record_measurement,
    get_measurement,
    search_component_info,
    load_board_file,
    list_components,
]

_SYSTEM_PROMPT = (
    "You are a voice assistant helping an engineer debug a PCB. "
    "Keep answers to 1-2 spoken sentences, no bullet points.\n\n"
    "Default board: 5V-to-3.3V power supply (U1=LM1117-3.3, R1, R2, C1, C2, D1, LED1, J1; TP1-TP4). "
    "When the user uploads a KiCad file, the board is already parsed — just tell them what was found.\n\n"
    "Tool rules: use get_component/get_test_point for board labels (R1, TP2…); "
    "list_components to see what's on the board; "
    "search_component_info for generic real-world parts; "
    "search_debugging_knowledge for general troubleshooting."
)


@server.rtc_session(agent_name="pcb-copilot")
async def my_agent(ctx: agents.JobContext):

    session = AgentSession(
        stt=deepgram.STT(
            model="nova-3",
            language="multi",
            keyterms=["TP1", "TP2", "TP3", "TP4", "U1", "R1", "R2", "C1", "C2",
                      "D1", "LED1", "J1"],
        ),
        llm=groq.LLM(
            model="openai/gpt-oss-120b",
            max_completion_tokens=250,
        ),
        tts=rime.TTS(
            model="coda",
            speaker="lyra",
            use_websocket=True,
            segment="immediate",
        ),
        turn_handling=TurnHandlingOptions(
            turn_detection=MultilingualModel(),
        ),
    )

    # ------------------------------------------------------------------
    # Stream finalized / partial transcripts back to the frontend UI
    # ------------------------------------------------------------------
    @session.on("user_input_transcribed")
    def on_transcript(ev):
        topic = "lk.final-transcript" if ev.is_final else "lk.live-partial"
        asyncio.create_task(
            ctx.room.local_participant.send_text(ev.transcript, topic=topic)
        )

    # Send the agent's spoken reply text back to the frontend so it appears
    # in the transcript panel alongside the user's speech.
    @session.on("agent_speech_committed")
    def on_agent_speech(ev):
        text = getattr(ev, "text", None) or getattr(ev, "transcript", None)
        if text:
            asyncio.create_task(
                ctx.room.local_participant.send_text(text, topic="lk.agent-response")
            )

    # ------------------------------------------------------------------
    # Handle board uploads sent by the frontend over the data channel
    # ------------------------------------------------------------------
    @ctx.room.on("data_received")
    def on_data(data_packet):
        """
        The frontend sends a JSON message on topic "lk.board-upload":
          { "sch_path": "...", "pcb_path": "..." }
        (either key may be null if only one file was uploaded)
        """
        payload = data_packet.data
        topic = getattr(data_packet, "topic", None)

        if topic != "lk.board-upload":
            return

        try:
            msg = json.loads(payload.decode("utf-8"))
        except Exception:
            return

        sch_path = msg.get("sch_path")
        pcb_path = msg.get("pcb_path")

        # Parse the board immediately in a background task rather than
        # asking the LLM to call load_board_file via tool-call JSON.
        # Reason: small Groq models produce malformed tool-call JSON when
        # the instruction embeds raw file paths → "Failed to parse tool call
        # arguments as JSON" error.  We do the work here and only ask the
        # LLM to narrate the result, which requires no tool call at all.
        async def _load_and_announce():
            import asyncio as _aio
            from pcb_tools import _session_boards
            from parse_kicad_schematics import (
                parse_kicad_schematic,
                parse_kicad_pcb,
                merge_board_data,
            )

            try:
                sch_data = (
                    await _aio.to_thread(parse_kicad_schematic, sch_path)
                    if sch_path else None
                )
                pcb_data = (
                    await _aio.to_thread(parse_kicad_pcb, pcb_path)
                    if pcb_path else None
                )
                merged = merge_board_data(sch_data, pcb_data)
                _session_boards[ctx.room.name] = merged

                n_comp = len(merged.get("components", {}))
                n_nets = len(merged.get("nets", {}))
                note = (
                    f"Board loaded: {n_comp} components, {n_nets} nets. "
                    "Tell the user this in one friendly sentence."
                )
            except Exception as exc:
                note = f"Board parsing failed: {exc}. Tell the user briefly."

            # generate_reply returns a SpeechHandle (not a coroutine),
            # so just call it — don't await or wrap in create_task.
            session.generate_reply(instructions=note)

        asyncio.create_task(_load_and_announce())

    # ------------------------------------------------------------------
    # Start the session
    # ------------------------------------------------------------------
    await session.start(
        agent=Agent(
            instructions=_SYSTEM_PROMPT,
            tools=_ALL_TOOLS,
        ),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            text_output=room_io.TextOutputOptions(
                sync_transcription=False
            )
        ),
    )

    await session.generate_reply(
        instructions="Greet the user briefly and ask what they're debugging today."
    )


if __name__ == "__main__":
    agents.cli.run_app(server)