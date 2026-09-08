# Changelog

## 0.2.4 - 2026-09-08

- New example `02_piopiy_gemini_live.py`: the same agent (warm transfer, blind transfer, hangup) on Gemini Live, a speech-to-speech model with no STT or TTS stage. Install with `pipecat-piopiy[example-gemini]`.
- `PiopiyEventsProcessor(narration="llm")`: for pipelines without a TTS stage, transfer progress is spoken by the model itself instead of through a `TTSSpeakFrame`. Default `"tts"` is unchanged.

## 0.2.3 - 2026-09-04

- Metadata: `requires-python >= 3.11`, matching Pipecat 1.x. On 3.10 pip now says so instead of failing to resolve `pipecat-ai`.

## 0.2.2 - 2026-09-04

- Documentation only: platform wording throughout (numbers, calls, transfers; no telephony internals). No code changes since 0.2.1.

## 0.2.1 - 2026-09-04

- Production defaults from piopiy-agent 1.2: REST `https://rest.piopiy.com/v3`, register `register.piopiy.com`. `PIOPIY_API_URL` is optional now.

## 0.2.0 - 2026-09-03

- `PiopiyCallControl` and friends now live in `piopiy-agent` (>= 1.1.0) and are
  shared with `livekit-piopiy`; imports from `pipecat_piopiy` are unchanged.

## 0.1.0 - 2026-09-03

First release. Tested with Pipecat v1.8.1.

- `PiopiyRunner`: runs the Piopiy worker and hands each call to your `bot(transport, call)` with a ready `LiveKitTransport`.
- `PiopiyCall`: who is calling whom, plus `variables` and `sip_account_id`.
- `PiopiyCallControl`: warm transfer, blind transfer, hangup, transfer status, call status over the Piopiy `/v3` API.
- `PiopiyEventsProcessor`: turns the platform's `transfer_status` room messages into `PiopiyTransferStatusFrame`s and, optionally, spoken narration.
- `piopiy_tools()`: `transfer_call` and `end_call` as LLM function calls.
