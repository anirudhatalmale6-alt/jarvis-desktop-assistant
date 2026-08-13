"""
Tests for the conversation loop, run without touching the network.

A fake Anthropic client stands in for the real one so the whole tool-calling
path -- including the two-round trip where Claude calls a tool and then answers
using the result -- can be exercised offline and deterministically.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.brain import Brain, split_speakable  # noqa: E402
from jarvis.config import Config  # noqa: E402

PASS, FAIL = [], []


def check(name: str, got, want) -> None:
    if got == want:
        PASS.append(name)
    else:
        FAIL.append(f"{name}\n      got:  {got!r}\n      want: {want!r}")


# -- sentence splitting ------------------------------------------------
# Note the trailing whitespace after a sentence is consumed by the match, so
# the leftover never starts with a space.

def test_splitter() -> None:
    cases = [
        ("Hello there. How are", ["Hello there."], "How are"),
        ("Dr. Smith called. He wants", ["Dr. Smith called."], "He wants"),
        ("Version 3.1 is out! Try it", ["Version 3.1 is out!"], "Try it"),
        ("no ending yet", [], "no ending yet"),
        ("One. Two. Three. ", ["One.", "Two.", "Three."], ""),
        ("Is that right? Yes", ["Is that right?"], "Yes"),
        ('He said "go." Then left', ['He said "go."'], "Then left"),
        ("", [], ""),
        ("e.g. this one. Done", ["e.g. this one."], "Done"),
    ]
    for src, want_sentences, want_rest in cases:
        got_s, got_rest = split_speakable(src)
        check(f"split {src!r}", (got_s, got_rest), (want_sentences, want_rest))


# -- fake API ----------------------------------------------------------


class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FakeStream:
    def __init__(self, script):
        self._script = script

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        for chunk in self._script.get("text", []):
            yield types.SimpleNamespace(
                type="content_block_delta",
                delta=types.SimpleNamespace(type="text_delta", text=chunk),
            )

    def get_final_message(self):
        content = []
        if self._script.get("text"):
            content.append(_Block(type="text", text="".join(self._script["text"])))
        for call in self._script.get("tool_calls", []):
            content.append(
                _Block(type="tool_use", id=call["id"], name=call["name"], input=call["input"])
            )
        return types.SimpleNamespace(
            content=content,
            stop_reason="tool_use" if self._script.get("tool_calls") else "end_turn",
        )


class FakeClient:
    """Replays a list of scripted responses and records what it was sent."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = types.SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeStream(self.script.pop(0) if self.script else {"text": ["(done)"]})


def _cfg(tmp: Path) -> Config:
    cfg = Config(anthropic_api_key="test-key")
    cfg.workspace = tmp
    return cfg


# -- loop behaviour ----------------------------------------------------


def test_plain_reply(tmp: Path) -> None:
    client = FakeClient([{"text": ["It is ", "half past four. "]}])
    spoken: list[str] = []
    brain = Brain(_cfg(tmp), speak=spoken.append, client=client)
    turn = brain.ask("what time is it")

    check("plain: spoken sentences", spoken, ["It is half past four."])
    check("plain: no tools", turn.tools_used, [])
    check("plain: stop reason", turn.stopped_because, "end_turn")
    check("plain: history length", len(brain.messages), 2)


def test_tool_round_trip(tmp: Path) -> None:
    client = FakeClient([
        {"text": ["Checking. "], "tool_calls": [
            {"id": "t1", "name": "get_datetime", "input": {}}]},
        {"text": ["It is Tuesday."]},
    ])
    spoken: list[str] = []
    brain = Brain(_cfg(tmp), speak=spoken.append, client=client)
    turn = brain.ask("what day is it")

    check("tool: was called", turn.tools_used, ["get_datetime"])
    check("tool: final text spoken", spoken[-1], "It is Tuesday.")
    # user, assistant(tool_use), user(tool_result), assistant(text)
    check("tool: history length", len(brain.messages), 4)
    result_msg = brain.messages[2]
    check("tool: result role", result_msg["role"], "user")
    check("tool: result type", result_msg["content"][0]["type"], "tool_result")
    check("tool: result id matches", result_msg["content"][0]["tool_use_id"], "t1")
    check("tool: not an error", result_msg["content"][0]["is_error"], False)


