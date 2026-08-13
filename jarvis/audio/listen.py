"""
The microphone.

Two jobs: notice the wake word, then record until the person stops talking.

The second one is the fiddly one. A fixed five-second recording window either
cuts people off mid-sentence or makes them wait after a three-word command, so
instead we watch the incoming level and stop when the speech has been quiet for
about three quarters of a second. Everything below is tuned around that.
"""

from __future__ import annotations

import collections
import threading
import time
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16_000
FRAME_MS = 32
FRAME = SAMPLE_RATE * FRAME_MS // 1000

# How long a gap counts as "they've finished", and how long we will let someone
# talk before cutting them off regardless.
SILENCE_TO_END = 0.75
MAX_UTTERANCE = 20.0
MIN_UTTERANCE = 0.35


class MicUnavailable(Exception):
    pass


@dataclass
class Level:
    """A rolling noise floor, so the assistant adapts to the room it is in."""

    floor: float = 0.004
    _seen: int = 0

    def update(self, rms: float) -> None:
        # Only quiet frames move the floor, otherwise a long sentence would
        # drag the threshold up above the speaker's own voice.
        if self._seen < 25 or rms < self.floor * 2.5:
            self.floor = (self.floor * 0.95) + (rms * 0.05)
            self._seen += 1

    @property
    def threshold(self) -> float:
        # Sits above the floor by enough to ignore fan noise, but low enough
        # that a softly spoken sentence still registers.
        return max(self.floor * 3.5, 0.006)


def _open_stream(device: str | int | None):
    import sounddevice as sd

    try:
        return sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=FRAME,
            device=device,
        )
    except Exception as exc:
        raise MicUnavailable(
            "Could not open the microphone. Check that one is plugged in, and that "
            "Windows has not blocked microphone access for desktop apps "
            "(Settings > Privacy & security > Microphone)."
        ) from exc


def find_device(name_fragment: str) -> int | None:
    """Match a microphone by part of its name, as typed in settings.txt."""
    if not name_fragment:
        return None
    import sounddevice as sd

    want = name_fragment.lower()
    for index, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and want in dev["name"].lower():
            return index
    return None


def list_microphones() -> list[str]:
    import sounddevice as sd

    return [
        f"{i}: {d['name']}"
        for i, d in enumerate(sd.query_devices())
        if d["max_input_channels"] > 0
    ]


def record_utterance(
    device: int | None = None,
    stop_flag: threading.Event | None = None,
    prime: np.ndarray | None = None,
) -> np.ndarray:
    """
    Record from the moment speech starts until it stops.

    `prime` is audio already captured (the tail of the wake-word buffer), so a
    command spoken straight after "hey jarvis" is not clipped at the front.
    """
    level = Level()
    collected: list[np.ndarray] = []
    if prime is not None and len(prime):
        collected.append(prime)

    started = time.monotonic()
    speech_seen = False
    last_voice = time.monotonic()

    stream = _open_stream(device)
    with stream:
        while True:
            if stop_flag is not None and stop_flag.is_set():
                break
            block, _overflow = stream.read(FRAME)
            samples = block[:, 0].copy()
            rms = float(np.sqrt(np.mean(samples**2)) or 0.0)
            level.update(rms)
            collected.append(samples)

            now = time.monotonic()
            if rms > level.threshold:
                speech_seen = True
                last_voice = now
            elif speech_seen and (now - last_voice) > SILENCE_TO_END:
                break

            if now - started > MAX_UTTERANCE:
                break
            if not speech_seen and now - started > 6.0:
                break  # they woke it and then said nothing

    if not collected:
        return np.zeros(0, dtype=np.float32)
    audio = np.concatenate(collected)
    if len(audio) < SAMPLE_RATE * MIN_UTTERANCE:
        return np.zeros(0, dtype=np.float32)
    return audio


class WakeWord:
    """
    Wake-word detection using openWakeWord, which ships a pretrained
    'hey jarvis' model -- the exact phrase wanted here, so no training needed.

    If the package or its model is missing, `available` stays False and the app
    falls back to a hotkey rather than pretending to listen.
    """

    def __init__(self, phrase: str = "hey jarvis", threshold: float = 0.5):
        self.phrase = phrase
        self.threshold = threshold
        self.model = None
        self.available = False
        self._error = ""
        try:
            from openwakeword.model import Model

            key = phrase.replace(" ", "_").lower()
            self.model = Model(wakeword_models=[key], inference_framework="onnx")
            self.available = True
        except Exception as exc:
            self._error = str(exc)

    @property
    def error(self) -> str:
        return self._error

    def wait(self, device: int | None = None, stop_flag: threading.Event | None = None) -> np.ndarray:
        """
        Block until the wake word is heard.

        Returns the last half second of audio, which gets handed to the
        recorder so that "hey jarvis, what time is it" works as one breath.
        """
        if not self.available or self.model is None:
            raise MicUnavailable("Wake word model is not loaded.")

        tail: collections.deque = collections.deque(maxlen=int(0.5 * SAMPLE_RATE / FRAME) + 1)
        stream = _open_stream(device)
        with stream:
            while True:
                if stop_flag is not None and stop_flag.is_set():
                    return np.zeros(0, dtype=np.float32)
                block, _overflow = stream.read(FRAME)
                samples = block[:, 0].copy()
                tail.append(samples)
                # openWakeWord wants 16-bit PCM
                scores = self.model.predict((samples * 32767).astype(np.int16))
                if any(score > self.threshold for score in scores.values()):
                    self.model.reset()
                    return np.concatenate(list(tail))
