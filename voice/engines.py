"""STT/TTS engines selected by config/voice.yaml. Fake is the test stack."""

from __future__ import annotations

import asyncio
import io
import math
import os
import struct
import wave
from typing import Protocol


class EngineMissing(RuntimeError):
    pass


class STT(Protocol):
    async def transcribe(self, pcm: bytes, sample_rate: int) -> str: ...


class TTS(Protocol):
    sample_rate: int

    async def synthesize(self, text: str) -> bytes: ...


def pcm_rms(pcm: bytes) -> float:
    n = len(pcm) // 2
    if n <= 0:
        return 0.0
    total = 0
    for i in range(0, n * 2, 2):
        s = int.from_bytes(pcm[i : i + 2], "little", signed=True)
        total += s * s
    return (total / n) ** 0.5 / 32768.0


def pcm16_wav(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def sine_pcm(ms: int, sample_rate: int = 16000, hz: float = 440.0, amp: float = 0.2) -> bytes:
    n = max(1, int(sample_rate * ms / 1000))
    return b"".join(
        struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * hz * i / sample_rate)))
        for i in range(n)
    )


class FakeSTT:
    def __init__(self, transcript: str = "open notepad") -> None:
        self.transcript = transcript
        self.calls: list[bytes] = []

    async def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        self.calls.append(pcm)
        return self.transcript


class FakeTTS:
    def __init__(self, ms: int = 80, sample_rate: int = 16000) -> None:
        self.ms = ms
        self.sample_rate = sample_rate
        self.spoken: list[str] = []

    async def synthesize(self, text: str) -> bytes:
        self.spoken.append(text)
        return sine_pcm(self.ms, self.sample_rate)


class GroqSTT:
    def __init__(self, cfg: dict) -> None:
        stt = cfg.get("stt") or {}
        self.model = str(stt.get("model") or "whisper-large-v3-turbo")
        self.language = str(stt.get("language") or "en")
        self.api_key_env = str(stt.get("api_key_env") or "GROQ_API_KEY")

    async def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        key = os.environ.get(self.api_key_env) or ""
        if not key:
            raise EngineMissing(f"{self.api_key_env} is not set")
        import httpx

        wav = pcm16_wav(pcm, sample_rate)
        files = {"file": ("clip.wav", wav, "audio/wav")}
        data = {"model": self.model, "language": self.language, "response_format": "json"}
        headers = {"Authorization": f"Bearer {key}"}
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers=headers,
                data=data,
                files=files,
            )
            r.raise_for_status()
            body = r.json()
        return str(body.get("text") or "").strip()


class FasterWhisperSTT:
    def __init__(self, cfg: dict) -> None:
        stt = cfg.get("stt") or {}
        self.model_id = str(stt.get("model") or "small.en")
        self.language = str(stt.get("language") or "en")
        self._model = None

    def _load(self):
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise EngineMissing(
                'STT engine faster-whisper is not installed. pip install -e ".[voice]"'
            ) from exc
        self._model = WhisperModel(self.model_id, device="cpu", compute_type="int8")

    async def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        def run() -> str:
            import numpy as np

            self._load()
            audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            segs, _info = self._model.transcribe(audio, language=self.language)
            return "".join(s.text for s in segs).strip()

        return await asyncio.to_thread(run)


class KokoroTTS:
    def __init__(self, cfg: dict) -> None:
        tts = cfg.get("tts") or {}
        self.voice = str(tts.get("voice") or "af_heart")
        self.model_path = str(tts.get("model") or "models/kokoro-v1.0.onnx")
        self.voices_path = str(tts.get("voices") or "models/voices-v1.0.bin")
        self.sample_rate = 24000
        self._kokoro = None
        self._ensure_files()

    def _ensure_files(self) -> None:
        from pathlib import Path

        model = Path(self.model_path)
        voices = Path(self.voices_path)
        if not model.is_file() or not voices.is_file():
            raise EngineMissing(
                f"Kokoro files missing ({model}, {voices}). "
                "Download kokoro-v1.0.onnx and voices-v1.0.bin into models/"
            )

    def _load(self):
        if self._kokoro is not None:
            return
        try:
            from kokoro_onnx import Kokoro
        except ImportError as exc:
            raise EngineMissing(
                'TTS engine kokoro is not installed. pip install -e ".[voice]"'
            ) from exc
        self._ensure_files()
        self._kokoro = Kokoro(self.model_path, self.voices_path)

    async def synthesize(self, text: str) -> bytes:
        def run() -> bytes:
            import numpy as np

            self._load()
            samples, sr = self._kokoro.create(text, voice=self.voice)
            self.sample_rate = int(sr or 24000)
            audio = np.asarray(samples, dtype=np.float32)
            clipped = np.clip(audio, -1.0, 1.0)
            return (clipped * 32767.0).astype(np.int16).tobytes()

        return await asyncio.to_thread(run)


def make_stt(cfg: dict) -> STT:
    engine = str((cfg.get("stt") or {}).get("engine") or "fake")
    if engine == "fake":
        return FakeSTT()
    if engine == "faster-whisper":
        try:
            import faster_whisper  # noqa: F401
        except ImportError as exc:
            raise EngineMissing(
                'STT engine faster-whisper is not installed. pip install -e ".[voice]"'
            ) from exc
        return FasterWhisperSTT(cfg)
    if engine == "groq":
        return GroqSTT(cfg)
    if engine == "parakeet-sherpa":
        raise EngineMissing("stt.engine parakeet-sherpa is not in this slice")
    raise ValueError(f"unknown stt engine {engine}")


def make_tts(cfg: dict) -> TTS:
    engine = str((cfg.get("tts") or {}).get("engine") or "fake")
    if engine == "fake":
        return FakeTTS()
    if engine == "kokoro":
        try:
            import kokoro_onnx  # noqa: F401
        except ImportError as exc:
            raise EngineMissing(
                'TTS engine kokoro is not installed. pip install -e ".[voice]"'
            ) from exc
        return KokoroTTS(cfg)
    if engine == "piper":
        raise EngineMissing("tts.engine piper is not in this slice")
    raise ValueError(f"unknown tts engine {engine}")
