"""Every number in the Aurora chamber model, with its source and uncertainty.

Units are millimetres. Scene frame: x runs along the box from the antechamber-end
wall (x = 0) to the far end, y runs from the open side (the window that was off
during the walkthrough; y = 0 at deck level) to the far window, z is up from the
deck.

Sources:
  reconstruction  measured on the metric 3D reconstruction of the walkthrough
                  video (dense cloud, mesh, solved keyframe poses). Multiplied
                  by SCALE. Uncertainty is the reading's, on top of the
                  reconstruction's +/-4 % scale.
  datasheet       manufacturer's drawing or catalogue size. Not scaled.
  photo           read off the issue #23 photos or video frames, not measured.
  assumption      a placeholder until someone measures it.

Two numbers wait on a tape measure (see README, "Open items"):
  SCALE    tape reading / modelled length, for the QR sign's width (279.4 mm in
           the model) or the open-side window opening's inner length (1100 mm).
  RISER_H  the plate under the Epson's base, deck to the base's underside.
Both can be overridden without editing this file through the environment
variables AURORA_CHAMBER_SCALE and AURORA_CHAMBER_RISER_MM.
"""

import os
from dataclasses import dataclass

import numpy as np

SCALE = float(os.environ.get("AURORA_CHAMBER_SCALE", "1.0"))

# The reconstruction can't separate two readings of arm 2's top (z_drop +155 or +185), which give a riser
# of 150 or 180 mm with the datasheet's 465.3 mm from the base to the top of arm 2. 180 mm is the design
# value: it puts the robot highest, so it is the worst case for anything above the robot. Checks below
# the robot use the low end (see robot.swept_bands_at).
RISER_RANGE = (150.0, 180.0)
RISER_H = float(os.environ.get("AURORA_CHAMBER_RISER_MM", str(RISER_RANGE[1])))

SCALE_UNC_PCT = 4.0   # the reconstruction's scale, from the landscape-Letter QR sign


@dataclass(frozen=True)
class Param:
    value: object
    unc: str      # e.g. "+/-30 mm"; for reconstruction values this is on top of the +/-4 % scale
    source: str   # reconstruction | datasheet | photo | assumption
    note: str


PARAMS = {}


def param(name, value, unc, source, note):
    """Records a number's provenance and returns the value unchanged."""
    assert source in ("reconstruction", "datasheet", "photo", "assumption"), source
    PARAMS[name] = Param(value, unc, source, note)
    return value


param("SCALE", SCALE, f"+/-{SCALE_UNC_PCT:.0f} %", "reconstruction",
      "1 model unit = 185.4 mm, from the QR sign (US Letter landscape). One tape reading tightens it to about 1 %")
param("RISER_H", RISER_H, f"{RISER_RANGE[0]:.0f} to {RISER_RANGE[1]:.0f} mm", "reconstruction",
      "arm 2's top above the deck (615 or 645 mm) minus the datasheet's 465.3 mm. Not scaled: set it from a tape "
      "reading")

# --- The reconstruction's own frame ------------------------------------------------------------------
# Origin at the bottom-left corner of the QR sign on the antechamber-end wall; x into the box from the
# open side, y along the box (negative away from the antechamber), z up.

DROP_WALL_Y = param("DROP_WALL_Y", 15.0, "+/-10 mm", "reconstruction", "antechamber-end inner wall, drop y")
DROP_FRONT_X = param("DROP_FRONT_X", -162.0, "+/-15 mm", "reconstruction",
                     "open-side window frame at deck level, drop x")
DROP_DECK_Z = param("DROP_DECK_Z", -460.0, "+/-10 mm", "reconstruction", "deck, drop z")


def from_drop(x, y, z=DROP_DECK_Z):
    """Scene position of a point measured in the reconstruction's frame (scaled by SCALE)."""
    return SCALE * np.array([DROP_WALL_Y - y, x - DROP_FRONT_X, z - DROP_DECK_Z], float)


def to_drop(p):
    """Inverse of from_drop: reconstruction-frame position of a scene point."""
    p = np.asarray(p, float) / SCALE
    return np.array([p[1] + DROP_FRONT_X, DROP_WALL_Y - p[0], p[2] + DROP_DECK_Z])


# --- Glovebox shell ----------------------------------------------------------------------------------

GB_W = SCALE * param("GB_W", 1200.0, "+/-50 mm", "reconstruction",
                     "interior length, antechamber-end wall (drop y +15) to the far end wall (drop y -1185); "
                     "the far end is the least covered part of the cloud")
