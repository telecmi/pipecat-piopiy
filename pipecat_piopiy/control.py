"""Act on a live call through the Piopiy ``/v3`` API: transfer, hang up, check status."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any

import aiohttp

from .call import PiopiyCall

#: Sanitized reasons a transfer can fail with.
TRANSFER_FAILURE_REASONS = (
    "busy",
    "no_answer",
    "rejected",
    "invalid_number",
    "unreachable",
    "call_barred",
    "network_error",
)


class PiopiyAPIError(Exception):
    """The platform refused an action.

    Attributes:
        status: The HTTP status.
        error: The platform's error code, e.g. ``transfer_in_progress``.
        body: The full response body.
        request_id: On ``409 transfer_in_progress``, the transfer already
            running - poll it instead of retrying.
    """

    def __init__(self, status: int, body: Any):
        self.status = status
        self.body = body if isinstance(body, dict) else {"raw": body}
        self.error = str(self.body.get("error") or self.body.get("message") or f"http_{status}")
        self.request_id: str | None = self.body.get("request_id")
        super().__init__(f"{status} {self.error}")


@dataclass(frozen=True)
class TransferResult:
    """The immediate answer to a transfer request.

    Attributes:
        request_id: The transfer's id. The outcome arrives later - as a
            :class:`~pipecat_piopiy.frames.PiopiyTransferStatusFrame` in the
            pipeline, on the customer's webhook, and from
            :meth:`PiopiyCallControl.transfer_status`.
        call_id: The call being transferred.
    """

    request_id: str
    call_id: str


@dataclass(frozen=True)
class TransferStatus:
    """A transfer's current verdict.

    Attributes:
        request_id: The transfer.
        call_id: The call.
        status: ``queued`` while ringing, then ``completed`` or ``failed``.
        reason: On ``failed``, one of :data:`TRANSFER_FAILURE_REASONS`.
    """

    request_id: str
    call_id: str
    status: str
    reason: str | None = None

    @property
    def settled(self) -> bool:
        """True once the transfer is no longer ringing."""
        return self.status != "queued"


class PiopiyCallControl:
    """Live-call actions for one call.

    Every method targets the call's customer leg, which is what the platform
    expects. Create one per call::

        control = PiopiyCallControl(call, token=os.environ["PIOPIY_TOKEN"])
        result = await control.warm_transfer(to_number="919876543210")
        verdict = await control.wait_for_transfer(result.request_id)

    Configuration comes from arguments or the environment: ``PIOPIY_TOKEN``
    (the same Bearer token that creates calls) and ``PIOPIY_API_URL`` (the
    platform's ``/v3`` base, e.g. ``https://api.example.com/v3``).
    """

    def __init__(
        self,
        call: PiopiyCall,
        *,
        token: str | None = None,
        api_url: str | None = None,
        session: aiohttp.ClientSession | None = None,
        timeout_sec: float = 10.0,
    ):
        """Initialize the control handle.

        Args:
            call: The call to act on.
            token: Bearer token; defaults to ``PIOPIY_TOKEN``.
            api_url: ``/v3`` base URL; defaults to ``PIOPIY_API_URL``.
            session: An ``aiohttp`` session to reuse. When omitted one is
                created on first use and closed by :meth:`close`.
            timeout_sec: Per-request timeout.

        Raises:
            ValueError: When no token or base URL is available.
        """
        self.call = call
        self._token = token or os.getenv("PIOPIY_TOKEN") or os.getenv("TELECMI_TOKEN")
        self._api_url = (api_url or os.getenv("PIOPIY_API_URL") or "").rstrip("/")
        if not self._token:
            raise ValueError("PiopiyCallControl needs a token: pass token= or set PIOPIY_TOKEN")
        if not self._api_url:
            raise ValueError(
                "PiopiyCallControl needs the API base URL: pass api_url= or set PIOPIY_API_URL "
                "(the platform's /v3 base, e.g. https://api.example.com/v3)"
            )
        self._session = session
        self._owns_session = session is None
        self._timeout = aiohttp.ClientTimeout(total=timeout_sec)

    # ---------- actions ----------

    async def warm_transfer(
        self,
        *,
        to_number: str | None = None,
        sip_uri: str | None = None,
        caller_id: str | None = None,
        timeout_sec: int | None = None,
        confirm: bool | None = None,
        hold_audio: Any | None = None,
        transfer_summary: str | None = None,
        sip_headers: dict[str, str] | None = None,
        variables: dict[str, Any] | None = None,
    ) -> TransferResult:
        """Ring a human while the caller stays with the agent; bridge on answer.

        If nobody answers, nothing changes for the caller - the conversation
        with the agent continues. Exactly one of ``to_number`` or ``sip_uri``
        must be given.

        Args:
            to_number: Phone number, digits with country code.
            sip_uri: SIP destination, dialled direct with no carrier.
            caller_id: DID to present. Required on SIP Connect calls.
            timeout_sec: How long the target rings.
            confirm: Require the human to press 1 before the bridge.
            hold_audio: Put the caller on hold instead: ``True`` for standard
                music, a file name, or an ``http(s)`` URL.
            transfer_summary: Context for the human; on ``sip_uri`` targets it
                also rides as an ``X-Transfer-Summary`` header.
            sip_headers: Extra ``X-`` headers for ``sip_uri`` targets.
            variables: Your own context, attached to the transfer leg's events
                and CDR.

        Returns:
            The queued transfer's ids.

        Raises:
            PiopiyAPIError: When the platform refuses, including
                ``transfer_in_progress`` when one is already ringing.
            ValueError: When zero or two destinations are given.
        """
        if bool(to_number) == bool(sip_uri):
            raise ValueError("warm_transfer needs exactly one of to_number or sip_uri")
        body: dict[str, Any] = {}
        if to_number:
            body["to_number"] = to_number
        if sip_uri:
            body["sip_uri"] = sip_uri
        for key, value in (
            ("caller_id", caller_id),
            ("timeout_sec", timeout_sec),
            ("confirm", confirm),
            ("hold_audio", hold_audio),
            ("transfer_summary", transfer_summary),
            ("sip_headers", sip_headers),
            ("variables", variables),
        ):
            if value is not None:
                body[key] = value
        data = await self._request("POST", f"/calls/{self.call.call_id}/actions/transfer", body)
        return TransferResult(request_id=data["request_id"], call_id=data.get("call_id", self.call.call_id))

    async def blind_transfer(
        self,
        pipeline: list[dict[str, Any]] | None = None,
        *,
        to_number: str | None = None,
        caller_id: str | None = None,
    ) -> TransferResult:
        """Hand the caller over immediately; the agent leaves the call.

        Give either a full PCMO ``pipeline`` or just ``to_number`` and the
        pipeline is built for you: one ``connect`` action to that number.

        Args:
            pipeline: A PCMO pipeline, same vocabulary as ``/voice/pcmo/call``.
            to_number: Phone number to connect the caller to.
            caller_id: DID to present when building the pipeline.

        Returns:
            The queued transfer's ids.

        Raises:
            PiopiyAPIError: When the platform refuses.
            ValueError: When neither a pipeline nor a number is given.
        """
        if pipeline is None:
            if not to_number:
                raise ValueError("blind_transfer needs a pipeline or a to_number")
            pipeline = build_connect_pipeline(to_number, caller_id=caller_id)
        data = await self._request(
            "POST", f"/calls/{self.call.call_id}/actions/transfer", {"pipeline": pipeline}
        )
        return TransferResult(request_id=data["request_id"], call_id=data.get("call_id", self.call.call_id))

    async def hangup(self, *, cause: str = "normal", reason: str | None = None) -> str:
        """End the call.

        Args:
            cause: Free text recorded with the hangup.
            reason: Free text recorded with the hangup.

        Returns:
            The request id of the hangup.
        """
        body: dict[str, Any] = {"cause": cause}
        if reason:
            body["reason"] = reason
        data = await self._request("POST", f"/calls/{self.call.call_id}/actions/hangup", body)
        return str(data.get("request_id", ""))

    # ---------- status ----------

    async def status(self) -> dict[str, Any]:
        """The call's live state, or raise ``PiopiyAPIError(404)`` once it has ended."""
        return await self._request("GET", f"/calls/{self.call.call_id}")

    async def transfer_status(self, request_id: str) -> TransferStatus:
        """Where a transfer stands. Kept for 15 minutes after it settles."""
        data = await self._request("GET", f"/transfers/{request_id}")
        return TransferStatus(
            request_id=data.get("request_id", request_id),
            call_id=data.get("call_id", self.call.call_id),
            status=data.get("status", "queued"),
            reason=data.get("reason"),
        )

    async def wait_for_transfer(
        self, request_id: str, *, poll_sec: float = 2.0, timeout_sec: float = 75.0
    ) -> TransferStatus:
        """Poll until a transfer settles.

        Prefer reacting to :class:`~pipecat_piopiy.frames.PiopiyTransferStatusFrame`
        in the pipeline; this is for code outside it. Returns the last status
        seen when ``timeout_sec`` passes, which may still be ``queued``.
        """
        deadline = time.monotonic() + timeout_sec
        last = await self.transfer_status(request_id)
        while not last.settled and time.monotonic() < deadline:
            await asyncio.sleep(poll_sec)
            last = await self.transfer_status(request_id)
        return last

    # ---------- plumbing ----------

    async def close(self) -> None:
        """Close the HTTP session this handle created. Idempotent."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
        self._session = None if self._owns_session else self._session

    async def __aenter__(self) -> PiopiyCallControl:  # noqa: PYI034 - Self needs 3.11
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        headers = {"authorization": f"Bearer {self._token}"}
        async with self._session.request(
            method, f"{self._api_url}{path}", json=body, headers=headers
        ) as response:
            try:
                data = await response.json(content_type=None)
            except ValueError:
                data = {"raw": await response.text()}
            if response.status >= 400:
                raise PiopiyAPIError(response.status, data)
            return data if isinstance(data, dict) else {"raw": data}


def build_connect_pipeline(to_number: str, *, caller_id: str | None = None) -> list[dict[str, Any]]:
    """A one-step PCMO pipeline that connects the caller to a phone number."""
    params: dict[str, Any] = {}
    if caller_id:
        params["caller_id"] = caller_id
    return [
        {
            "action": "connect",
            "params": params,
            "endpoints": [{"type": "pstn", "number": to_number}],
        }
    ]
