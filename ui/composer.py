"""Framed message composer for the Friday CLI."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from prompt_toolkit.application import Application
from prompt_toolkit.completion import Completer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import AnyFormattedText, HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import Float, FloatContainer, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.processors import AfterInput, ConditionalProcessor
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, TextArea

from ui.plans import PLAN_APPROVE, PLAN_CHANGES, PLAN_COMMENT, PLAN_QUIT

COMPOSER_STYLE = Style.from_dict(
    {
        "frame.border": "#505050",
        "frame.label": "#e0af68",
        "bottom-toolbar": "#e1e1e1 bg:#161618",
        "bottom-toolbar.text": "#e1e1e1",
        "placeholder": "#6c6c6c italic",
        "completion-menu": "bg:#202024 #e1e1e1",
        "completion-menu.completion.current": "bg:#323238 #e0af68",
        "completion-menu.meta.completion": "#8b8b90",
        "completion-menu.meta.completion.current": "#e0af68",
        "hint": "#6c6c6c",
        "hint.key": "#e1e1e1",
    }
)


def size_changed(prev, size) -> bool:
    """True when the compositor should redraw for a real terminal resize.

    Windows ConPTY emits a window-buffer-size event on focus changes even
    when columns/rows are unchanged. Treating those as resizes makes
    prompt_toolkit erase+redraw the inline frame using a stale cursor,
    which stacks a second copy of the composer.
    """
    if size is None:
        return False
    columns = getattr(size, "columns", 0) or 0
    rows = getattr(size, "rows", 0) or 0
    if columns < 8 or rows < 2:
        return False
    if prev is None:
        return True
    return columns != getattr(prev, "columns", None) or rows != getattr(prev, "rows", None)


class InlineApp(Application):
    """Inline (non-fullscreen) app that ignores no-op Windows resize events."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._stable_size = None

    def _on_resize(self) -> None:
        try:
            size = self.output.get_size()
        except Exception:
            return
        prev = self._stable_size
        self._stable_size = size
        if not size_changed(prev, size):
            return
        super()._on_resize()


