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

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402
from _hostpaths import require_repo  # noqa: E402

_TCLSH = shutil.which("tclsh") or shutil.which("tclsh8.6")

_FIXTURE = ("vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
            "fixtures", "drt_residual_types", "openroad_drt0701_tail.txt")

_RPT = "/tmp/vic-probe-out/routed_router.drc.rpt"


def _run_tcl(stub_body: str) -> tuple[str, dict]:
    """Execute the emitted probe under a stub `detailed_route` and report what
    the router was actually called with.

    `stub_body` is the stub proc's body -- the probe reads it through
    `info body`, exactly as it reads OpenROAD's real proc.
    """
    script = (
        "proc detailed_route {args} {\n" + stub_body + "\n"
        "  puts \"CALLED_WITH=|$args|\"\n"
        "}\n"
        + R._route_drc_report_tcl(_RPT) +
        "puts \"OPT=|$_vic_drc_opt|\"\n"
        "detailed_route {*}$_vic_drc_opt\n"
    )
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "probe.tcl"
        f.write_text(script)
        out = subprocess.run([_TCLSH, str(f)], capture_output=True, text=True,
                             timeout=60)
    assert out.returncode == 0, f"tcl failed: {out.stderr}\n{script}"
    fields = {}
    for line in out.stdout.splitlines():
        if "=|" in line:
            k, _, v = line.partition("=|")
            fields[k] = v.rstrip("|")
    return out.stdout, fields


# A stub whose body carries the option in its `keys` list, the way OpenROAD's
# own `detailed_route` proc does. NOT a copy of any design's data.
_ACCEPTS = "  # sta::parse_key_args detailed_route args keys {-output_drc -verbose}"
_REJECTS = "  # sta::parse_key_args detailed_route args keys {-verbose}"


@pytest.mark.skipif(_TCLSH is None, reason="no tclsh on this host")
def test_probe_requests_the_report_when_the_router_accepts_the_option():
    """SUBJECT: on a build that takes `-output_drc`, the flow asks for it."""
    out, f = _run_tcl(_ACCEPTS)
    assert f["OPT"] == f"-output_drc {_RPT}"
    assert f["CALLED_WITH"] == f"-output_drc {_RPT}"
    assert f"ROUTE_DRC_REPORT_REQUESTED: {_RPT}" in out


@pytest.mark.skipif(_TCLSH is None, reason="no tclsh on this host")
def test_probe_leaves_the_route_bare_when_the_router_rejects_the_option():
    """SUBJECT -- the load-bearing safety property: on a build WITHOUT the
    option the router is still called, with nothing extra.

    This is the whole reason for the probe. An unguarded `-output_drc` would
    raise STA-0562 inside the surrounding `catch`, be reported as a NONFATAL,
    and lose the route.
    """
    out, f = _run_tcl(_REJECTS)
    assert f["OPT"] == "", "the option must not be selected"
    assert f["CALLED_WITH"] == "", "the route must still run, with no extra arg"
    assert "ROUTE_DRC_REPORT_UNSUPPORTED" in out, "and it must say so out loud"


@pytest.mark.skipif(_TCLSH is None, reason="no tclsh on this host")
def test_probe_survives_a_router_that_is_not_a_tcl_proc():
    """A build where `info body` RAISES degrades to bare, never to broken.

    Stated as a deliberate false negative in `_route_drc_report_tcl`: it costs
    the report and never the route.
    """
    script = (
        # A C++-backed command has no Tcl body; `info body` raises for it.
        "proc detailed_route {args} { puts \"CALLED_WITH=|$args|\" }\n"
        "rename detailed_route _real\n"
        "proc detailed_route {args} { _real {*}$args }\n"
        "rename info _real_info\n"
        "proc info {sub args} {\n"
        "  if {$sub eq \"body\"} { error \"not a procedure\" }\n"
        "  return [_real_info $sub {*}$args]\n"
        "}\n"
        + R._route_drc_report_tcl(_RPT) +
        "detailed_route {*}$_vic_drc_opt\n"
    )
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "p.tcl"
        f.write_text(script)
        out = subprocess.run([_TCLSH, str(f)], capture_output=True, text=True,
                             timeout=60)
    assert out.returncode == 0, out.stderr
    assert "CALLED_WITH=||" in out.stdout, "route must still run"
    assert "ROUTE_DRC_REPORT_UNSUPPORTED" in out.stdout


