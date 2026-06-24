"""render connect four boards as jpeg images."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

COLS = 7
ROWS = 6
CELL = 72
PAD = 28
HEADER = 36

BG = "#1e1f22"
FRAME = "#2563eb"
SLOT = "#0b1220"
RED = "#ef4444"
YELLOW = "#facc15"
LABEL = "#94a3b8"
WIN_GLOW = "#38bdf8"


def render_connect4_board(
    board: list[list[int]],
    *,
    last_move: tuple[int, int] | None = None,
) -> BytesIO:
    width = COLS * CELL + PAD * 2
    height = ROWS * CELL + PAD * 2 + HEADER
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    frame_left = PAD - 8
    frame_top = PAD + HEADER - 8
    frame_right = width - PAD + 8
    frame_bottom = height - PAD + 8
    draw.rounded_rectangle(
        (frame_left, frame_top, frame_right, frame_bottom),
        radius=24,
        fill=FRAME,
    )

    for col in range(COLS):
        cx = PAD + col * CELL + CELL // 2
        draw.text((cx - 6, 10), str(col + 1), fill=LABEL)

    for row in range(ROWS):
        for col in range(COLS):
            cx = PAD + col * CELL + CELL // 2
            cy = PAD + HEADER + row * CELL + CELL // 2
            cell = board[row][col]
            fill = SLOT
            if cell == 1:
                fill = RED
            elif cell == 2:
                fill = YELLOW
            radius = CELL // 2 - 8
            if last_move == (row, col) and cell:
                draw.ellipse(
                    (cx - radius - 4, cy - radius - 4, cx + radius + 4, cy + radius + 4),
                    fill=WIN_GLOW,
                )
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=fill)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=92, optimize=True)
    buf.seek(0)
    return buf
