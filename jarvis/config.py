"""
Settings, loaded from a plain .env file sitting next to run.bat.

Everything the user is ever expected to edit lives in that one file. Nothing
here reads from the registry, a cloud profile, or a hidden AppData folder --
if something is misconfigured the fix is always "open settings.txt".
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def app_dir() -> Path:
    """The folder the app lives in, whether run from source or a frozen exe."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


SETTINGS_FILE = app_dir() / "settings.txt"


class ConfigError(Exception):
    """Raised with a message written for the person running the app."""


@dataclass
class Config:
    anthropic_api_key: str = ""
    model: str = "claude-opus-5"

    # Voice
    wake_word: str = "hey jarvis"
    voice: str = "en-US-AndrewNeural"
    speech_rate: str = "+8%"
    whisper_model: str = "base.en"
    mic_name: str = ""          # blank = system default
    push_to_talk: bool = False  # skip the wake word, use a hotkey instead

    # Email (Google Workspace over IMAP -- see docs/EMAIL-SETUP.md)
    gmail_address: str = ""
    gmail_app_password: str = ""
    gmail_imap_host: str = "imap.gmail.com"

    # Behaviour
    send_email_needs_confirmation: bool = True
    log_actions: bool = True

    # Where the assistant is allowed to read and write files.
    workspace: Path = field(default_factory=lambda: Path.home() / "Documents")

    @property
    def email_configured(self) -> bool:
        return bool(self.gmail_address and self.gmail_app_password)


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load(strict: bool = True) -> Config:
    """
    Read settings.txt into a Config.

    strict=False is used by the diagnostics script, which wants to report every
    problem at once rather than stopping at the first one.
    """
    if SETTINGS_FILE.exists():
        load_dotenv(SETTINGS_FILE, override=False)

    cfg = Config(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        model=os.getenv("MODEL", "claude-opus-5").strip() or "claude-opus-5",
        wake_word=os.getenv("WAKE_WORD", "hey jarvis").strip().lower(),
        voice=os.getenv("VOICE", "en-US-AndrewNeural").strip(),
        speech_rate=os.getenv("SPEECH_RATE", "+8%").strip(),
        whisper_model=os.getenv("WHISPER_MODEL", "base.en").strip(),
        mic_name=os.getenv("MIC_NAME", "").strip(),
        push_to_talk=_flag("PUSH_TO_TALK", False),
        gmail_address=os.getenv("GMAIL_ADDRESS", "").strip(),
        gmail_app_password=os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "").strip(),
        send_email_needs_confirmation=_flag("SEND_EMAIL_NEEDS_CONFIRMATION", True),
        log_actions=_flag("LOG_ACTIONS", True),
    )

    ws = os.getenv("WORKSPACE", "").strip()
    if ws:
        cfg.workspace = Path(os.path.expandvars(ws)).expanduser()

    if strict and not cfg.anthropic_api_key:
        raise ConfigError(
            "No Anthropic API key found.\n\n"
            f"Open this file in Notepad:\n  {SETTINGS_FILE}\n\n"
            "and put your key on the ANTHROPIC_API_KEY line."
        )

    return cfg
