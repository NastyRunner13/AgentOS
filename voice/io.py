"""VoiceIO: audio in/out on the bus. Does not import Master."""

from __future__ import annotations

import asyncio
import re
import sys
import time
from typing import Awaitable, Callable, Optional

from kernel.bus import Bus
from voice.engines import TTS, STT, pcm_rms

TurnFn = Callable[[str], Awaitable[str]]

YES = {"yes", "y", "yeah", "yep", "ok", "okay", "allow", "approve"}
NO = {"no", "n", "nope", "deny", "cancel", "stop"}
THINK = re.compile(r"<think>.*?</think>", re.S)


def speakable(text: str) -> str:
    return THINK.sub("", text or "").strip()


def verdict(text: str) -> bool | None:
    word = (text or "").strip().split(None, 1)
    if not word:
        return None
    token = word[0].lower().strip(".,!?")
    if token in YES:
        return True
    if token in NO:
        return False
    return None


class VoiceIO:
    def __init__(
        self,
        bus: Bus,
        cfg: dict,
        stt: STT,
        tts: TTS,
        *,
        resolve_card: Optional[Callable[[str, bool], bool]] = None,
        sleep: Optional[Callable[[float], Awaitable[None]]] = None,
    ) -> None:
        self.bus = bus
        self.cfg = cfg
        self.stt = stt
        self.tts = tts
        self.resolve_card = resolve_card
        self._sleep = sleep or asyncio.sleep
        self.origin = False
        self.muted = False
        self.last_latency_ms = 0.0
        self._first_amp: float | None = None
        self._cancel = asyncio.Event()
        self._heard: asyncio.Queue[str] = asyncio.Queue()
        self._inbox: asyncio.Queue[str | bytes] = asyncio.Queue()
        self._record_stop = asyncio.Event()
        self._running = False
        self._recording = False
        self._playing = False
        self._card_wait = False
        self._turn: TurnFn | None = None
        self._listen_task: asyncio.Task | None = None
        self._loop_task: asyncio.Task | None = None
        self._watchers: list[asyncio.Task] = []
        self._hotkey = None

    @property
    def waiting_for_card(self) -> bool:
        return self._card_wait

    @property
    def recording(self) -> bool:
        return self._recording

    def budget_ms(self) -> int:
        return int((self.cfg.get("latency_budget_ms") or {}).get("wake_to_first_audio") or 2500)

    def frame_ms(self) -> int:
        return int((self.cfg.get("latency_budget_ms") or {}).get("barge_in_frame_ms") or 32)

    def fps(self) -> int:
        return max(1, int(self.cfg.get("amplitude_fps") or 30))

    def sample_rate(self) -> int:
        return int(self.cfg.get("sample_rate") or 16000)

    def _stop_secs(self) -> float:
        return float((self.cfg.get("vad") or {}).get("stop_secs") or 0.6)

    def _vad_threshold(self) -> float:
        return float((self.cfg.get("vad") or {}).get("threshold") or 0.02)

    def _vad_on(self, use_vad: bool | None) -> bool:
        if use_vad is False:
            return False
        engine = str((self.cfg.get("vad") or {}).get("engine") or "none")
        return engine in ("energy", "silero")

    def cancel(self) -> None:
        self._cancel.set()

    def toggle_listen(self) -> None:
        """Click / hotkey: stop a capture, cancel TTS, or start a VAD utterance."""
        if self.muted:
            return
        if self._recording:
            self.stop_record()
            return
        if self._playing:
            self.cancel()
            return
        if self.origin and not self._card_wait:
            return
        turn = self._turn
        if turn is None:
            return
        if self._listen_task and not self._listen_task.done():
            return
        self._listen_task = asyncio.create_task(self.listen_once(turn), name="voice-listen")

    async def listen_once(self, turn: TurnFn) -> str:
        try:
            pcm = await self.record(use_vad=True)
            if not pcm or self.muted:
                self.bus.publish("agent.state", {"phase": "idle"})
                return ""
            if self.origin and self._card_wait:
                text = await self.transcribe(pcm)
                if text:
                    await self.hear(text)
                return text
            return await self.utter(pcm=pcm, turn=turn)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.bus.publish("error", {"error": str(exc)})
            self.bus.publish("agent.state", {"phase": "idle"})
            return ""

    async def hear(self, text: str) -> None:
        await self._heard.put(text)

    async def transcribe(self, pcm: bytes) -> str:
        return (await self.stt.transcribe(pcm, self.sample_rate())).strip()

    async def utter(self, *, pcm: bytes | None = None, text: str | None = None, turn: TurnFn) -> str:
        t0 = time.perf_counter()
        self._first_amp = None
        if text is None:
            if pcm is None:
                raise ValueError("pcm or text required")
            self.bus.publish("agent.state", {"phase": "listening"})
            text = await self.transcribe(pcm)
        if not text:
            self.bus.publish("agent.state", {"phase": "idle"})
            return ""
        spawned = None
        if not self._running:
            spawned = asyncio.create_task(self._watch_cards(), name="voice-cards")
            await asyncio.sleep(0)
        self.origin = True
        try:
            reply = await turn(text)
            spoken = speakable(reply)
            if spoken:
                await self.speak(spoken)
            mark = self._first_amp or time.perf_counter()
            self.last_latency_ms = (mark - t0) * 1000
            return reply
        finally:
            self.origin = False
            if spawned is not None:
                spawned.cancel()
                try:
                    await spawned
                except asyncio.CancelledError:
                    pass

    async def speak(self, text: str) -> None:
        spoken = speakable(text)
        if not spoken:
            return
        self._cancel.clear()
        self.bus.publish("agent.state", {"phase": "speaking"})
        pcm = await self.tts.synthesize(spoken)
        await self._play(pcm)
        self.bus.publish("agent.state", {"phase": "idle"})

    async def push(self, item: str | bytes) -> None:
        await self._inbox.put(item)

    def start(self, turn: TurnFn) -> None:
        if self._running:
            return
        self._running = True
        self._turn = turn
        self._watchers.append(asyncio.create_task(self._watch_cards(), name="voice-cards"))
        self._loop_task = asyncio.create_task(self._run_loop(turn), name="voice-loop")
        hk = str(self.cfg.get("hotkey") or "")
        if hk and hk.lower() not in ("none", "off"):
            from voice.hotkey import Hotkey

            loop = asyncio.get_running_loop()
            self._hotkey = Hotkey(hk, lambda: loop.call_soon_threadsafe(self.toggle_listen))
            self._hotkey.start()

    async def stop(self) -> None:
        self._running = False
        self.cancel()
        self._record_stop.set()
        if self._hotkey is not None:
            self._hotkey.stop()
            self._hotkey = None
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
        pending = [w for w in self._watchers if not w.done()]
        for w in pending:
            w.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._watchers.clear()
        self._turn = None

    async def record(
        self,
        stop: asyncio.Event | None = None,
        *,
        use_vad: bool | None = None,
        source=None,
    ) -> bytes:
        """WASAPI shared capture until `stop`, VAD silence, or `source` ends."""
        if self._recording:
            return b""
        halt = stop or self._record_stop
        halt.clear()
        self._record_stop = halt
        vad = self._vad_on(use_vad)
        buf = bytearray()
        state = {"voiced": False, "silence": 0.0, "elapsed": 0.0, "buf": buf}
        self._recording = True
        self.bus.publish("agent.state", {"phase": "listening"})
        try:
            if source is not None:
                async for chunk in source:
                    if halt.is_set():
                        break
                    if await self._ingest(chunk, vad=vad, state=state):
                        break
            else:
                await self._capture_mic(halt, vad, state)
            if vad and not state["voiced"]:
                return b""
            return bytes(buf)
        finally:
            self._recording = False
            self.bus.publish("mic.amplitude", {"rms": 0.0, "t": time.time()})

    async def _capture_mic(self, halt: asyncio.Event, vad: bool, state: dict) -> None:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError(
                'mic not available. pip install -e ".[voice]" or /listen <text>'
            ) from exc
        loop = asyncio.get_running_loop()
        chunks: asyncio.Queue[bytes] = asyncio.Queue()

        def cb(indata, frames, time_info, status) -> None:
            loop.call_soon_threadsafe(chunks.put_nowait, bytes(indata))

        extra = None
        if sys.platform == "win32" and hasattr(sd, "WasapiSettings"):
            extra = sd.WasapiSettings(exclusive=False)
        kwargs = dict(
            samplerate=self.sample_rate(),
            channels=1,
            dtype="int16",
            callback=cb,
        )
        device = self.cfg.get("mic_device")
        if device and device != "default":
            kwargs["device"] = device
        if extra is not None:
            kwargs["extra_settings"] = extra
        stream = sd.RawInputStream(**kwargs)
        stream.start()
        try:
            while not halt.is_set():
                try:
                    chunk = await asyncio.wait_for(chunks.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                if await self._ingest(chunk, vad=vad, state=state):
                    return
        finally:
            stream.stop()
            stream.close()

    async def _ingest(self, pcm: bytes, *, vad: bool, state: dict) -> bool:
        """Append a chunk unless TTS is playing. True when VAD says the utterance ended."""
        if self._playing:
            return False
        state["buf"].extend(pcm)
        rms = pcm_rms(pcm)
        self.bus.publish("mic.amplitude", {"rms": rms, "t": time.time()})
        dt = (len(pcm) / 2) / max(1, self.sample_rate())
        state["elapsed"] += dt
        if not vad:
            return False
        if rms >= self._vad_threshold():
            state["voiced"] = True
            state["silence"] = 0.0
        elif state["voiced"]:
            state["silence"] += dt
            if state["silence"] >= self._stop_secs():
                return True
        if not state["voiced"] and state["elapsed"] >= 8.0:
            return True
        return state["elapsed"] >= 30.0

    def stop_record(self) -> None:
        self._record_stop.set()

    async def _run_loop(self, turn: TurnFn) -> None:
        while self._running:
            try:
                item = await self._inbox.get()
            except asyncio.CancelledError:
                return
            text = item if isinstance(item, str) else await self.transcribe(item)
            if not text:
                continue
            try:
                await self.utter(text=text, turn=turn)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                self.bus.publish("error", {"error": str(exc)})

    async def _watch_cards(self) -> None:
        req = self.bus.subscribe("approval.request")
        resolved = self.bus.subscribe("approval.resolved")
        try:
            while True:
                try:
                    ev = await req.get()
                except asyncio.CancelledError:
                    return
                if not self.origin:
                    continue
                cid = str(ev.get("id") or "")
                preview = str(ev.get("action_preview") or "this action")
                await self.speak(f"Allow {preview}? Yes or no.")
                await self._wait_card(cid, resolved)
        finally:
            self.bus.unsubscribe("approval.request", req)
            self.bus.unsubscribe("approval.resolved", resolved)

    async def _wait_card(self, cid: str, resolved: asyncio.Queue) -> None:
        self._card_wait = True
        try:
            while True:
                heard_t = asyncio.create_task(self._heard.get())
                res_t = asyncio.create_task(resolved.get())
                try:
                    done, pending = await asyncio.wait(
                        {heard_t, res_t}, return_when=asyncio.FIRST_COMPLETED
                    )
                except asyncio.CancelledError:
                    heard_t.cancel()
                    res_t.cancel()
                    raise
                for p in pending:
                    p.cancel()
                if res_t in done:
                    try:
                        ev = res_t.result()
                    except (asyncio.CancelledError, asyncio.InvalidStateError):
                        return
                    if str(ev.get("id") or "") == cid:
                        return
                    continue
                try:
                    text = heard_t.result()
                except (asyncio.CancelledError, asyncio.InvalidStateError):
                    return
                decision = verdict(text)
                if decision is None:
                    await self.speak("Say yes or no.")
                    continue
                if self.resolve_card:
                    self.resolve_card(cid, decision)
                return
        finally:
            self._card_wait = False

    async def _play(self, pcm: bytes) -> None:
        rate = int(getattr(self.tts, "sample_rate", None) or self.sample_rate())
        fps = self.fps()
        frame_bytes = max(1, int(rate / fps)) * 2
        speaker = _Speaker.open(rate) if self.cfg.get("playback", True) else None
        i = 0
        self._playing = True
        next_tick = time.perf_counter()
        try:
            while i < len(pcm):
                if self._cancel.is_set():
                    break
                chunk = pcm[i : i + frame_bytes]
                if self._first_amp is None:
                    self._first_amp = time.perf_counter()
                self.bus.publish(
                    "tts.amplitude",
                    {"rms": pcm_rms(chunk), "t": time.time()},
                )
                if speaker is not None:
                    await asyncio.to_thread(speaker.write, chunk)
                next_tick += 1.0 / fps
                delay = next_tick - time.perf_counter()
                await self._sleep(delay if delay > 0 else 0)
                i += frame_bytes
        finally:
            self._playing = False
            if speaker is not None:
                speaker.stop()
            self.bus.publish("tts.amplitude", {"rms": 0.0, "t": time.time()})


class _Speaker:
    """Optional sounddevice playback. Missing extra is amplitude events only."""

    def __init__(self, stream) -> None:
        self.stream = stream

    @classmethod
    def open(cls, sample_rate: int):
        try:
            import sounddevice as sd
        except ImportError:
            return None
        try:
            extra = None
            if sys.platform == "win32" and hasattr(sd, "WasapiSettings"):
                extra = sd.WasapiSettings(exclusive=False)
            kwargs = dict(samplerate=sample_rate, channels=1, dtype="int16")
            if extra is not None:
                kwargs["extra_settings"] = extra
            stream = sd.RawOutputStream(**kwargs)
            stream.start()
            return cls(stream)
        except Exception:
            return None

    def write(self, pcm: bytes) -> None:
        try:
            self.stream.write(pcm)
        except Exception:
            pass

    def stop(self) -> None:
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass
