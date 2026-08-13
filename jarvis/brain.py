"""
The conversation loop.

Takes a line of transcribed speech, talks to Claude, runs whatever tools Claude
asks for, and streams the reply back out a sentence at a time so the assistant
starts speaking while it is still thinking about the rest.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Iterable

import anthropic

from .config import Config
from .tools import registry

# Claude is told to keep replies short because they are spoken aloud, not read.
# A paragraph that looks reasonable on screen is a long time to sit listening.
SYSTEM = """You are a voice assistant running on the user's own Windows PC. \
You are speaking out loud, so write the way a person talks.

Keep replies short. One or two sentences for anything routine. The user can \
always ask for more. Never read out a list of ten things unless asked -- \
summarise it and offer the detail.

Never use markdown, bullet points, asterisks, or emoji: every character you \
write is going to be read aloud by a speech engine, and punctuation salad \
sounds like nonsense. Write numbers and dates the way you would say them.

You have tools for the user's email, their files, and their applications. Use \
them rather than guessing. If a tool fails, say plainly what failed -- do not \
invent a result.

When you are asked to do something you cannot do, say so in one sentence and \
suggest the nearest thing you can do.

The user's name is not known to you unless they say it. Do not invent personal \
details, appointments, or messages. If you did not read it from a tool, you do \
not know it."""

# A sentence has ended when we see . ! or ? followed by whitespace, but not
# when it is an abbreviation or a decimal. Good enough to chunk speech on, and
# a wrong guess only costs a slightly odd pause.
_SENTENCE_END = re.compile(r"(?<![A-Z])(?<!\b[A-Z][a-z])[.!?]['\")\]]*\s")
_ABBREV = re.compile(r"\b(mr|mrs|ms|dr|prof|sr|jr|st|vs|etc|e\.g|i\.e|approx|no)\.$", re.I)


def split_speakable(buffer: str) -> tuple[list[str], str]:
    """
    Pull complete sentences out of a growing buffer.

    Returns the sentences that are safe to speak now, plus whatever is left
    over and still incomplete.
    """
    out: list[str] = []
    pos = 0
    for m in _SENTENCE_END.finditer(buffer):
        candidate = buffer[pos : m.end()].strip()
        if not candidate:
            continue
        # "Dr." is not the end of a sentence.
        if _ABBREV.search(candidate):
            continue
        # Neither is "3." in "version 3.1".
        if re.search(r"\d[.]$", candidate):
            continue
        out.append(candidate)
        pos = m.end()
    return out, buffer[pos:]


@dataclass
class Turn:
    """What a single exchange produced, for logging and for the tests."""

    reply: str
    tools_used: list[str]
    seconds: float
    stopped_because: str


class Brain:
    def __init__(
        self,
        cfg: Config,
        speak: Callable[[str], None] | None = None,
        client: anthropic.Anthropic | None = None,
        confirm: Callable[[str], bool] | None = None,
    ):
        self.cfg = cfg
        self.speak = speak or (lambda _s: None)
        self.confirm = confirm or (lambda _q: False)
        self.client = client or anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        self.messages: list[dict] = []
        self.tools = registry.build(cfg)

    # -- history -------------------------------------------------------

    def reset(self) -> None:
        self.messages = []

    def _trim(self) -> None:
        """
        Keep the conversation from growing without limit.

        Trims from the front, but never leaves the history starting on an
        assistant turn or on a tool result whose tool_use block has been cut
        away -- both are rejected by the API.
        """
        MAX_TURNS = 40
        if len(self.messages) <= MAX_TURNS:
            return
        cut = len(self.messages) - MAX_TURNS
        while cut < len(self.messages):
            m = self.messages[cut]
            if m["role"] != "user":
                cut += 1
                continue
            content = m.get("content")
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            ):
                cut += 1
                continue
            break
        self.messages = self.messages[cut:]

    # -- tools ---------------------------------------------------------

    def _run_tool(self, name: str, args: dict) -> tuple[str, bool]:
        tool = self.tools.get(name)
        if tool is None:
            return f"There is no tool called {name}.", True

        if tool.needs_confirmation and not self.confirm(tool.describe(args)):
            return "The user declined this action. Do not retry it.", False

        try:
            return tool.run(args), False
        except Exception as exc:  # surfaced to Claude, which explains it aloud
            return f"{type(exc).__name__}: {exc}", True

    # -- the loop ------------------------------------------------------

    def ask(self, text: str, max_rounds: int = 6) -> Turn:
        started = time.monotonic()
        self.messages.append({"role": "user", "content": text})
        self._trim()

        spoken: list[str] = []
        used: list[str] = []
        stopped = "end_turn"

        for _round in range(max_rounds):
            pending = ""
            with self.client.messages.stream(
                model=self.cfg.model,
                max_tokens=4096,
                system=SYSTEM,
                # Thinking is left on deliberately. With it disabled, Opus 5
                # will occasionally write a tool call into its visible text
                # instead of actually calling the tool -- which here would mean
                # the assistant says "checking your email" out loud and then
                # does nothing at all. Low effort keeps it quick.
                thinking={"type": "adaptive"},
                output_config={"effort": "low"},
                tools=[t.schema for t in self.tools.values()],
                messages=self.messages,
            ) as stream:
                for event in stream:
                    if event.type != "content_block_delta":
                        continue
                    if event.delta.type != "text_delta":
                        continue
                    pending += event.delta.text
                    ready, pending = split_speakable(pending)
                    for sentence in ready:
                        spoken.append(sentence)
                        self.speak(sentence)

                response = stream.get_final_message()

            if pending.strip():
                spoken.append(pending.strip())
                self.speak(pending.strip())

            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                stopped = "refusal"
                break

            if response.stop_reason != "tool_use":
                stopped = response.stop_reason or "end_turn"
                break

            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                used.append(block.name)
                out, failed = self._run_tool(block.name, dict(block.input))
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": out[:20000],
                        "is_error": failed,
                    }
                )
            self.messages.append({"role": "user", "content": results})
        else:
            stopped = "max_rounds"

        return Turn(
            reply=" ".join(spoken).strip(),
            tools_used=used,
            seconds=round(time.monotonic() - started, 2),
            stopped_because=stopped,
        )
