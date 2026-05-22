#!/usr/bin/env python3
"""
Smoke test for the canonical splitting_style / buffer_u resolution.

Covers:
  - the new canonical `splitting_style` key (distance | plant | plot)
  - an invalid splitting_style raising ValueError
  - canonical `buffer_u` overriding legacy buffer aliases
  - the exact messy real-world config the user is trying to clean up,
    asserting the legacy fallback still resolves it unchanged

open3d is stubbed because central_runner imports pipeline_core, which
imports open3d at module load. open3d is only used by the PLY writer at
runtime, never at import, so an empty stub module is sufficient.
"""
import sys
import types

sys.modules.setdefault("open3d", types.ModuleType("open3d"))

from lidar_analysis.central_runner import resolve_splitting_style, resolve_buffer_u


def main() -> None:
    # ---- canonical splitting_style ----
    assert resolve_splitting_style({"splitting_style": "distance"}) == ("distance", "auto")
    assert resolve_splitting_style({"splitting_style": "plant"}) == ("marks", "plant")
    assert resolve_splitting_style({"splitting_style": "plot"}) == ("marks", "plot")
    assert resolve_splitting_style({"splitting_style": "PLOT"}) == ("marks", "plot")

    # invalid value fails loudly
    try:
        resolve_splitting_style({"splitting_style": "rows"})
        raise AssertionError("expected ValueError for bad splitting_style")
    except ValueError:
        pass

    # ---- canonical buffer_u wins over legacy aliases ----
    assert resolve_buffer_u({"buffer_u": 1.5, "mark_z_buffer_u": 9.0}) == 1.5
    assert resolve_buffer_u({"marks": {"buffer_u": 2.0}}) == 2.0
    assert resolve_buffer_u({"mark_z_buffer_u": 3.0}) == 3.0
    assert resolve_buffer_u({"marker_z_buffer_u": 4.0}) == 4.0
    assert resolve_buffer_u({}) == 0.0

    # ---- the real messy config (legacy fallback must be unchanged) ----
    messy = {
        "fusion_method": "interp",
        "split_source": "marks",
        "use_markers": True,
        "marker_target_type": "plot",
        "mark_target_type": "plot",
        "marker_z_buffer_u": 0.0,
        "plant_marker_buffer_u": 0.0,   # dead key, never read (no warning yet)
        "plot_marker_buffer_u": 0.0,    # dead key, never read (no warning yet)
        "mark_z_buffer_u": 0.0,
        "markers_required": True,
        "write_marker_pointcloud": True,
        "dim_units": "ft",
    }
    assert resolve_splitting_style(messy) == ("marks", "plot")
    assert resolve_buffer_u(messy) == 0.0

    # Same intent expressed canonically collapses to one key:
    assert resolve_splitting_style({"splitting_style": "plot"}) == ("marks", "plot")

    print("PASS")


if __name__ == "__main__":
    main()
