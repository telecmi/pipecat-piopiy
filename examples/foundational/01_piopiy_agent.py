"""A Piopiy voice agent that can transfer the caller to a human and hang up.

It answers calls the Piopiy API places, calls arriving on your phone numbers,
and calls arriving over SIP Connect. Three things it can do mid-call:

  - warm transfer   the human's phone rings while the caller stays with the
                    agent; if nobody answers, the agent carries on
  - blind transfer  the caller is handed straight to a number; the agent leaves
  - hang up         after saying goodbye

Run:

    cp .env.example .env    # fill it in
    python 01_piopiy_agent.py

Tested with Pipecat v1.8.1.
"""

import os

from deepgram import LiveOptions
from dotenv import load_dotenv
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.openai.llm import OpenAILLMService

from pipecat_piopiy import PiopiyCall, PiopiyCallControl, PiopiyRunner, piopiy_tools
from pipecat_piopiy.processors import PiopiyEventsProcessor

load_dotenv()

SYSTEM_PROMPT = """You are the phone assistant for Acme Support. Your words are spoken
aloud, so keep replies to one or two short sentences, with no lists, markdown or emoji.

You can act on the call:
- If the caller asks for a person, or you cannot help, say you are connecting them and
  call transfer_call. Stay on the line while it rings; you will be told the outcome.
- If the caller asks to be put through to the billing line, call transfer_call with
  mode "blind": they are handed over straight away and you leave the call.
- When the conversation is over, say goodbye first, then call end_call.
"""


async def bot(transport, call: PiopiyCall):
    """Runs once per call, with a transport already pointed at the call's room."""
    logger.info("handling {} call from {} (sip account {})", call.direction, call.from_number, call.sip_account_id)

    # language MUST be the plain string "en": Pipecat's Language enum
    # serialises as "Language.EN" in Deepgram's query string and Deepgram
    # answers 400 - which surfaces only as "unable to connect".
    stt = DeepgramSTTService(
        api_key=os.environ["DEEPGRAM_API_KEY"],
        sample_rate=16000,
        live_options=LiveOptions(
            model="nova-3-general",
            language="en",
            encoding="linear16",
            sample_rate=16000,
            channels=1,
            interim_results=True,
            punctuate=True,
            smart_format=True,
        ),
    )
    llm = OpenAILLMService(
        api_key=os.environ["OPENAI_API_KEY"],
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    )
    tts = DeepgramTTSService(
        api_key=os.environ["DEEPGRAM_API_KEY"],
        voice=os.getenv("DEEPGRAM_VOICE", "aura-2-thalia-en"),
    )

    # Live-call actions for THIS call. Token and API base come from
    # PIOPIY_TOKEN and PIOPIY_API_URL.
    control = PiopiyCallControl(call)

    # transfer_call and end_call become function calls. The human's number and
    # the caller id to present are fixed here, so the caller cannot talk the
    # agent into dialling anywhere else.
    tools = piopiy_tools(
        control,
        transfer_number=os.environ["PIOPIY_TRANSFER_NUMBER"],
        transfer_caller_id=os.getenv("PIOPIY_CALLER_ID"),
    )

    caller = f"The caller's number is {call.from_number}." if not call.is_sip_connect else ""
    context = LLMContext(
        messages=[{"role": "system", "content": SYSTEM_PROMPT + caller}],
        tools=tools.schemas,
    )
    aggregators = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            PiopiyEventsProcessor(call),  # transfer progress -> frames + narration
            stt,
            aggregators.user(),
            llm,
            tts,
            transport.output(),
            aggregators.assistant(),
        ]
    )
    task = PipelineTask(
        pipeline,
        params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=16000),
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
    PiopiyRunner(max_sessions=int(os.getenv("PIOPIY_MAX_SESSIONS", "10"))).run(bot)
