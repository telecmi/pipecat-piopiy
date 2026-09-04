"""The call a Piopiy worker was handed: who is calling whom, and how to act on it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PiopiyCall:
    """One phone call, as offered to your agent.

    Built by :class:`~pipecat_piopiy.runner.PiopiyRunner` from the job the
    Piopiy platform dispatched. Every live-call action (transfer, hangup,
    status) keys on ``call_id``, the id the platform expects on
    ``/v3/calls/{call_id}/actions/*``.

    Attributes:
        call_id: The call's id. Use it for every action.
        room_name: The LiveKit room the call's media is bridged into.
        direction: ``"inbound"`` when someone called the agent, ``"outbound"``
            when the agent called them.
        from_number: The caller's number. When the call came from a phone system you connected
            to Piopiy this is that system's user name, not a phone number.
        to_number: The number dialled, or the agent id or extension a connected
            phone system dialled.
        agent_id: The Piopiy agent handling this call.
        variables: Key/values passed on call creation as ``variables`` - a
            campaign's context for the conversation. Empty on inbound calls
            unless the platform attached any.
        sip_headers: Extra headers a connected phone system sent with the call,
            when any.
        sip_account_id: When the call came from a phone system you connected
            to Piopiy, which connection it came through, so one agent can tell
            your sites apart. ``None`` on calls to a phone number.
        trace_id: The platform's trace id for this call. Quote it to support.
    """

    call_id: str
    room_name: str
    direction: str
    from_number: str
    to_number: str
    agent_id: str
    variables: dict[str, str] = field(default_factory=dict)
    sip_headers: dict[str, str] = field(default_factory=dict)
    sip_account_id: str | None = None
    trace_id: str = ""

    # Processors that want the platform's room messages register here; the
    # runner fans each message out to them. Not part of the public surface.
    _listeners: list[Any] = field(default_factory=list, repr=False, compare=False)

    @property
    def is_inbound(self) -> bool:
        """True when the person on the line called us."""
        return self.direction == "inbound"

    @property
    def is_sip_connect(self) -> bool:
        """True when the call came from a phone system you connected to Piopiy."""
        return self.sip_account_id is not None

    @classmethod
    def from_job(cls, job: Any, *, agent_id: str) -> PiopiyCall:
        """Build a call from a ``piopiy_agent.Job``.

        Args:
            job: The job the worker received.
            agent_id: The agent id this worker serves.

        Returns:
            The call, ready to hand to your bot.
        """
        headers = dict(getattr(job.call, "sip_headers", {}) or {})
        variables = dict(getattr(job.call, "variables", {}) or {})
        sip_account_id = (
            headers.get("X-SIP-Account-ID")
            or headers.get("x-sip-account-id")
            or variables.get("sip_account_id")
        )
        return cls(
            call_id=job.call.call_uuid,
            room_name=job.room_name,
            direction=job.call.direction or "inbound",
            from_number=job.call.from_number,
            to_number=job.call.to_number,
            agent_id=agent_id,
            variables=variables,
            sip_headers=headers,
            sip_account_id=sip_account_id,
            trace_id=getattr(job, "trace_id", "") or "",
        )
