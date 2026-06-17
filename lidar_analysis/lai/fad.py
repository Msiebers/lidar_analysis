from __future__ import annotations

try:
    from ..fad import (  # noqa: F401
        Box3D,
        FadResult,
        LayeredFadResult,
        compute_fad_in_box,
        compute_layered_fad,
        ray_box_intersection,
    )
except ImportError:
    from fad import (  # type: ignore  # noqa: F401
        Box3D,
        FadResult,
        LayeredFadResult,
        compute_fad_in_box,
        compute_layered_fad,
        ray_box_intersection,
    )
