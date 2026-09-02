"""The DRT-0701 supersession rule applied to ONE of its two readers.

`router_post_route_verified_count` refuses a DRT-0701 that a later
`detailed_route` superseded. `router_post_route_verified_pair` — the reader
`phase3_one_shot_runner._drt_reading` actually consults when it decides whether
to override the metrics JSON — took `findall(...)[-1]` and refused nothing. The
stale half was the half with authority.

MEASURED (subservient x gf180mcuD, host 8HD-4, image
`ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2e057…`, OpenROAD 26Q3-1472-g42cadea9df,
2026-09-02). In that run's `openroad.log` the last DRT-0701 read
`4 violation(s) … (2 in-loop)` and TWO more `Start detail routing` calls
followed it. Everything that describes the route that SHIPPED said 2: the last
`DRT-0199`, the final `DRT-0702`, the router's own `-output_drc` report (2
records), and the metrics JSON — whose five duplicate
`detailedroute__route__drc_errors` keys, `0, 2, 4, 2, 2`, `json.load` resolves
last-wins to 2.

`_drt_reading` saw `metric == in_loop` (2 == 2), `verified != in_loop` (4 != 2),
concluded the metric was the superseded quantity and substituted 4. `pnr` FAILed
`ROUTE_DRC_METRIC_DISAGREEMENT: METRIC=4 but LOG=2` — against a metrics JSON
that was correct — and no GDS, DRC or LVS ran.

chip-AGNOSTIC: OpenROAD log grammar only; no design, PDK or vendor literal in
any assertion.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _signoff_drc_format as _sdf  # noqa: E402

FIXTURE = (Path(__file__).resolve().parent / "fixtures" / "drt_residual_types"
           / "openroad_armA_0701_two_routes_stale.txt")


@pytest.fixture(scope="module")
def stale_log() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_the_pair_reader_refuses_a_verification_two_routes_stale(stale_log):
    """THE CONTROL. Pre-fix this returned (4, 2) — the stale pair — so the
    assertion names the expected VALUE, not a None sentinel: a reviewer must be
    able to tell "observed the wrong pair" from "observed an absence"."""
    observed = _sdf.router_post_route_verified_pair(stale_log)
    assert observed is None, (
        f"the last DRT-0701 is followed by "
        f"{len(_sdf.RE_DRT_0194.findall(stale_log.split('(2 in-loop)')[-1]))} "
        f"more detail route(s), so it does not describe the shipped geometry; "
        f"the reader returned {observed!r} (pre-fix value: (4, 2))")


def test_both_readers_agree_about_which_0701_is_stale(stale_log):
    """The defect was an ASYMMETRY, so the regression test is the symmetry."""
    assert _sdf.router_post_route_verified_count(stale_log) is None
    assert _sdf.router_post_route_verified_pair(stale_log) is None


def test_the_dropped_verification_is_still_reported_loudly(stale_log):
    """Refusing it must not become the same silence as never verifying."""
    assert _sdf.router_post_route_verified_superseded(stale_log) == (4, 2)


def test_a_0701_that_no_route_followed_is_still_read(stale_log):
    """SOUNDNESS, both halves: the rule must not swallow a live verification.

    Truncating the fixture right after the last DRT-0701 leaves it unsuperseded,
    and both readers must then return its numbers."""
    tail = "(2 in-loop). The published result is the verified one."
    live = stale_log[:stale_log.index(tail) + len(tail)]
    assert _sdf.RE_DRT_0194.search(
        live, live.index(tail)) is None, "the truncation left a later route in"
    assert _sdf.router_post_route_verified_pair(live) == (4, 2)
    assert _sdf.router_post_route_verified_count(live) == 4
    assert _sdf.router_post_route_verified_superseded(live) is None


def test_the_metrics_json_this_run_wrote_resolves_to_the_shipped_count():
    """The number the reader was overriding was never wrong.

    Five duplicate bare keys, `0, 2, 4, 2, 2`; `json.load` is last-wins, which
    is the shipped route's count. Built here rather than shipped as a 200 kB
    artefact — the duplication is the whole content."""
    raw = ('{' + ', '.join(
        f'"detailedroute__route__drc_errors": {v}' for v in (0, 2, 4, 2, 2))
        + '}')
    assert json.loads(raw)["detailedroute__route__drc_errors"] == 2