def test_unknown_tool_is_reported_not_crashed(tmp: Path) -> None:
    client = FakeClient([
        {"tool_calls": [{"id": "t1", "name": "launch_missiles", "input": {}}]},
        {"text": ["I cannot do that."]},
    ])
    brain = Brain(_cfg(tmp), client=client)
    brain.ask("do something impossible")
    block = brain.messages[2]["content"][0]
    check("unknown tool: flagged as error", block["is_error"], True)
    check("unknown tool: message", "no tool called" in block["content"], True)


def test_declined_confirmation(tmp: Path) -> None:
    client = FakeClient([
        {"tool_calls": [{"id": "t1", "name": "write_note",
                         "input": {"filename": "x.txt", "content": "hello"}}]},
        {"text": ["Alright, left it alone."]},
    ])
    brain = Brain(_cfg(tmp), client=client, confirm=lambda q: False)
    brain.ask("save a note")
    block = brain.messages[2]["content"][0]
    check("declined: told Claude", "declined" in block["content"], True)
    check("declined: file not written", (tmp / "x.txt").exists(), False)


def test_accepted_confirmation(tmp: Path) -> None:
    client = FakeClient([
        {"tool_calls": [{"id": "t1", "name": "write_note",
                         "input": {"filename": "note.txt", "content": "buy milk"}}]},
        {"text": ["Saved."]},
    ])
    asked: list[str] = []

    def yes(question: str) -> bool:
        asked.append(question)
        return True

    brain = Brain(_cfg(tmp), client=client, confirm=yes)
    brain.ask("save a note")
    check("accepted: was asked", asked, ["Save that to note.txt?"])
    check("accepted: file written", (tmp / "note.txt").read_text(), "buy milk")


def test_tool_exception_becomes_error_result(tmp: Path) -> None:
    client = FakeClient([
        {"tool_calls": [{"id": "t1", "name": "read_file",
                         "input": {"path": "../../../etc/passwd"}}]},
        {"text": ["I could not read that."]},
    ])
    brain = Brain(_cfg(tmp), client=client)
    brain.ask("read the password file")
    block = brain.messages[2]["content"][0]
    check("escape attempt: flagged as error", block["is_error"], True)
    check("escape attempt: named", "OutsideWorkspace" in block["content"], True)


def test_request_shape(tmp: Path) -> None:
    """The settings that keep this usable as a voice assistant."""
    client = FakeClient([{"text": ["Hi."]}])
    brain = Brain(_cfg(tmp), client=client)
    brain.ask("hello")
    sent = client.calls[0]
    check("request: model", sent["model"], "claude-opus-5")
    check("request: thinking on", sent["thinking"], {"type": "adaptive"})
    check("request: low effort", sent["output_config"], {"effort": "low"})
    check("request: tools present", len(sent["tools"]) > 0, True)
    check("request: no markdown instruction", "markdown" in sent["system"], True)


def test_history_trim_keeps_valid_start(tmp: Path) -> None:
    """
    Trimming must never leave the history starting on an assistant turn or on
    an orphaned tool_result -- the API rejects both.
    """
    brain = Brain(_cfg(tmp), client=FakeClient([]))
    for i in range(30):
        brain.messages.append({"role": "user", "content": f"q{i}"})
        brain.messages.append({"role": "assistant", "content": f"a{i}"})
    brain.messages.append({"role": "user", "content": [{"type": "tool_result",
                                                        "tool_use_id": "x", "content": "y"}]})
    brain._trim()
    first = brain.messages[0]
    check("trim: starts on user", first["role"], "user")
    check("trim: not an orphan tool_result", isinstance(first["content"], str), True)
    check("trim: bounded", len(brain.messages) <= 41, True)


def main() -> int:
    import tempfile

    test_splitter()
    for fn in (
        test_plain_reply,
        test_tool_round_trip,
        test_unknown_tool_is_reported_not_crashed,
        test_declined_confirmation,
        test_accepted_confirmation,
        test_tool_exception_becomes_error_result,
        test_request_shape,
        test_history_trim_keeps_valid_start,
    ):
        with tempfile.TemporaryDirectory() as td:
            fn(Path(td))

    for line in FAIL:
        print(f"  FAIL  {line}")
    print(f"\n  brain: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
