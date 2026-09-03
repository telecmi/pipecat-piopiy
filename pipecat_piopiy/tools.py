"""LLM function calls for acting on the live call: transfer it, end it."""

from __future__ import annotations

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams

from .control import PiopiyAPIError, PiopiyCallControl


class PiopiyTools:
    """``transfer_call`` and ``end_call`` as function calls the LLM can make.

    Build one per call with :func:`piopiy_tools` and advertise ``schemas`` on
    the LLM context::

        tools = piopiy_tools(control, transfer_number="919876543210",
                             transfer_caller_id="911203134087")
        context = LLMContext(messages=[...], tools=tools.schemas)

    Each schema carries its handler, so Pipecat registers them automatically;
    no ``register_function`` call is needed.

    ``transfer_call`` starts a **warm** transfer by default: the caller stays in
    conversation with the agent while the human's phone rings, and if nobody
    answers the agent simply carries on (the events processor narrates that).
    ``mode="blind"`` hands the caller straight to the destination and removes
    the agent immediately.

    ``end_call`` hangs up. Tell the model to say goodbye *before* calling it.
    """

    def __init__(
        self,
        control: PiopiyCallControl,
        *,
        transfer_number: str | None = None,
        transfer_sip_uri: str | None = None,
        transfer_caller_id: str | None = None,
        allow_model_destination: bool = False,
        confirm: bool | None = None,
        timeout_sec: int | None = None,
    ):
        """Initialize the tools.

        Args:
            control: The call's control handle.
            transfer_number: The phone number a transfer goes to when the model
                does not name one. Usually your human desk.
            transfer_sip_uri: A SIP destination instead of a number.
            transfer_caller_id: The DID to present on the transfer leg. Required
                on SIP Connect calls, which have no dialled number to reuse.
            allow_model_destination: Let the model pass its own ``to_number`` or
                ``sip_uri``. Off by default so a caller cannot talk the agent into
                dialling an arbitrary number.
            confirm: Require the human to press 1 before the bridge, so a
                voicemail greeting can never accept a transfer.
            timeout_sec: How long the human's phone rings.
        """
        self._control = control
        self._number = transfer_number
        self._sip_uri = transfer_sip_uri
        self._caller_id = transfer_caller_id
        self._allow_model_destination = allow_model_destination
        self._confirm = confirm
        self._timeout_sec = timeout_sec

        properties = {
            "mode": {
                "type": "string",
                "enum": ["warm", "blind"],
                "description": (
                    "warm: stay with the caller while the human's phone rings and keep "
                    "them if nobody answers (default). blind: hand the caller over "
                    "immediately and leave the call."
                ),
            },
            "summary": {
                "type": "string",
                "description": (
                    "One or two sentences for the human who picks up: who is calling "
                    "and what they need."
                ),
            },
        }
        if allow_model_destination:
            properties["to_number"] = {
                "type": "string",
                "description": "Phone number to transfer to, digits only with country code.",
            }
            properties["sip_uri"] = {
                "type": "string",
                "description": "SIP address to transfer to, e.g. sip:desk@pbx.example.com.",
            }

        self.transfer_schema = FunctionSchema(
            name="transfer_call",
            description=(
                "Transfer the caller to a human. Use it when the caller asks for a "
                "person, or when you cannot help. Say you are connecting them first."
            ),
            properties=properties,
            required=[],
            handler=self.transfer_call,
        )
        self.end_call_schema = FunctionSchema(
            name="end_call",
            description=(
                "Hang up the call. Use it only after saying goodbye, when the "
                "conversation is finished."
            ),
            properties={
                "reason": {
                    "type": "string",
                    "description": "A few words on why the call ended, for the call record.",
                }
            },
            required=[],
            handler=self.end_call,
        )

    @property
    def schemas(self) -> ToolsSchema:
        """Both tools, ready for ``LLMContext(tools=...)``."""
        return ToolsSchema(standard_tools=self.function_schemas)

    @property
    def function_schemas(self) -> list[FunctionSchema]:
        """The individual schemas, to merge with your own tools."""
        return [self.transfer_schema, self.end_call_schema]

    async def transfer_call(self, params: FunctionCallParams) -> None:
        """Handle a ``transfer_call`` function call."""
        args = params.arguments or {}
        mode = str(args.get("mode") or "warm").lower()
        summary = args.get("summary")

        to_number = self._number
        sip_uri = self._sip_uri
        if self._allow_model_destination:
            to_number = args.get("to_number") or to_number
            sip_uri = args.get("sip_uri") or sip_uri

        if not to_number and not sip_uri:
            await params.result_callback(
                {"status": "error", "detail": "no transfer destination is configured"}
            )
            return

        try:
            if mode == "blind":
                result = await self._control.blind_transfer(
                    to_number=to_number, caller_id=self._caller_id
                )
                await params.result_callback(
                    {
                        "status": "transferred",
                        "request_id": result.request_id,
                        "detail": "the caller has been handed over; you are leaving the call",
                    }
                )
                return

            result = await self._control.warm_transfer(
                to_number=to_number,
                sip_uri=sip_uri,
                caller_id=self._caller_id,
                transfer_summary=summary,
                confirm=self._confirm,
                timeout_sec=self._timeout_sec,
            )
            await params.result_callback(
                {
                    "status": "ringing",
                    "request_id": result.request_id,
                    "detail": (
                        "the human's phone is ringing; stay with the caller. You will be "
                        "told if nobody answers."
                    ),
                }
            )
        except PiopiyAPIError as err:
            logger.warning("transfer_call failed: {} {}", err.status, err.error)
            if err.error == "transfer_in_progress":
                detail = "a transfer is already in progress; wait for its outcome"
            elif err.error == "CALL_NOT_FOUND":
                detail = "the call is no longer live"
            else:
                detail = f"the platform refused the transfer ({err.error})"
            await params.result_callback({"status": "error", "detail": detail})

    async def end_call(self, params: FunctionCallParams) -> None:
        """Handle an ``end_call`` function call."""
        reason = (params.arguments or {}).get("reason") or "agent_ended"
        try:
            await self._control.hangup(reason=str(reason)[:120])
            await params.result_callback({"status": "ended"})
        except PiopiyAPIError as err:
            logger.warning("end_call failed: {} {}", err.status, err.error)
            await params.result_callback({"status": "error", "detail": err.error})


def piopiy_tools(control: PiopiyCallControl, **kwargs) -> PiopiyTools:
    """Create the call tools for one call. See :class:`PiopiyTools` for arguments."""
    return PiopiyTools(control, **kwargs)
