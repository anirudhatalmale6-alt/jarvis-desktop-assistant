"""
Tests for the tools themselves -- mostly the boundaries, since that is where
a voice assistant with filesystem access can do real damage.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.config import Config  # noqa: E402
from jarvis.tools import apps, files, registry, system  # noqa: E402

PASS, FAIL = [], []


def check(name: str, got, want) -> None:
    if got == want:
        PASS.append(name)
    else:
        FAIL.append(f"{name}\n      got:  {got!r}\n      want: {want!r}")


def _cfg(root: Path) -> Config:
    cfg = Config(anthropic_api_key="k")
    cfg.workspace = root
    return cfg


# -- the path boundary -------------------------------------------------


def test_workspace_boundary(root: Path) -> None:
    cfg = _cfg(root)
    (root / "ok.txt").write_text("inside")
    (root / "sub").mkdir()
    (root / "sub" / "deep.txt").write_text("also inside")

    escapes = [
        "../outside.txt",
        "../../etc/passwd",
        "/etc/passwd",
        "sub/../../outside.txt",
        "sub/../../../etc/shadow",
    ]
    for attempt in escapes:
        try:
            files._safe(cfg, attempt)
            check(f"boundary blocks {attempt}", "allowed", "blocked")
        except files.OutsideWorkspace:
            check(f"boundary blocks {attempt}", "blocked", "blocked")

    allowed = ["ok.txt", "sub/deep.txt", "./ok.txt", str(root / "ok.txt")]
    for attempt in allowed:
        try:
            files._safe(cfg, attempt)
            check(f"boundary allows {attempt}", "allowed", "allowed")
        except files.OutsideWorkspace:
            check(f"boundary allows {attempt}", "blocked", "allowed")


def test_symlink_escape_blocked(root: Path) -> None:
    """A symlink pointing out of the workspace must not be a way around it."""
    cfg = _cfg(root)
    outside = root.parent / "secret.txt"
    outside.write_text("not for the assistant")
    link = root / "shortcut.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        return  # no symlink support; nothing to test
    try:
        files._safe(cfg, "shortcut.txt")
        check("boundary blocks symlink escape", "allowed", "blocked")
    except files.OutsideWorkspace:
        check("boundary blocks symlink escape", "blocked", "blocked")


def test_read_file(root: Path) -> None:
    cfg = _cfg(root)
    tools = {t.name: t for t in files.tools(cfg)}
    (root / "notes.txt").write_text("remember the milk")
    (root / "photo.jpg").write_bytes(b"\xff\xd8\xff")

    check("read: text file", tools["read_file"].run({"path": "notes.txt"}), "remember the milk")
    check("read: missing file",
          "no file at" in tools["read_file"].run({"path": "nope.txt"}), True)
    check("read: binary refused",
          "not a text file" in tools["read_file"].run({"path": "photo.jpg"}), True)


def test_find_files(root: Path) -> None:
    cfg = _cfg(root)
    tools = {t.name: t for t in files.tools(cfg)}
    for name in ("report-2026.txt", "report-2025.txt", "invoice.csv"):
        (root / name).write_text("x")

    out = tools["find_files"].run({"pattern": "report"})
    check("find: matches both reports", out.count("report-"), 2)
    check("find: excludes others", "invoice" in out, False)
    check("find: glob works", "invoice" in tools["find_files"].run({"pattern": "*.csv"}), True)
    check("find: no match message",
          "No files matching" in tools["find_files"].run({"pattern": "zzz"}), True)


def test_write_note(root: Path) -> None:
    cfg = _cfg(root)
    tools = {t.name: t for t in files.tools(cfg)}
    note = tools["write_note"]

    check("write: needs confirmation", note.needs_confirmation, True)
    check("write: confirm text", note.describe({"filename": "a.txt"}), "Save that to a.txt?")

    note.run({"filename": "list", "content": "eggs"})
    check("write: extension added", (root / "list.txt").read_text(), "eggs")

    out = note.run({"filename": "evil.exe", "content": "x"})
    check("write: refuses non-text", "Only plain text" in out, True)
    check("write: exe not created", (root / "evil.exe").exists(), False)


# -- the app allowlist -------------------------------------------------


def test_app_allowlist(root: Path) -> None:
    cfg = _cfg(root)
    tools = {t.name: t for t in apps.tools(cfg)}
    out = tools["open_app"].run({"name": "definitely not an app"})
    check("apps: unknown refused", "not in the list" in out, True)

    # A name that is not on the list must not reach the OS even if it looks
    # like a command.
    out = tools["open_app"].run({"name": "cmd.exe /c del *.*"})
    check("apps: command string refused", "not in the list" in out, True)


def test_url_scheme_guard(root: Path) -> None:
    cfg = _cfg(root)
    tools = {t.name: t for t in apps.tools(cfg)}
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "ftp://x.com"):
        out = tools["open_website"].run({"url": bad})
        check(f"url: refuses {bad}", "Only ordinary web addresses" in out, True)


def test_extra_apps_from_settings(root: Path) -> None:
    os.environ["EXTRA_APPS"] = "quickbooks=qbw.exe;sage=sage.exe"
    try:
        table = apps._extra_apps()
        check("extra apps parsed", table, {"quickbooks": "qbw.exe", "sage": "sage.exe"})
    finally:
        del os.environ["EXTRA_APPS"]


# -- registry ----------------------------------------------------------


def test_email_tools_hidden_without_credentials(root: Path) -> None:
    cfg = _cfg(root)
    built = registry.build(cfg)
    check("registry: no mail tools when unconfigured",
          any(n.endswith("_mail") or "inbox" in n for n in built), False)

    cfg.gmail_address = "a@b.com"
    cfg.gmail_app_password = "abcd efgh ijkl mnop"
    built = registry.build(cfg)
    check("registry: mail tools appear when configured", "check_inbox" in built, True)
    check("registry: send is gated", built["send_mail"].needs_confirmation, True)


def test_app_password_spaces_stripped() -> None:
    """Google shows app passwords in four blocks of four; people paste them that way."""
    os.environ["GMAIL_APP_PASSWORD"] = "abcd efgh ijkl mnop"
    os.environ["GMAIL_ADDRESS"] = "a@b.com"
    os.environ["ANTHROPIC_API_KEY"] = "k"
    try:
        from jarvis import config as config_mod

        cfg = config_mod.load(strict=False)
        check("password: spaces stripped", cfg.gmail_app_password, "abcdefghijklmnop")
    finally:
        for k in ("GMAIL_APP_PASSWORD", "GMAIL_ADDRESS", "ANTHROPIC_API_KEY"):
            os.environ.pop(k, None)


def test_datetime_tool(root: Path) -> None:
    cfg = _cfg(root)
    tools = {t.name: t for t in system.tools(cfg)}
    out = tools["get_datetime"].run({})
    check("datetime: has a year", any(str(y) in out for y in range(2024, 2100)), True)
    check("datetime: has a timezone", "timezone" in out, True)


def test_every_tool_has_a_valid_schema(root: Path) -> None:
    cfg = _cfg(root)
    cfg.gmail_address, cfg.gmail_app_password = "a@b.com", "x"
    for name, tool in registry.build(cfg).items():
        schema = tool.schema
        check(f"schema {name}: has name", schema["name"], name)
        check(f"schema {name}: described", len(schema["description"]) > 20, True)
        check(f"schema {name}: object type", schema["input_schema"]["type"], "object")
        for required in schema["input_schema"].get("required", []):
            check(f"schema {name}: {required} defined",
                  required in schema["input_schema"]["properties"], True)


def main() -> int:
    for fn in (
        test_workspace_boundary,
        test_symlink_escape_blocked,
        test_read_file,
        test_find_files,
        test_write_note,
        test_app_allowlist,
        test_url_scheme_guard,
        test_extra_apps_from_settings,
        test_email_tools_hidden_without_credentials,
        test_datetime_tool,
        test_every_tool_has_a_valid_schema,
    ):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "ws"
            workspace.mkdir()
            fn(workspace)
    test_app_password_spaces_stripped()

    for line in FAIL:
        print(f"  FAIL  {line}")
    print(f"\n  tools: {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
