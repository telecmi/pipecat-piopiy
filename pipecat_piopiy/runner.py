"""Run a Pipecat bot for every call the Piopiy platform sends this worker."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from loguru import logger
from piopiy_agent import PiopiyWorker
from pipecat.transports.livekit.transport import LiveKitParams, LiveKitTransport

from .call import PiopiyCall

BotHandler = Callable[[LiveKitTransport, PiopiyCall], Awaitable[None]]
CallHook = Callable[[PiopiyCall], Awaitable[None]]


class PiopiyRunner:
    """Connects to Piopiy as an agent worker and runs your bot once per call.

    You write the pipeline; the runner does the telephony side::

        async def bot(transport, call):
            ...build the pipeline around transport.input()/output()...
            await PipelineRunner(handle_sigint=False).run(task)

        PiopiyRunner(max_sessions=10).run(bot)

    For each call the platform dispatches, the runner builds a
    :class:`LiveKitTransport` already pointed at the call's room, calls your
    ``bot`` with it and a :class:`PiopiyCall`, and accepts the call the moment
    the transport is connected - which is when the caller is bridged in. If the
    room join misses the platform's accept deadline the call has gone to
    another worker, and the bot is cancelled so two agents never share a call.

    Credentials come from arguments or the environment: ``PIOPIY_AGENT_ID``,
    ``PIOPIY_TOKEN``, and optionally ``PIOPIY_REGISTER`` and ``PIOPIY_TLS``.
    """

    def __init__(
        self,
        *,
        agent_id: str | None = None,
        token: str | None = None,
        register: str | None = None,
        max_sessions: int = 10,
        tls: bool | None = None,
        sample_rate: int = 16000,
        livekit_params: LiveKitParams | None = None,
        on_call_start: CallHook | None = None,
        on_call_end: CallHook | None = None,
    ):
        """Initialize the runner.

        Args:
            agent_id: The Piopiy agent this worker serves.
            token: The agent's worker token from the dashboard.
            register: ``host:port`` of the Piopiy register; defaults to the
                platform's public endpoint.
            max_sessions: Calls this process handles at once.
            tls: Use TLS to the register. On by default.
            sample_rate: Audio in/out rate for the transport, in Hz.
            livekit_params: Full transport params, overriding ``sample_rate``.
            on_call_start: Awaited with the call before the bot runs.
            on_call_end: Awaited with the call after the bot returns.
        """
        self._worker = PiopiyWorker(
            agent_id=agent_id,
            token=token,
            register=register,
            max_sessions=max_sessions,
            tls=tls,
            runtime="pipecat-piopiy/0.2.4",
        )
        self._sample_rate = sample_rate
        self._livekit_params = livekit_params
        self._on_call_start = on_call_start
        self._on_call_end = on_call_end

    @property
    def agent_id(self) -> str:
        """The agent this worker serves."""
        return self._worker.agent_id

    def run(self, bot: BotHandler) -> None:
        """Serve calls until interrupted. Blocks."""
        try:
            asyncio.run(self.serve(bot))
        except KeyboardInterrupt:
            logger.info("stopped")

    async def serve(self, bot: BotHandler) -> None:
        """Serve calls until the task is cancelled. Awaitable form of :meth:`run`."""

        @self._worker.on_job
        async def handle(job):
            await self._handle_job(job, bot)

        await self._worker.run()

    def _transport_params(self) -> LiveKitParams:
        if self._livekit_params is not None:
            return self._livekit_params
        return LiveKitParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=self._sample_rate,
            audio_out_sample_rate=self._sample_rate,
        )

    async def _handle_job(self, job, bot: BotHandler) -> None:
        call = PiopiyCall.from_job(job, agent_id=self.agent_id)
        logger.info(
            "call {} {} -> {} (room {})",
            call.direction,
            call.from_number,
            call.to_number,
            call.room_name,
        )

        transport = LiveKitTransport(
            url=job.livekit_url,
            token=job.access_token,
            room_name=job.room_name,
            params=self._transport_params(),
        )

        bot_task: asyncio.Task | None = None
        cancelled_by_us = False

        @transport.event_handler("on_connected")
        async def _on_connected(_transport):
            nonlocal cancelled_by_us
            # Accept only now: the platform bridges the caller on this message,
            # and accepting before we are in the room lands them in silence.
            if not await job.accept():
                cancelled_by_us = True
                logger.warning("joined {} after the accept deadline - leaving", call.room_name)
                if bot_task:
                    bot_task.cancel()

        @transport.event_handler("on_data_received")
        async def _on_data(_transport, data, participant_id):
            for listener in list(call._listeners):
                try:
                    await listener.on_room_data(data, participant_id)
                except Exception as err:  # noqa: BLE001 - a listener must not take the call down
                    logger.error("room message handler failed: {}", err)

        if self._on_call_start:
            await self._on_call_start(call)

        bot_task = asyncio.create_task(bot(transport, call), name=f"piopiy-call-{call.call_id}")
        try:
            await bot_task
        except asyncio.CancelledError:
            if not cancelled_by_us:
                raise
        finally:
            if self._on_call_end:
                with contextlib.suppress(Exception):
                    await self._on_call_end(call)
