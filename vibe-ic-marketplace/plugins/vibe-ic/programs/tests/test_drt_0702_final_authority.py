"""DRT-0702 is OpenROAD's final route-verification authority."""
from __future__ import annotations

import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _signoff_drc_format as S  # noqa: E402


def _shape(loop: int, verified: int) -> str:
    return (
        "[INFO DRT-0194] Start detail routing.\n"
        f"[INFO DRT-0199]   Number of violations = {loop}.\n"
        f"[INFO DRT-0702] Post-route verification: {verified} violation(s).\n"
    )


def test_0702_zero_supersedes_nonzero_loop_for_shipped_geometry():
    text = _shape(2, 0)
    assert S.router_post_route_final_count(text) == 0
    assert S.router_iter_last_count(text) == 0


def test_0702_nonzero_cannot_be_collapsed_to_clean():
    text = _shape(0, 3)
    assert S.router_post_route_final_count(text) == 3
    assert S.router_iter_last_count(text) == 3


def test_a_later_route_supersedes_an_earlier_0702():
    text = _shape(2, 0) + (
        "[INFO DRT-0194] Start detail routing.\n"
        "[INFO DRT-0199]   Number of violations = 4.\n")
    assert S.router_post_route_final_count(text) is None
    assert S.router_iter_last_count(text) == 4


def test_0702_without_a_loop_does_not_manufacture_a_trajectory():
    text = "[INFO DRT-0702] Post-route verification: 0 violation(s).\n"
    assert S.router_post_route_final_count(text) == 0
    assert S.router_iter_counts(text) == []
    assert S.router_iter_last_count(text) is None
