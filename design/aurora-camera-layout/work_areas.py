"""Work areas the camera plan proposes (26 Oct walkthrough), drawn on the chamber model.

Not designated yet. Drawn on the deck behind the exfoliator, beside the
antechamber door and outside the robot's reach. That corner isn't empty in the
reconstruction (something about 0.5 m tall stands at x 50-400, y 800-1060).
"""

import numpy as np

import aurora_chamber as ch
from aurora_chamber.primitives import box, cyl, ring

UNPACK_C = np.array([ch.SCALE * 150.0, ch.SCALE * 690.0, 0.0])
MOTHER_TAPE_C = np.array([ch.SCALE * 190.0, ch.SCALE * 950.0, 0.0])


def floor_zone(center, size, color):
    """Thin coloured mat marking a designated area on the deck (or a plate)."""
    return box((center[0], center[1], center[2] + 1.5), (size[0], size[1], 3.0)), color


def unpack_area():
    out = [floor_zone(UNPACK_C, (260, 220), "#ffd8b5")]
    cx, cy, _ = UNPACK_C
    out.append((cyl((cx - 60, cy + 40, 35), (0, 0, 1), 32, 70), "#7a4b2a"))   # shipping jar
    out.append((cyl((cx - 60, cy + 40, 74), (0, 0, 1), 34, 10), "#333333"))   # lid
    out.append((box((cx + 50, cy - 30, 8), (110, 80, 10)), "#e9eef3"))       # opened bag
    out.append((cyl((cx + 40, cy + 60, 12), (0, 0, 1), 18, 18), "#bfc6cc"))   # vial
    return out


def mother_tape_area():
    out = [floor_zone(MOTHER_TAPE_C, (240, 180), "#cfe8ff")]
    cx, cy, _ = MOTHER_TAPE_C
    out.append((box((cx, cy, 6), (190, 110, 6)), "#2a8c6e"))                       # cutting mat
    out.append((ring((cx - 60, cy + 60, 22), (0, 0, 1), 18, 34, 22), ch.BLUE_TAPE))  # tape roll
    out.append((box((cx + 20, cy, 10), (120, 40, 1.5)), ch.BLUE_TAPE))              # mother tape strip
    return out
