"""The foundational examples must at least import against the pinned Pipecat.

Compile-only checks missed a Deepgram SDK API change once; this catches the
next one. Each example is skipped when its provider extras are not installed.
"""

import importlib.util
import pathlib

import pytest

EXAMPLES = pathlib.Path(__file__).resolve().parents[1] / "examples" / "foundational"

CASES = [
    ("01_piopiy_agent.py", ["pipecat.services.deepgram.stt", "pipecat.services.openai.llm", "pipecat.audio.vad.silero"]),
    ("02_piopiy_gemini_live.py", ["pipecat.services.google.gemini_live.llm"]),
]


@pytest.mark.parametrize("filename,required", CASES, ids=[c[0] for c in CASES])
def test_example_imports(monkeypatch, filename, required):
    for module in required:
        pytest.importorskip(module)
    monkeypatch.setenv("PIOPIY_AGENT_ID", "agent")
    monkeypatch.setenv("PIOPIY_TOKEN", "token")
    spec = importlib.util.spec_from_file_location("piopiy_example_" + filename[:2], EXAMPLES / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.bot)
