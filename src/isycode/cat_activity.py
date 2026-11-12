"""Original subcell pixel cats for the composer activity track."""
from rich.cells import cell_len
from rich.text import Text


_CAT = "#f6a34a"
_TRACK = "#9aa3ad"
# Original hand-drawn kitten: round head, two ears, short back, four paws
# and an upright curled tail. Sparse outlines keep the 2×4 subcell dots clear.
_BODY = (
    "........#..#....",
    "........####....",
    ".......#....#...",
    "..##...#.#..##..",
    ".#..#..#....#...",
    ".#..#...####....",
    "..#..####..#....",
    "..#.#......#....",
    "...##......#....",
)
# The tail tip leans back on every other step.
_TAIL_SWAY = (
    ".##.",
    "#..#",
    "#..#",
    ".#..",
)
_EYE = (3, 9)
# One stride: stand, reach, gather, push. Each pose is held for two ticks.
_LEGS = (
    ("....#.#..#.#....",
     "....#.#..#.#....",
     "....##...##....."),
    ("....#.#..#.#....",
     "...#..#..#..#...",
     "...#..#...#.#..."),
    ("....#.#..#.#....",
     "....#..##..#....",
     "....##....##...."),
    ("....#.#..#.#....",
     ".....#.#..#.#...",
     ".....#.#..#.#..."),
)
_SPRITE_PIXELS = 16
_SPRITE_CELLS = _SPRITE_PIXELS // 2
_STEP_TICKS = 2
_SWAY_TICKS = 4
# At each end of the track the cat stops, blinks and turns round.
_TURN_TICKS = 6
_BLINK = (2, 3)
# Whole cat curled up on all three rows: ears, closed eyes, back, belly and a
# tail curling out on the right. Used whenever the column has room for it.
_REST_LOAF = (
    ".#...#..........",
    ".##.##..........",
    ".#####..........",
    "#.....#.........",
    "#.##.##.####....",
    "#.....##....#...",
    ".#####......#...",
    ".#...........#..",
    ".#...........#.#",
    "..#.........#..#",
    "...#########...#",
    "...........####.",
)
# The same cat lying flat in two rows. A narrow column keeps the whole animal
# above its caption instead of a clipped piece of one beside it.
_REST_LOW = (
    ".#...#............",
    ".##.##...#####....",
    ".#####.##.....#...",
    "#.....##.......#..",
    "#.##.##........#.#",
    "#.....#........#.#",
    ".#####.........#.#",
    "..#############.#.",
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


def _walk_pose(step: int, sway: bool, blink: bool) -> tuple[str, ...]:
    rows = list(_BODY)
    if sway:
        for index, tail in enumerate(_TAIL_SWAY):
            rows[3 + index] = tail + rows[3 + index][len(tail):]
    if blink:
        y, x = _EYE
        rows[y] = rows[y][:x] + "." + rows[y][x + 1:]
    return tuple(rows) + _LEGS[step % len(_LEGS)]


def walk_period(width: int) -> int:
    """Ticks until the walk repeats: out, turn, back, turn."""
    travel = (max(10, width) - 2 - _SPRITE_CELLS) * 2
    if not travel:
        return len(_LEGS) * _STEP_TICKS * _SWAY_TICKS
    return 2 * (travel + _TURN_TICKS)


def _ascii_walk(width: int, tick: int) -> Text:
    face = "=^.^="
    if width < 10:
        return Text(("[:3]" if tick % 2 else "[3:]").ljust(width)[:width], style=_CAT)
    travel = width - 2 - len(face)
    phase = (tick // _STEP_TICKS) % (2 * travel) if travel else 0
    position = phase if phase <= travel else 2 * travel - phase
    result = Text(" " * width + "\n")
    result.append("[", style=_TRACK)
    result.append(" " * position)
    result.append(face, style=_CAT)
    result.append(" " * (travel - position))
    result.append("]", style=_TRACK)
    result.append("\n" + " " * width)
    return result


def walking_cat(width: int, tick: int, ascii_only: bool = False) -> Text:
    """The kitten pacing its track one subcell dot per tick."""
    width = max(1, width)
    if ascii_only or width < 10:
        return _ascii_walk(width, tick)
    travel = (width - 2 - _SPRITE_CELLS) * 2
    turning = blink = False
    right, offset = True, 0
    tick %= walk_period(width)
    if travel:
        phase = tick
        half = travel + _TURN_TICKS
        right = phase < half
        along = phase % half
        turning = along >= travel
        blink = turning and along - travel in _BLINK
        offset = min(along, travel) if right else travel - min(along, travel)
    step = 0 if turning else tick // _STEP_TICKS
    bitmap = _walk_pose(step, (tick // _SWAY_TICKS) % 2 == 1, blink)
    if not right:
        bitmap = tuple(row[::-1] for row in bitmap)
    canvas = tuple("." * offset + row + "." * (travel - offset) for row in bitmap)
    result = Text()
    for row, pixels in enumerate(_dots(canvas)):
        result.append("[" if row == 1 else " ", style=_TRACK)
        result.append(pixels, style=_CAT)
        result.append("]" if row == 1 else " ", style=_TRACK)
        if row != 2:
            result.append("\n")
    return result



def _clip_cells(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if cell_len(text) <= width:
        return text
    if width == 1:
        return text[:1]
    ellipsis = "…"
    budget = width - cell_len(ellipsis)
    cut = text
    while cut and cell_len(cut) > budget:
        cut = cut[:-1]
    return (cut.rstrip() + ellipsis) if cut else ellipsis


def _wrap_words(label: str, width: int, rows: int = 3) -> list[str]:
    """Fit a status into the activity column. No line paints past that column."""
    words = label.split(" ")
    lines: list[str] = []
    current = ""
    index = 0
    while index < len(words) and len(lines) < rows:
        word = words[index]
        candidate = word if not current else f"{current} {word}"
        if cell_len(candidate) <= width:
            current = candidate
            index += 1
            continue
        if current:
            lines.append(current)
            current = ""
            continue
        lines.append(_clip_cells(word, width))
        index += 1
    if current and len(lines) < rows:
        lines.append(current)
    if index < len(words) and lines:
        lines[-1] = _clip_cells(lines[-1] + " …", width)
    # Blanks go under the words. A blank on top drops the last line onto the prompt border.
    while len(lines) < rows:
        lines.append("")
    padded = []
    for line in lines[:rows]:
        gap = width - cell_len(line)
        padded.append(line + (" " * gap if gap > 0 else ""))
    return padded


def _wrapped_status(label: str, width: int, style: str) -> Text:
    result = Text()
    for index, line in enumerate(_wrap_words(label, width)):
        if index:
            result.append("\n")
        result.append(line, style=style)
    return result


def sleeping_cat(width: int, caption: str = "Chat ready", caption_style: str = "#9aa3ad",
                 ascii_only: bool = False) -> Text:
    """Curled kitten with a visible tail and stepped sleep marks when space permits.

    The walking pose still fills the activity box and bounces when a turn starts.
    A caption that does not fit beside the cat wraps inside the column, and a
    column too narrow for the whole cat keeps the caption alone.
    """
    width = max(1, width)
    label = " ".join((caption or "Chat ready").split()) or "Chat ready"
    if width < 10:
        return Text(_clip_cells(label, width), style=caption_style)
    if cell_len(label) > width:
        return _wrapped_status(label, width, caption_style)
    blank = " " * width
    if ascii_only:
        nap = "=-.-= z"
        result = Text(blank + "\n")
        result.append(nap.ljust(width)[:width] if len(nap) <= width else blank, style=_CAT)
        result.append("\n")
        result.append(label.ljust(width), style=caption_style)
        return result

    loaf = _dots(_REST_LOAF)
    start = cell_len(label) + 1
    sleep_width = 3 if start + 3 + cell_len(loaf[0]) <= width else 1
    if start + sleep_width + cell_len(loaf[0]) <= width:
        result = Text()
        for row, pixels in enumerate(loaf):
            line = Text(label, style=caption_style) if row == 2 else Text(" " * cell_len(label))
            line.append(" ")
            sleep = ("  z", " z ", "z  ")[row] if sleep_width == 3 else ("z" if row == 1 else " ")
            line.append(sleep, style=_CAT)
            line.append(pixels, style=_CAT)
            line.append(" " * (width - start - sleep_width - cell_len(pixels)))
            result.append(line)
            if row < 2:
                result.append("\n")
        return result

    # The cat lies on the caption: whole animal above, words below.
    low = _dots(_REST_LOW)
    result = Text()
    for row, pixels in enumerate(low):
        result.append(pixels, style=_CAT)
        room = width - cell_len(pixels)
        result.append((" z" if row == 0 and room >= 2 else "").ljust(room), style=_CAT)
        result.append("\n")
    result.append(label.ljust(width), style=caption_style)
    return result
