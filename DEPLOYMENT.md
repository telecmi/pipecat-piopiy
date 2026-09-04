# Deployment — pipecat-piopiy

This package runs **on the customer's side**: it is the worker process that
answers their Piopiy calls with a Pipecat pipeline. Nothing here is deployed
on TeleCMI infrastructure. This file is for whoever operates that worker.

## Where it runs, and who talks to whom

```
worker (this package)  ──gRPC/TLS──▶  Piopiy register        :50051   (outbound only)
worker                 ──WebRTC────▶  LiveKit room per call            (outbound only)
worker                 ──HTTPS─────▶  Piopiy API  PIOPIY_API_URL /v3  (transfer, hangup, status)
worker                 ──HTTPS/WSS─▶  your STT / LLM / TTS providers
```

The worker opens every connection itself. It needs **no inbound port, no
public IP and no firewall rule**; it can run behind NAT, in a container, on a
laptop.

## Configure

| variable | provide | why |
|---|---|---|
| `PIOPIY_AGENT_ID` | the agent's id from the Piopiy dashboard | which agent this process serves; one process serves one agent |
| `PIOPIY_TOKEN` | the account's Bearer token | authenticates the worker to the register and the API |
| `PIOPIY_API_URL` | optional override | the REST base for transfer, hangup and status; default `https://rest.piopiy.com/v3` |
| `PIOPIY_MAX_SESSIONS` | calls per process, default 10 | capacity reported to the platform; size it to the box (each call runs STT, LLM and TTS streams) |
| `PIOPIY_REGISTER` | optional | default `register.piopiy.com` (host only, gRPC over TLS); `host:port` for a regional or private register |
| `PIOPIY_TLS` | optional, `false` only for a private register without TLS | never `false` against the public register |
| `PIOPIY_TRANSFER_NUMBER`, `PIOPIY_CALLER_ID` | example only | where `transfer_call` sends the caller, and the DID to present; SIP Connect calls require the caller id |
| provider keys | `DEEPGRAM_API_KEY`, `OPENAI_API_KEY`, ... | whatever the pipeline uses |

Put them in the environment or a `.env` next to the script.

## Deploy order

1. `pip install pipecat-piopiy` (plus your provider extras) in Python 3.10+.
2. Check credentials before anything else: `python -m piopiy_agent` prints
   `OK registered` or a precise failure. This separates "credentials wrong"
   from "agent code wrong", which otherwise look identical.
3. Run the worker: `python your_agent.py`. Watch for `registered as
   <instance>` in the log; from then on the platform can send it calls.
4. Place a test call to the agent. `403 ai_agent_not_running` from the call
   API means step 3 is not running or is serving a different agent id.

## Scaling and restarts

- Run more processes for more capacity; each registers as its own instance
  and the platform spreads calls across them by load.
- A fresh process reports as unproven until its first successful call and is
  sorted behind proven ones, so rolling restarts do not send calls to a
  process that cannot yet answer.
- On shutdown the platform's drain message stops new calls; in-flight calls
  finish. Send SIGTERM and wait rather than SIGKILL.
- The worker reconnects to the register on its own with backoff; a register
  deploy is a log line, not an outage.

## Verify after deploy

```bash
python -m piopiy_agent            # OK registered in <ms>
# then call the agent and check the log for:
#   call inbound <from> -> <to> (room tcmi_...)
#   joined room ... / registered
```

## Known limits

- One process serves one `PIOPIY_AGENT_ID`. Run separate processes for
  separate agents.
- `PIOPIY_API_URL` and `PIOPIY_REGISTER` only need setting for a regional or private deployment.
- Tested with Pipecat v1.8.1; the dependency range is `>=1.8,<2`.
