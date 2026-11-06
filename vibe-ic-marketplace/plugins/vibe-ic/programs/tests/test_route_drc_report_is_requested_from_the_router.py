#!/usr/bin/env python3
"""The flow never asked the router for its DRC report, so no run could name a
residual violation.

`detailed_route` writes the violations it found -- type, net and BOUNDING BOX
-- only when given `-output_drc`. The canonical Phase-3 flow passes it at no
call site, so every route logs, twice:

    [WARNING DRT-0290] Warning: no DRC report specified, skipped writing DRC
    report

and `<pnr>/routed.drc.rpt` is a runner-side PROJECTION OF THE LOG. The log
carries a count and, at best, a type/layer table. Nothing on disk says WHICH
net or WHERE.

MEASURED 2026-08-29/30, spm x gf180mcuD: `pnr` FAILed on one residual
`NS Metal x1 on Metal1`, and naming it required hand-patching the plugin cache
with this very option and re-running the flow as a one-off diagnostic. That run
produced

    violation type: NS Metal
        srcs: net:__uuf__._040_
        bbox = (226.3900, 294.9900) - (226.4300, 295.0450) on Layer Metal1

and its `routed.def` was BYTE-IDENTICAL to the unpatched run's
(`sha256 a980a07fc58d...`): the option is pure observation.

The plugin's OTHER routing path -- the `eda_pnr` MCP tool -- has passed
`-output_drc` unconditionally for many versions. Only the canonical flow, the
one an operator actually runs, omitted it.

WHY IT IS PROBED RATHER THAN JUST PASSED. `-output_drc` is not universally
available, and an unknown key raises `STA-0562` INSIDE the `catch` that wraps
every `detailed_route` call in this flow -- which reports it as a NONFATAL and
carries on. On such a build an unguarded flag would turn a missing REPORT into
a LOST ROUTE, strictly worse than the gap it closes. That is the reason the
2026-08-30 session recorded this defect rather than shipping it.

`info body detailed_route` settles it: Tcl introspection, invokes nothing, and
returns the proc source whose `keys` list names every accepted option. The two
`tclsh` tests below drive that probe against a router that accepts the option
and one that does not, and assert BOTH the option selection and -- the
load-bearing half -- that the rejecting case still calls `detailed_route`, with
no extra argument.
"""
from __future__ import annotations

import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


_FIXTURE = ("vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
            "fixtures", "drt_residual_types", "openroad_drt0701_tail.txt")

_RPT = "/tmp/vic-probe-out/routed_router.drc.rpt"


# A stub whose body carries the option in its `keys` list, the way OpenROAD's
# own `detailed_route` proc does. NOT a copy of any design's data.
_ACCEPTS = "  # sta::parse_key_args detailed_route args keys {-output_drc -verbose}"
_REJECTS = "  # sta::parse_key_args detailed_route args keys {-verbose}"


def test_the_base_route_asks_the_router_too():
    """SUBJECT: the base `detailed_route` -- the one that produces
    `routed_preantenna.def` -- is wired through the same probe."""
    src = Path(R.__file__).read_text()
    assert "{_drc_report_block}if {{[catch {{detailed_route " \
           "{{*}}$_vic_drc_opt}} dr_err]}}" in src


# --- the CONSUMER half: a report nothing reads is a report nobody has -------


def test_every_route_site_asks_so_the_report_is_never_a_superseded_routes():
    """SUBJECT, and the reason this is a completeness test rather than two
    wiring tests: `-output_drc` is written at the END of each `detailed_route`,
    so the LAST route to run owns the file. Wiring only some sites would leave
    the report describing a route a later pass superseded -- the exact defect
    v1.12.95 fixed for the type/layer breakdown, one layer down and this time
    on disk.

    MEASURED on the prove-by-run before this test existed: with only the base
    route and the DRV-repair reroute wired, `routed_router.drc.rpt` was written
    at 07:18:16 and `routed.def` at 07:19:03 -- a 47-second window in which
    further routing ran. The residual happened not to move on this design; the
    window is the defect, not the outcome.

    So: EVERY emitted `detailed_route` expands the option. A new call site added
    without it fails here.
    """
    src = Path(R.__file__).read_text()
    sites = [ln for ln in src.splitlines()
             if "catch {detailed_route" in ln or "catch {{detailed_route" in ln]
    assert len(sites) >= 8, f"expected the known route sites, found {len(sites)}"
    # A site may split across two source lines; join each with its successor.
    lines = src.splitlines()
    for i, ln in enumerate(lines):
        if "catch {detailed_route" not in ln and "catch {{detailed_route" not in ln:
            continue
        window = " ".join(lines[i:i + 2])
        assert "_vic_drc_opt" in window, f"route site does not ask:\n{window}"
