"""
Speech output.

Microsoft's neural voices via edge-tts are the default: they are free, need no
API key, and sound like a person rather than a 1998 screen reader. They do need
the internet. When that fails we drop to the voice built into Windows, which is
worse but always there -- an assistant that goes mute when the wifi hiccups is
useless.

Sentences are queued and played on a worker thread so the caller can keep
streaming text in while the current sentence is still being spoken.
"""

from __future__ import annotations

import asyncio
import queue
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

_STOP = object()


class Speaker:
    def __init__(self, voice: str = "en-US-AndrewNeural", rate: str = "+8%", enabled: bool = True):
        self.voice = voice
        self.rate = rate
        self.enabled = enabled
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._fallback = None
        self._interrupt = threading.Event()
        self._tmp = Path(tempfile.mkdtemp(prefix="jarvis-tts-"))
        self._current: subprocess.Popen | None = None

    # -- lifecycle -----------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker, daemon=True, name="speaker")
        self._thread.start()

    def stop(self) -> None:
        self._q.put(_STOP)
        if self._thread:
            self._thread.join(timeout=5)
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- api -----------------------------------------------------------

    def say(self, text: str) -> None:
        text = (text or "").strip()
        if text and self.enabled:
            self._q.put(text)

    def interrupt(self) -> None:
        """Drop anything queued and cut off the sentence being spoken."""
        self._interrupt.set()
        while True:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            if item is _STOP:
                self._q.put(_STOP)
                break
        proc = self._current
        if proc and proc.poll() is None:
            proc.terminate()
        self._interrupt.clear()

    def wait_until_quiet(self, timeout: float = 60.0) -> None:
        deadline = threading.Event()
        threading.Timer(timeout, deadline.set).start()
        while not deadline.is_set():
            if self._q.empty() and self._current is None:
                return
            deadline.wait(0.05)

    @property
    def speaking(self) -> bool:
        return self._current is not None or not self._q.empty()

    # -- internals -----------------------------------------------------

    def _worker(self) -> None:
        counter = 0
        while True:
            item = self._q.get()
            if item is _STOP:
                return
            counter += 1
            path = self._tmp / f"line-{counter}.mp3"
            try:
                self._synthesise(item, path)
                self._play(path)
            except Exception:
                self._speak_locally(item)
            finally:
                path.unlink(missing_ok=True)

    def _synthesise(self, text: str, path: Path) -> None:
        import edge_tts

        async def go() -> None:
            comm = edge_tts.Communicate(text, self.voice, rate=self.rate)
            await comm.save(str(path))

        asyncio.run(go())
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError("the speech service returned nothing")

    def _play(self, path: Path) -> None:
        try:
            from playsound3 import playsound

            self._current = None
            playsound(str(path), block=True)
            return
        except Exception:
            pass

        # Fall back to whatever the OS ships with, so playback does not depend
        # on a single Python package continuing to work.
        for command in (
            ["powershell", "-NoProfile", "-c",
             f"(New-Object Media.SoundPlayer '{path}').PlaySync()"],
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)],
            ["mpg123", "-q", str(path)],
            ["afplay", str(path)],
        ):
            if shutil.which(command[0]) is None:
                continue
            self._current = subprocess.Popen(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self._current.wait()
            self._current = None
            return
        raise RuntimeError("no way to play audio on this machine")

    def _speak_locally(self, text: str) -> None:
        """Windows' own voice. Robotic, but it works with no internet."""
        try:
            import pyttsx3

            if self._fallback is None:
                self._fallback = pyttsx3.init()
            self._fallback.say(text)
            self._fallback.runAndWait()
        except Exception:
            print(f"[assistant] {text}")


def list_voices() -> list[str]:
    """Used by check.bat so the user can pick a voice they like."""
    import edge_tts

    async def go():
        return await edge_tts.list_voices()

    voices = asyncio.run(go())
    return sorted(
        v["ShortName"] for v in voices if v["ShortName"].startswith(("en-US", "en-GB", "en-AU"))
    )
