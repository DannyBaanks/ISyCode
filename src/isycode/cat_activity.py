"""Original subcell pixel cats for the composer activity track."""
from rich.text import Text


# Each terminal cell holds two by four dots; spaces preserve the silhouette.
# Loading-bar walk of U+130E0. The Noto glyph was mirrored to face right, its
# own leg strokes were swung, and each pose was downsampled with ascii-art
# (width 16, legacy box filter). One dot is dropped wherever a cell would be
# U+28FF, which DejaVu draws as .notdef. The resting sprites stay as they were.
_WALK_FRAMES = (
    (
        "................",
        "................",
        "...........###..",
        "..........#####.",
        "..........######",
        "........###.####",
        "....######..##..",
        "######.....##...",
        "..######....##..",
        ".##.##########..",
        ".##.#####..####.",
        ".####.#.##..#.##",
    ),
    (
        "................",
        "................",
        "...........###..",
        "..........#####.",
        "..........######",
        "........###.####",
        "....######..##..",
        "######.....##...",
        "..######....##..",
        ".##.##########..",
        ".##.#####..###..",
        ".####.#.#####.##",
    ),
    (
        "................",
        "................",
        "...........###..",
        "..........#####.",
        "..........######",
        "........###.####",
        "....######..##..",
        "######.....##...",
        "..######....##..",
        ".##.##########..",
        ".##..####.###...",
        ".######.#######.",
    ),
    (
        "................",
        "................",
        "...........###..",
        "..........#####.",
        "..........######",
        "........###.####",
        "....######..##..",
        "######.....##...",
        "..######..####..",
        ".##.##########..",
        ".##.#####..#####",
        ".####.#.#####.##",
    ),
)
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
    ".#...........#..",
    "..#.........#..#",
    "...#########...#",
    "...........####.",
)
# Face on the left, tail trailing on the right. The widest one is used when
# the caption line has room; the others keep a face and a tail in narrow columns.
_REST_FULL = (
    "#...#.............",
    "##.##.............",
    "#####.............",
    "#...#.............",
    ".###..##..........",
    "....#..#.#........",
    ".......#.#.#......",
    "........#...#.....",
)
_REST_MED = (
    "#.#.......",
    "#.#.......",
    "###.......",
    "#.........",
    ".###.#....",
    "...#.#.#..",
    "....#.#...",
    ".....#....",
)
_REST_TINY = (
    "#.#.",
    "#..#",
    ".##.",
    ".#..",
    ".##.",
    "..##",
    "..#.",
    "...#",
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
    bitmap = _WALK_FRAMES[tick % 4]
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


def _rest_rows(bitmap: tuple[str, ...]) -> tuple[str, str]:
    cols = max(len(row) for row in bitmap)
    if cols % 2:
        cols += 1
    packed = _dots(tuple(row.ljust(cols, ".")[:cols] for row in bitmap))
    return packed[0], packed[1]


def _clip_cells(text: str, width: int) -> str:
    from rich.cells import cell_len

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
    from rich.cells import cell_len

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


def sleeping_cat(width: int, caption: str = "Chat ready", caption_style: str = "#9aa3ad") -> Text:
    """Cat resting on the caption line, z on its face and a tail behind it.

    The walking pose still fills the activity box and bounces when a turn starts.
    A caption that does not fit beside the cat wraps inside the column.
    """
    from rich.cells import cell_len

    width = max(1, width)
    label = " ".join((caption or "Chat ready").split()) or "Chat ready"
    if width < 10:
        return Text(_clip_cells(label, width), style=caption_style)
    if cell_len(label) > width:
        return _wrapped_status(label, width, caption_style)

    loaf = _dots(_REST_LOAF)
    start = cell_len(label) + 1
    if start + 1 + cell_len(loaf[0]) <= width:
        result = Text()
        for row, pixels in enumerate(loaf):
            line = Text(label, style=caption_style) if row == 2 else Text(" " * cell_len(label))
            line.append(" ")
            line.append("z" if row == 1 else " ", style="#77d8b0")
            line.append(pixels, style="#77d8b0")
            line.append(" " * (width - start - 1 - cell_len(pixels)))
            result.append(line)
            if row < 2:
                result.append("\n")
        return result

    chosen: tuple[str, str, int] | None = None
    for bitmap, gap in (
        (_REST_FULL, 1), (_REST_MED, 1), (_REST_TINY, 1), (_REST_TINY, 0),
    ):
        top, body = _rest_rows(bitmap)
        block = 1 + cell_len(top)  # the z sits on the face, then the sprite
        if cell_len(label) + gap + block <= width:
            chosen = (top, body, gap)
            break

    blank = " " * width
    if chosen is None:
        result = Text()
        result.append(blank + "\n" + blank + "\n")
        result.append(label.ljust(width), style=caption_style)
        return result

    top, body, gap = chosen
    start = cell_len(label) + gap
    face = Text(" " * start)
    face.append("z" + top, style="#77d8b0")
    face.append(" " * (width - start - cell_len("z" + top)))
    feet = Text(label, style=caption_style)
    feet.append(" " * gap)
    feet.append(" " + body, style="#77d8b0")  # the space sits under the z
    feet.append(" " * (width - cell_len(label) - gap - cell_len(" " + body)))
    result = Text()
    result.append(blank)
    result.append("\n")
    result.append(face)
    result.append("\n")
    result.append(feet)
    return result
