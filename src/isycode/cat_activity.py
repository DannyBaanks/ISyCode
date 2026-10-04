"""Original subcell pixel cats for the composer activity track."""
from rich.text import Text


# Each terminal cell holds two by four dots; spaces preserve the silhouette.
_WALK = (
    "..........#...#.",
    ".........##..##.",
    ".##......######.",
    "#..#.....#..#.#.",
    "#..#.....#....##",
    "#...######...#..",
    ".#.#......###...",
    "..##.......#....",
    "...#.......#....",
    "...#########....",
)
_SLEEP = (
    "..#...#.......",
    "..##.##..###..",
    "..#####.#...#.",
    "..#...##.....#",
    "..#.#.#..##..#",
    "...###..#..#.#",
    "..#.....####.#",
    "...##########.",
)


def _dots(bitmap: tuple[str, ...]) -> list[str]:
    """Pack a hand-drawn bitmap into Unicode Braille without solid blocks."""
    bits = ((1, 8), (2, 16), (4, 32), (64, 128))
    rows = []
    for y in range(0, len(bitmap), 4):
        row = ""
        for x in range(0, len(bitmap[0]), 2):
            mask = sum(bits[dy][dx] for dy in range(4) for dx in range(2)
                       if y + dy < len(bitmap) and bitmap[y + dy][x + dx] == "#")
            row += chr(0x2800 + mask) if mask else " "
        rows.append(row)
    return rows


def walking_cat(width: int, tick: int) -> Text:
    width = max(1, width)
    if width < 10:
        return Text(("[:3]" if tick % 2 else "[3:]").ljust(width)[:width], style="#77d8b0")
    travel = width - 10
    phase = tick % (2 * travel) if travel else 0
    right = phase <= travel
    position = phase if right else 2 * travel - phase
    feet = ("...#.#...#.#....", "..##......##....") if tick % 2 else (
        "....#.#.#.#.....", "....##..##......")
    bitmap = _WALK + feet
    if not right:
        bitmap = tuple(row[::-1] for row in bitmap)
    result = Text()
    for row, pixels in enumerate(_dots(bitmap)):
        result.append("[" if row == 1 else " ", style="#9aa3ad")
        result.append(" " * position)
        result.append(pixels, style="#77d8b0")
        result.append(" " * (travel - position))
        result.append("]" if row == 1 else " ", style="#9aa3ad")
        if row != 2:
            result.append("\n")
    return result


def sleeping_cat(width: int, caption: str = "Chat ready", caption_style: str = "#9aa3ad") -> Text:
    """Outlined cat with its tail curled around its body, resting quietly."""
    width = max(1, width)
    label = " ".join((caption or "Chat ready").split()) or "Chat ready"
    if width < 10:
        return Text(label[:width], style=caption_style)
    travel = width - 10
    left = travel // 2
    right = travel - left
    sprite = _dots(_SLEEP)
    result = Text()
    result.append(" " + " " * left + sprite[0] + "z" + " " * right + " ", style="#77d8b0")
    result.append("\n[", style="#9aa3ad")
    result.append(" " * left + sprite[1] + " " + " " * right, style="#77d8b0")
    result.append("]\n", style="#9aa3ad")
    result.append(label[:width].ljust(width), style=caption_style)
    return result
