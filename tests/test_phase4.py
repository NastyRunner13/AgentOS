"""Phase 4 done-conditions from AGENTARCH.md (VoiceIO bus contract)."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest
import yaml

from brain.master import Master
from brain.registry import FakeAdapter, Registry
from kernel import Bus, Gate, TaskManager
from memory import Episodic
from tools import NativeTools
from voice import EngineMissing, FakeSTT, FakeTTS, VoiceIO, make_stt, make_tts, speakable
from voice.engines import GroqSTT, KokoroTTS, sine_pcm
from voice.hotkey import parse as parse_hotkey
from voice.io import _Speaker

ROOT = Path(__file__).resolve().parents[1]


def _cfg(**overrides) -> dict:
    cfg = {
        "enabled": False,
        "mode": "local",
        "latency_budget_ms": {"wake_to_first_audio": 2500, "barge_in_frame_ms": 32},
        "wake_word": {"engine": "none"},
        "stt": {"engine": "fake"},
        "tts": {"engine": "fake"},
        "vad": {"engine": "none"},
        "turn": "off",
        "amplitude_fps": 30,
        "sample_rate": 16000,
        "playback": False,
    }
    cfg.update(overrides)
    return cfg


async def _nosleep(_: float) -> None:
    await asyncio.sleep(0)


def _voice(bus=None, stt=None, tts=None, **kwargs) -> tuple[Bus, VoiceIO, FakeSTT, FakeTTS]:
    bus = bus or Bus()
    stt = stt or FakeSTT("open notepad")
    tts = tts or FakeTTS(ms=80)
    voice = VoiceIO(bus, _cfg(), stt, tts, sleep=_nosleep, **kwargs)
    return bus, voice, stt, tts


def test_voice_yaml_schema():
    cfg = yaml.safe_load((ROOT / "config" / "voice.yaml").read_text(encoding="utf-8"))
    assert "latency_budget_ms" in cfg
    assert "wake_to_first_audio" in cfg["latency_budget_ms"]
    assert "barge_in_frame_ms" in cfg["latency_budget_ms"]
    assert cfg["stt"]["engine"]
    assert cfg["tts"]["engine"]
    assert "amplitude_fps" in cfg
    assert cfg["wake_word"]["engine"] in ("none", "openwakeword", "porcupine")
    assert cfg["mode"] in ("local", "cloud", "realtime")
    assert cfg["vad"]["engine"] in ("none", "energy", "silero")
    assert "threshold" in cfg["vad"]
    assert cfg["orb"]["enabled"] in (True, False)
    assert int(cfg["orb"]["size"]) >= 80


def test_voice_package_does_not_import_master():
    for path in (ROOT / "voice").glob("*.py"):
        name = str(path.relative_to(ROOT)).replace("\\", "/")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("brain"), name
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("brain"), name
                assert node.module != "brain.master", name


def test_d_yaml_swap_changes_engine_class():
    fake = make_stt({"stt": {"engine": "fake"}})
    groq = make_stt({"stt": {"engine": "groq"}})
    assert type(fake) is FakeSTT
    assert type(groq) is GroqSTT
    tts_fake = make_tts({"tts": {"engine": "fake"}})
    assert type(tts_fake) is FakeTTS


def test_speakable_drops_think():
    assert speakable("<think>secret</think>Opening Spotify.") == "Opening Spotify."


async def test_stt_text_is_what_turn_receives():
    bus, voice, stt, tts = _voice()
    got: list[str] = []

    async def turn(text: str) -> str:
        got.append(text)
        return "Opening Notepad."

    reply = await voice.utter(pcm=b"\x00\x01" * 32, turn=turn)
    assert got == ["open notepad"]
    assert stt.calls
    assert reply == "Opening Notepad."
    assert tts.spoken == ["Opening Notepad."]


async def test_a_transcript_to_first_audio_under_budget():
    bus, voice, stt, tts = _voice()

    async def turn(text: str) -> str:
        return "On it."

    amps: list[dict] = []
    q = bus.subscribe("tts.amplitude")

    async def collect():
        while True:
            ev = await q.get()
            amps.append(ev)
            if ev.get("rms") == 0:
                return

    collector = asyncio.create_task(collect())
    await voice.utter(text="open notepad", turn=turn)
    await asyncio.wait_for(collector, timeout=2)
    assert voice.last_latency_ms < voice.budget_ms()
    assert any(a.get("rms", 0) > 0 for a in amps)
    assert amps[-1]["rms"] == 0


async def test_b_barge_in_cancels_playback():
    bus = Bus()
    tts = FakeTTS(ms=800)
    frames = {"n": 0}

    async def gated(dt: float) -> None:
        frames["n"] += 1
        if frames["n"] == 2:
            voice.cancel()
        await asyncio.sleep(0)

    voice = VoiceIO(bus, _cfg(), FakeSTT(), tts, sleep=gated)
    amps: list[float] = []
    q = bus.subscribe("tts.amplitude")

    async def collect():
        while True:
            ev = await q.get()
            amps.append(float(ev.get("rms") or 0))
            if ev.get("rms") == 0:
                return

    collector = asyncio.create_task(collect())
    await voice.speak("this is a long spoken reply for barge-in")
    await asyncio.wait_for(collector, timeout=2)
    nonzero = [r for r in amps if r > 0]
    assert 1 <= len(nonzero) <= 3
    assert amps[-1] == 0.0


async def test_c_speaking_phase_and_amplitude_topic():
    bus, voice, stt, tts = _voice()
    state = bus.subscribe("agent.state")
    amp = bus.subscribe("tts.amplitude")
    await voice.speak("hi")
    phases = []
    while not state.empty():
        phases.append((await state.get()).get("phase"))
    assert "speaking" in phases
    assert "idle" in phases
    assert not amp.empty()


async def test_voice_card_yes_resolves():
    bus = Bus()
    perm = yaml.safe_load((ROOT / "config" / "permissions.yaml").read_text(encoding="utf-8"))
    gate = Gate(perm, bus)
    tts = FakeTTS(ms=40)
    voice = VoiceIO(
        bus,
        _cfg(),
        FakeSTT(),
        tts,
        resolve_card=gate.resolve,
        sleep=_nosleep,
    )

    async def turn(text: str) -> str:
        ok = await gate.check("shell", {"command": "Remove-Item -Recurse C:\\nope"})
        return "ran" if ok else "denied"

    req = bus.subscribe("approval.request")
    task = asyncio.create_task(voice.utter(text="wipe that folder", turn=turn))
    ev = await asyncio.wait_for(req.get(), timeout=2)
    assert ev.get("id")
    await voice.hear("yes")
    reply = await asyncio.wait_for(task, timeout=2)
    assert reply == "ran"
    assert any("Allow" in s for s in tts.spoken)


async def test_d_two_stacks_two_runs():
    async def turn(text: str) -> str:
        return f"ack {text}"

    bus_a = Bus()
    stt_a = FakeSTT("open spotify")
    voice_a = VoiceIO(bus_a, _cfg(), stt_a, FakeTTS(ms=40), sleep=_nosleep)
    reply_a = await voice_a.utter(pcm=b"\x00\x00" * 8, turn=turn)

    bus_b = Bus()
    stt_b = FakeSTT("what time is it")
    voice_b = VoiceIO(bus_b, _cfg(), stt_b, FakeTTS(ms=40), sleep=_nosleep)
    reply_b = await voice_b.utter(pcm=b"\x00\x00" * 8, turn=turn)

    assert reply_a == "ack open spotify"
    assert reply_b == "ack what time is it"
    assert type(stt_a) is type(stt_b)
    assert make_stt({"stt": {"engine": "fake"}}).__class__ is not make_stt({"stt": {"engine": "groq"}}).__class__


async def test_push_loop_runs_turn_without_blocking_inbox_after_idle():
    bus, voice, stt, tts = _voice()
    seen: list[str] = []

    async def turn(text: str) -> str:
        seen.append(text)
        return "ok"

    voice.start(turn)
    await voice.push("open notepad")
    await voice.push("pause")
    for _ in range(50):
        if len(seen) >= 2:
            break
        await asyncio.sleep(0.01)
    await voice.stop()
    assert seen == ["open notepad", "pause"]


async def test_transcript_roundtrip_through_master(tmp_path: Path):
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": '{"clarity":"clear"}',
                "master-a": "Opening Notepad.",
            }
        }
    )
    models_cfg = {
        "default_provider": "fake",
        "providers": {"fake": {"kind": "fake"}},
        "roles": {"master": "master-a", "fast": "fast-a", "vision": "master-a", "embeddings": "master-a"},
        "prompts": {"master": "You are Friday.", "clarify": "JSON only."},
    }
    perm = yaml.safe_load((ROOT / "config" / "permissions.yaml").read_text(encoding="utf-8"))
    bus = Bus()
    gate = Gate(perm, bus)
    tasks = TaskManager(bus, concurrent_slots=4)
    registry = Registry(models_cfg, extra={"fake": fake})
    memory = Episodic(tmp_path / "events.db")
    tools = NativeTools(tmp_path, perm)
    master = Master(
        registry,
        gate,
        tasks,
        memory,
        tools,
        bus,
        system_prompt="You are Friday.",
        clarify_prompt='Reply JSON {"clarity":"clear","questions":[],"assumption":""}',
        clarify=True,
        max_tool_steps=8,
    )
    voice = VoiceIO(bus, _cfg(), FakeSTT("open notepad"), FakeTTS(ms=40), sleep=_nosleep)

    async def turn(text: str) -> str:
        return await master.turn(text)

    reply = await voice.utter(pcm=b"\x00\x00" * 16, turn=turn)
    assert reply == "Opening Notepad."
    assert memory.count() >= 1
    memory.close()


def test_hotkey_parse():
    assert parse_hotkey("ctrl+shift+space") == (0x0002 | 0x0004, 0x20)
    assert parse_hotkey("none") is None
    assert parse_hotkey("") is None


async def test_energy_vad_stops_after_silence():
    bus = Bus()
    cfg = _cfg()
    cfg["vad"] = {"engine": "energy", "stop_secs": 0.25, "threshold": 0.02}
    voice = VoiceIO(bus, cfg, FakeSTT(), FakeTTS(ms=40), sleep=_nosleep)

    async def chunks():
        yield b"\x00\x00" * 800
        yield sine_pcm(200, amp=0.5)
        for _ in range(40):
            yield b"\x00\x00" * 800

    pcm = await voice.record(use_vad=True, source=chunks())
    assert len(pcm) > 2000
    assert len(pcm) < 16000 * 2


async def test_mic_gate_drops_frames_while_playing():
    bus, voice, _stt, _tts = _voice()
    state = {"voiced": False, "silence": 0.0, "elapsed": 0.0, "buf": bytearray()}
    voice._playing = True
    assert await voice._ingest(b"\x00\x01" * 100, vad=False, state=state) is False
    assert len(state["buf"]) == 0
    voice._playing = False
    await voice._ingest(b"\x00\x01" * 100, vad=False, state=state)
    assert len(state["buf"]) == 200


async def test_mic_amplitude_ends_at_zero():
    bus, voice, _stt, _tts = _voice()
    q = bus.subscribe("mic.amplitude")

    async def src():
        yield b"\x00\x01" * 32

    await voice.record(use_vad=False, source=src())
    evs = []
    while not q.empty():
        evs.append(await q.get())
    assert evs
    assert evs[-1]["rms"] == 0.0
    assert any(float(e.get("rms") or 0) > 0 for e in evs[:-1])


async def test_toggle_listen_starts_utter():
    bus, voice, stt, tts = _voice()
    seen: list[str] = []

    async def turn(text: str) -> str:
        seen.append(text)
        return "ok"

    voice._turn = turn

    async def fake_record(**_k):
        return b"\x00\x01" * 32

    voice.record = fake_record
    voice.toggle_listen()
    for _ in range(50):
        if seen:
            break
        await asyncio.sleep(0.01)
    assert seen == ["open notepad"]
    assert tts.spoken == ["ok"]


async def test_toggle_listen_stops_record_or_cancels_tts():
    bus, voice, _stt, _tts = _voice()
    voice._recording = True
    voice.toggle_listen()
    assert voice._record_stop.is_set()
    voice._recording = False
    voice._playing = True
    voice.toggle_listen()
    assert voice._cancel.is_set()


async def test_energy_vad_silence_returns_empty():
    bus = Bus()
    cfg = _cfg()
    cfg["vad"] = {"engine": "energy", "stop_secs": 0.25, "threshold": 0.02}
    voice = VoiceIO(bus, cfg, FakeSTT(), FakeTTS(ms=40), sleep=_nosleep)

    async def chunks():
        for _ in range(200):
            yield b"\x00\x00" * 800

    pcm = await voice.record(use_vad=True, source=chunks())
    assert pcm == b""


async def test_listen_once_silence_skips_turn():
    bus, voice, stt, tts = _voice()
    seen: list[str] = []

    async def turn(text: str) -> str:
        seen.append(text)
        return "nope"

    async def fake_record(**_k):
        return b""

    voice.record = fake_record
    assert await voice.listen_once(turn) == ""
    assert seen == []
    assert tts.spoken == []
    assert stt.calls == []


async def test_play_paces_when_speaker_accepts_instantly():
    slept: list[float] = []

    async def track(dt: float) -> None:
        slept.append(dt)
        await asyncio.sleep(0)

    bus = Bus()
    voice = VoiceIO(bus, _cfg(playback=True), FakeSTT(), FakeTTS(ms=80), sleep=track)

    class Instant:
        def write(self, pcm: bytes) -> None:
            return None

        def stop(self) -> None:
            return None

    orig = _Speaker.open
    _Speaker.open = classmethod(lambda cls, rate: Instant())
    try:
        await voice.speak("hello")
    finally:
        _Speaker.open = orig
    assert slept


async def test_listen_once_turn_error_publishes_error():
    bus, voice, _stt, _tts = _voice()
    errors = bus.subscribe("error")
    state = bus.subscribe("agent.state")

    async def turn(text: str) -> str:
        raise RuntimeError("boom")

    async def fake_record(**_k):
        return b"\x00\x01" * 32

    voice._turn = turn
    voice.record = fake_record
    voice.toggle_listen()
    ev = await asyncio.wait_for(errors.get(), timeout=2)
    assert "boom" in str(ev.get("error") or "")
    phases = []
    while not state.empty():
        phases.append((await state.get()).get("phase"))
    assert "idle" in phases


async def test_record_refuses_second_capture():
    bus, voice, _stt, _tts = _voice()
    voice._recording = True

    async def src():
        yield b"\x00\x01" * 32

    assert await voice.record(use_vad=False, source=src()) == b""


async def test_stop_awaits_watchers():
    bus, voice, _stt, _tts = _voice()

    async def turn(text: str) -> str:
        return "ok"

    voice.start(turn)
    watchers = list(voice._watchers)
    assert watchers
    await voice.stop()
    assert all(w.done() for w in watchers)


def test_kokoro_missing_files_raise_before_load():
    with pytest.raises(EngineMissing, match="Kokoro files missing"):
        KokoroTTS({"tts": {"model": "nope.onnx", "voices": "nope.bin"}})


def test_waiting_for_card_is_public():
    _bus, voice, _stt, _tts = _voice()
    assert voice.waiting_for_card is False
    voice._card_wait = True
    assert voice.waiting_for_card is True
