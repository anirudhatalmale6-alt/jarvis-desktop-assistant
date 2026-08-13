"""
Speech to text, running locally.

Whisper runs on the user's own machine rather than through a cloud API. That is
partly cost -- an always-on microphone sending everything it hears to a paid
endpoint gets expensive fast -- and mostly privacy: the room audio never leaves
the PC. Only the text of what was actually said to the assistant is sent
anywhere.

'base.en' is the default because it is accurate enough for commands and runs
comfortably on a normal desktop CPU. 'small.en' is noticeably better on accents
and background noise if the machine can take it.
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

_MODELS: dict[str, object] = {}
_LOCK = threading.Lock()

# Whisper hallucinates politely on silence: fed nothing, it confidently returns
# a YouTube sign-off. These are the usual suspects and are dropped outright.
_HALLUCINATIONS = {
    "thank you.", "thanks for watching!", "thank you for watching.",
    "you", "bye.", ".", "please subscribe.", "subtitles by the amara.org community",
    "thanks for watching.", "thank you for watching!", "okay.",
}


def load(model_name: str = "base.en"):
    """Load (and cache) a Whisper model. First call downloads it."""
    with _LOCK:
        if model_name not in _MODELS:
            from faster_whisper import WhisperModel

            _MODELS[model_name] = WhisperModel(
                model_name, device="cpu", compute_type="int8"
            )
        return _MODELS[model_name]


def transcribe_array(audio: np.ndarray, model_name: str = "base.en") -> str:
    """
    Transcribe mono 16 kHz float32 samples in the range -1..1.

    Returns an empty string when nothing intelligible was said, including when
    Whisper produces one of its silence hallucinations.
    """
    model = load(model_name)
    segments, _info = model.transcribe(
        audio,
        language="en",
        beam_size=1,          # greedy: this is short commands, not dictation
        vad_filter=True,
        condition_on_previous_text=False,  # stops one bad guess poisoning the next
    )
    text = " ".join(seg.text.strip() for seg in segments).strip()

    if text.lower().strip() in _HALLUCINATIONS:
        return ""
    if len(text) < 2:
        return ""
    return text


def transcribe_file(path: str | Path, model_name: str = "base.en") -> str:
    model = load(model_name)
    segments, _info = model.transcribe(str(path), language="en", beam_size=1)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return "" if text.lower().strip() in _HALLUCINATIONS else text
