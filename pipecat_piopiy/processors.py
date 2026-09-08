"""Bring the platform's room messages into the pipeline as frames."""

from __future__ import annotations

import json
from collections.abc import Callable

from loguru import logger
from pipecat.frames.frames import Frame, LLMMessagesAppendFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from .call import PiopiyCall
from .frames import PiopiyTransferStatusFrame

#: What the agent says for each failure reason when narration is on.
DEFAULT_FAILURE_LINES: dict[str, str] = {
    "busy": "I'm sorry, their line is busy right now. Let me help you myself.",
    "no_answer": "I'm sorry, they're not picking up. Let me see what I can do for you.",
    "rejected": "I'm sorry, they're not available right now. Let me help you instead.",
    "invalid_number": "I'm sorry, I couldn't reach them. Let me help you myself.",
    "unreachable": "I'm sorry, I couldn't reach them. Let me help you myself.",
    "call_barred": "I'm sorry, I couldn't connect that call. Let me help you myself.",
    "network_error": "I'm sorry, something went wrong connecting you. Let me help you myself.",
}

DEFAULT_STARTED_LINE = "I'm connecting you now. Please stay on the line."


class PiopiyEventsProcessor(FrameProcessor):
    """Turns Piopiy ``transfer_status`` room messages into pipeline frames.

    Place it right after ``transport.input()`` so that what it emits reaches
    the LLM context and the TTS downstream::

        pipeline = Pipeline([
            transport.input(),
            PiopiyEventsProcessor(call),
            stt, context_aggregator.user(), llm, tts,
            transport.output(), context_aggregator.assistant(),
        ])

    For every message it pushes a :class:`PiopiyTransferStatusFrame`. With
    ``narrate=True`` (the default) it also speaks: "I'm connecting you now"
    when the target starts ringing, and an apology when the transfer fails, and
    it appends a short note to the LLM context so the model knows the outcome
    and carries on. Set ``narrate=False`` to handle the frames yourself.

    With a speech-to-speech model (Gemini Live, OpenAI Realtime) there is no
    TTS service to speak a line, so pass ``narration="llm"``: the processor then
    asks the model itself to say it, by appending the note to the context and
    running the model, instead of pushing a ``TTSSpeakFrame``.

    The platform pushes these messages for every transfer on the call, whether
    the agent's tool started it or your backend did through the API.
    """

    def __init__(
        self,
        call: PiopiyCall,
        *,
        narrate: bool = True,
        narration: str = "tts",
        started_line: str = DEFAULT_STARTED_LINE,
        failure_lines: dict[str, str] | None = None,
        on_status: Callable[[PiopiyTransferStatusFrame], None] | None = None,
        **kwargs,
    ):
        """Initialize the processor.

        Args:
            call: The call this pipeline serves. The processor registers itself
                on it so the runner can deliver the room messages.
            narrate: Speak the transfer's progress to the caller and inform the
                LLM context. Off, only frames are emitted.
            narration: ``"tts"`` (default) speaks the line through the TTS
                service in the pipeline; ``"llm"`` has the model say it
                itself - use this with speech-to-speech models, which have no
                TTS stage.
            started_line: What to say when the target starts ringing.
            failure_lines: What to say per failure reason; merged over
                :data:`DEFAULT_FAILURE_LINES`.
            on_status: Optional callback invoked with every status frame.
            **kwargs: Passed to :class:`FrameProcessor`.
        """
        super().__init__(**kwargs)
        self._call = call
        if narration not in ("tts", "llm"):
            raise ValueError('narration must be "tts" or "llm"')
        self._narrate = narrate
        self._narration = narration
        self._started_line = started_line
        self._failure_lines = {**DEFAULT_FAILURE_LINES, **(failure_lines or {})}
        self._on_status = on_status
        call._listeners.append(self)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Pass every frame through untouched."""
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

    async def _say(self, line: str, note: str) -> None:
        """Speak ``line`` to the caller and tell the model ``note``.

        ``tts`` mode: the line goes to the TTS service as a ``TTSSpeakFrame``
        and the note is appended to the context without a model turn.
        ``llm`` mode: there is no TTS stage, so the note asks the model to say
        the line itself and a model turn is run at once.
        """
        if self._narration == "tts":
            await self.push_frame(TTSSpeakFrame(line))
            await self.push_frame(
                LLMMessagesAppendFrame([{"role": "system", "content": note}], run_llm=False)
            )
        else:
            await self.push_frame(
                LLMMessagesAppendFrame(
                    [
                        {
                            "role": "system",
                            "content": f'{note} Say to the caller now, in your own voice: "{line}"',
                        }
                    ],
                    run_llm=True,
                )
            )

    async def on_room_data(self, data: bytes, sender: str | None = None) -> None:
        """Handle one data message from the call's room.

        Called by :class:`~pipecat_piopiy.runner.PiopiyRunner` for every data
        message the transport receives. Messages that are not Piopiy transfer
        status reports are ignored, so a bot's own data channel is unaffected.

        Args:
            data: The raw message bytes.
            sender: The sending participant, ``None`` for platform messages.
        """
        try:
            message = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return
        if not isinstance(message, dict) or message.get("type") != "transfer_status":
            return

        frame = PiopiyTransferStatusFrame(
            status=str(message.get("status", "")),
            request_id=str(message.get("request_id", "")),
            call_id=str(message.get("call_id", self._call.call_id)),
            reason=message.get("reason"),
        )
        logger.info(
            "transfer {} for call {}{}",
            frame.status,
            frame.call_id,
            f" ({frame.reason})" if frame.reason else "",
        )

        if self._on_status:
            self._on_status(frame)

        await self.push_frame(frame)

        if not self._narrate:
            return

        if frame.status == "started":
            await self._say(
                self._started_line,
                "The transfer target is now ringing. Keep the caller company "
                "briefly; do not start a new topic.",
            )
        elif frame.status == "failed":
            line = self._failure_lines.get(
                (frame.reason or "").replace("_and_call_ended", ""),
                self._failure_lines["network_error"],
            )
            await self._say(
                line,
                f"The transfer failed ({frame.reason or 'unknown'}). You are still "
                "with the caller. Continue helping them; do not retry the "
                "transfer unless they ask.",
            )
        # "completed": the platform is removing the agent from the call right
        # now. Nothing to say - the caller is already with the human.