GB_D = SCALE * param("GB_D", 1120.0, "+/-30 mm", "reconstruction",
                     "interior depth at the deck, open-side frame (drop x -162) to the far window (drop x +958)")
GB_H = SCALE * param("GB_H", 790.0, "+/-15 mm", "reconstruction",
                     "deck (drop z -460) to ceiling (drop z +330); the ceiling's highest points reach +345")
FRONT_LEAN = SCALE * param("FRONT_LEAN", 57.0, "+/-15 mm", "reconstruction",
                           "the open-side window is this much further in at the ceiling than at the deck")
BACK_LEAN = SCALE * param("BACK_LEAN", 60.0, "+/-15 mm", "reconstruction", "the far window leans in by this much")
WALL_T = param("WALL_T", 12.0, "unknown", "assumption", "wall, deck and ceiling thickness (drawing only)")
STAND_H = param("STAND_H", 880.0, "+/-100 mm", "assumption",
                "stand height under the deck; the floor isn't in the reconstruction (the stand runs >= 450 mm "
                "below the lip)")
OPENING = SCALE * np.array(param("OPENING", (50.0, 1150.0, 55.0, 765.0), "+/-20 mm", "reconstruction",
                                 "open-side window opening: x0, x1, z0, z1 (1.10 x 0.71 m); rays from the "
                                 "14:06 keyframe"))
FLANGE_PITCH = SCALE * param("FLANGE_PITCH", 95.0, "+/-10 mm", "reconstruction",
                             "welded studs round both window openings, about every 95 mm")
FLANGE_STUD_LEN = param("FLANGE_STUD_LEN", 45.0, "+/-10 mm", "reconstruction",
                        "flange studs stand about 45 mm proud; acorn nuts on some")
STUD_THREAD = param("STUD_THREAD", "M6", "unknown", "assumption",
                    "thread of the welded studs (flange and ceiling); nobody has measured it")
STUD_D = param("STUD_D", 6.0, "unknown", "assumption", "major diameter for STUD_THREAD")
CEILING_STUD_LEN = param("CEILING_STUD_LEN", 25.0, "unknown", "assumption",
                         "ceiling studs' length below the ceiling (the mount designs need >= 13.6 mm)")
GLOVE_R = param("GLOVE_R", 102.0, "+/-5 mm", "datasheet", "8-inch glove ports (LC Technology), port radius")
GLOVE_X_FRAC = param("GLOVE_X_FRAC", (0.29, 0.71), "+/-100 mm", "assumption",
                     "two glove ports per side, at these fractions of the length; not in the reconstruction")
GLOVE_X = tuple(f * GB_W for f in GLOVE_X_FRAC)
GLOVE_Z = SCALE * param("GLOVE_Z", 400.0, "+/-50 mm", "assumption", "glove-port centre height above the deck")

# --- Wall sign: the scale reference -----------------------------------------------------------------

SIGN_SIZE = param("SIGN_SIZE", (279.4, 215.9), "exact", "datasheet",
                  "US Letter landscape; bottom-left corner is the drop frame's origin")
SIGN = (from_drop(0.0, 0.0, 0.0), from_drop(SIGN_SIZE[0], 0.0, SIGN_SIZE[1]))

# --- Antechambers -----------------------------------------------------------------------------------

ANTE_DOOR_DROP = param("ANTE_DOOR_DROP", (297.0, 0.0, -249.0), "+/-20 mm", "reconstruction",
                       "large antechamber inner door hub (drop x, y, z); rays from the 18:30 keyframe")
ANTE_DOOR_C = from_drop(*ANTE_DOOR_DROP) * np.array([0.0, 1.0, 1.0])
ANTE_DOOR_R = SCALE * param("ANTE_DOOR_R", 190.0, "+/-15 mm", "datasheet",
                            "LC Technology 15-inch antechamber; the reconstruction's 0.18 to 0.2 m matches the radius")
MINI_C = SCALE * np.array(param("MINI_C", (0.0, 150.0, 150.0), "+/-50 mm", "photo",
                                "mini (6-inch) antechamber, lower open-side corner of the same wall; not in the "
                                "reconstruction"))
MINI_R = param("MINI_R", 80.0, "+/-10 mm", "datasheet", "6-inch mini antechamber tube radius")

# --- Exfoliator (along the open side) ---------------------------------------------------------------

EXF_DROP_Y = param("EXF_DROP_Y", (-150.0, -1150.0), "+/-30 mm", "reconstruction",
                   "exfoliator's extent along the box, drop y")