class Composer:
    """Boxed input field. Enter sends; Ctrl-C / empty Ctrl-D leave like PromptSession."""

    def __init__(
        self,
        completer: Completer,
        get_toolbar: Callable[[], AnyFormattedText],
        get_title: Callable[[], AnyFormattedText],
        history_path: Path,
        *,
        on_cycle_mode: Callable[[], None] | None = None,
        get_input_mode: Callable[[], str] | None = None,
    ) -> None:
        self.completer = completer
        self.get_toolbar = get_toolbar
        self.get_title = get_title
        self.on_cycle_mode = on_cycle_mode
        self.get_input_mode = get_input_mode or (lambda: "normal")
        self._free_text = False
        history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history = FileHistory(str(history_path))

    async def prompt_async(self, *args: Any, **kwargs: Any) -> str:
        self._free_text = False
        box: list[TextArea] = []
        cols = _term_cols()
        input_height = 3 if cols >= 48 else 2
        menu_height = 8 if cols >= 72 else (5 if cols >= 48 else 3)

        textarea = TextArea(
            multiline=True,
            completer=self.completer,
            complete_while_typing=True,
            history=self.history,
            wrap_lines=True,
            height=Dimension(min=1, max=8, preferred=input_height),
            dont_extend_height=True,
            input_processors=[
                ConditionalProcessor(
                    AfterInput(self._placeholder),
                    filter=Condition(lambda: not box or box[0].buffer.text == ""),
                )
            ],
        )
        box.append(textarea)
        frame = Frame(textarea, title=self.get_title)
        root = FloatContainer(
            content=HSplit(
                [
                    frame,
                    Window(
                        FormattedTextControl(self._hint),
                        height=1,
                        wrap_lines=False,
                        style="class:hint",
                    ),
                    Window(
                        FormattedTextControl(self.get_toolbar),
                        height=1,
                        wrap_lines=False,
                        style="class:bottom-toolbar",
                    ),
                ]
            ),
            floats=[
                Float(
                    xcursor=True,
                    ycursor=True,
                    content=CompletionsMenu(max_height=menu_height, scroll_offset=1),
                )
            ],
        )
        kb = KeyBindings()

        @kb.add("enter", eager=True)
        def _submit(event) -> None:
            buf = event.current_buffer
            state = buf.complete_state
            if state is not None and state.current_completion is not None:
                buf.apply_completion(state.current_completion)
                return
            event.app.exit(result=buf.text)

        @kb.add("c-j")
        def _newline(event) -> None:
            event.current_buffer.insert_text("\n")

        if sys.platform != "win32":
            # Esc+Enter is Alt+Enter on Windows and toggles console fullscreen.
            kb.add("escape", "enter")(_newline)

        @kb.add("c-x")
        def _shortcuts(event) -> None:
            event.app.exit(result="/shortcuts")

        @kb.add("c-q")
        def _quit(event) -> None:
            event.app.exit(result="/exit")

        @kb.add(
            "s-tab",
            filter=Condition(lambda: textarea.buffer.complete_state is None),
            eager=True,
        )
        def _cycle_mode(event) -> None:
            if self.on_cycle_mode:
                self.on_cycle_mode()
            event.app.invalidate()

        def _plan_empty() -> bool:
            return (
                self.get_input_mode() == "plan_approval"
                and textarea.buffer.text == ""
                and not self._free_text
            )

        @kb.add("a", filter=Condition(_plan_empty), eager=True)
        def _plan_a(event) -> None:
            event.app.exit(result=PLAN_APPROVE)

        @kb.add("s", filter=Condition(_plan_empty), eager=True)
        def _plan_s(event) -> None:
            event.app.exit(result=PLAN_CHANGES)

        @kb.add("c", filter=Condition(_plan_empty), eager=True)
        def _plan_c(event) -> None:
            event.app.exit(result=PLAN_COMMENT)

        @kb.add("q", filter=Condition(_plan_empty), eager=True)
        def _plan_q(event) -> None:
            event.app.exit(result=PLAN_QUIT)

        @kb.add(
            "tab",
            filter=Condition(
                lambda: self.get_input_mode() == "plan_approval"
                and textarea.buffer.text == ""
                and textarea.buffer.complete_state is None
            ),
            eager=True,
        )
        def _plan_tab(event) -> None:
            self._free_text = True
            event.app.invalidate()

        @kb.add("c-c")
        def _interrupt(event) -> None:
            event.app.exit(exception=KeyboardInterrupt())

        @kb.add("c-d", filter=Condition(lambda: textarea.buffer.text == ""))
        def _eof(event) -> None:
            event.app.exit(exception=EOFError())

        app = InlineApp(
            layout=Layout(root, focused_element=textarea.window),
            key_bindings=kb,
            style=COMPOSER_STYLE,
            full_screen=False,
            mouse_support=False,
            erase_when_done=True,
            min_redraw_interval=0.05,
        )
        try:
            app._stable_size = app.output.get_size()
        except Exception:
            pass
        result = await app.run_async()
        return "" if result is None else str(result)

    def _placeholder(self) -> AnyFormattedText:
        mode = self.get_input_mode()
        if mode == "plan_approval" and not getattr(self, "_free_text", False):
            text = "a approve · s changes · c comment · q quit"
        elif mode in ("plan_approval", "plan_feedback"):
            text = "feedback on the plan, or /command"
        else:
            text = "message, @file, or /command"
        return HTML(f'<style fg="#6c6c6c">{text}</style>')

    def _hint(self) -> AnyFormattedText:
        cols = _term_cols()
        mode = self.get_input_mode()
        if mode == "plan_approval" and not getattr(self, "_free_text", False):
            if cols >= 64:
                return HTML(
                    '<style fg="#6c6c6c">'
                    '<style fg="#e1e1e1">a</style>:approve  │  '
                    '<style fg="#e1e1e1">s</style>:changes  │  '
                    '<style fg="#e1e1e1">c</style>:comment  │  '
                    '<style fg="#e1e1e1">q</style>:quit  │  '
                    '<style fg="#e1e1e1">Tab</style>:prompt'
                    "</style>"
                )
            return HTML(
                '<style fg="#6c6c6c">'
                '<style fg="#e1e1e1">a</style>:approve  │  '
                '<style fg="#e1e1e1">q</style>:quit  │  '
                '<style fg="#e1e1e1">Tab</style>:prompt'
                "</style>"
            )
        if cols >= 78:
            return HTML(
                '<style fg="#6c6c6c">'
                '<style fg="#e1e1e1">Shift+Tab</style>:mode  │  '
                '<style fg="#e1e1e1">Ctrl+X</style>:shortcuts  │  '
                '<style fg="#e1e1e1">Ctrl+J</style>:newline  │  '
                '<style fg="#e1e1e1">Ctrl+Q</style>:exit'
                "</style>"
            )
        if cols >= 48:
            return HTML(
                '<style fg="#6c6c6c">'
                '<style fg="#e1e1e1">Shift+Tab</style>:mode  │  '
                '<style fg="#e1e1e1">Ctrl+X</style>:shortcuts  │  '
                '<style fg="#e1e1e1">Ctrl+Q</style>:exit'
                "</style>"
            )
        return HTML(
            '<style fg="#6c6c6c"><style fg="#e1e1e1">Ctrl+X</style>:shortcuts</style>'
        )


def create_composer(
    stack_getter: Callable[[], dict[str, Any]],
    get_toolbar: Callable[[], AnyFormattedText],
    get_title: Callable[[], AnyFormattedText],
    history_path: Path,
    *,
    on_cycle_mode: Callable[[], None] | None = None,
    get_input_mode: Callable[[], str] | None = None,
) -> Optional[Composer]:
    if not sys.stdin.isatty():
        return None
    try:
        from ui.completer import FridayCommandCompleter

        return Composer(
            FridayCommandCompleter(stack_getter),
            get_toolbar,
            get_title,
            history_path,
            on_cycle_mode=on_cycle_mode,
            get_input_mode=get_input_mode,
        )
    except Exception:
        return None


def _term_cols() -> int:
    try:
        return max(20, shutil.get_terminal_size(fallback=(80, 24)).columns)
    except Exception:
        return 80
