"""Push-to-talk recording and local speech-to-text (faster-whisper, runs on CPU, no API key)."""

from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd

RATE = 16_000
# Biases Whisper toward command vocabulary and proper app names.
PROMPT = ("Open Chrome. Switch to Slack. Click Submit. Scroll down. Snap window left. "
          "Press command shift T. Volume up. New tab. Search for the weather.")


class Recorder:
    def __init__(self):
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None

    def start(self) -> None:
        with self._lock:
            self._chunks = []
        self._stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32", callback=self._cb)
        self._stream.start()

    def _cb(self, data, frames, time_info, status):
        with self._lock:
            self._chunks.append(data[:, 0].copy())

    def stop(self) -> np.ndarray:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._lock:
            return np.concatenate(self._chunks) if self._chunks else np.zeros(0, dtype=np.float32)


class Transcriber:
    def __init__(self, model: str = "base.en"):
        from faster_whisper import WhisperModel  # slow import; keep it off the --text path

        self.model = WhisperModel(model, device="cpu", compute_type="int8")
        self.model.transcribe(np.zeros(RATE // 2, dtype=np.float32))  # warm up

    def __call__(self, audio: np.ndarray) -> str:
        if len(audio) < RATE * 0.25:  # under a quarter second: a stray tap
            return ""
        segments, _ = self.model.transcribe(audio, language="en", beam_size=1,
                                            initial_prompt=PROMPT, vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()
