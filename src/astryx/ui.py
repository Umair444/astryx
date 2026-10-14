"""Terminal output for the CLI: a header, step marks (✓ ✗ ○), the fix line, calm notes.

rich when it is importable (a pip install always has it); plain ANSI otherwise, so the CLI still works
from a venv that predates the dependency. Colour only on a TTY, and never when NO_COLOR is set.
"""
from __future__ import annotations

import os
import sys

try:                                                   # pragma: no cover - depends on the venv
    from rich.console import Console
    from rich.markup import escape
    from rich.panel import Panel
    from rich.table import Table
    HAVE_RICH = True
except ImportError:                                    # pragma: no cover
    HAVE_RICH = False

    def escape(s):
        return s

MARKS = {"ok": ("✓", "green"), "fail": ("✗", "red"), "skip": ("○", "yellow"), "info": ("·", "cyan")}
_ANSI = {"green": "32", "red": "31", "yellow": "33", "cyan": "36", "dim": "2", "bold": "1"}


class UI:
    def __init__(self, stream=None):
        self.stream = stream or sys.stdout
        self.color = self.stream.isatty() and not os.environ.get("NO_COLOR")
        self.rich = Console(file=self.stream, highlight=False, no_color=not self.color,
                            soft_wrap=True) if HAVE_RICH else None

    def _plain(self, text, style=None):
        if style and self.color:
            codes = ";".join(_ANSI[s] for s in style.split() if s in _ANSI)
            text = f"\033[{codes}m{text}\033[0m"
        print(text, file=self.stream, flush=True)

    def _p(self, text, style=None):
        if self.rich:
            self.rich.print(f"[{style}]{escape(text)}[/]" if style else escape(text))
        else:
            self._plain(text, style)

    def header(self, title, sub=""):
        if self.rich:
            self.rich.print(Panel.fit(f"[bold cyan]astryx[/] · [bold]{escape(title)}[/]", border_style="cyan",
                                      padding=(0, 2)))
        else:
            self._plain(f"astryx · {title}", "bold")
        if sub:                                        # outside the box: a long path wraps instead of being cut
            self._p(f"  {sub}", "dim")

    def section(self, title):
        self.blank()
        self._p(title, "bold")

    def step(self, state, text, fix=None, detail=None):
        mark, colour = MARKS[state]
        if self.rich:
            self.rich.print(f"  [{colour}]{mark}[/] {escape(text)}")
        else:
            self._plain(f"  {self._c(mark, colour)} {text}")
        if detail:
            self._p(f"      {detail}", "dim")
        if fix:
            self._p(f"      fix: {fix}", "yellow")

    def _c(self, text, colour):
        return f"\033[{_ANSI[colour]}m{text}\033[0m" if self.color else text

    def note(self, text):
        self._p(text)

    def dim(self, text):
        self._p(text, "dim")

    def warn(self, text):
        self._p(text, "yellow")

    def error(self, text):
        self._p(text, "red")

    def cmd(self, line):
        self._p(f"    $ {line}", "cyan")

    def blank(self):
        print(file=self.stream, flush=True)

    def table(self, title, columns, rows):
        if self.rich:
            t = Table(title=title, title_justify="left", title_style="bold", box=None, pad_edge=False)
            for c in columns:
                t.add_column(c, style="dim" if c == columns[-1] and len(columns) > 2 else None)
            for r in rows:
                t.add_row(*[escape(str(x)) for x in r])
            self.rich.print(t)
        else:
            self._plain(title, "bold")
            widths = [max(len(str(x)) for x in [c, *[r[i] for r in rows]]) for i, c in enumerate(columns)]
            for r in [columns, *rows]:
                self._plain("  " + "  ".join(str(x).ljust(w) for x, w in zip(r, widths)))
