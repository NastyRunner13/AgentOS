"""Tests for Friday interactive UI & TUI components."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from rich.console import Console

from brain.openai_compat import _consume_openai_sse
from brain.skills import Skill
from ui.completer import FridayCommandCompleter, SLASH_COMMANDS, resolve_slash
from ui.dialogs import (
    pick_session,
    show_mode_dialog,
    show_plugins_dialog,
    show_provider_dialog,
    show_skills_dialog,
)
from ui.renderer import (
    TurnRenderer,
    display_user_content,
    fmt_duration,
    render_banner,
    render_card,
    render_facts,
    render_history,
    render_proposals,
    render_roles,
    render_sessions,
    render_settings,
    render_tasks,
    render_tool_call,
    render_user,
)
from ui.sessions import SessionStore
from ui.workspace import display_cwd, git_branch


class DummyTask:
    def __init__(self, id: str, status: str, title: str):
        self.id = id
        self.status = status
        self.title = title


def _console():
    buf = StringIO()
    c = Console(file=buf, force_terminal=False, color_system=None, width=80, legacy_windows=False)
    return c, buf


def test_completer_matches_root_slash_commands():
    completer = FridayCommandCompleter()
    doc = Document(text="/pro")
    event = CompleteEvent()
    matches = list(completer.get_completions(doc, event))
    texts = [m.text for m in matches]
    assert "/provider" in texts
    assert "/proposals" in texts


def test_completer_includes_session_commands():
    for cmd in ("/new", "/resume", "/sessions", "/rename", "/exit"):
        assert cmd in SLASH_COMMANDS
    completer = FridayCommandCompleter()
    texts = [m.text for m in completer.get_completions(Document(text="/re"), CompleteEvent())]
    assert "/resume" in texts
    assert "/rename" in texts
    exits = [m.text for m in completer.get_completions(Document(text="/ex"), CompleteEvent())]
    assert "/exit" in exits


def test_completer_matches_subcommand_cards_and_proposals():
    stack = {
        "gate": type("DummyGate", (), {"pending": lambda self: ["card123"]})(),
        "memory": type(
            "DummyMemory",
            (),
            {"pending": lambda self: [{"id": "prop456", "kind": "fact", "payload": {"statement": "User prefers tabs"}}]},
        )(),
        "tasks": type("DummyTasks", (), {"tasks": {"task789": DummyTask("task789", "running", "Refactor UI")}})(),
        "sessions": type(
            "DummyStore",
            (),
            {"list": lambda self: [{"id": "abc123", "title": "list files"}]},
        )(),
    }
    completer = FridayCommandCompleter(lambda: stack)

    doc = Document(text="/approve car")
    event = CompleteEvent()
    matches = list(completer.get_completions(doc, event))
    assert any(m.text == "card123" for m in matches)

    doc_prop = Document(text="/approve prop")
    matches_prop = list(completer.get_completions(doc_prop, event))
    assert any(m.text == "prop456" for m in matches_prop)

    doc_steer = Document(text="/steer task")
    matches_steer = list(completer.get_completions(doc_steer, event))
    assert any(m.text == "task789" for m in matches_steer)

    resume = list(completer.get_completions(Document(text="/resume abc"), event))
    assert any(m.text == "abc123" for m in resume)


def test_completer_lists_skills_as_slash_commands(tmp_path: Path):
    skill = Skill(
        name="commit",
        description="Write a git commit",
        path=tmp_path / "commit",
        user_invocable=True,
    )
    hidden = Skill(
        name="internal",
        description="Hidden",
        path=tmp_path / "internal",
        user_invocable=False,
    )
    collision = Skill(
        name="help",
        description="Collides with builtin",
        path=tmp_path / "help",
    )
    completer = FridayCommandCompleter(lambda: {"skills": [skill, hidden, collision]})
    texts = [m.text for m in completer.get_completions(Document(text="/com"), CompleteEvent())]
    assert "/commit" in texts
    all_slash = [m.text for m in completer.get_completions(Document(text="/"), CompleteEvent())]
    assert "/internal" not in all_slash
    assert "/skill:help" in all_slash
    skill_args = [
        m.text
        for m in completer.get_completions(Document(text="/skill com"), CompleteEvent())
    ]
    assert "commit" in skill_args


def test_resolve_slash_routes_builtins_and_skills(tmp_path: Path):
    skill = Skill(name="commit", description="c", path=tmp_path / "c", user_invocable=True)
    hidden = Skill(name="internal", description="i", path=tmp_path / "i", user_invocable=False)
    skills = [skill, hidden]
    assert resolve_slash("hello", skills)[0] == "text"
    assert resolve_slash("/new", skills) == ("command", "new", "")
    assert resolve_slash("/exit", skills) == ("command", "exit", "")
    assert resolve_slash("/resume abc", skills) == ("command", "resume", "abc")
    assert resolve_slash("/commit fix typo", skills) == ("skill", "commit", "fix typo")
    assert resolve_slash("/skill commit fix typo", skills) == ("skill", "commit", "fix typo")
    assert resolve_slash("/skill", skills) == ("command", "skills", "")
    assert resolve_slash("/internal", skills)[0] == "unknown"
    assert resolve_slash("/nope", skills)[0] == "unknown"


def test_render_banner_shows_directory_branch_and_session():
    c, buf = _console()
    render_banner(
        "claude-3-7-sonnet",
        "Code",
        cwd="~/AgentOS",
        branch="main",
        session_id="abc123",
        title="list files",
        out=c,
    )
    out = buf.getvalue()
    assert "AgentOS" in out
    assert "main" in out
    assert "abc123" in out
    assert "/exit" in out


def test_display_cwd_abbreviates_home(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    proj = home / "work" / "AgentOS"
    proj.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    assert display_cwd(proj) == "~/work/AgentOS"
    assert display_cwd(home) == "~"


def test_git_branch_outside_repo(tmp_path: Path):
    assert git_branch(tmp_path) == ""


def test_display_user_content_collapses_skill_turn():
    raw = (
        "[skill:commit]\nFollow this skill exactly.\n\nWrite a commit.\n\n"
        "User request: fix the build"
    )
    assert display_user_content(raw) == "/commit fix the build"
    assert display_user_content("plain hello") == "plain hello"


def test_render_history_replays_turns():
    c, buf = _console()
    render_history(
        [
            {"role": "user", "content": "list the files"},
            {"role": "assistant", "content": "here they are"},
        ],
        out=c,
    )
    out = buf.getvalue()
    assert "list the files" in out
    assert "here they are" in out


async def test_pick_session_empty_returns_none():
    assert await pick_session([]) is None


def test_render_functions_do_not_crash(tmp_path: Path):
    render_banner("claude-3-7-sonnet", "Code")
    render_card({"id": "c1", "ring": 2, "action_preview": "rm -rf", "reason": "delete"})
    render_tool_call("shell", {"command": "dir"}, ring=2)
    render_user("hello")
    render_facts([{"id": "f1", "statement": "Editor is VSCode", "confidence": 0.95}])
    render_facts([])
    render_proposals([{"id": "p1", "kind": "fact", "payload": {"statement": "Likes dark mode"}}])
    render_proposals([])
    render_tasks([DummyTask("t1", "running", "Task 1")])
    render_tasks([])
    render_roles({"master": "claude-3-7-sonnet", "fast": "gpt-4o-mini"})
    render_settings({"clarify": True, "max_tool_steps": 8, "concurrent_slots": 4}, {"skill_autonomy": "suggest_only"})
    render_sessions([{"id": "abc", "updated_at": "2026-01-01T00:00:00", "mode": "Code", "title": "hi"}], "abc")
    render_sessions([])
    show_mode_dialog("Code")
    show_provider_dialog(
        {"default_provider": "openrouter", "providers": {"openrouter": {"kind": "openrouter", "api_key_env": "KEY"}}}
    )
    show_skills_dialog(tmp_path)
    show_plugins_dialog()


def test_fmt_duration():
    assert fmt_duration(0.04) == "40ms"
    assert fmt_duration(1.5) == "1.5s"
    assert fmt_duration(75) == "1m15s"


def test_turn_renderer_streaming():
    c, buf = _console()
    renderer = TurnRenderer(c)
    renderer.on_token("<think>")
    renderer.on_token("Analyzing prompt...")
    renderer.on_token("</think>")
    renderer.on_token("Hello world!")
    assert "Hello world!" in renderer.streamed_text
    renderer.on_stuck("Which folder?")
    renderer.on_idle()
    assert renderer.streamed_text == ""
    out = buf.getvalue()
    assert "thought" in out
    assert "Hello world!" in out


def test_turn_renderer_streams_tokens_incrementally():
    c, buf = _console()
    renderer = TurnRenderer(c)
    renderer.begin_turn()
    renderer.on_token("Hello ")
    renderer.on_token("world!")
    renderer.finish()
    out = buf.getvalue()
    assert "Hello world!" in out


def test_turn_renderer_renders_markdown_not_raw_markers():
    c, buf = _console()
    renderer = TurnRenderer(c)
    renderer.begin_turn()
    renderer.on_token("# Heading\n\nUse **bold** and `code`.")
    renderer.finish()
    out = buf.getvalue()
    assert "Heading" in out
    assert "bold" in out
    assert "code" in out
    assert "# Heading" not in out


def test_turn_renderer_think_tags_split_across_tokens():
    c, buf = _console()
    renderer = TurnRenderer(c)
    renderer.on_token("<thi")
    renderer.on_token("nk>secret</thi")
    renderer.on_token("nk>visible")
    assert "secret" not in renderer.streamed_text
    assert "visible" in renderer.streamed_text
    renderer.finish()
    out = buf.getvalue()
    assert "thought" in out
    assert "visible" in out


def test_turn_renderer_tools_and_footer():
    c, buf = _console()
    renderer = TurnRenderer(c)
    renderer.begin_turn()
    renderer.on_tool_call("files", {"action": "read", "path": "AGENTARCH.md"}, ring=0)
    renderer.on_tool_result("files", "AGENTARCH — build")
    renderer.on_token("Done.")
    renderer.on_card()
    renderer.finish()
    out = buf.getvalue()
    assert "files" in out
    assert "ring 0" in out
    assert "AGENTARCH" in out
    assert "1 tool" in out
    assert "1 card" in out


def test_session_store_roundtrip(tmp_path: Path):
    store = SessionStore(tmp_path)
    sid = store.id
    history = [
        {"role": "user", "content": "list the files please"},
        {"role": "assistant", "content": "here they are"},
    ]
    store.save(history, "Code")
    assert store.title == "list the files please"
    assert (tmp_path / f"{sid}.json").is_file()

    other = SessionStore(tmp_path)
    other.create("Ask")
    other.save([{"role": "user", "content": "later work"}], "Ask")

    rows = store.list()
    assert len(rows) == 2
    loaded = SessionStore(tmp_path)
    loaded.load(sid[:4])
    assert loaded.id == sid
    assert loaded.history[0]["content"] == "list the files please"
    loaded.rename("files recap")
    assert loaded.title == "files recap"


def test_session_store_skips_empty(tmp_path: Path):
    store = SessionStore(tmp_path)
    store.save([], "Code")
    assert store.list() == []


async def test_openai_reasoning_is_wrapped_not_in_reply():
    class Resp:
        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"reasoning_content":"plan"}}]}'
            yield 'data: {"choices":[{"delta":{"content":"hello"}}]}'
            yield "data: [DONE]"

    tokens: list[str] = []
    text, calls = await _consume_openai_sse(Resp(), tokens.append)
    assert text == "hello"
    assert tokens == ["<think>", "plan", "</think>", "hello"]
    assert calls == []
