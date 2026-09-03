# Changelog

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
