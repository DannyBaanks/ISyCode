"""AGY-style reasoning effort slider for the model picker.

Shows only the levels ``reasoning_levels`` knows for the highlighted
provider/model, plus an explicit ``auto`` stop (provider default). It is a
draft control: nothing is applied until the picker's Choose action.
"""
from __future__ import annotations

from rich.text import Text
from textual.message import Message
from textual.widgets import Static

from isycode.localization import tr
from isycode.tui_theme import CYAN, GREEN, MUTED, RED, TEXT, YELLOW

ORDER = {"none": 0, "off": 0, "minimal": 1, "on": 1, "low": 2, "medium": 3,
         "high": 4, "xhigh": 5, "max": 6}
DESCRIPTIONS = {
    "none": "No reasoning — fastest replies",
    "off": "Thinking disabled — fastest replies",
    "on": "Thinking enabled for this model",
    "minimal": "Barely any reasoning — very fast",
    "low": "Faster responses, lighter reasoning — good for simpler tasks",
    "medium": "Balanced speed and reasoning quality for most tasks",
    "high": "Deeper reasoning for complex problems — slower",
    "xhigh": "Extra-deep reasoning — slower and costlier",
    "max": "Maximum reasoning budget — slowest but strongest",
}
PREFIX = "Effort  ◂  "


def level_color(level: str) -> str:
    if level == "default":
        return CYAN
    if level in {"none", "off"}:
        return MUTED
    if level in {"minimal", "low", "on"}:
        return GREEN
    if level == "medium":
        return YELLOW
    return RED


def ordered_levels(levels) -> tuple[str, ...]:
    return tuple(sorted(dict.fromkeys(levels), key=lambda level: ORDER.get(level, 99)))


class EffortSlider(Static):
    """Draws ``◂ ●──●──○ ▸`` with labels and a description for one model."""

    DEFAULT_CSS = """
    EffortSlider { height: auto; padding: 0 1; }
    """

    class Changed(Message):
        def __init__(self, level: str) -> None:
            super().__init__()
            self.level = level

    def on_click(self, event) -> None:
        event.stop()
        level = self.stop_at(event.x)
        if level is not None:
            self.post_message(self.Changed(level))

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self.stops: tuple[str, ...] = ()
        self.level = "default"
        self.default_hint: str | None = None
        self._positions: list[int] = []

    def show(self, levels, level: str, default_hint: str | None) -> None:
        known = ordered_levels(levels)
        self.stops = ("default", *known) if known else ()
        self.level = level if level in self.stops else "default"
        self.default_hint = default_hint
        self.display = True
        self.refresh(layout=True)

    def clear(self) -> None:
        self.stops = ()
        self.display = False

    def step(self, direction: int) -> str | None:
        if not self.stops:
            return None
        index = self.stops.index(self.level) + direction
        self.level = self.stops[max(0, min(len(self.stops) - 1, index))]
        self.refresh()
        return self.level

    def _label(self, stop: str) -> str:
        return tr("auto") if stop == "default" else tr(stop)

    def _spacing(self, width: int) -> int:
        count = len(self.stops)
        if count < 2:
            return 0
        available = max(0, width - len(PREFIX) - 4)
        return max(3, min(10, available // (count - 1) - 1))

    def render(self) -> Text:
        if not self.stops:
            card = Text(tr("Effort") + "  ", style=MUTED)
            card.append(tr("this model publishes no adjustable levels · provider default"), style=MUTED)
            return card
        width = max(20, self.size.width - 2)
        segment = self._spacing(width)
        selected = self.stops.index(self.level)
        color = level_color(self.level)
        line = Text(tr("Effort"), style=f"bold {TEXT}")
        line.append(PREFIX[len("Effort"):-3], style=TEXT)
        line.append("◂", style=CYAN if selected > 0 else MUTED)
        line.append("  ")
        self._positions = []
        for index, stop in enumerate(self.stops):
            if index:
                line.append("─" * segment, style=color if index <= selected else MUTED)
            self._positions.append(len(line.plain))
            if index == selected:
                line.append("◉", style=f"bold {color}")
            elif index < selected:
                line.append("●", style=color)
            else:
                line.append("○", style=MUTED)
        line.append("  ")
        line.append("▸", style=CYAN if selected < len(self.stops) - 1 else MUTED)
        labels = [" "] * (self._positions[-1] + 12)
        roomy = segment + 1 >= max(len(self._label(stop)) for stop in self.stops) + 1
        styles: list[tuple[int, int, str]] = []
        for index, (stop, position) in enumerate(zip(self.stops, self._positions)):
            if not roomy and index != selected:
                continue
            text = self._label(stop)
            start = max(0, position - len(text) // 2)
            labels[start:start + len(text)] = list(text)
            styles.append((start, start + len(text),
                           f"bold {level_color(stop)}" if index == selected else MUTED))
        label_line = Text("".join(labels).rstrip())
        for start, end, style in styles:
            label_line.stylize(style, start, end)
        if self.level == "default":
            description = (tr("Provider decides · currently {level}", level=self.default_hint)
                           if self.default_hint else tr("Provider decides the reasoning effort"))
        else:
            description = tr(DESCRIPTIONS.get(self.level, self.level))
        card = Text()
        card.append_text(line)
        card.append("\n")
        card.append_text(label_line)
        card.append("\n" + " " * len(PREFIX) + description, style=f"italic {MUTED}")
        return card

    def stop_at(self, x: int) -> str | None:
        """The stop under a click column, or a step from the ◂ / ▸ arrows."""
        if not self.stops or not self._positions:
            return None
        x -= 1  # padding
        if x <= len(PREFIX) - 2:
            return self.step(-1)
        if x >= self._positions[-1] + 2:
            return self.step(1)
        nearest = min(range(len(self._positions)), key=lambda i: abs(self._positions[i] - x))
        self.level = self.stops[nearest]
        self.refresh()
        return self.level
