# Deployment — pipecat-piopiy

This package runs **on your side**: it is the process that answers your
Piopiy calls with a Pipecat pipeline. Piopiy hosts everything else, the numbers,
the calls and the voice infrastructure. This page is for whoever operates
that process.

## Where it runs, and what it talks to

The process opens every connection itself, all outbound:

- to Piopiy, to receive calls and act on them
- to the voice room Piopiy provides for each call
- to your own speech, language and voice providers

It needs **no inbound port, no public IP and no firewall rule**; it can run
behind NAT, in a container, on a laptop.

## Configure

| variable | provide | why |
|---|---|---|
| `PIOPIY_AGENT_ID` | the agent's id from the Piopiy dashboard | which agent this process serves; one process serves one agent |
| `PIOPIY_TOKEN` | your API token | authenticates the process to Piopiy |
| `PIOPIY_MAX_SESSIONS` | calls per process, default 10 | capacity reported to Piopiy; size it to the machine (each call runs speech, language and voice streams) |
| `PIOPIY_TRANSFER_NUMBER`, `PIOPIY_CALLER_ID` | example only | where `transfer_call` sends the caller, and which of your Piopiy numbers the human sees |
| provider keys | `DEEPGRAM_API_KEY`, `OPENAI_API_KEY`, ... | whatever the agent uses |
| `PIOPIY_API_URL`, `PIOPIY_REGISTER` | leave unset | only for a regional or private Piopiy deployment |

Put them in the environment or a `.env` next to the script.

## Deploy order

1. `pip install pipecat-piopiy` (plus your provider extras) in Python 3.10+.
2. Check the credentials before anything else: `python -m piopiy_agent`
   prints `OK registered` or a precise failure. This separates "credentials
   wrong" from "agent code wrong", which otherwise look identical.
3. Run the process: `python your_agent.py`. Watch for `registered as
   <instance>` in the log; from then on Piopiy can send it calls.
4. Call the agent. `403 ai_agent_not_running` from the call API means step 3
   is not running or is serving a different agent id.

## Scaling and restarts

- Run more processes for more capacity; each registers as its own instance
  and Piopiy spreads calls across them by load.
- A fresh process is offered calls only after the ones already proven, so
  rolling restarts do not send calls to a process that cannot yet answer.
- On shutdown Piopiy stops sending new calls; calls in progress finish. Send
  SIGTERM and wait rather than SIGKILL.
- The process reconnects to Piopiy on its own with backoff.

## Verify after deploy

```bash
python -m piopiy_agent            # OK registered in <ms>
# then call the agent and check the log for:
#   call inbound <from> -> <to> (room tcmi_...)
```

## Known limits

- One process serves one `PIOPIY_AGENT_ID`. Run separate processes for
  separate agents.
- Tested with Pipecat v1.8.1; the dependency range is `>=1.8,<2`.
