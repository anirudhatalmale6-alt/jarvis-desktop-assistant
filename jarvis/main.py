"""
The assistant itself: wake, listen, think, speak, repeat.

Also runs as a plain typing chat with --text, which is the quickest way to
check the tools and the API key are working without involving a microphone.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from .brain import Brain
from .config import Config, ConfigError, app_dir, load

BANNER = r"""
   JARVIS  --  personal desktop assistant
"""


class ActionLog:
    """
    A plain text record of everything the assistant did.

    Not for debugging -- it is there so the user can see, after the fact,
    exactly what a program with access to their mail and files got up to.
    """

    def __init__(self, enabled: bool):
        self.path = app_dir() / "activity.log"
        self.enabled = enabled

    def write(self, kind: str, detail: str) -> None:
        if not self.enabled:
            return
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(f"{stamp}  {kind:<9} {detail}\n")
        except OSError:
            pass


def _console_confirm(question: str, speaker=None) -> bool:
    """
    Ask before doing something that cannot be undone.

    Spoken as well as printed, because the whole point of this app is that the
    user is not necessarily looking at the screen.
    """
    if speaker is not None:
        speaker.say(question)
        speaker.wait_until_quiet(15)
    try:
        answer = input(f"\n  {question}  [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes")


def run_text_mode(cfg: Config) -> int:
    log = ActionLog(cfg.log_actions)
    brain = Brain(
        cfg,
        speak=lambda s: print(s, end=" ", flush=True),
        confirm=lambda q: _console_confirm(q),
    )
    print(BANNER)
    print("  Typing mode. Ctrl-C to quit.\n")
    while True:
        try:
            text = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            continue
        if text.lower() in ("quit", "exit"):
            return 0
        print("jarvis > ", end="", flush=True)
        turn = brain.ask(text)
        print(f"\n  ({turn.seconds}s{', ' + ', '.join(turn.tools_used) if turn.tools_used else ''})\n")
        log.write("said", text)
        log.write("replied", turn.reply[:200])
        for tool in turn.tools_used:
            log.write("tool", tool)


def run_voice_mode(cfg: Config) -> int:
    from .audio import listen, stt, tts

    log = ActionLog(cfg.log_actions)
    print(BANNER)

    device = listen.find_device(cfg.mic_name) if cfg.mic_name else None
    if cfg.mic_name and device is None:
        print(f"  ! No microphone matching {cfg.mic_name!r}; using the default one.")

    speaker = tts.Speaker(voice=cfg.voice, rate=cfg.speech_rate)
    speaker.start()

    print("  Loading the speech recogniser (first run downloads it)...")
    stt.load(cfg.whisper_model)

    wake = None
    if not cfg.push_to_talk:
        wake = listen.WakeWord(cfg.wake_word)
        if not wake.available:
            print(f"  ! Wake word unavailable ({wake.error.splitlines()[0] if wake.error else 'unknown'}).")
            print("  ! Falling back to press-Enter-to-talk.")
            wake = None

    brain = Brain(
        cfg,
        speak=speaker.say,
        confirm=lambda q: _console_confirm(q, speaker),
    )

    if wake:
        print(f"\n  Ready. Say \"{cfg.wake_word}\".   Ctrl-C to quit.\n")
    else:
        print("\n  Ready. Press Enter, then speak.   Ctrl-C to quit.\n")

    stop = threading.Event()
    try:
        while not stop.is_set():
            prime = None
            if wake:
                prime = wake.wait(device=device, stop_flag=stop)
                if stop.is_set():
                    break
                print("  [listening]", flush=True)
            else:
                try:
                    input()
                except (EOFError, KeyboardInterrupt):
                    break
                print("  [listening]", flush=True)

            # If it is mid-sentence when spoken to, stop talking and listen.
            if speaker.speaking:
                speaker.interrupt()

            audio = listen.record_utterance(device=device, stop_flag=stop, prime=prime)
            if audio.size == 0:
                continue

            heard = stt.transcribe_array(audio, cfg.whisper_model)
            if not heard:
                continue
            print(f"  you    : {heard}")
            log.write("said", heard)

            if heard.lower().strip(" .!?") in ("stop", "never mind", "nevermind", "cancel"):
                speaker.interrupt()
                continue
            if heard.lower().strip(" .!?") in ("goodbye", "shut down", "go to sleep"):
                speaker.say("Goodbye.")
                speaker.wait_until_quiet(10)
                break

            print("  jarvis : ", end="", flush=True)
            turn = brain.ask(heard)
            print(f"{turn.reply}\n           ({turn.seconds}s)")
            log.write("replied", turn.reply[:200])
            for tool in turn.tools_used:
                log.write("tool", tool)

    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        speaker.stop()
    print("\n  Stopped.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis", description="Personal desktop assistant")
    parser.add_argument("--text", action="store_true", help="type instead of speaking")
    parser.add_argument("--say", metavar="TEXT", help="answer one question and exit")
    args = parser.parse_args(argv)

    try:
        cfg = load()
    except ConfigError as exc:
        print(f"\n  {exc}\n")
        return 2

    if args.say:
        brain = Brain(cfg, speak=lambda s: print(s, end=" ", flush=True))
        brain.ask(args.say)
        print()
        return 0

    if args.text:
        return run_text_mode(cfg)
    return run_voice_mode(cfg)


if __name__ == "__main__":
    sys.exit(main())
