"""
The tool table.

Each tool is a small object with a JSON schema, a run function, and a flag
saying whether it needs the user's say-so first. Anything that sends, deletes,
or otherwise cannot be taken back sets that flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..config import Config


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    run: Callable[[dict], str]
    needs_confirmation: bool = False
    # Rendered to the user when confirmation is required. Kept short because
    # it is read aloud.
    confirm_template: str = ""

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def describe(self, args: dict) -> str:
        if not self.confirm_template:
            return f"Run {self.name}?"
        try:
            return self.confirm_template.format(**args)
        except (KeyError, IndexError):
            return f"Run {self.name}?"


def build(cfg: Config) -> dict[str, Tool]:
    """Assemble the tools this install is actually able to offer."""
    from . import apps, email_gmail, files, system

    tools: list[Tool] = []
    tools += system.tools(cfg)
    tools += files.tools(cfg)
    tools += apps.tools(cfg)

    # Email tools are only offered when an account is configured. Claude is
    # never shown a tool it cannot successfully call -- otherwise it promises
    # the user things that then fail.
    if cfg.email_configured:
        tools += email_gmail.tools(cfg)

    return {t.name: t for t in tools}
