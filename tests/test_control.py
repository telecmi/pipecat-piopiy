import pytest
from aiohttp import web

from pipecat_piopiy import PiopiyAPIError, PiopiyCall, PiopiyCallControl, build_connect_pipeline


def make_call():
    return PiopiyCall(
        call_id="call-1", room_name="room", direction="inbound",
        from_number="9198", to_number="9112", agent_id="agent",
    )


@pytest.fixture
async def api():
    """A stand-in for the Piopiy /v3 API that records what it received."""
    received = []

    async def transfer(request):
        body = await request.json()
        received.append(("transfer", request.headers.get("authorization"), body))
        if body.get("to_number") == "busy":
            return web.json_response({"error": "transfer_in_progress", "request_id": "req-running"}, status=409)
        return web.json_response({"message": "queued", "call_id": "call-1", "request_id": "req-1"})

    async def hangup(request):
        received.append(("hangup", request.headers.get("authorization"), await request.json()))
        return web.json_response({"message": "queued", "call_id": "call-1", "request_id": "req-h"})

    async def transfer_status(request):
        return web.json_response({"request_id": request.match_info["rid"], "call_id": "call-1",
                                  "status": "failed", "reason": "no_answer"})

    app = web.Application()
    app.router.add_post("/v3/calls/{cid}/actions/transfer", transfer)
    app.router.add_post("/v3/calls/{cid}/actions/hangup", hangup)
    app.router.add_get("/v3/transfers/{rid}", transfer_status)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}/v3", received
    await runner.cleanup()


@pytest.mark.asyncio
async def test_warm_transfer_body_and_auth(api):
    url, received = api
    async with PiopiyCallControl(make_call(), token="T", api_url=url) as control:
        result = await control.warm_transfer(to_number="9198", transfer_summary="refund", confirm=True)
    assert result.request_id == "req-1"
    kind, auth, body = received[0]
    assert kind == "transfer" and auth == "Bearer T"
    assert body == {"to_number": "9198", "transfer_summary": "refund", "confirm": True}


@pytest.mark.asyncio
async def test_blind_transfer_builds_pipeline(api):
    url, received = api
    async with PiopiyCallControl(make_call(), token="T", api_url=url) as control:
        await control.blind_transfer(to_number="9198", caller_id="9112")
    body = received[0][2]
    assert body == {"pipeline": build_connect_pipeline("9198", caller_id="9112")}
    assert body["pipeline"][0]["endpoints"] == [{"type": "pstn", "number": "9198"}]


@pytest.mark.asyncio
async def test_hangup_and_status(api):
    url, received = api
    async with PiopiyCallControl(make_call(), token="T", api_url=url) as control:
        assert await control.hangup(reason="done") == "req-h"
        verdict = await control.transfer_status("req-1")
    assert received[0][2] == {"cause": "normal", "reason": "done"}
    assert verdict.settled and verdict.status == "failed" and verdict.reason == "no_answer"


@pytest.mark.asyncio
async def test_transfer_in_progress_error(api):
    url, _ = api
    async with PiopiyCallControl(make_call(), token="T", api_url=url) as control:
        with pytest.raises(PiopiyAPIError) as info:
            await control.warm_transfer(to_number="busy")
    assert info.value.status == 409
    assert info.value.error == "transfer_in_progress"
    assert info.value.request_id == "req-running"


def test_requires_exactly_one_destination():
    control = PiopiyCallControl(make_call(), token="T", api_url="http://x/v3")
    import asyncio
    with pytest.raises(ValueError):
        asyncio.run(control.warm_transfer())
    with pytest.raises(ValueError):
        asyncio.run(control.warm_transfer(to_number="1", sip_uri="sip:a@b"))


def test_missing_config_is_explicit(monkeypatch):
    monkeypatch.delenv("PIOPIY_TOKEN", raising=False)
    monkeypatch.delenv("TELECMI_TOKEN", raising=False)
    monkeypatch.delenv("PIOPIY_API_URL", raising=False)
    with pytest.raises(ValueError):
        PiopiyCallControl(make_call())
    with pytest.raises(ValueError):
        PiopiyCallControl(make_call(), token="T")
