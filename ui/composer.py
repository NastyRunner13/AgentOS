"""Framed message composer for the Friday CLI."""

from __future__ import annotations

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
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.processors import AfterInput, ConditionalProcessor
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, TextArea

COMPOSER_STYLE = Style.from_dict(
    {
        "frame.border": "#89b4fa",
        "frame.label": "#cdd6f4",
        "bottom-toolbar": "#cdd6f4 bg:#1e1e2e",
        "bottom-toolbar.text": "#cdd6f4",
        "placeholder": "#6c7086 italic",
        "completion-menu": "bg:#313244 #cdd6f4",
        "completion-menu.completion.current": "bg:#45475a #cdd6f4",
        "completion-menu.meta.completion": "#6c7086",
        "completion-menu.meta.completion.current": "#a6adc8",
    }
)


class Composer:
    """Boxed input field. Enter sends; Ctrl-C / empty Ctrl-D leave like PromptSession."""

    def __init__(
        self,
        completer: Completer,
        get_toolbar: Callable[[], AnyFormattedText],
        get_title: Callable[[], AnyFormattedText],
        history_path: Path,
    ) -> None:
        self.completer = completer
        self.get_toolbar = get_toolbar
        self.get_title = get_title
        history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history = FileHistory(str(history_path))

    async def prompt_async(self, *args: Any, **kwargs: Any) -> str:
        box: list[TextArea] = []

        textarea = TextArea(
            multiline=True,
            completer=self.completer,
            complete_while_typing=True,
            history=self.history,
            wrap_lines=True,
            height=3,
            dont_extend_height=True,
            input_processors=[
                ConditionalProcessor(
                    AfterInput(HTML('<style fg="#6c7086">message or /command</style>')),
                    filter=Condition(lambda: not box or box[0].buffer.text == ""),
                )
            ],
        )
        box.append(textarea)
        frame = Frame(textarea, title=self.get_title())
        root = FloatContainer(
            content=HSplit(
                [
                    frame,
                    Window(
                        FormattedTextControl(self.get_toolbar),
                        height=1,
                        style="class:bottom-toolbar",
                    ),
                ]
            ),
            floats=[
                Float(
                    xcursor=True,
                    ycursor=True,
                    content=CompletionsMenu(max_height=8, scroll_offset=1),
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
            event.app.exit(result=buf.text)

        @kb.add("escape", "enter")
        @kb.add("c-j")
        def _newline(event) -> None:
            event.current_buffer.insert_text("\n")

        @kb.add("c-c")
        def _interrupt(event) -> None:
            event.app.exit(exception=KeyboardInterrupt())

        @kb.add("c-d", filter=Condition(lambda: textarea.buffer.text == ""))
        def _eof(event) -> None:
            event.app.exit(exception=EOFError())

        app = Application(
            layout=Layout(root, focused_element=textarea.window),
            key_bindings=kb,
            style=COMPOSER_STYLE,
            full_screen=False,
            mouse_support=False,
        )
        result = await app.run_async()
        return "" if result is None else str(result)


def create_composer(
    stack_getter: Callable[[], dict[str, Any]],
    get_toolbar: Callable[[], AnyFormattedText],
    get_title: Callable[[], AnyFormattedText],
    history_path: Path,
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
        )
    except Exception:
        return None
