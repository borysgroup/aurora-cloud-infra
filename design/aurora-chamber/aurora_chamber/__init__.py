"""Aurora glovebox (Borys group, U of U) as a measured model that designs can build on.

    import sys; sys.path.insert(0, "design/aurora-chamber")
    import aurora_chamber as ac

    ac.GB_H                        # interior height, mm (scene frame, see params.py)
    ac.CEILING_STUDS["S2"]["xy"]   # a welded ceiling stud
    ac.robot_clearance(mesh)       # gap to the Epson's swept volume (riser 150 to 180 mm)
    ac.camera_view(origin, target, ac.FOV["cm3"])
    ac.PARAMS["GB_W"]              # value, uncertainty, source and note of any number

The STEP/STL export lives in aurora_chamber.cad (needs CadQuery), so it isn't imported here.
"""

from . import checks, params, robot, scene  # noqa: F401
from .checks import (FOV, CameraView, as_points, camera_view, fixed_clearance, grid_on_rect,  # noqa: F401
                     line_of_sight, robot_clearance, view_coverage)
from .params import *  # noqa: F401,F403
from .params import PARAMS, RISER_H, RISER_RANGE, SCALE, from_drop, params_table, to_drop  # noqa: F401
from .robot import (ARCH_R, SCARA_REACH, SHAFT_REACH, base_xyz, duct_top, envelope, joints,  # noqa: F401
                    robot_top_at, swept_bands_at)
from .scene import *  # noqa: F401,F403
