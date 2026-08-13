"""
Reading and finding files, confined to one folder.

Every path Claude supplies is resolved and then checked against the workspace
root before anything is opened. That check is the whole security model here:
without it, "read my notes" and a misheard filename is enough to walk out of
the folder and into somewhere it should not be.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..config import Config
from .registry import Tool

TEXTUAL = {
    ".txt", ".md", ".csv", ".json", ".xml", ".yml", ".yaml", ".log", ".ini",
    ".cfg", ".py", ".js", ".ts", ".html", ".css", ".sql", ".sh", ".bat", ".ps1",
}


class OutsideWorkspace(Exception):
    pass


def _safe(cfg: Config, raw: str) -> Path:
    """Resolve a user-supplied path and refuse anything outside the workspace."""
    root = cfg.workspace.expanduser().resolve()
    candidate = Path(os.path.expandvars(str(raw))).expanduser()
    target = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if target != root and root not in target.parents:
        raise OutsideWorkspace(
            f"{target} is outside the folder this assistant is allowed to touch ({root})."
        )
    return target


def tools(cfg: Config) -> list[Tool]:
    def find_files(args: dict) -> str:
        pattern = str(args.get("pattern", "")).strip() or "*"
        limit = max(1, min(int(args.get("limit", 20)), 50))
        root = cfg.workspace.expanduser().resolve()
        if not root.exists():
            return f"The folder {root} does not exist."

        if not any(ch in pattern for ch in "*?["):
            pattern = f"*{pattern}*"

        hits = []
        for path in root.rglob(pattern):
            if path.is_file():
                hits.append(path)
            if len(hits) >= limit:
                break
        if not hits:
            return f"No files matching {pattern!r} under {root}."

        hits.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        lines = [f"{len(hits)} file(s) under {root}:"]
        for p in hits:
            size = p.stat().st_size
            lines.append(f"  {p.relative_to(root)}  ({size:,} bytes)")
        return "\n".join(lines)

    def read_file(args: dict) -> str:
        target = _safe(cfg, str(args.get("path", "")))
        if not target.exists():
            return f"There is no file at {target}."
        if target.is_dir():
            return f"{target} is a folder, not a file."
        if target.suffix.lower() not in TEXTUAL:
            return (
                f"{target.name} is not a text file, so it cannot be read aloud. "
                "Only plain text formats are supported."
            )
        if target.stat().st_size > 400_000:
            return f"{target.name} is too large to read in one go."
        text = target.read_text(encoding="utf-8", errors="replace")
        return text[:20_000]

    def write_note(args: dict) -> str:
        name = str(args.get("filename", "")).strip()
        body = str(args.get("content", ""))
        if not name:
            return "A filename is needed."
        if not Path(name).suffix:
            name += ".txt"
        target = _safe(cfg, name)
        if target.suffix.lower() not in TEXTUAL:
            return "Only plain text files can be written."
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        target.write_text(body, encoding="utf-8")
        verb = "Replaced" if existed else "Created"
        return f"{verb} {target}."

    return [
        Tool(
            name="find_files",
            description=(
                "Search the user's documents folder for files by name. Give a word "
                "from the filename, or a glob like '*.pdf'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["pattern"],
            },
            run=find_files,
        ),
        Tool(
            name="read_file",
            description=(
                "Read a plain text file so you can answer questions about it or read "
                "it aloud. Text formats only."
            ),
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            run=read_file,
        ),
        Tool(
            name="write_note",
            description=(
                "Save text to a file in the user's documents folder, for notes or "
                "lists they dictate. Overwrites the file if it already exists."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["filename", "content"],
            },
            run=write_note,
            needs_confirmation=True,
            confirm_template="Save that to {filename}?",
        ),
    ]
