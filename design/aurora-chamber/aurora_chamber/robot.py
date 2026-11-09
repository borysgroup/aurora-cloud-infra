"""Epson T6-B602S kinematics and swept volume, as functions of the riser height.

The swept volume is a stack of bands around J1, taken over a full J1 turn (the
real range is +/-132 deg, but which way the base faces is unknown):

  shaft    r <= L1 + L2 + nut radius   from the tool's lowest point to the shaft top at Z fully up
  arm 2    r <= L1 + L2 + end radius   from arm 2's underside to its fittings
  arm 1    r <= L1 + 67                arm 1's own height band
  duct     r <= L1 + 40                from arm 2's top to the duct arch, capped just under the ceiling

Anything above the robot is worst case at the high riser (RISER_RANGE[1]),
anything below it at the low one, so the checks take the union over the range.
"""

import numpy as np

from .params import (DUCT_UNDER_CEILING, EPSON_L1, EPSON_L2, EPSON_STROKE, GB_H, RISER_H, RISER_RANGE,
                     SCARA_PARK_J3, SCARA_XY, SHAFT_NUT, T6, TOOL_BELOW_BASE, ARM2_FITTINGS)

ARM1_R = EPSON_L1 + 67.0          # arm 1's housing round J2
ARCH_R = EPSON_L1 + 40.0          # the duct runs from over J1 to over J2, plus its own radius
SCARA_REACH = EPSON_L1 + EPSON_L2 + T6["arm2_end"]   # arm 2's housing, 658.5 mm
SHAFT_REACH = EPSON_L1 + EPSON_L2 + T6["nut_r"]      # the J3 shaft and its nut, 619 mm


def base_xyz(riser=None):
    """J1 axis (x, y) and the underside of the base (z)."""
    return np.r_[SCARA_XY, RISER_H if riser is None else riser]


def envelope(riser=None):
    """Heights and radii of the swept volume for one riser height."""
    bz = RISER_H if riser is None else float(riser)
    return dict(
        riser=bz,
        tool_low=bz - TOOL_BELOW_BASE,
        shaft_r=SHAFT_REACH, shaft_top=bz + T6["shaft_top"] + SHAFT_NUT,
        arm2_r=SCARA_REACH, arm2_low=bz + T6["arm2"][0], arm2_top=bz + T6["arm2"][1] + ARM2_FITTINGS,
        arm1_r=ARM1_R, arm1_low=bz + T6["arm1"][0], arm1_top=bz + T6["arm1"][1],
        arch_r=ARCH_R, arch_low=bz + T6["arm2"][1], arch_top=duct_top(bz),
    )


def duct_top(riser=None):
    """Duct arch's top: 700 mm above the base in Epson's drawing, but no higher than just under the ceiling."""
    bz = RISER_H if riser is None else riser
    return min(bz + T6["duct_max"], GB_H - DUCT_UNDER_CEILING)


def _bands_one(r, e):
    bands = []
    if r <= e["shaft_r"]:
        bands.append(("shaft", e["tool_low"], e["shaft_top"]))
    if r <= e["arm2_r"]:
        bands.append(("arm 2", e["arm2_low"], e["arm2_top"]))
    if r <= e["arm1_r"]:
        bands.append(("arm 1", e["arm1_low"], e["arm1_top"]))
    if r <= e["arch_r"]:
        bands.append(("duct", e["arch_low"], e["arch_top"]))
    return bands


def swept_bands_at(xy, risers=RISER_RANGE, xy_margin=0.0):
    """Height bands (name, z0, z1) the robot can occupy above (x, y), over every riser in `risers`.

    With two risers the band runs from the lower riser's bottom to the higher riser's top, which covers
    every riser in between. xy_margin grows the radii (e.g. by J1's +/-30 mm position uncertainty).
    """
    risers = np.atleast_1d(risers).astype(float)
    r = float(np.hypot(xy[0] - SCARA_XY[0], xy[1] - SCARA_XY[1])) - xy_margin
    lo = _bands_one(r, envelope(risers.min()))
    hi = {n: z1 for n, _, z1 in _bands_one(r, envelope(risers.max()))}
    return [(n, z0, max(z1, hi.get(n, z1))) for n, z0, z1 in lo]


def robot_top_at(xy, riser=None, xy_margin=0.0):
    """Highest point the robot can reach above (x, y): duct, shaft or arm 2, whichever applies (0 if none)."""
    risers = RISER_RANGE[1] if riser is None else riser
    bands = swept_bands_at(xy, risers, xy_margin)
    return max((z1 for _, _, z1 in bands), default=0.0)


def joints(target, elbow_left=True):
    """J1, J2, J3 (x, y) for the arm reaching `target` (x, y)."""
    bx, by = SCARA_XY
    dx, dy = target[0] - bx, target[1] - by
    r = np.clip(np.hypot(dx, dy), abs(EPSON_L1 - EPSON_L2) + 1, EPSON_L1 + EPSON_L2 - 1)
    elbow = np.arccos((r**2 - EPSON_L1**2 - EPSON_L2**2) / (2 * EPSON_L1 * EPSON_L2))
    if not elbow_left:
        elbow = -elbow
    t1 = np.arctan2(dy, dx) - np.arctan2(EPSON_L2 * np.sin(elbow), EPSON_L1 + EPSON_L2 * np.cos(elbow))
    j1 = np.array([bx, by])
    j2 = j1 + EPSON_L1 * np.array([np.cos(t1), np.sin(t1)])
    j3 = j2 + EPSON_L2 * np.array([np.cos(t1 + elbow), np.sin(t1 + elbow)])
    return j1, j2, j3


def shaft_top_z(quill_z):
    """Top of the J3 shaft for a tool height `quill_z` (the shaft moves with the tool)."""
    return quill_z + (T6["shaft_top"] - EPSON_STROKE)


PARK_J3 = SCARA_PARK_J3
