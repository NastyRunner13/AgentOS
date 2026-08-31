The best way to build Friday’s voice layer is a cascaded local pipeline that is a client of the existing kernel, not a second brain. That is what every shipped Jarvis-style system that actually does tools has converged on. Speech-to-speech models (Moshi, GLM-4-Voice, OpenAI Realtime) are the wrong first move for this repo.

Friday’s daily product is: wake → short spoken command → allowlisted Windows app or research → spoken progress + a card if it is risky. That is already specified. Computer control is already in the tree. Voice is the missing input/output.

───

What this agent is for

From this repo, not from a generic assistant pitch:

• Hands-free Windows: “Hey Friday, open Spotify / Notepad / VS Code.”
• Browser and desktop actions on the allowlist (notepad, chrome, code, explorer, spotify).
• Research and file work without blocking the conversation.
• Cards for ring 2–3. Spoken if the turn came from voice.
• Presence later (orb). Daily use is desktop + voice, phone last.

PRINCIPLES.md is explicit: voice and “open Spotify” stay a chat, not a loop. Phase 4 is a surface on Master.turn, not a new planner.

The contract you already wrote is the right one:

STT emits the same user text the CLI already sends to Master.turn. TTS consumes assistant text + tts.amplitude. Open/close of allowlisted apps is computer. Do not add a second voice-tools API.

