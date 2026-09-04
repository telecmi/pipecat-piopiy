# pipecat-piopiy

Piopiy telephony for [Pipecat](https://github.com/pipecat-ai/pipecat) voice
agents. Your Pipecat bot takes real phone calls on the Piopiy platform by
TeleCMI: calls the Piopiy API places, calls arriving on your numbers, and
calls arriving from your PBX over SIP Connect. Mid-call it can transfer the
caller to a human, warm or blind, and hang up.

Piopiy bridges each call into a LiveKit room and hands your worker the room.
Media runs through Pipecat's own `LiveKitTransport`; this package supplies the
rest - taking the call, knowing who is calling, acting on the call, and hearing
about transfers.

**Tested with Pipecat v1.8.1.** Community-maintained by
[TeleCMI](https://telecmi.com); not part of the Pipecat core.

## Install

```bash
pip install pipecat-piopiy
# for the example, with Deepgram + OpenAI + Silero VAD:
pip install "pipecat-piopiy[example]"
```

Python 3.10+. Depends on `pipecat-ai[livekit]` and `piopiy-agent`, the
framework-agnostic Piopiy worker SDK.

## Use with a pipeline

```python
from pipecat_piopiy import PiopiyRunner, PiopiyCallControl, piopiy_tools
from pipecat_piopiy.processors import PiopiyEventsProcessor

async def bot(transport, call):
    control = PiopiyCallControl(call)
    tools = piopiy_tools(control, transfer_number="919876543210",
                         transfer_caller_id="911203134087")

    context = LLMContext(messages=[{"role": "system", "content": PROMPT}],
                         tools=tools.schemas)
    aggregators = LLMContextAggregatorPair(
        context, user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()))

    pipeline = Pipeline([
        transport.input(),
        PiopiyEventsProcessor(call),      # transfer progress -> frames + narration
        stt, aggregators.user(), llm, tts,
        transport.output(), aggregators.assistant(),
    ])
    task = PipelineTask(pipeline)

    @transport.event_handler("on_first_participant_joined")
    async def on_caller_joined(_t, participant_id):
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_participant_left")
    async def on_caller_left(_t, participant_id, reason):
        await task.cancel()

    await PipelineRunner(handle_sigint=False).run(task)

PiopiyRunner().run(bot)
```

`PiopiyRunner` connects to Piopiy as a worker for your agent, and for every
call builds a `LiveKitTransport` pointed at the call's room and calls `bot`.
It accepts the call when the transport connects, which is when the caller is
bridged in. Use `PipelineRunner(handle_sigint=False)`: the worker owns the
process signals.

## Run the example

```bash
cd examples/foundational
cp .env.example .env        # agent id, token, API base, transfer number, keys
python 01_piopiy_agent.py
```

Then call your agent: place a call with `POST /v3/voice/agent/call`, ring one of
your numbers mapped to the agent, or dial the agent id from a PBX registered
over SIP Connect. Ask for a person to see a warm transfer, ask for "the billing
line" to see a blind transfer, and say goodbye to see it hang up.

## Configuration

| variable | what |
|---|---|
| `PIOPIY_AGENT_ID` | the agent this worker serves, from the dashboard |
| `PIOPIY_TOKEN` | the Bearer token, the same one that creates calls |
| `PIOPIY_API_URL` | the platform's `/v3` base URL, as given in your account |
| `PIOPIY_REGISTER` | optional; `host:port` of the worker register |
| `PIOPIY_TLS` | optional; `false` to talk to the register without TLS (development) |
| `PIOPIY_MAX_SESSIONS` | calls one process handles at once |

## What the package gives you

**`PiopiyCall`** - who is calling whom: `call_id`, `direction`, `from_number`,
`to_number`, `agent_id`, `variables` from the create request, and
`sip_account_id` on SIP Connect calls so one agent can tell your PBXs apart.

**`PiopiyCallControl`** - actions on the live call over the Piopiy API:

```python
result  = await control.warm_transfer(to_number="9198...", transfer_summary="Refund on order A-1042")
result  = await control.warm_transfer(sip_uri="sip:desk@pbx.example.com", sip_headers={"X-Ticket": "A-1042"})
result  = await control.blind_transfer(to_number="9198...", caller_id="9112...")
await control.hangup(reason="resolved")
verdict = await control.wait_for_transfer(result.request_id)   # queued -> completed | failed
```

A warm transfer rings the human while the caller stays in conversation with
the agent; on answer the caller is handed over and the agent leaves; if nobody
answers the conversation simply continues. A blind transfer hands the caller
over at once. One transfer at a time per call: a second one is refused with
`PiopiyAPIError(409, "transfer_in_progress")` carrying the running transfer's
`request_id`.

**`piopiy_tools()`** - `transfer_call` and `end_call` as LLM function calls.
Each `FunctionSchema` carries its handler, so advertising `tools.schemas` on
the `LLMContext` is all the wiring. The destination is fixed in code by
default; pass `allow_model_destination=True` to let the model choose a
number, and `transfer_caller_id` for the DID to present, which SIP Connect
calls require.

**`PiopiyEventsProcessor`** - the platform pushes every transfer's progress
into the call's room. The processor turns each message into a
`PiopiyTransferStatusFrame` (`started`, `failed` with a reason, `completed`)
and, by default, speaks it: "I'm connecting you now" as the target rings, an
apology when it fails, plus a note into the LLM context so the model carries
on sensibly. Pass `narrate=False` to handle the frames yourself. `completed`
is best-effort: at that moment the agent is being removed from the call, and
`on_participant_left` fires.

## Notes

- Every action uses the call's customer leg, which `PiopiyCall.call_id` is.
- SIP Connect calls consume no phone number, so a transfer to a phone from one
  needs `transfer_caller_id` (a DID you own).
- Accept timing is handled for you: the runner accepts on `on_connected`, and
  if the join missed the platform's deadline it cancels the bot so two agents
  never share a call.
- Pipecat changes quickly. This release is tested against v1.8.1; the pinned
  range in `pyproject.toml` is `>=1.8,<2`.

## License

MIT. Copyright TeleCMI.
