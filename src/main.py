"""Kali Vivo Terminal: entry point and terminal screen wiring."""
import os
import queue
import sys

# Make `ui` and `core` importable whether run from src/ or the project root.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.utils import escape_markup

from core.shell_engine import CLEAR, ERR, INFO, OUT, CommandHistory, ShellEngine
from ui import theme as T

Builder.load_file(os.path.join(_HERE, "ui", "terminal_screen.kv"))

# Extra event kinds used only by the UI (not emitted by the engine).
EVENT_PROMPT = "prompt"        # echo a submitted command line
EVENT_INTERRUPT = "interrupt"  # ^C pressed while idle
MAX_EVENTS_PER_TICK = 200


class TerminalScreen(BoxLayout):
    MAX_LINES = 500

    def on_kv_post(self, base_widget):
        self._events = queue.Queue()
        self.history = CommandHistory()
        home = os.path.join(App.get_running_app().user_data_dir, "home")
        self.engine = ShellEngine(home, emit=self._emit)

        self._emit(OUT, "Kali Vivo Terminal v0.1 - type 'help' for commands.")
        self._emit(INFO, "Quick keys: TAB  CTRL+C  ESC  /  -  UP  DOWN")
        Clock.schedule_interval(self._drain_events, 1 / 30.0)

    # ------------------------------------------------------------------
    # Event pipeline: worker threads -> queue -> UI thread
    # ------------------------------------------------------------------
    def _emit(self, kind, text):
        """Thread-safe: may be called from the engine's worker threads."""
        self._events.put((kind, text))

    def _drain_events(self, dt):
        for _ in range(MAX_EVENTS_PER_TICK):
            try:
                kind, text = self._events.get_nowait()
            except queue.Empty:
                break
            self._render(kind, text)

    def _render(self, kind, text):
        if kind == EVENT_PROMPT:
            self._log(T.PROMPT + T.markup(T.TEXT, escape_markup(text)))
        elif kind == EVENT_INTERRUPT:
            self._log(T.PROMPT + T.markup(T.KALI_RED, "^C"))
        elif kind == CLEAR:
            self.ids.output.clear_widgets()
        else:
            color = {OUT: T.TEXT, ERR: T.KALI_RED, INFO: T.MUTED}.get(kind, T.TEXT)
            self._log(T.markup(color, escape_markup(text)))

    def _log(self, markup_text):
        """Append a pre-marked-up line to the output log and keep it bounded."""
        output = self.ids.output
        label = Label(
            text=markup_text,
            markup=True,
            size_hint_y=None,
            halign="left",
            valign="top",
            font_name=T.FONT_MONO,
            font_size=T.FONT_OUTPUT,
            color=T.TEXT,
        )
        label.bind(width=lambda lbl, w: setattr(lbl, "text_size", (w, None)))
        label.bind(texture_size=lambda lbl, size: setattr(lbl, "height", size[1]))
        output.add_widget(label)

        while len(output.children) > self.MAX_LINES:
            output.remove_widget(output.children[-1])

        Clock.schedule_once(lambda dt: setattr(self.ids.scroll, "scroll_y", 0), 0)

    # ------------------------------------------------------------------
    # Command submission
    # ------------------------------------------------------------------
    def submit(self):
        cmd_input = self.ids.cmd
        line = cmd_input.text
        cmd_input.text = ""

        self._emit(EVENT_PROMPT, line)
        self.history.add(line.strip())
        self.engine.run(line)
        cmd_input.focus = True

    # ------------------------------------------------------------------
    # Quick-tap keys
    # ------------------------------------------------------------------
    def key_tap(self, key):
        handlers = {
            "TAB": self._autocomplete,
            "CTRL+C": self._interrupt,
            "ESC": self._clear_input,
            "/": lambda: self._insert("/"),
            "-": lambda: self._insert("-"),
            "UP": lambda: self._history_nav(-1),
            "DOWN": lambda: self._history_nav(1),
        }
        handler = handlers.get(key)
        if handler:
            handler()
        self.ids.cmd.focus = True

    def _insert(self, text):
        self.ids.cmd.insert_text(text)

    def _clear_input(self):
        self.ids.cmd.text = ""
        self.history.reset()

    def _interrupt(self):
        self.ids.cmd.text = ""
        self.history.reset()
        if self.engine.cancel():
            self._emit(INFO, "^C")
        else:
            self._emit(EVENT_INTERRUPT, "")

    def _autocomplete(self):
        cmd_input = self.ids.cmd
        prefix = cmd_input.text
        if " " in prefix:
            return  # only command names complete for now
        matches = [c for c in ShellEngine.BUILTINS if c.startswith(prefix)]
        if len(matches) == 1:
            cmd_input.text = matches[0] + " "
            cmd_input.do_cursor_movement("cursor_end")
        elif len(matches) > 1:
            self._emit(INFO, "  ".join(matches))

    def _history_nav(self, step):
        cmd_input = self.ids.cmd
        if step < 0:
            text = self.history.older(cmd_input.text)
        else:
            text = self.history.newer()
        if text is None:
            return
        cmd_input.text = text
        cmd_input.do_cursor_movement("cursor_end")


class KaliVivoTerminalApp(App):
    title = "Kali Vivo Terminal"

    def build(self):
        Window.clearcolor = T.BG
        # Pan the layout so the focused input stays above the soft keyboard.
        Window.softinput_mode = "below_target"
        return TerminalScreen()

    def on_stop(self):
        if self.root is not None:
            self.root.engine.shutdown()


if __name__ == "__main__":
    KaliVivoTerminalApp().run()