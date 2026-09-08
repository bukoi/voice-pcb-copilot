import asyncio
from dotenv import load_dotenv

load_dotenv()

from livekit import agents
from livekit.agents import AgentServer, Agent, AgentSession, TurnHandlingOptions, room_io
from livekit.plugins import deepgram, groq, rime
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from pcb_tools import get_component, get_test_point, record_measurement, get_measurement, search_component_info

server = AgentServer()


@server.rtc_session(agent_name="pcb-copilot")
async def my_agent(ctx: agents.JobContext):

    session = AgentSession(
       stt=deepgram.STT(
    model="nova-3",
    language="multi",
    keyterms=["TP1", "TP2", "TP3", "TP4", "U1", "R1", "R2", "C1", "C2", "D1", "LED1", "J1"],
),
        llm=groq.LLM(
            model="openai/gpt-oss-20b",
            max_completion_tokens=60,
        ),
        tts=rime.TTS(
            model="coda",
            speaker="lyra",
            use_websocket=True,
            segment="bySentence",
        ),
        turn_handling=TurnHandlingOptions(
            turn_detection=MultilingualModel(),
        ),
    )

    @session.on("user_input_transcribed")
    def on_transcript(ev):
        topic = "lk.final-transcript" if ev.is_final else "lk.live-partial"
        asyncio.create_task(
            ctx.room.local_participant.send_text(ev.transcript, topic=topic)
        )

    await session.start(
        agent=Agent(
           instructions=(
    "You are a hands-free voice assistant helping an engineer debug a "
    "5V-to-3.3V power supply PCB. Keep answers short and spoken-friendly — "
    "one or two sentences, no bullet points.\n\n"
    "This board's components are: U1, R1, R2, C1, C2, D1, LED1, J1. "
    "Its test points are: TP1, TP2, TP3, TP4.\n\n"
    "If the user asks about one of THOSE specific labels, use get_component "
    "or get_test_point.\n\n"
    "If the user asks about a real-world generic part that is NOT one of "
    "those labels (e.g. '555 timer', 'LM7805', 'ESP32'), use "
    "search_component_info instead of asking for a reference designator — "
    "these are real components, not part of this board's labeling scheme."
),
            tools=[get_component, get_test_point, record_measurement, get_measurement, search_component_info],
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