"""
Opening applications and web pages.

An allowlist, not a shell. Claude names an application from a fixed table and
the app is launched by that entry -- it never gets to hand Windows an arbitrary
command line. Adding a program the user wants means adding a line to
settings.txt, which is a deliberate speed bump on the one tool that could
otherwise run anything.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import webbrowser
from urllib.parse import quote, urlparse

from ..config import Config
from .registry import Tool

# Spoken name -> what to launch. Windows resolves these through the App Paths
# registry key, so no absolute paths and no guessing at Program Files layout.
KNOWN_APPS: dict[str, str] = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calendar": "outlookcal:",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "paint": "mspaint.exe",
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
    "outlook": "outlook.exe",
    "teams": "ms-teams:",
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "firefox": "firefox.exe",
    "terminal": "wt.exe",
    "command prompt": "cmd.exe",
    "settings": "ms-settings:",
    "task manager": "taskmgr.exe",
}

SAFE_SCHEMES = {"http", "https"}

# "scheme:" at the start of the string, per RFC 3986.
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")


def _extra_apps() -> dict[str, str]:
    """EXTRA_APPS=name=command;name=command in settings.txt."""
    raw = os.getenv("EXTRA_APPS", "").strip()
    out: dict[str, str] = {}
    for entry in raw.split(";"):
        if "=" not in entry:
            continue
        name, _, command = entry.partition("=")
        name, command = name.strip().lower(), command.strip()
        if name and command:
            out[name] = command
    return out


def tools(cfg: Config) -> list[Tool]:
    table = {**KNOWN_APPS, **_extra_apps()}

    def open_app(args: dict) -> str:
        name = str(args.get("name", "")).strip().lower()
        if not name:
            return "No application was named."

        command = table.get(name)
        if command is None:
            close = [k for k in table if name in k or k in name]
            if len(close) == 1:
                name, command = close[0], table[close[0]]
            else:
                options = ", ".join(sorted(table)[:12])
                return (
                    f"{name!r} is not in the list of applications this assistant can "
                    f"open. Known ones include: {options}. More can be added in "
                    "settings.txt."
                )

        if platform.system() != "Windows":
            return f"(Not running on Windows -- would have launched {command}.)"

        try:
            os.startfile(command)  # type: ignore[attr-defined]  # Windows-only
        except OSError as exc:
            return f"Windows could not start {name}: {exc}"
        return f"Opened {name}."

    def open_website(args: dict) -> str:
        url = str(args.get("url", "")).strip()
        if not url:
            return "No address was given."
        # Add https:// only to a bare hostname. Testing for "://" is not enough:
        # "javascript:alert(1)" has no "://", so it would be turned into
        # "https://javascript:alert(1)", which then parses as a perfectly valid
        # https URL and sails through the scheme check below.
        if _SCHEME.match(url):
            if urlparse(url).scheme not in SAFE_SCHEMES:
                return "Only ordinary web addresses can be opened."
        else:
            url = "https://" + url
        parsed = urlparse(url)
        if parsed.scheme not in SAFE_SCHEMES:
            return "Only ordinary web addresses can be opened."
        if not parsed.netloc:
            return f"{url!r} does not look like a web address."
        webbrowser.open(url)
        return f"Opened {parsed.netloc} in the browser."

    def web_search(args: dict) -> str:
        query = str(args.get("query", "")).strip()
        if not query:
            return "No search text was given."
        webbrowser.open(f"https://www.google.com/search?q={quote(query)}")
        return f"Searched the web for {query}."

    return [
        Tool(
            name="open_app",
            description=(
                "Open an application on the user's PC by its everyday name, for "
                "example 'excel' or 'chrome'."
            ),
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            run=open_app,
        ),
        Tool(
            name="open_website",
            description="Open a web page in the user's default browser.",
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            run=open_website,
        ),
        Tool(
            name="web_search",
            description=(
                "Open a Google search in the browser. Use when the user wants to see "
                "results themselves, not when they want you to answer."
            ),
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            run=web_search,
        ),
    ]
