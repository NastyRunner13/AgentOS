"""Interactive UI package for Friday AgentOS."""

from ui.completer import FridayCommandCompleter, SLASH_COMMANDS, resolve_slash
from ui.dialogs import (
    pick_session,
    show_mode_dialog,
    show_plugins_dialog,
    show_provider_dialog,
    show_shortcuts_dialog,
    show_skills_dialog,
)
from ui.renderer import (
    TurnRenderer,
    console,
    display_user_content,
    fmt_duration,
    render_banner,
    term_cols,
    render_card,
    render_facts,
    render_history,
    render_plan,
    render_proposals,
    render_roles,
    render_sessions,
    render_settings,
    render_shortcuts,
    render_tasks,
    render_tool_call,
    render_user,
)
from ui.sessions import SessionStore
from ui.workspace import display_cwd, git_branch

__all__ = [
    "FridayCommandCompleter",
    "SLASH_COMMANDS",
    "SessionStore",
    "TurnRenderer",
    "console",
    "display_cwd",
    "display_user_content",
    "fmt_duration",
    "git_branch",
    "pick_session",
    "render_banner",
    "render_card",
    "render_facts",
    "render_history",
    "render_plan",
    "render_proposals",
    "render_roles",
    "render_sessions",
    "render_settings",
    "render_shortcuts",
    "render_tasks",
    "render_tool_call",
    "render_user",
    "resolve_slash",
    "show_mode_dialog",
    "show_plugins_dialog",
    "show_provider_dialog",
    "show_shortcuts_dialog",
    "show_skills_dialog",
    "term_cols",
]

