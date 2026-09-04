"""The foundational example must at least import against the pinned Pipecat.

Compile-only checks missed a Deepgram SDK API change once; this catches the
next one. Skipped when the example's provider extras are not installed.
"""

import importlib.util
import pathlib

import pytest

EXAMPLE = pathlib.Path(__file__).resolve().parents[1] / "examples" / "foundational" / "01_piopiy_agent.py"


def test_example_imports(monkeypatch):
    pytest.importorskip("pipecat.services.deepgram.stt")
    pytest.importorskip("pipecat.services.openai.llm")
    pytest.importorskip("pipecat.audio.vad.silero")
    monkeypatch.setenv("PIOPIY_AGENT_ID", "agent")
    monkeypatch.setenv("PIOPIY_TOKEN", "token")
    spec = importlib.util.spec_from_file_location("piopiy_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.bot)
