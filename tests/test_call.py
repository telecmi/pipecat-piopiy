from types import SimpleNamespace

from pipecat_piopiy import PiopiyCall


def fake_job(**overrides):
    call = SimpleNamespace(
        call_uuid="8957d4a3-0000-0000-0000-000000000001",
        from_number="919894396168",
        to_number="911203134087",
        direction="inbound",
        sip_headers={},
        variables={},
    )
    for key, value in overrides.items():
        setattr(call, key, value)
    return SimpleNamespace(
        job_id="job-1",
        room_name="tcmi_org_x_uuid",
        livekit_url="ws://livekit.local:7880",
        access_token="tok",
        trace_id="trace-1",
        call=call,
    )


def test_from_job_maps_fields():
    call = PiopiyCall.from_job(fake_job(variables={"order_id": "A-1042"}), agent_id="agent-1")
    assert call.call_id == "8957d4a3-0000-0000-0000-000000000001"
    assert call.room_name == "tcmi_org_x_uuid"
    assert call.from_number == "919894396168"
    assert call.to_number == "911203134087"
    assert call.agent_id == "agent-1"
    assert call.variables == {"order_id": "A-1042"}
    assert call.is_inbound
    assert not call.is_sip_connect
    assert call.sip_account_id is None


def test_sip_connect_account_from_headers():
    job = fake_job(
        from_number="murugan",
        to_number="14ec3fc5-8e6c-4bc6-bdca-d52b0f24a201",
        sip_headers={"X-SIP-Account-ID": "c89625cd-3392-45c2-a4bb-1258f69924f1"},
    )
    call = PiopiyCall.from_job(job, agent_id="agent-1")
    assert call.is_sip_connect
    assert call.sip_account_id == "c89625cd-3392-45c2-a4bb-1258f69924f1"


def test_outbound_direction():
    call = PiopiyCall.from_job(fake_job(direction="outbound"), agent_id="a")
    assert not call.is_inbound
