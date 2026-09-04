"""Slider puzzle gap detection using OpenCV Canny edge template matching.

Extracts the alpha outline of the puzzle piece and matches it against the Canny
edge map of the background to locate the notch's x-coordinate.
"""
import cv2
import numpy as np


def find_gap_x(bg_bytes: bytes, piece_bytes: bytes) -> tuple:
    """Returns (gap_x, confidence). gap_x is the left edge of the notch in natural background pixels."""
    bg = cv2.imdecode(np.frombuffer(bg_bytes, np.uint8), cv2.IMREAD_COLOR)
    piece = cv2.imdecode(np.frombuffer(piece_bytes, np.uint8), cv2.IMREAD_UNCHANGED)
    if piece is None or bg is None:
        raise ValueError("Failed to decode captcha images")

    if piece.shape[2] == 4:
        alpha = piece[:, :, 3]
    else:
        alpha = cv2.cvtColor(piece, cv2.COLOR_BGR2GRAY)

    piece_edge = cv2.Canny(alpha, 100, 200)
    bg_edge = cv2.Canny(cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY), 100, 200)

    # Template must not exceed background dimensions
    if piece_edge.shape[0] > bg_edge.shape[0] or piece_edge.shape[1] > bg_edge.shape[1]:
        raise ValueError("Puzzle piece exceeds background dimensions")

    res = cv2.matchTemplate(bg_edge, piece_edge, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    return int(max_loc[0]), float(max_val)


if __name__ == "__main__":
    import sys
    from pathlib import Path
    bg = Path(sys.argv[1] if len(sys.argv) > 1 else "dbg_bg.jpg").read_bytes()
    piece = Path(sys.argv[2] if len(sys.argv) > 2 else "dbg_piece.png").read_bytes()
    x, conf = find_gap_x(bg, piece)
    print(f"gap_x={x} conf={conf:.3f}")