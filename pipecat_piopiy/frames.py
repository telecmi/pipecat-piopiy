"""Frames that carry Piopiy call events through a Pipecat pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from pipecat.frames.frames import DataFrame


@dataclass
class PiopiyTransferStatusFrame(DataFrame):
    """A transfer's progress, as the platform reported it into the call's room.

    Emitted by :class:`~pipecat_piopiy.processors.PiopiyEventsProcessor` for
    every ``transfer_status`` room message, whoever started the transfer - the
    agent's own tool call or the customer's backend through the API.

    Attributes:
        status: ``"started"`` when the target begins ringing, ``"failed"`` when
            it did not answer or refused, ``"completed"`` when the caller was
            handed over. ``completed`` is best-effort: at that moment the agent
            is being removed from the call, and leaving the room is itself the
            success signal.
        request_id: The transfer request this reports on.
        call_id: The call the transfer belongs to.
        reason: On ``failed`` only: ``busy``, ``no_answer``, ``rejected``,
            ``invalid_number``, ``unreachable``, ``call_barred`` or
            ``network_error``. A reason ending in ``_and_call_ended`` means the
            whole call ended too.
    """

    status: str = ""
    request_id: str = ""
    call_id: str = ""
    reason: str | None = None

    @property
    def failed(self) -> bool:
        """True when the transfer did not go through and the agent still has the caller."""
        return self.status == "failed"
