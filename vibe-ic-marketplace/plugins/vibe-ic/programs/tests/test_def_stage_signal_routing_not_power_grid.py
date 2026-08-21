"""def_stage_progression_check Check 4 asked "does this DEF contain ANY routed
wire", and reported the answer as "the design is routed".

A DEF's power grid lives in `SPECIALNETS` and is written by the PDN step, which
runs BEFORE detailed routing. So a `routed.def` whose detailed route ABORTED —
every signal net bare, only the power straps carrying `+ ROUTED` — satisfied
Check 4 on the strength of its power grid, and the gate printed
`routing=yes` for it and exited 0 with "routed geometry present".

Worse, the column was constant: `placed`, `post_cts`, `post_hold` and `routed`
all reported `routing=yes` in the same run, because the power grid is in all
four. A column that cannot vary across the transition it is read for carries no
information about that transition.

OBSERVED: a run whose `detailed_route` aborted shipped `routed.def` with 563
signal nets declared, ZERO signal-net routing statements, and 471 SPECIALNETS
routing statements. This gate returned OK. The absence then surfaced three
steps downstream as a five-figure DRC count, an LVS extraction with no
interconnect, and an EM report with no current — three sign-off failures whose
stated causes were all sign-off, and whose actual cause was that the design was
never routed.

Fix: measure the two sections separately and ask the question Check 4 means —
does the NETS section carry routing.

POSITIVE: a routed.def with signal-net routing is still OK (the gate must be
able to say yes, or it proves nothing when it says no).

NEGATIVE no-leak — each of these must FAIL:
  - signal nets declared, zero signal routing, power grid routed;
  - the same, when the runner's `DETAILED_ROUTE_NONFATAL:` marker is present
    AND the log shows the router reached the design. That marker is emitted by
    a `catch` around `detailed_route`, so it fires both for a PDK that has no
    detailed-router rule files (the intentional mode) and for a router that ran
    and aborted (a failure). Keyed on the marker alone, the failure is silently
    reclassified as the intentional mode — so the demotion must additionally
    require that the router never reached the design.

chip-AGNOSTIC: DEF grammar plus router phase markers; no chip, PDK, library or
design literal anywhere in the fix or in this test.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import def_stage_progression_check as D  # noqa: E402
import _path_layout as _pl  # noqa: E402


def _components(n: int, pad: int) -> str:
    body = ["COMPONENTS %d ;" % n]
    body += ["  - U_%d AND2X1 + PLACED ( %d %d ) N ;" % (i, i * 100, i * 100)
             for i in range(n)]
    body.append("END COMPONENTS")
    return "\n".join(body) + "\n# pad " + ("x" * pad) + "\n"


def _power_grid(n: int = 6) -> str:
    """SPECIALNETS with routing — present from the PDN step onward."""
    out = ["SPECIALNETS 2 ;"]
    for i in range(n):
        out.append("- VDD + ROUTED met1 ( 0 %d ) ( 1000 %d )" % (i * 10, i * 10))
    out.append("END SPECIALNETS")
    return "\n".join(out) + "\n"


def _nets(n: int, routed: bool) -> str:
    """NETS section. `routed=False` is the aborted-route shape: the nets are
    declared and connected to pins, but no wire geometry was ever written."""
    out = ["NETS %d ;" % n]
    for i in range(n):
        if routed:
            out.append("- n%d ( U_0 A ) ( U_1 Z )\n  + ROUTED met1 ( %d 0 ) "
                       "( %d 100 ) ;" % (i, i * 10, i * 10))
        else:
            out.append("- n%d ( U_0 A ) ( U_1 Z ) ;" % i)
    out.append("END NETS")
    return "\n".join(out) + "\n"


def _mk(tmp_path, *, signal_routed: bool, n_nets: int = 8,
        nonfatal_marker: bool = False, router_reached_design: bool = False,
        routing_mode_json: bool = False):
    """A 5-stage DEF set that passes Checks 1-3, isolating Check 4/4b.

    The power grid is present from `placed` onward, exactly as a real flow
    writes it — that is the condition under test.
    """
    pnr = _pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "floorplan.def").write_text(_components(2, 0))
    (pnr / "placed.def").write_text(_components(3, 100) + _power_grid())
    (pnr / "post_cts.def").write_text(_components(4, 200) + _power_grid())
    (pnr / "post_hold.def").write_text(_components(4, 300) + _power_grid())
    (pnr / "routed.def").write_text(
        _components(5, 400) + _power_grid() + _nets(n_nets, signal_routed))

    log = []
    if router_reached_design:
        log.append("[INFO DRT-0165] Start pin access.")
        log.append("[ERROR DRT-0073] No access point for U_0/A (CELL_X).")
    if nonfatal_marker:
        log.append("DETAILED_ROUTE_NONFATAL: DRT-0073")
    if log:
        (pnr / "openroad.log").write_text("\n".join(log) + "\n")

    if routing_mode_json:
        fh = tmp_path / "phase3" / "stage4" / "foundry_handoff"
        fh.mkdir(parents=True, exist_ok=True)
        (fh / "routing_mode.json").write_text(json.dumps({"mode": "global_only"}))
    return tmp_path


def _rules(tmp_path):
    _infos, finds = D.inspect(tmp_path)
    return {f.rule: f.severity for f in finds}


def _routed_stage(tmp_path):
    infos, _ = D.inspect(tmp_path)
    return next(i for i in infos if i.name == "routed")


# --------------------------------------------------------------- POSITIVE ---

def test_signal_routing_present_is_still_ok(tmp_path):
    """The gate must be able to say yes, or its no means nothing."""
    _mk(tmp_path, signal_routed=True)
    assert "signal-nets-unrouted" not in _rules(tmp_path)
    assert "signal-nets-unrouted-global-route-only" not in _rules(tmp_path)
    assert D.main([str(tmp_path)]) == 0


def test_signal_and_power_routing_are_counted_separately(tmp_path):
    """The measurement the old boolean could not express."""
    _mk(tmp_path, signal_routed=True, n_nets=8)
    rt = _routed_stage(tmp_path)
    assert rt.signal_route_stmts == 8
    assert rt.special_route_stmts == 6
    assert rt.declared_signal_nets == 8


def test_power_grid_alone_does_not_count_as_signal_routing(tmp_path):
    """The exact confusion: has_routing stays True, signal routing is zero."""
    _mk(tmp_path, signal_routed=False)
    rt = _routed_stage(tmp_path)
    assert rt.has_routing is True, "power grid does provide routing geometry"
    assert rt.special_route_stmts == 6
    assert rt.signal_route_stmts == 0, "and none of it is design interconnect"


# ------------------------------------------------------- NEGATIVE no-leak ---

def test_unrouted_signal_nets_with_routed_power_grid_fails(tmp_path):
    """The observed shape. Check 4 alone passes this; 4b must not."""
    _mk(tmp_path, signal_routed=False)
    assert _rules(tmp_path).get("signal-nets-unrouted") == "error"
    assert D.main([str(tmp_path)]) == 1


def test_nonfatal_marker_does_not_excuse_an_aborted_route(tmp_path):
    """`DETAILED_ROUTE_NONFATAL:` fires for the intentional mode AND for an
    abort. When the log proves the router reached the design, it was an abort
    and must stay an error."""
    _mk(tmp_path, signal_routed=False,
        nonfatal_marker=True, router_reached_design=True)
    assert _rules(tmp_path).get("signal-nets-unrouted") == "error"
    assert D.main([str(tmp_path)]) == 1


def test_declared_global_route_only_mode_is_still_demoted(tmp_path):
    """A PDK with no detailed-router rule files cannot reach the design, so
    the intentional mode keeps its demotion — this fix must not convert a
    declared global-route-only run into a failure."""
    _mk(tmp_path, signal_routed=False,
        nonfatal_marker=True, router_reached_design=False,
        routing_mode_json=True)
    r = _rules(tmp_path)
    assert r.get("signal-nets-unrouted-global-route-only") == "warning"
    assert "signal-nets-unrouted" not in r
    assert D.main([str(tmp_path)]) == 0


def test_no_signal_nets_declared_is_not_reported_as_unrouted(tmp_path):
    """Zero routed of zero declared is an empty design, not an unrouted one —
    fail-closed must not become fire-always."""
    _mk(tmp_path, signal_routed=False, n_nets=0)
    r = _rules(tmp_path)
    assert "signal-nets-unrouted" not in r
    assert "signal-nets-unrouted-global-route-only" not in r
