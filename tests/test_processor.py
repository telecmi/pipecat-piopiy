import json

import pytest
from pipecat.frames.frames import LLMMessagesAppendFrame, TTSSpeakFrame

from pipecat_piopiy import PiopiyCall, PiopiyTransferStatusFrame
from pipecat_piopiy.processors import PiopiyEventsProcessor


class Collecting(PiopiyEventsProcessor):
    """Captures pushed frames instead of forwarding them into a pipeline."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pushed = []

    async def push_frame(self, frame, direction=None):
        self.pushed.append(frame)


def make_call():
    return PiopiyCall(
        call_id="call-1", room_name="room", direction="inbound",
        from_number="9198", to_number="9112", agent_id="agent",
    )


def message(**fields):
    return json.dumps({"type": "transfer_status", "call_id": "call-1", "request_id": "req-1", **fields}).encode()


@pytest.mark.asyncio
async def test_started_narrates_and_emits_frame():
    call = make_call()
    processor = Collecting(call)
    assert processor in call._listeners

    await processor.on_room_data(message(status="started"), None)

    kinds = [type(f) for f in processor.pushed]
    assert kinds[0] is PiopiyTransferStatusFrame
    assert processor.pushed[0].status == "started"
    assert TTSSpeakFrame in kinds
    assert LLMMessagesAppendFrame in kinds


@pytest.mark.asyncio
async def test_failed_uses_reason_line():
    processor = Collecting(make_call())
    await processor.on_room_data(message(status="failed", reason="no_answer"), None)
    status = processor.pushed[0]
    assert status.failed and status.reason == "no_answer"
    spoken = [f for f in processor.pushed if isinstance(f, TTSSpeakFrame)]
    assert "not picking up" in spoken[0].text


@pytest.mark.asyncio
async def test_narrate_off_only_emits_frame():
    processor = Collecting(make_call(), narrate=False)
    await processor.on_room_data(message(status="completed"), None)
    assert [type(f) for f in processor.pushed] == [PiopiyTransferStatusFrame]


@pytest.mark.asyncio
async def test_ignores_other_messages():
    processor = Collecting(make_call())
    await processor.on_room_data(b"not json", "someone")
    await processor.on_room_data(json.dumps({"type": "chat", "text": "hi"}).encode(), "someone")
    assert processor.pushed == []


@pytest.mark.asyncio
async def test_llm_narration_has_the_model_speak():
    """Speech-to-speech pipelines have no TTS: the model must say the line itself."""
    processor = Collecting(make_call(), narration="llm")
    await processor.on_room_data(message(status="failed", reason="busy"), None)
    kinds = [type(f) for f in processor.pushed]
    assert TTSSpeakFrame not in kinds
    appended = [f for f in processor.pushed if isinstance(f, LLMMessagesAppendFrame)]
    assert appended and appended[0].run_llm is True
    content = appended[0].messages[0]["content"]
    assert "busy" in content and "Say to the caller now" in content


def test_narration_mode_is_validated():
    with pytest.raises(ValueError):
        PiopiyEventsProcessor(make_call(), narration="loud")
