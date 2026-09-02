"""Tool schemas advertised to the master. Unknown names are ring 2 at the gate."""

SPECS = [
    {
        "type": "function",
        "function": {
            "name": "shell",
            "description": "Run a PowerShell command. Output is truncated.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "number"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "files",
            "description": "Read, write, move, search, or delete files inside approved roots.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read", "write", "move", "search", "delete"],
                    },
                    "path": {"type": "string"},
                    "dest": {"type": "string"},
                    "content": {"type": "string"},
                    "query": {"type": "string"},
                },
                "required": ["action", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the public web. Returns numbered hits "
                "{n, title, url, domain, snippet}, wrapped as untrusted. "
                "Use instead of browser for lookup. Pass site to restrict to a domain."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "site": {"type": "string"},
                    "max_results": {"type": "number"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "HTTP GET a public URL and return extracted text, wrapped as untrusted. "
                "Blocks localhost and private IPs. Pass pattern to return matching slices. "
                "Use browser for login or clicking."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "pattern": {"type": "string"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser",
            "description": "Control a Chromium page: navigate, snapshot, click, type, upload, wait, screenshot, close.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["navigate", "snapshot", "click", "type", "upload", "wait", "screenshot", "close"],
                    },
                    "url": {"type": "string"},
                    "ref": {"type": "string"},
                    "text": {"type": "string"},
                    "path": {"type": "string"},
                    "timeout": {"type": "number"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spawn_task",
            "description": "Start a background task. Returns the task id for later steer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "prompt": {"type": "string"},
                },
                "required": ["title", "prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "computer",
            "description": (
                "Desktop operator: open, snapshot, click, type, keys, see (visual screen understanding), "
                "focus (switch window), list_windows, close. A11y first, pixels last. Actions verified."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["open", "snapshot", "click", "type", "keys", "close", "see", "focus", "list_windows"],
                    },
                    "app": {"type": "string"},
                    "ref": {"type": "string"},
                    "text": {"type": "string"},
                    "url": {"type": "string"},
                    "expect": {"type": "string"},
                    "query": {"type": "string"},
                    "title": {"type": "string"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill",
            "description": (
                "Load a skill body by name from the catalog. "
                "Call before inventing a procedure. Follow the body exactly."
            ),
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_read",
            "description": "Recall user-confirmed facts. Pending proposals are not returned.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_propose",
            "description": (
                "Draft a memory proposal (fact, entity, or edge). "
                "It stays pending until the user approves it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["fact", "entity", "edge", "preference"]},
                    "statement": {"type": "string"},
                    "entity_kind": {"type": "string", "enum": ["Person", "Project", "Preference"]},
                    "name": {"type": "string"},
                    "attrs": {"type": "object"},
                    "src": {"type": "string"},
                    "rel": {"type": "string", "enum": ["OWNS", "ABOUT", "SUPERSEDES"]},
                    "dst": {"type": "string"},
                    "about": {"type": "string"},
                    "supersedes": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["kind"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_consolidate",
            "description": (
                "Run the librarian on recent episodes. Drafts proposals only; "
                "never writes confirmed facts."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Ask the user a multiple-choice question when there is ambiguity or a key "
                "design/implementation decision before proceeding. Do not use for general "
                "post-implementation questions or chit-chat."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to clarify before proceeding with implementation.",
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "2 to 4 distinct options for the user to choose from.",
                    },
                },
                "required": ["question", "options"],
            },
        },
    },
]
