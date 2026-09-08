"""Piopiy + Pipecat with Gemini Live: one speech-to-speech model, no STT/TTS.

Gemini listens and talks directly, so the pipeline is shorter than the
Deepgram/OpenAI one in ``01_piopiy_agent.py``. Everything else is the same:
the agent can warm-transfer the caller to a person, hand them over blind, and
end the call, all as function calls.

Run it:

    pip install "pipecat-piopiy[example-gemini]"
    cp .env.example .env      # agent id + token, transfer number, GOOGLE_API_KEY
    python 02_piopiy_gemini_live.py

Then call your agent from one of your Piopiy numbers or with
POST /v3/voice/agent/call.
"""

import os

from dotenv import load_dotenv
from loguru import logger
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService, InputParams
from pipecat.services.google.gemini_live.vertex.llm import GeminiLiveVertexLLMService
from pipecat.transports.livekit.transport import LiveKitParams

from pipecat_piopiy import PiopiyCall, PiopiyCallControl, PiopiyRunner, piopiy_tools
from pipecat_piopiy.processors import PiopiyEventsProcessor

load_dotenv()

# Gemini Live takes 16 kHz audio in and produces 24 kHz audio out.
AUDIO_IN_RATE = 16000
AUDIO_OUT_RATE = 24000

SYSTEM_PROMPT = """You are the phone assistant for Acme Support. You are speaking on a
phone call, so keep replies to one or two short sentences, no lists, no markdown.

You can act on the call:
- If the caller asks for a person, or you cannot help, say you are connecting them and
  call transfer_call. Stay on the line while it rings; you will be told the outcome.
- If the caller asks to be put through to the billing line, call transfer_call with
  mode "blind": they are handed over straight away and you leave the call.
- When the conversation is over, say goodbye first, then call end_call.
"""


async def bot(transport, call: PiopiyCall):
    """Runs once per call, with a transport already pointed at the call's room."""
    logger.info("handling {} call from {} (connection {})", call.direction, call.from_number, call.sip_account_id)

    # Live-call actions for THIS call. Token and API base come from
    # PIOPIY_TOKEN and PIOPIY_API_URL.
    control = PiopiyCallControl(call)

    # transfer_call and end_call become Gemini function calls. The human's
    # number and the caller id to present are fixed here, so the caller cannot
    # talk the agent into dialling anywhere else.
    tools = piopiy_tools(
        control,
        transfer_number=os.environ["PIOPIY_TRANSFER_NUMBER"],
        transfer_caller_id=os.getenv("PIOPIY_CALLER_ID"),
    )

    caller = f" The caller's number is {call.from_number}." if not call.is_sip_connect else ""
    # Language: the native-audio model detects the spoken language itself and
    # rejects most explicit codes (e.g. "en-IN"). Only pass one when set.
    params = InputParams(language=os.environ["GEMINI_LANGUAGE"]) if os.getenv("GEMINI_LANGUAGE") else None
    voice = os.getenv("GEMINI_VOICE", "Kore")  # female; Aoede, Leda, Zephyr also female

    if os.getenv("GOOGLE_CLOUD_PROJECT"):
        # Vertex AI: works from any server location, billed to your Google
        # Cloud project. Credentials via GOOGLE_APPLICATION_CREDENTIALS or the
        # machine's default Google credentials.
        llm = GeminiLiveVertexLLMService(
            project_id=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
            credentials_path=os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
            model=os.getenv("GEMINI_MODEL") or None,
            voice_id=voice,
            system_instruction=SYSTEM_PROMPT + caller,
            params=params,
        )
    else:
        # Google AI Studio key. Not offered from every region: if the log says
        # "User location is not supported", switch to Vertex AI above.
        llm = GeminiLiveLLMService(
            api_key=os.environ["GOOGLE_API_KEY"],
            model=os.getenv("GEMINI_MODEL") or None,  # None = Pipecat's current default
            voice_id=voice,
            system_instruction=SYSTEM_PROMPT + caller,
            params=params,
        )

    # The first turn: Gemini speaks as soon as the context is initialised, so
    # the opening user message is the cue to greet.
    context = LLMContext(
        messages=[{"role": "user", "content": "Greet the caller and ask how you can help."}],
        tools=tools.schemas,
    )
    # No VAD analyzer here: Gemini detects turns and interruptions itself.
    aggregators = LLMContextAggregatorPair(context)

    pipeline = Pipeline(
        [
            transport.input(),
            # narration="llm": there is no TTS stage, so transfer progress
            # ("I'm connecting you now", the apology on failure) is spoken by
            # Gemini itself.
            PiopiyEventsProcessor(call, narration="llm"),
            aggregators.user(),
            llm,
            transport.output(),
            aggregators.assistant(),
        ]
    )
    task = PipelineTask(
        pipeline,
        params=PipelineParams(audio_in_sample_rate=AUDIO_IN_RATE, audio_out_sample_rate=AUDIO_OUT_RATE),
    )

    @transport.event_handler("on_first_participant_joined")
    async def on_caller_joined(_transport, participant_id):
        # The caller is on the line: greet them.
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_participant_left")
    async def on_caller_left(_transport, participant_id, reason):
        # The caller hung up, or a transfer completed and the platform is
        # taking the agent out of the call.
        await task.cancel()

    try:
        # The runner owns process signals; the pipeline must not.
        await PipelineRunner(handle_sigint=False).run(task)
    finally:
        await control.close()


if __name__ == "__main__":
    PiopiyRunner(
        max_sessions=int(os.getenv("PIOPIY_MAX_SESSIONS", "10")),
        # Match the transport to Gemini's rates so no resampling happens.
        livekit_params=LiveKitParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=AUDIO_IN_RATE,
            audio_out_sample_rate=AUDIO_OUT_RATE,
        ),
    ).run(bot)
