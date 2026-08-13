"""
The small facts a voice assistant is asked for constantly: the time, the date,
what it can do.

Claude has no clock and no idea what today is, so without this it will either
refuse or make something up. Both are worse than a one-line tool.
"""

from __future__ import annotations

import platform
from datetime import datetime

from ..config import Config
from .registry import Tool


def tools(cfg: Config) -> list[Tool]:
    def now(args: dict) -> str:
        n = datetime.now().astimezone()
        return (
            f"{n.strftime('%A %d %B %Y')}, {n.strftime('%H:%M')} "
            f"({n.strftime('%I:%M %p').lstrip('0')}), timezone {n.tzname()}."
        )

    def capabilities(args: dict) -> str:
        from . import registry

        built = registry.build(cfg)
        lines = ["Tools currently available:"]
        for name, tool in sorted(built.items()):
            first_line = tool.description.split(".")[0]
            lines.append(f"  {name}: {first_line}.")
        if not cfg.email_configured:
            lines.append(
                "  (Email is not set up on this machine, so no mail tools are loaded.)"
            )
        lines.append(f"Running on {platform.system()} {platform.release()}.")
        return "\n".join(lines)

    return [
        Tool(
            name="get_datetime",
            description=(
                "Get the current date, time and timezone from the user's PC. Call this "
                "before answering anything that depends on today's date -- you have no "
                "clock of your own."
            ),
            input_schema={"type": "object", "properties": {}},
            run=now,
        ),
        Tool(
            name="list_capabilities",
            description=(
                "List what this assistant can currently do on this machine. Use when "
                "the user asks what you can do or why something is unavailable."
            ),
            input_schema={"type": "object", "properties": {}},
            run=capabilities,
        ),
    ]