@pytest.mark.skipif(_TCLSH is None, reason="no tclsh on this host")
def test_the_probe_is_idempotent_so_several_call_sites_may_emit_it():
    """Two route sites emit it, and a PnR resume deletes the block carrying
    the first. It must decide once and survive either way."""
    script = (
        "proc detailed_route {args} { }\n"
        "  # keys {-output_drc}\n"
        + R._route_drc_report_tcl(_RPT)
        + R._route_drc_report_tcl("/somewhere/else.rpt") +
        "puts \"OPT=|$_vic_drc_opt|\"\n"
    )
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "p.tcl"
        f.write_text(script)
        out = subprocess.run([_TCLSH, str(f)], capture_output=True, text=True,
                             timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.count("ROUTE_DRC_REPORT_") == 1, out.stdout
    assert "else.rpt" not in out.stdout


def test_the_drv_repair_reroute_asks_the_router_too():
    """SUBJECT: the reroute that can be LAST to touch the shipped geometry
    carries the probe and expands the option."""
    tcl = R._v1_8_100_signoff_drv_repair_tcl("/OUT")
    assert "info body detailed_route" in tcl
    assert "detailed_route {*}$_vic_drc_opt" in tcl
    assert f"/OUT/{R.ROUTER_DRC_REPORT_NAME}" in tcl


def test_the_base_route_asks_the_router_too():
    """SUBJECT: the base `detailed_route` -- the one that produces
    `routed_preantenna.def` -- is wired through the same probe."""
    src = Path(R.__file__).read_text()
    assert "{_drc_report_block}if {{[catch {{detailed_route " \
           "{{*}}$_vic_drc_opt}} dr_err]}}" in src


# --- the CONSUMER half: a report nothing reads is a report nobody has -------

def test_the_projection_carries_the_routers_own_report():
    """SUBJECT: when the router wrote a report, `routed.drc.rpt` carries the
    per-violation detail -- the net and bbox the log never had."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        (out / R.ROUTER_DRC_REPORT_NAME).write_text(
            "  violation type: NS Metal\n"
            "\tsrcs: net:n_042_\n"
            "\tbbox = (1.0, 2.0) - (1.04, 2.055) on Layer M1\n")
        block = R._router_drc_report_block(out, "irrelevant log text")
    assert "net:n_042_" in block
    assert "bbox = (1.0, 2.0) - (1.04, 2.055)" in block
    assert "detailed_route -output_drc" in block


def test_an_empty_router_report_is_not_reported_as_silence():
    """A router that found nothing and a router that was never asked are
    different facts."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        (out / R.ROUTER_DRC_REPORT_NAME).write_text("")
        block = R._router_drc_report_block(out, "")
    assert "EMPTY report" in block
    assert "no residual violations" in block


def test_the_projection_says_so_when_the_build_cannot_produce_one():
    """DEGRADE LOUDLY: a build without the option is named, not silent."""
    with tempfile.TemporaryDirectory() as td:
        block = R._router_drc_report_block(
            Path(td), "...\nROUTE_DRC_REPORT_UNSUPPORTED: this OpenROAD "
                      "build's detailed_route does not accept -output_drc\n")
    assert "UNAVAILABLE" in block
    assert "ROUTE_DRC_REPORT_UNSUPPORTED" in block


def test_never_asked_is_distinguished_from_asked_and_empty():
    """REAL ARTEFACT: a checked-in OpenROAD log from a route that predates the
    request. It has no report and no ROUTE_DRC_REPORT_* record, and must not
    read like a clean route."""
    # REAL ARTEFACT, resolved through `_hostpaths.require_repo` so it is a
    # checked-in file this checkout actually has -- not a fixture authored
    # alongside this change, which could not tell the change from its absence.
    real_log = require_repo(*_FIXTURE).read_text()
    assert "ROUTE_DRC_REPORT_" not in real_log
    with tempfile.TemporaryDirectory() as td:
        block = R._router_drc_report_block(Path(td), real_log)
    assert "NOT REQUESTED" in block
    assert "never asked the router" in block


def test_the_probe_names_no_design_pdk_or_vendor_literal():
    """chip-AGNOSTIC: the only design-derived value is the caller's path."""
    tcl = R._route_drc_report_tcl("/OUT/x.rpt")
    lowered = tcl.lower()
    for token in ("gf180", "sky130", "metal1", "nangate", "spm", "nwell",
                  "calibre", "synopsys", "cadence"):
        assert token not in lowered, token


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


def test_a_site_that_forgets_the_option_still_defines_it():
    """Every site carries the `info exists` default, so no route can reference
    an undefined variable -- including on a PnR RESUME, which deletes the block
    that carries the first probe."""
    src = Path(R.__file__).read_text()
    lines = src.splitlines()
    uses = [i for i, ln in enumerate(lines) if "$_vic_drc_opt" in ln]
    # NON-VACUITY. Without this the loop below has an always-false antecedent
    # and passes on a tree with no wiring at all -- it passed on clean main
    # while every other test in this module failed.
    assert len(uses) >= 8, f"expected the wired route sites, found {len(uses)}"
    for i in uses:
        back = " ".join(lines[max(0, i - 3):i + 1])
        assert ("info exists _vic_drc_opt" in back
                or "_drc_report_block" in back
                or "_route_drc_report_tcl" in back), \
            f"use of $_vic_drc_opt with no guard above it:\n{back}"
