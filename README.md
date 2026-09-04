# pipecat-piopiy

Give your [Pipecat](https://github.com/pipecat-ai/pipecat) agent a phone.

[Piopiy](https://piopiy.com) is a communication platform: we provide the
phone numbers, carry the calls, and host all the voice infrastructure. You
build the agent with Pipecat and run it wherever you like; this package
connects the two. Your agent answers calls to your Piopiy numbers, places
calls through the Piopiy API, and mid-call it can hand the caller to a human
or end the call. Nothing telephony-related to host or configure on your side.

**Tested with Pipecat v1.8.1.** Community-maintained by
[TeleCMI](https://telecmi.com); not part of the Pipecat core.

## Install

```bash
pip install pipecat-piopiy
# for the example, with Deepgram + OpenAI + Silero VAD:
pip install "pipecat-piopiy[example]"
```

Python 3.11+ (what Pipecat 1.x requires).

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

`PiopiyRunner` registers your process with Piopiy as the worker for your
agent. For every call, Piopiy hands it the call; the runner builds a
transport already connected to that call's audio and calls `bot`. The
caller is joined the moment the transport is connected. Use
`PipelineRunner(handle_sigint=False)`: the runner owns the process signals.

## Run the example

```bash
cd examples/foundational
cp .env.example .env        # your agent id and token, the transfer number, your keys
python 01_piopiy_agent.py
```

Then call your agent: ring one of your Piopiy numbers, or place a call with
`POST /v3/voice/agent/call`. Ask for a person to see a warm transfer, ask
for "the billing line" to see a blind transfer, and say goodbye to see it
hang up.

## Configuration

Two values, both from your Piopiy dashboard:

| variable | what |
|---|---|
| `PIOPIY_AGENT_ID` | the agent this process serves |
| `PIOPIY_TOKEN` | your API token |

Optional: `PIOPIY_MAX_SESSIONS` (calls one process handles at once, default
10). `PIOPIY_API_URL` and `PIOPIY_REGISTER` exist only for regional or
private deployments; the public platform needs neither.

## What the package gives you

**`PiopiyCall`** - the call in hand: `call_id`, `direction`, `from_number`,
`to_number`, `agent_id`, the `variables` you attached when placing the call,
and `sip_account_id` when the call came from a phone system you connected
to Piopiy, so one agent can tell your sites apart.

**`PiopiyCallControl`** - act on the call:

```python
result  = await control.warm_transfer(to_number="9198...", transfer_summary="Refund on order A-1042")
result  = await control.blind_transfer(to_number="9198...", caller_id="9112...")
await control.hangup(reason="resolved")
verdict = await control.wait_for_transfer(result.request_id)   # queued -> completed | failed
```

A **warm transfer** rings the human while the caller stays in conversation
with the agent; when the human answers the caller is handed over and the
agent leaves; if nobody answers the conversation simply continues. A
**blind transfer** hands the caller over at once. One transfer at a time per
call: a second one is refused with `PiopiyAPIError(409,
"transfer_in_progress")`.

**`piopiy_tools()`** - `transfer_call` and `end_call` as LLM function calls.
Each `FunctionSchema` carries its handler, so advertising `tools.schemas` on
the `LLMContext` is all the wiring. The destination is fixed in your code by
default so a caller cannot talk the agent into dialling anywhere else; pass
`allow_model_destination=True` to let the model choose. `transfer_caller_id`
is the number shown to the human being called; use one of your Piopiy
numbers.

**`PiopiyEventsProcessor`** - Piopiy tells the agent how a transfer is going.
The processor turns each update into a `PiopiyTransferStatusFrame`
(`started`, `failed` with a reason, `completed`) and, by default, speaks it:
"I'm connecting you now" as the human's phone rings, an apology if nobody
answers, plus a note into the LLM context so the model carries on sensibly.
Pass `narrate=False` to handle the frames yourself.

## Notes

- Every action uses `PiopiyCall.call_id`; the runner gives you the right one.
- Accept timing is handled for you: if your process was too slow to join a
  call, the bot is cancelled so two agents never share one call.
- Pipecat changes quickly. This release is tested against v1.8.1; the pinned
  range in `pyproject.toml` is `>=1.8,<2`.

## License

MIT. Copyright TeleCMI.