EXF_DROP_X = param("EXF_DROP_X", (-130.0, 370.0), "+/-30 mm", "reconstruction",
                   "exfoliator's extent across the box, drop x")
EXF_X0, EXF_X1 = from_drop(0, EXF_DROP_Y[0])[0], from_drop(0, EXF_DROP_Y[1])[0]
EXF_Y0, EXF_Y1 = from_drop(EXF_DROP_X[0], 0)[1], from_drop(EXF_DROP_X[1], 0)[1]
EXF_DECK_Z = SCALE * param("EXF_DECK_Z", 160.0, "+/-15 mm", "reconstruction",
                           "breadboard top on its posts (drop z -300)")
EXF_STROKE = param("EXF_STROKE", 400.0, "exact", "photo", "rear linear stage stroke ('400mm' on the axis)")
EXF_C = np.array([(EXF_X0 + EXF_X1) / 2, (EXF_Y0 + EXF_Y1) / 2, 0.0])
COLUMN_XY = from_drop(*param("COLUMN_DROP", (106.0, -547.0), "+/-20 mm", "reconstruction",
                             "vertical press column (drop x, y)"))[:2]
SPOOL_C = from_drop(*param("SPOOL_DROP", (150.0, -720.0, -156.0), "+/-20 mm", "reconstruction",
                           "supply spool centre, red flange and blue tape (drop x, y, z)"))
TIP_C = from_drop(*param("TIP_DROP", (130.0, -690.0, -245.0), "+/-20 mm", "reconstruction",
                         "roller on the tape, the exfoliation point (drop x, y, z); rays from the 03:14 keyframe"))
PLATE_C = from_drop(*param("PLATE_DROP", (256.0, -502.0, -245.0), "+/-15 mm", "reconstruction",
                           "white substrate plate on the rear stage, centre of its top (drop x, y, z); white "
                           "points in the cloud and the 17:58 keyframe"))
PLATE_SIZE = SCALE * np.array(param("PLATE_SIZE", (160.0, 180.0), "+/-15 mm", "reconstruction",
                                    "substrate plate, x by y"))
ESTOP_C = from_drop(*param("ESTOP_DROP", (43.0, -992.0, -274.0), "+/-20 mm", "reconstruction",
                           "e-stop on the LED source (drop x, y, z)"))
MICRO_STAGE_C = from_drop(*param("MICRO_STAGE_DROP", (176.0, -966.0, -236.0), "+/-30 mm", "reconstruction",
                                 "microscope XY stage (drop x, y, z)"))
MICRO_OBJ_C = from_drop(*param("MICRO_OBJ_DROP", (219.0, -1102.0, -192.0), "+/-30 mm", "reconstruction",
                               "microscope objective (drop x, y, z)"))
TRAY_SIZE = param("TRAY_SIZE", (150.0, 120.0, 14.0), "+/-10 mm", "photo",
                  "8 x 8 chip tray in its metal holder, on the substrate plate (6 Nov close-up)")

# --- Epson T6-B602S SCARA, standing on a riser behind the exfoliator --------------------------------
# Model settled from the reconstruction: J1-J2 measures about 300 mm and J2-J3 about 260 mm in the parked
# pose (T6-B: 325 + 275; T3-B: 225 + 175), arm 2's housing is about 350 x 170 x 200 mm, and the substrate
# plate is 592 mm from J1, out of a T3-B's 400 mm reach. Heights are from Epson's T6-B outline drawing
# (T-B manual rev. 6, 2.3.2), measured from the underside of the base.

EPSON_MODEL = param("EPSON_MODEL", "T6-B602S", "settled", "reconstruction",
                    "arm lengths, housing size and reach to the substrate plate; T3-B401S ruled out")
EPSON_L1 = param("EPSON_L1", 325.0, "exact", "datasheet", "J1 to J2 (T6-B602S)")
EPSON_L2 = param("EPSON_L2", 275.0, "exact", "datasheet", "J2 to J3 (T6-B602S)")
EPSON_STROKE = param("EPSON_STROKE", 200.0, "exact", "datasheet", "J3 (Z) stroke")
EPSON_J1_RANGE = param("EPSON_J1_RANGE", 132.0, "exact", "datasheet",
                       "J1 range is +/-132 deg about the base's forward direction; the swept volume uses a full "
                       "turn because the base's facing is unknown")
