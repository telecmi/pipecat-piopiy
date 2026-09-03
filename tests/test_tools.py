from types import SimpleNamespace

import pytest

from pipecat_piopiy import PiopiyAPIError, TransferResult, piopiy_tools


class FakeControl:
    def __init__(self, fail_with=None):
        self.calls = []
        self.fail_with = fail_with

    async def warm_transfer(self, **kwargs):
        self.calls.append(("warm", kwargs))
        if self.fail_with:
            raise self.fail_with
        return TransferResult(request_id="req-w", call_id="call-1")

    async def blind_transfer(self, **kwargs):
        self.calls.append(("blind", kwargs))
        return TransferResult(request_id="req-b", call_id="call-1")

    async def hangup(self, **kwargs):
        self.calls.append(("hangup", kwargs))
        return "req-h"


def params(**arguments):
    results = []

    async def result_callback(result, **_):
        results.append(result)

    return SimpleNamespace(arguments=arguments, result_callback=result_callback), results


def test_schemas_carry_handlers():
    tools = piopiy_tools(FakeControl(), transfer_number="9198")
    names = [s.name for s in tools.function_schemas]
    assert names == ["transfer_call", "end_call"]
    assert all(s.handler is not None for s in tools.function_schemas)
    assert "to_number" not in tools.transfer_schema.properties  # model cannot pick a number by default


@pytest.mark.asyncio
async def test_warm_transfer_default():
    control = FakeControl()
    tools = piopiy_tools(control, transfer_number="9198", transfer_caller_id="9112")
    p, results = params(summary="wants a refund")
    await tools.transfer_call(p)
    kind, kwargs = control.calls[0]
    assert kind == "warm"
    assert kwargs["to_number"] == "9198" and kwargs["caller_id"] == "9112"
    assert kwargs["transfer_summary"] == "wants a refund"
    assert results[0]["status"] == "ringing" and results[0]["request_id"] == "req-w"


@pytest.mark.asyncio
async def test_blind_transfer_mode():
    control = FakeControl()
    tools = piopiy_tools(control, transfer_number="9198", transfer_caller_id="9112")
    p, results = params(mode="blind")
    await tools.transfer_call(p)
    assert control.calls[0] == ("blind", {"to_number": "9198", "caller_id": "9112"})
    assert results[0]["status"] == "transferred"


@pytest.mark.asyncio
async def test_transfer_in_progress_is_reported_not_raised():
    control = FakeControl(fail_with=PiopiyAPIError(409, {"error": "transfer_in_progress", "request_id": "r"}))
    tools = piopiy_tools(control, transfer_number="9198")
    p, results = params()
    await tools.transfer_call(p)
    assert results[0]["status"] == "error" and "already in progress" in results[0]["detail"]


@pytest.mark.asyncio
async def test_no_destination_configured():
    tools = piopiy_tools(FakeControl())
    p, results = params()
    await tools.transfer_call(p)
    assert results[0]["status"] == "error"


@pytest.mark.asyncio
async def test_end_call():
    control = FakeControl()
    tools = piopiy_tools(control, transfer_number="9198")
    p, results = params(reason="resolved")
    await tools.end_call(p)
    assert control.calls[0] == ("hangup", {"reason": "resolved"})
    assert results[0] == {"status": "ended"}
