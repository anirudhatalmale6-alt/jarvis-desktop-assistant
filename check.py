"""
Diagnostics.

Run this when something is not working. It checks every part in turn and says
in plain English what is wrong and what to do about it, rather than leaving a
stack trace on screen. Each check is independent, so one failure does not hide
the rest.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

OK, WARN, BAD = "  [ ok ]", "  [warn]", "  [FAIL]"
problems: list[str] = []


def report(state: str, label: str, detail: str = "") -> None:
    print(f"{state}  {label}")
    if detail:
        for line in detail.splitlines():
            print(f"          {line}")
    if state == BAD:
        problems.append(label)


def heading(text: str) -> None:
    print(f"\n{text}\n{'-' * len(text)}")


def check_python() -> None:
    heading("Python")
    v = sys.version_info
    if v < (3, 10):
        report(BAD, f"Python {v.major}.{v.minor}", "Python 3.10 or newer is needed.")
    else:
        report(OK, f"Python {v.major}.{v.minor}.{v.micro}")
    report(OK, f"{platform.system()} {platform.release()}")


def check_settings():
    heading("Settings")
    from jarvis import config as config_mod

    if not config_mod.SETTINGS_FILE.exists():
        report(BAD, "settings.txt is missing",
               f"Expected at: {config_mod.SETTINGS_FILE}\n"
               "Copy settings-example.txt to settings.txt and fill it in.")
        return None

    report(OK, f"Found {config_mod.SETTINGS_FILE.name}")
    cfg = config_mod.load(strict=False)

    if not cfg.anthropic_api_key:
        report(BAD, "No Anthropic API key",
               "Put your key on the ANTHROPIC_API_KEY line in settings.txt.")
    elif not cfg.anthropic_api_key.startswith("sk-ant-"):
        report(WARN, "API key looks unusual",
               "Anthropic keys normally start with sk-ant-. Check it was pasted whole.")
    else:
        report(OK, f"API key present ({cfg.anthropic_api_key[:11]}...)")

    if cfg.workspace.exists():
        report(OK, f"Documents folder: {cfg.workspace}")
    else:
        report(WARN, f"Documents folder does not exist: {cfg.workspace}",
               "File tools will not find anything until this path is correct.")
    return cfg


def check_claude(cfg) -> None:
    heading("Claude")
    if cfg is None or not cfg.anthropic_api_key:
        report(WARN, "Skipped -- no API key to test with")
        return
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        reply = client.messages.create(
            model=cfg.model,
            max_tokens=32,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": "Reply with the single word: ready"}],
        )
        text = next((b.text for b in reply.content if b.type == "text"), "")
        report(OK, f"{cfg.model} answered", f"Said: {text.strip()[:40]}")
    except Exception as exc:
        name = type(exc).__name__
        hint = {
            "AuthenticationError": "The API key was rejected. Check it in the Anthropic console.",
            "NotFoundError": f"The model {getattr(cfg, 'model', '?')} was not found. Check the MODEL line.",
            "PermissionDeniedError": "This key does not have access to that model.",
            "APIConnectionError": "Could not reach the internet.",
        }.get(name, str(exc)[:200])
        report(BAD, f"Could not talk to Claude ({name})", hint)


def check_speakers(cfg) -> None:
    heading("Speech output")
    voice = getattr(cfg, "voice", "en-US-AndrewNeural")
    try:
        import asyncio

        import edge_tts

        out = Path(__file__).parent / ".voice-test.mp3"
        asyncio.run(edge_tts.Communicate("Speech is working.", voice).save(str(out)))
        size = out.stat().st_size
        if size < 2000:
            report(BAD, "The speech service returned almost nothing")
        else:
            report(OK, f"Voice {voice} generated audio ({size:,} bytes)")
            try:
                from playsound3 import playsound

                print("          Playing it now -- you should hear a voice...")
                playsound(str(out), block=True)
                report(OK, "Played through the speakers")
            except Exception as exc:
                report(WARN, "Could not play the audio automatically", str(exc)[:120])
        out.unlink(missing_ok=True)
    except Exception as exc:
        report(BAD, "Speech output failed", f"{type(exc).__name__}: {str(exc)[:160]}")


def check_microphone(cfg) -> None:
    heading("Microphone")
    try:
        from jarvis.audio import listen

        mics = listen.list_microphones()
        if not mics:
            report(BAD, "Windows reports no microphones",
                   "Plug one in, then check Settings > Privacy & security > Microphone.")
            return
        report(OK, f"{len(mics)} input device(s)")
        for line in mics[:6]:
            print(f"          {line}")

        wanted = getattr(cfg, "mic_name", "")
        if wanted:
            index = listen.find_device(wanted)
            if index is None:
                report(WARN, f"No microphone matches MIC_NAME={wanted!r}",
                       "The default will be used instead.")
            else:
                report(OK, f"MIC_NAME matches device {index}")

        import numpy as np

        print("          Say something for three seconds...")
        device = listen.find_device(wanted) if wanted else None
        stream = listen._open_stream(device)
        peak = 0.0
        with stream:
            for _ in range(int(3 * listen.SAMPLE_RATE / listen.FRAME)):
                block, _ = stream.read(listen.FRAME)
                peak = max(peak, float(np.abs(block).max()))
        if peak < 0.01:
            report(BAD, f"Heard almost nothing (peak {peak:.3f})",
                   "The microphone is muted, too quiet, or the wrong device.")
        else:
            report(OK, f"Heard you (peak level {peak:.2f})")
    except Exception as exc:
        report(BAD, "Microphone check failed", f"{type(exc).__name__}: {str(exc)[:160]}")


def check_recogniser(cfg) -> None:
    heading("Speech recognition")
    model = getattr(cfg, "whisper_model", "base.en")
    try:
        import time

        from jarvis.audio import stt

        t0 = time.time()
        stt.load(model)
        report(OK, f"Model {model} loaded in {time.time() - t0:.1f}s")
    except Exception as exc:
        report(BAD, f"Could not load the {model} model",
               f"{type(exc).__name__}: {str(exc)[:160]}\n"
               "The first run downloads it, so this needs the internet.")


def check_wake_word(cfg) -> None:
    heading("Wake word")
    if getattr(cfg, "push_to_talk", False):
        report(OK, "Push-to-talk mode -- no wake word needed")
        return
    try:
        from jarvis.audio import listen

        wake = listen.WakeWord(getattr(cfg, "wake_word", "hey jarvis"))
        if wake.available:
            report(OK, f"Listening for \"{cfg.wake_word}\"")
        else:
            report(WARN, "Wake word model not available",
                   f"{wake.error[:160]}\n"
                   "The assistant will use press-Enter-to-talk instead.")
    except Exception as exc:
        report(WARN, "Wake word unavailable", str(exc)[:160])


def check_email(cfg) -> None:
    heading("Email")
    if cfg is None or not cfg.email_configured:
        report(WARN, "Not set up",
               "Add GMAIL_ADDRESS and GMAIL_APP_PASSWORD to settings.txt to turn on\n"
               "the mail tools. See docs/EMAIL-SETUP.md -- it takes about two minutes.")
        return
    try:
        from jarvis.tools import email_gmail

        good, message = email_gmail.selftest(cfg)
        report(OK if good else BAD, message if good else "Could not sign in", "" if good else message)
    except Exception as exc:
        report(BAD, "Email check failed", f"{type(exc).__name__}: {str(exc)[:160]}")


def main() -> int:
    print("\n  Jarvis -- system check\n" + "=" * 40)
    check_python()
    cfg = check_settings()
    check_claude(cfg)
    check_recogniser(cfg)
    check_speakers(cfg)
    check_microphone(cfg)
    check_wake_word(cfg)
    check_email(cfg)

    print("\n" + "=" * 40)
    if problems:
        print(f"  {len(problems)} thing(s) need fixing:")
        for p in problems:
            print(f"    - {p}")
        print("\n  Everything above marked [warn] is optional and can be left.")
        return 1
    print("  Everything checks out. Run run.bat to start.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
