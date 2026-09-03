"""Web research eval scenarios."""

from __future__ import annotations

from pathlib import Path

from evals.fakes import perm
from evals.harness import ScenarioResult
from kernel import Bus, Gate, TaskManager
from memory import Episodic
from tools import NativeTools


async def research_query_cites_fetch(root: Path) -> ScenarioResult:
    """Offline: search then fetch, cite the URL, never claim success without tools."""
    import tools.web as webmod
    from brain.master import Master
    from brain.registry import FakeAdapter, Registry

    async def fake_search(query, perm_cfg, clip=None, **opts):
        return (
            '<untrusted source="web">\n'
            '[{"n":1,"title":"Example","url":"https://example.com/x","domain":"example.com","snippet":"about x"}]\n'
            "</untrusted>"
        )

    async def fake_fetch(url, perm_cfg, clip=None, **opts):
        return f'<untrusted source="web" url="{url}">\nExample Domain facts about x.\n</untrusted>'

    orig_search, orig_fetch = webmod.search, webmod.fetch
    webmod.search = fake_search
    webmod.fetch = fake_fetch
    try:
        fake = FakeAdapter(
            {
                "script": {
                    "fast-a": '{"clarity":"clear"}',
                    "master-a": [
                        (
                            "",
                            [
                                {
                                    "id": "w1",
                                    "type": "function",
                                    "function": {
                                        "name": "web_search",
                                        "arguments": '{"query":"X"}',
                                    },
                                }
                            ],
                        ),
                        (
                            "",
                            [
                                {
                                    "id": "w2",
                                    "type": "function",
                                    "function": {
                                        "name": "web_fetch",
                                        "arguments": '{"url":"https://example.com/x"}',
                                    },
                                }
                            ],
                        ),
                        ("According to Example (https://example.com/x), facts about x.", []),
                    ],
                }
            }
        )
        cfg = perm(root)
        bus = Bus()
        gate = Gate(cfg, bus)
        tasks = TaskManager(bus, concurrent_slots=2)
        registry = Registry(
            {
                "default_provider": "fake",
                "providers": {"fake": {"kind": "fake"}},
                "roles": {
                    "master": "master-a",
                    "fast": "fast-a",
                    "vision": "master-a",
                    "embeddings": "master-a",
                },
            },
            extra={"fake": fake},
        )
        memory = Episodic(root / "events.db")
        tools = NativeTools(root, cfg)
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
            max_tool_steps=16,
        )
        reply = await master.turn("what is X (web)")
        tool_roles = [e["role"] for e in memory.latest(40) if e["kind"] == "tool"]
        search_row = next(e for e in memory.latest(40) if e.get("role") == "web_search")
        ok = (
            tool_roles[:2] == ["web_search", "web_fetch"]
            and "browser" not in tool_roles
            and "<untrusted" in search_row["content"]
            and "https://example.com/x" in reply
            and "facts about x" in reply.lower()
        )
        memory.close()
        return ScenarioResult(
            "research_query_cites_fetch",
            ok,
            trace=[
                {
                    "action": "web_search+web_fetch",
                    "path": "none",
                    "verified": ok,
                    "verify": {"ok": ok, "detail": f"roles={tool_roles} reply={reply[:120]}"},
                }
            ],
            error=None if ok else f"roles={tool_roles} reply={reply}",
        )
    finally:
        webmod.search = orig_search
        webmod.fetch = orig_fetch
