"""Piopiy (TeleCMI) telephony for Pipecat voice agents.

    from pipecat_piopiy import PiopiyRunner, PiopiyCallControl, piopiy_tools
    from pipecat_piopiy.processors import PiopiyEventsProcessor

    async def bot(transport, call):
        control = PiopiyCallControl(call)
        tools = piopiy_tools(control, transfer_number="919876543210")
        ...

    PiopiyRunner().run(bot)
"""

from .call import PiopiyCall
from .control import (
    TRANSFER_FAILURE_REASONS,
    PiopiyAPIError,
    PiopiyCallControl,
    TransferResult,
    TransferStatus,
    build_connect_pipeline,
)
from .frames import PiopiyTransferStatusFrame
from .processors import PiopiyEventsProcessor
from .runner import PiopiyRunner
from .tools import PiopiyTools, piopiy_tools

__version__ = "0.2.1"

__all__ = [
    "TRANSFER_FAILURE_REASONS",
    "PiopiyAPIError",
    "PiopiyCall",
    "PiopiyCallControl",
    "PiopiyEventsProcessor",
    "PiopiyRunner",
    "PiopiyTools",
    "PiopiyTransferStatusFrame",
    "TransferResult",
    "TransferStatus",
    "__version__",
    "build_connect_pipeline",
    "piopiy_tools",
]