That matches the one project that shipped this exact split: indyfive11/voice-agent (https://github.com/indyfive11/voice-agent) — a Pipecat audio shell, brain-agnostic over HTTP/SSE. Steal that boundary. Do not steal their process.

───

What shipped systems actually built

┌──────────────┬────────────────────────┬────────────────────────────────┐
│ Project      │ What it is             │ Lesson for Friday              │
├──────────────┼────────────────────────┼────────────────────────────────┤
│ Fono         │ One Rust binary: local │ Local default, every stage     │
│              │ STT/TTS/LLM, hotkey +  │ YAML/CLI-swappable. Hotkey and │
│              │ wake, Wyoming +        │ wake word. Dictation (type     │
│              │ OpenAI-compatible      │ into focused app) vs assistant │
│              │ APIs. GPL-3. Windows   │ (think + speak) as two modes.  │
│              │ still experimental.    │ Overlay for state. Hardware    │
│              │                        │ -probed model size.            │
├──────────────┼────────────────────────┼────────────────────────────────┤
│ indyfive11   │ Pipecat shell: Silero  │ Voice owns audio and turn-     │
│ /voice-agent │ + SmartTurn v3,        │ taking. Brain owns tools and   │
│              │ Whisper, Kokoro,       │ safety. State file for a HAL-  │
│              │ openWakeWord. Brain is │ eye overlay = your agent.state │
│              │ a separate process.    │ + tts.amplitude. Duck media on │
│              │                        │ wake.                          │
├──────────────┼────────────────────────┼────────────────────────────────┤
│ Pipecat (    │ Production voice-agent │ Use as a library of VAD/turn/  │
│ Daily)       │ framework. Local       │ barge-in, not as Friday’s      │
│              │ plugins: Silero,       │ kernel. A Windows local        │
│              │ SmartTurn v3, faster-  │ example exists (windows-voice- │
│              │ whisper, Kokoro,       │ agent): faster-whisper +       │
│              │ Piper, Groq,           │ Kokoro ONNX + Silero, <800 ms  │
│              │ OpenRouter.            │ on Mac.                        │
├──────────────┼────────────────────────┼────────────────────────────────┤
│ Home         │ Wake → STT → intent →  │ One message format per stage.  │
│ Assistant    │ TTS over a tiny        │ Swap engines without rewriting │
│ Assist +     │ protocol.              │ the loop. Your voice.yaml is   │
│ Wyoming      │ openWakeWord, faster-  │ this idea.                     │
│              │ whisper, Piper as      │                                │
│              │ separate processes.    │                                │
├──────────────┼────────────────────────┼────────────────────────────────┤
│ Kyutai       │ Wrap any text LLM in   │ Kyutai’s own verdict: Moshi is │
│ Unmute       │ streaming STT+TTS.     │ more natural, Unmute keeps     │
│              │ Sub-second on GPU.     │ tool-calling. Cascade wins for │
│              │ They built Moshi       │ agents. Linux/WSL, not native  │
│              │ first, then Unmute.    │ Windows.                       │
├──────────────┼────────────────────────┼────────────────────────────────┤
│ GLaDOS       │ Local cascade, Kokoro, │ Aggressive sentence chunking.  │
│              │ <600 ms target,        │ Filler-word prompting. CPU-    │
│              │ OpenAI-compatible TTS  │ capable.                       │
│              │ server.                │                                │
├──────────────┼────────────────────────┼────────────────────────────────┤
│ RealtimeSTT  │ Python STT+VAD+wake (  │ Ready-made recorder loop if    │
│              │ faster-whisper /       │ you do not want Pipecat.       │
│              │ sherpa-onnx /          │ Windows multiprocessing        │
│              │ Parakeet).             │ caveat: if __name__ == "__     │
│              │                        │ main__".                       │
├──────────────┼────────────────────────┼────────────────────────────────┤
│ Microsoft    │ Windows AgentOS:       │ Closest sibling on computer    │
│ UFO²         │ HostAgent + AppAgents, │ control. You already copied    │
│              │ UIA + OmniParser, COM  │ the right ideas (a11y first,   │
│              │ for Office, Picture    │ verify, allowlist). Steal: COM │
│              │ -in-Picture desktop so │ for Office later, speculative  │
│              │ the agent does not     │ multi-action (they claim 51%   │
│              │ steal the user’s       │ fewer LLM calls), isolated     │
│              │ session. Paper.        │ desktop so voice commands do   │
│              │                        │ not yank focus.                │
├──────────────┼────────────────────────┼────────────────────────────────┤
│ Windows-MCP  │ 6.9k★ MIT MCP server.  │ Proof that a11y trees beat     │
│              │ UIA snapshots, any     │ screenshots for Windows. Do    │
│              │ LLM, no vision         │ not add it as a second tool    │
│              │ required. ~20 tools.   │ API. Steal Snapshot/App/Click  │
│              │                        │ -by-ref patterns into          │
│              │                        │ computer.                      │
├──────────────┼────────────────────────┼────────────────────────────────┤
│ Agent-S2 /   │ Screenshot-only CUAs.  │ That is your pixels path,      │
│ UI-TARS /    │ SOTA on OSWorld.       │ already last resort. Do not    │
│ Fara-7B      │                        │ switch the operator to pixels- │
│              │                        │ first because a paper did well │
│              │                        │ on a benchmark.                │
└──────────────┴────────────────────────┴────────────────────────────────┘

Fono and voice-agent both treat the LLM as a plug. Home Assistant treats STT/TTS as plug. UFO² treats the OS as a first-class API. Friday should look like voice-agent’s shell + UFO²’s hands + this repo’s kernel.

───

Recommended stack (2026, mapped to Phase 4)

Keep the three modes in ARCHITECTURE.md §5: local first, cloud adapters second, realtime last.

Default local pipeline

mic (WASAPI shared)
  → openWakeWord ("Hey Friday")          always-on, CPU, ~200 KB ONNX
  → Silero VAD v5                        speech vs silence
  → Smart Turn v3 (optional, CPU ONNX)   end-of-turn, not just a pause
  → STT                                  see table
  → Bus: same text as CLI → Master.turn
  → sentence-chunk TTS                   first sentence while the rest generates
  → speakers + tts.amplitude ~30 fps
  → barge-in: VAD speech during TTS cancels playback in one frame

Per-component pick

┌──────────┬───────────────┬───────────────────┬──────────┬──────────────┐
│ Stage    │ Ship first    │ Why               │ License  │ Free hosted  │
│          │               │                   │          │ fallback     │
├──────────┼───────────────┼───────────────────┼──────────┼──────────────┤
│ Wake     │ openWakeWord  │ Spec already      │ Apache   │ none needed  │
│          │ custom hey_   │ names it. Trains  │ 2.0      │              │
│          │ friday.onnx   │ from synthetic    │          │              │
│          │               │ Piper clips. Two- │          │              │
│          │               │ word phrases beat │          │              │
│          │               │ one-word on false │          │              │
│          │               │ accepts (“Hey     │          │              │
│          │               │ Atlas” vs “       │          │              │
│          │               │ Atlas”).          │          │              │
├──────────┼───────────────┼───────────────────┼──────────┼──────────────┤
│ VAD      │ Silero VAD v5 │ MIT, CPU, used by │ MIT      │ —            │
│          │ ONNX          │ Pipecat, Hugging  │          │              │
│          │               │ Face speech-to-   │          │              │
│          │               │ speech,           │          │              │
│          │               │ RealtimeSTT.      │          │              │
├──────────┼───────────────┼───────────────────┼──────────┼──────────────┤
│ Turn     │ Pipecat Smart │ Silence VAD cuts  │ BSD-2 (  │ —            │
│          │ Turn v3       │ you off mid-      │ Pipecat) │              │
│          │               │ thought. Smart    │          │              │
│          │               │ Turn is the 2026  │          │              │
│          │               │ default in        │          │              │
│          │               │ Pipecat. Bundled  │          │              │
│          │               │ ONNX, CPU.        │          │              │
├──────────┼───────────────┼───────────────────┼──────────┼──────────────┤
│ STT      │ faster-       │ Spec.             │ MIT      │ —            │
│ local    │ whisper small │ CTranslate2, 4–8× │          │              │
│          │ .en or        │ original Whisper. │          │              │
│          │ distil-large  │ GPU if present,   │          │              │
│          │ -v3           │ int8 CPU          │          │              │
│          │               │ otherwise. Huge   │          │              │
│          │               │ ecosystem.        │          │              │
├──────────┼───────────────┼───────────────────┼──────────┼──────────────┤
│ STT      │ NVIDIA        │ Beats Whisper     │ CC-BY-   │ —            │
│ local (  │ Parakeet TDT  │ large-v3 on       │ 4.0 (    │              │
│ upgrade) │ 0.6B v3 via   │ English WER at ~¼ │ NVIDIA   │              │
│          │ sherpa-onnx   │ the size; fast on │ NeMo)    │              │
│          │               │ CPU. 2026         │          │              │
│          │               │ dictation default │          │              │
│          │               │ in OpenWhispr.    │          │              │
│          │               │ Keep Whisper for  │          │              │
│          │               │ the long tail of  │          │              │
│          │               │ languages.        │          │              │
├──────────┼───────────────┼───────────────────┼──────────┼──────────────┤
│ STT      │ Groq whisper  │ Fastest cheap     │ MIT      │ Groq free,   │
│ cloud    │ -large-v3-    │ host. Free tier:  │ weights  │ no card      │
│          │ turbo         │ 20 RPM, 2,000     │          │              │
│          │               │ req/day, ~8 hours │          │              │
│          │               │ of audio/day.     │          │              │
│          │               │ Paid: $0.04/hour. │          │              │
│          │               │ OpenAI-           │          │              │
│          │               │ compatible.       │          │              │
├──────────┼───────────────┼───────────────────┼──────────┼──────────────┤
│ TTS      │ Kokoro-82M (  │ Apache 2.0, <1    │ Apache   │ DeepInfra    │
│ local (  │ kokoro-onnx)  │ GB, CPU realtime, │ 2.0      │ ~$0.62/1M    │
│ voice)   │               │ sounds like a     │          │ chars if you │
│          │               │ person. 2026      │          │ ever host it │
│          │               │ desktop-assistant │          │              │
│          │               │ default (         │          │              │
│          │               │ InnerZero, Fono,  │          │              │
│          │               │ GLaDOS, Pipecat). │          │              │
│          │               │ First audio ~90   │          │              │
│          │               │ ms.               │          │              │
├──────────┼───────────────┼───────────────────┼──────────┼──────────────┤
│ TTS      │ Piper via     │ Spec. First audio │ GPL-3.0  │ —            │
│ local (  │ OHF-Voice/    │ ~40 ms, 60–100 MB │ (new     │              │
│ snappy)  │ piper1-gpl    │ voices. rhasspy   │ tree)    │              │
│          │               │ /piper was        │          │              │
│          │               │ archived Oct      │          │              │
│          │               │ 2025; development │          │              │
│          │               │ continues under   │          │              │
│          │               │ OHF-Voice, GPL-3. │          │              │
│          │               │ Use for chime / “ │          │              │
│          │               │ on it”, not the   │          │              │
│          │               │ speaking voice.   │          │              │
├──────────┼───────────────┼───────────────────┼──────────┼──────────────┤
│ TTS      │ Groq Orpheus  │ Only if local TTS │ Apache   │ Groq free (  │
│ cloud    │ (open         │ is blocked. Not   │ 2.0      │ terms click- │
│          │ weights, ~170 │ day one.          │ weights  │ through)     │
│          │ ms to first   │                   │          │              │
│          │ audio)        │                   │          │              │
├──────────┼───────────────┼───────────────────┼──────────┼──────────────┤
│ LLM      │ Existing      │ Do not put a      │ —        │ Groq Llama   │
│          │ Master (      │ second model in   │          │ 8B /         │
│          │ config/models │ the voice loop.   │          │ OpenRouter : │
│          │ .yaml)        │                   │          │ free for the │
│          │               │                   │          │ fast spoken  │
│          │               │                   │          │ path only    │
└──────────┴───────────────┴───────────────────┴──────────┴──────────────┘

Wake-word training: openwakeword.com (https://openwakeword.com/) or oww_trainer (https://github.com/damvolkov/oww_trainer). Training still wants Linux/WSL + older torch; inference is ONNX on Windows. Ship a pre-trained hey_friday.onnx; do not block Phase 4 on a trainer UI.

What not to pick first

• Moshi / GLM-4-Voice / native speech-to-speech. No reliable tool-calling. Kyutai built Unmute for this reason.
• OpenAI / Gemini Realtime as the daily path. Spec says last. Cost, closed audio, weak tool loop, you lose Master.turn as the single brain.
• Porcupine for wake word. Quality is fine; it is not free for a custom “Hey Friday” in a product.
• Coqui XTTS / Fish Audio S2 Pro on the live path. Quality and cloning, 600 ms–seconds of latency, Fish is non-commercial.
• Pipecat as the process. It wants to own the LLM in the pipeline. Friday already has a kernel.
• Windows-MCP as a second computer tool. Same reason.

───

Latency: the honest budget

Naive cascade on a laptop:

┌────────────────────────────────────────┬───────────────────────────────┐
│ Step                                   │ Typical                       │
├────────────────────────────────────────┼───────────────────────────────┤
│ Wake detect                            │ <50 ms                        │
├────────────────────────────────────────┼───────────────────────────────┤
│ End-of-speech (Silero 200 ms + Smart   │ 200–400 ms                    │
│ Turn)                                  │                               │
├────────────────────────────────────────┼───────────────────────────────┤
│ STT small.en GPU                       │ 300–800 ms                    │
├────────────────────────────────────────┼───────────────────────────────┤
│ STT Parakeet CPU                       │ often faster than Whisper GPU │
│                                        │ for English                   │
├────────────────────────────────────────┼───────────────────────────────┤
│ LLM first token                        │ 300–2000+ ms — this is the    │
│                                        │ killer                        │
├────────────────────────────────────────┼───────────────────────────────┤
│ Piper first audio                      │ ~40 ms                        │
├────────────────────────────────────────┼───────────────────────────────┤
│ Kokoro first audio                     │ ~90 ms                        │
├────────────────────────────────────────┼───────────────────────────────┤
│ Spoken first word, GPU, if you stream  │ ~1.5–3 s                      │
├────────────────────────────────────────┼───────────────────────────────┤
│ CPU Whisper + free OpenRouter master,  │ 5–10 s, feels dead            │
│ no streaming                           │                               │
└────────────────────────────────────────┴───────────────────────────────┘

Shipped tricks that matter here:

1. Wake pre-warms STT (already in ARCHITECTURE.md).
2. Stream the first sentence into TTS before the turn finishes.
3. Speak from tool.call: “Opening Spotify” the moment the operator runs, not after the whole ReAct loop.
4. Fast path for trivial voice already exists (roles.fast, clarify). “Open Spotify”, “what time is it”, “stop” must not hit Nemotron 120B on OpenRouter :free.
5. Do not wait for retrieval on those turns.

Current config/models.yaml uses nvidia/nemotron-3-super-120b-a12b:free for both master and fast. That will make voice feel broken even with a perfect STT/TTS. For voice, roles.fast needs a real low-latency model: Ollama 8B local, or Groq llama-3.1-8b-instant (free, 30 RPM, no card). Keep the big model for hard tool work.

Done-condition (a) in AGENTARCH — wake → spoken response under config/voice.yaml budget — is mostly an LLM and streaming problem, not a Whisper problem.

───

Windows audio (the part that actually breaks)

This is where Python voice demos die on Windows.

• Capture with WASAPI shared (sounddevice or pyaudiowpatch), never exclusive. Exclusive mode fights Spotify and games.
• AEC / ducking: TTS into the same mic looks like barge-in. Mute-or-gate the mic against the playback envelope; only treat as barge-in if energy is above the known TTS amplitude. voice-agent ducks media on wake for the same reason.
• Default device vs “communications” device: Windows has two. Pin the mic in voice.yaml.
• RealtimeSTT on Windows: models in a child process; guard with if __name__ == "__main__".
• Always-on wake is a background thread on the kernel process. Do not put it in a second Python interpreter unless you have to (ONNX Runtime + faster-whisper CUDA in one process is the usual fight).

Amplitude for the orb: RMS of the TTS PCM, 30 fps, publish tts.amplitude. Phase 5’s overlay only subscribes. Phase 4 can dump a CLI [speaking] bar so you can verify without Tauri.

───

Computer control: you already built the right one

Phase 2 operator is the correct Windows architecture:

allowlist → UIA/a11y (pywinauto) → Playwright for browsers → Set-of-Marks last
every action re-read → 2 fails → stuck → ask
screen/OCR is untrusted

That is UFO²’s hybrid pipeline minus COM and PiP. Windows-MCP is the same UIA idea as an MCP server.

What to steal, not vendor

From UFO² (docs (https://microsoft.github.io/UFO/ufo2/overview)):

• Prefer native APIs over clicks when they exist (Excel COM, Outlook, xlwings). Add later as computer actions for allowlisted Office apps, still ring 1.
• Speculative multi-action: predict a small batch of UIA clicks, verify between them. Cuts LLM round-trips. Voice feels twice as fast.
• Picture-in-Picture / Agent Workspace: run GUI actions on a virtual desktop so “Hey Friday, click Send” does not steal the window you are typing in. Windows 11 Agent Workspace is in private preview (Ignite 2025). Until then, focus policy: computer.open may focus; click/type on an already-open app should not yank the user’s keyboard if they are in another window. Voice makes this painful; CLI does not.

From Windows-MCP:

• Snapshot of the a11y tree as the primary observation (you already have computer snapshot).
• Launch by app id, not by clicking the taskbar.
• Bound tree size so Snapshot cannot hang (they hit this in July 2026).

From Ignite 2025 Windows MCP: File Explorer and Settings connectors, On-Device Registry. Future mcp/ adapters. Not Phase 4.

Pixels path stays last. Agent-S2 winning OSWorld on screenshots is interesting for roles.vision later (UI-TARS / Fara-7B as the grounder). It is not how you open Spotify.

Voice × operator UX

Short commands should be one computer call:

┌───────────────────────┬────────────────────────────────────────────────┐
│ Spoken                │ Tool                                           │
├───────────────────────┼────────────────────────────────────────────────┤
│ “Open Spotify”        │ computer {action: open, app: spotify}          │
├───────────────────────┼────────────────────────────────────────────────┤
│ “Pause” / “next song” │ computer keys/click on the Spotify tree, or a  │
│                       │ tiny skill                                     │
├───────────────────────┼────────────────────────────────────────────────┤
│ “Click Send”          │ computer {action: click, …} after snapshot     │
├───────────────────────┼────────────────────────────────────────────────┤
│ “Research X and save  │ spawn_task — speak “working on it”, do not     │
│ a doc”                │ block the mic loop                             │
└───────────────────────┴────────────────────────────────────────────────┘

Ring 2–3: speak the card, wait for “yes” / “no” as the next utterance (same as CLI y/n). Do not invent a voice-tools API.

───

How to structure the code (stay inside AGENTARCH)

Phase 4 done-when is already the right test. Implementation shape:

1. config/voice.yaml — engines, model ids, latency budget, mic device, barge-in frame ms, amplitude fps. Schema change updates AGENTARCH in the same commit.
2. voice/ — wakeword/, vad/, stt/, tts/, playback.py. One VoiceIO interface. No Master imports.
3. Bus only:
   • wake → agent.state listening
   • final transcript → existing Master.turn (identical to CLI user text)
   • agent.state token / idle → TTS
   • PCM RMS → tts.amplitude
   • VAD during playback → cancel + optional steer
4. Hotkey + wake. Fono’s F7/F8 split is the usability lesson. Push-to-talk is how you debug when the wake model is bad. Wake is how you live with it.
5. YAML swap test: run twice, stt.local: faster-whisper vs stt.cloud: groq, and Piper vs Kokoro. That is done-when (d).
6. Do not build the orb. Publish events. CLI can print state. Phase 5 subscribes.

Keep python main.py --cli as the entrypoint; add --voice or voice.enabled in YAML so the same process owns mic + CLI.

───

Suggested voice.yaml (spec delta vs ARCHITECTURE §5)

Piper-as-default is slightly stale. 2026 desktop assistants that people actually talk to use Kokoro for speech and Piper for latency-critical blips.

mode: local                 # local | cloud | realtime
latency_budget_ms:
  wake_to_first_audio: 2500
  barge_in_frame_ms: 32
wake_word:
  engine: openwakeword      # openwakeword | porcupine | none
  model: models/hey_friday.onnx
  threshold: 0.5
hotkey: "ctrl+shift+space"  # push-to-talk always available
stt:
  engine: faster-whisper    # faster-whisper | parakeet-sherpa | groq
  model: small.en           # or distil-large-v3 if GPU
  language: en
tts:
  engine: kokoro            # kokoro | piper | groq-orpheus
  voice: af_heart
  piper_voice: en_US-lessac-medium   # chime / ack only
vad:
  engine: silero
  stop_secs: 0.2
turn: smart_turn_v3         # off | smart_turn_v3
amplitude_fps: 30

Cloud adapter when you flip stt.engine: groq: GROQ_API_KEY, model whisper-large-v3-turbo. Same for TTS later. Realtime (openai-realtime / Gemini Live / Grok Voice) still last.

───

Build order that will not stall

Narrow path, same rule as PRINCIPLES:

1. Push-to-talk → faster-whisper tiny.en → print transcript in CLI → Master.turn → Piper/Kokoro speaks the reply. No wake, no barge-in. Proves the bus contract.
2. Silero VAD + barge-in + tts.amplitude. Measure cancel time.
3. openWakeWord with a downloaded “hey friday” (or “hey jarvis” from the community pack) so you can live with it while you train your own.
4. Sentence-stream TTS. Speak tool.call titles.
5. Groq STT adapter behind YAML. Run the swap test.
6. Parakeet as an optional stt.engine if English WER on your mic is bad.
7. Wake-word trainer is a script in WSL, not a product feature.
8. Orb, Tauri, phone: Phase 5.

Eval that matches done-when: a recorded “Hey Friday, open Notepad” wav → wall clock to first PCM sample; a second wav overlapping TTS → playback cancelled within one VAD frame; two YAML stacks, two runs.

───

Cost / privacy for your machine

Local cascade: $0, audio never leaves, GPU optional (Kokoro + Silero + openWakeWord are CPU; Whisper small.en is fine on CPU, nicer on NVIDIA).

Free cloud that is actually usable for a single desktop:

┌──────────────┬─────────────────────┬───────────────────────────────────┐
│ Need         │ Provider            │ Catch                             │
├──────────────┼─────────────────────┼───────────────────────────────────┤
│ Fast STT     │ Groq Whisper turbo  │ 2,000 req/day free; audio leaves  │
│              │                     │ the box                           │
├──────────────┼─────────────────────┼───────────────────────────────────┤
│ Fast spoken  │ Groq Llama 8B       │ 30 RPM; use as roles.fast for     │
│ LLM          │ instant             │ voice trivia                      │
├──────────────┼─────────────────────┼───────────────────────────────────┤
│ Hard tool    │ Keep OpenRouter     │ :free is too slow for the spoken  │
│ LLM          │ master              │ path                              │
├──────────────┼─────────────────────┼───────────────────────────────────┤
│ TTS          │ Stay local (Kokoro) │ Hosted Orpheus only as adapter    │
└──────────────┴─────────────────────┴───────────────────────────────────┘

Do not route every voice turn through OpenRouter :free 120B. That is the difference between a demo and something you will talk to.

───

Sources

• AgentOS: AGENTARCH.md Phase 4, ARCHITECTURE.md §5–6, PRINCIPLES.md, config/permissions.yaml operator allowlist, tools/operator.py
• Voice shells: Fono (https://fono.page/), indyfive11/voice-agent (https://github.com/indyfive11/voice-agent), Pipecat (https://docs.pipecat.ai/pipecat/learn/speech-input), windows-voice-agent (https://github.com/vsukhwani/windows-voice-agent), Hugging Face speech-to-speech (https://github.com/huggingface/speech-to-speech)
• Models: faster-whisper (https://github.com/SYSTRAN/faster-whisper), sherpa-onnx (https://github.com/k2-fsa/sherpa-onnx), Parakeet vs Whisper 2026 (https://openwhispr.com/blog/parakeet-vs-whisper-vs-nemotron), Kokoro vs Piper vs XTTS (https://contracollective.com/blog/kokoro-vs-piper-vs-xtts-local-text-to-speech-m5-max-2026), Piper continuation (https://github.com/OHF-Voice/piper1-gpl), Kyutai Unmute vs Moshi (https://kyutai.org/unmute)
• Cloud free: Groq Whisper limits (https://spokenly.app/blog/free-speech-to-text-apis) ($0.04/hr turbo; 2,000 req/day free)
• Windows control: UFO² paper (https://arxiv.org/abs/2504.14603), UFO² docs (https://microsoft.github.io/UFO/ufo2/overview), Windows-MCP (https://github.com/CursorTouch/Windows-MCP), Windows MCP at Ignite 2025 (https://blogs.windows.com/windowsdeveloper/2025/11/18/ignite-2025-furthering-windows-as-the-premier-platform-for-developers-governed-by-security/)

If you want a next step in-repo, the first concrete patch is config/voice.yaml + the VoiceIO bus contract and the push-to-talk loop — no wake word, no Tauri — so done-when (a) and (c) can be measured against a real budget.


The deeper pass finished and landed on the same design. A few facts from primary docs that should change how you build it:

Groq cannot own the mic loop. Their Whisper API is file/URL POST, 25 MB max, clips under 10 s billed as 10 s. There is no streaming barge-in endpoint. Wake, VAD, and interrupt stay on-device even if STT later posts a clip to Groq.

openWakeWord licensing is split. Code is Apache 2.0; the bundled models are CC BY-NC-SA 4.0. A custom hey_friday.onnx you train is the clean path. On Windows it is ONNX Runtime only (no TFLite).

Piper licensing is split too. Archived rhasspy/piper is MIT; current OHF-Voice/piper1-gpl is GPL-3.0. Voice checkpoints can be tighter than the engine. Kokoro-82M weights stay Apache 2.0; NVIDIA’s kokoro-82M-onnx-opt is the Windows GPU ONNX build.

Unmute / Riva are not Phase 4. Kyutai Unmute has no native Windows (WSL, ≥16 GB CUDA). NVIDIA Riva is AI Enterprise Docker/NIM, not a free library.

Barge-in is not “VAD saw speech.” LiveKit’s documented failure: VAD-only cuts on “uh-huh.” Pipecat: do not raise VAD confidence to fight noise — filter audio upstream. Turning interruptions off still transcribes overlapping speech and queues it. Home Assistant / OpenVoiceOS disable hotword during TTS because otherwise the device transcribes itself.

UFO² hybrid rule is concrete: CONTROL_BACKEND: ["uia"]; keep every UIA hit; drop OmniParser boxes with IoU > 0.1 against a UIA control. Vision only for controls the tree cannot see.

Windows-MCP holes to inherit as tests, not surprises: no games; Firefox has no UIA RootWebArea; Type can dump a whole file in an IDE; 4K screenshots blow a 1 MB tool-result cap; their focus watchdog can crash after sleep (off by default).

Same “voice is I/O” pattern in production SDKs: OpenAI Agents VoicePipeline is STT → existing text agent → TTS. Their Chat-Supervisor pattern keeps tools on the text brain and limits realtime to greetings. OpenClaw’s default hides the TTS tool because the voice surface owns the speakers.

None of that changes the recommendation: local cascade on this kernel, UIA-first computer, YAML-swappable STT/TTS, realtime last. The new constraints are: never put barge-in on Groq, train your own wake model, prefer Kokoro if you care about GPL, and treat self-TTS as a first-class bug.