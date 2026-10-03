"""Original cell-aligned walking cat for indeterminate activity."""
from rich.text import Text


def walking_cat(width: int, tick: int) -> Text:
    width = max(1, width)
    if width < 7:
        return Text(("[:3]" if tick % 2 else "[3:]").ljust(width)[:width], style="#77d8b0")
    travel = width - 7
    phase = tick % (2 * travel) if travel else 0
    right = phase <= travel
    position = phase if right else 2 * travel - phase
    legs = " ▘▝  " if tick % 2 else " ▝ ▘ "
    sprite = [" ▄▄▖ ", "▗██▛▘", legs]
    if not right:
        mirrors = str.maketrans("▗▖▛▜▘▝▙▟", "▖▗▜▛▝▘▟▙")
        sprite = [line[::-1].translate(mirrors) for line in sprite]
    result = Text()
    for row, pixels in enumerate(sprite):
        result.append("[" if row == 1 else " ", style="#9aa3ad")
        result.append(" " * position)
        result.append(pixels, style="bold #77d8b0")
        result.append(" " * (travel - position))
        result.append("]" if row == 1 else " ", style="#9aa3ad")
        if row != 2:
            result.append("\n")
    return result


def sleeping_cat(width: int) -> Text:
    """Curled-up, motionless cat; ready remains explicit below the track."""
    width = max(1, width)
    if width < 9:
        return Text("Chat ready"[:width], style="#9aa3ad")
    travel = width - 9
    left = travel // 2
    right = travel - left
    result = Text()
    result.append(" " + " " * left + " ▄▄  z " + " " * right + " ", style="#77d8b0")
    result.append("\n[", style="#9aa3ad")
    result.append(" " * left + "▗▟██▙▖ " + " " * right, style="#77d8b0")
    result.append("]\n", style="#9aa3ad")
    result.append("Chat ready"[:width].ljust(width), style="#9aa3ad")
    return result