T6 = param("T6", dict(arm1=(209.5, 259.5), arm2=(272.5, 465.3), box=(289.2, 465.3), shaft_top=590.5,
                      duct_max=700.0, arm1_w=90.0, arm2_w=135.5, arm2_end=58.5, shaft_r=10.0, nut_r=19.0,
                      base=(150.0, 35.0, 160.0)),
           "+/-2 mm", "datasheet",
           "T6-B outline: arm 1 and arm 2 z ranges, controller box, shaft top at Z fully up, duct arch height, "
           "widths, arm 2 end radius, shaft and nut radii, base (width, front, back); heights above the base")
ARM2_FITTINGS = param("ARM2_FITTINGS", 25.0, "+/-10 mm", "reconstruction",
                      "fittings on arm 2 stand this far above its cover")
SHAFT_NUT = param("SHAFT_NUT", 10.0, "+/-5 mm", "assumption", "nut and fittings on top of the J3 shaft")
TOOL_BELOW_BASE = param("TOOL_BELOW_BASE", 45.0, "+/-30 mm", "assumption",
                        "lowest point of the vacuum tool below the base's underside at Z fully down")
J1_DROP = param("J1_DROP", (670.0, -925.0), "+/-30 mm", "reconstruction",
                "J1 axis (drop x, y); joint positions from rays cast from the 17:58 keyframe and the duct's legs")
PARK_J3_DROP = param("PARK_J3_DROP", (568.0, -895.0), "+/-30 mm", "reconstruction",
                     "J3 in the parked pose of the walkthrough (drop x, y)")
BASE_BACK = np.array(param("BASE_BACK", (0.0, 1.0), "unknown", "assumption",
                           "unit vector from J1 to the back of the base (cable outlet); drawn towards the far "
                           "window. Which way the base faces is open"))
DUCT_UNDER_CEILING = param("DUCT_UNDER_CEILING", 6.0, "+/-10 mm", "photo",
                           "the duct arches to just under the ceiling in the video; Epson's 700 mm arch would "
                           "be above it, so the model caps it here")
SCARA_XY = from_drop(*J1_DROP)[:2]
SCARA_PARK_J3 = from_drop(*PARK_J3_DROP)[:2]
SHELF_T = SCALE * param("SHELF_T", 13.0, "+/-5 mm", "photo",
                        "black breadboard under the robot (teal strips in the 6 Nov close-up)")

# --- Ceiling --------------------------------------------------------------------------------------------

CEILING_STUDS_DROP = param(
    "CEILING_STUDS_DROP",
    {"S1": (420.0, -46.0), "S2": (122.0, -230.0), "S3": (427.0, -421.0), "S4": (129.0, -562.0)},
    "+/-50 mm", "reconstruction",
    "welded ceiling studs circled in the 6 Nov upward photo (drop x, y); rays from the solved 14:06 keyframe "
    "onto the ceiling")
CEILING_STUD_NOTES = {
    "S1": ("free", "between two ceiling ports, antechamber end"),
    "S2": ("free", "single stud, open side"),
    "S3": ("free", "between two ceiling ports, middle"),
    "S4": ("taken", "clamp bracket already on it"),
}
CEILING_SLOT = (from_drop(-15, -307), from_drop(50, -841))
param("CEILING_SLOT_DROP", ((-15.0, -307.0), (50.0, -841.0)), "+/-30 mm", "reconstruction",
      "recess along the top of the open side (drop x, y corners)")
TERMINAL_BOX = (from_drop(716, -225), from_drop(699, -615))
param("TERMINAL_BOX_DROP", ((716.0, -225.0), (699.0, -615.0)), "+/-30 mm", "reconstruction",
      "black terminal rail with red wiring on the ceiling's far edge (drop x, y ends)")
FILTER_C = from_drop(-13, -134)
param("FILTER_DROP", (-13.0, -134.0), "+/-30 mm", "reconstruction", "filter cartridge on the ceiling (drop x, y)")
DOME_C = np.array([SCALE * param("DOME_X", 300.0, "+/-100 mm", "photo", "Amcrest dome, front left of the ceiling"),
                   SCALE * param("DOME_Y", 130.0, "+/-100 mm", "photo", "Amcrest dome, behind the top flange"),
                   GB_H])


def params_table(sources=None):
    """Markdown table of every parameter (optionally only some sources)."""
    rows = ["| Name | Value | Uncertainty | Source | Note |", "|---|---|---|---|---|"]
    for name, p in PARAMS.items():
        if sources and p.source not in sources:
            continue
        v = p.value
        if isinstance(v, dict) and name == "T6":
            v = "see robot.py"
        rows.append(f"| `{name}` | {v} | {p.unc} | {p.source} | {p.note} |")
    return "\n".join(rows)
