"""Step 10 (pre-layout multi-corner STA) must time the SYNTH netlist, even in
a dir that already holds a routed netlist from an earlier round.

The defect
----------
`step_prelayout_signoff` is documented to compose `pre_pnr_timing.rpt` from a
GENUINE pre-layout OpenSTA run (its own docstring: "selects the synth netlist
and stamps STA_BASIS: PRE_LAYOUT_ESTIMATE"). But it delegated basis selection
to `_multi_corner_sta_inputs`, whose precedence is purely file-existence driven
and returns POST_ROUTE_SPEF whenever `<pnr>/<top>_pnr.v` + `<top>.spef` exist.

On a RE-RUN — the routed netlist and SPEF are already on disk from a prior
round — the "pre-layout" step therefore emitted a POST_ROUTE report and the
composed `pre_pnr_timing.rpt` carried the routed header
("PRE-LAYOUT STA ... emitted BEFORE PnR") over a body stamped
`STA_BASIS: POST_ROUTE_SPEF`. `sta_report_check --mode sta` correctly flags the
contradiction (`reports_contradicting_declared_basis > 0`) and Step 10 FAILs —
which blocks-by-upstream Step 11 and voids every step that depends on it.

The fix adds `force_prelayout` to `_multi_corner_sta_inputs`: when set (Step 10
sets it) the synth netlist is the ONLY acceptable basis and a routed netlist is
never a stand-in — its absence is MISSING, not a mislabelled report.

Negative control (bidirectional)
---------------------------------
* FORWARD  — `force_prelayout=True` with a routed netlist + SPEF present must
  return PRE_LAYOUT_ESTIMATE on the synth netlist. FAILS on the pre-fix file
  (no such parameter / the routed precedence wins) and PASSES after.
* REVERSE  — the DEFAULT call (no force) with the same inputs must STILL return
  POST_ROUTE_SPEF on the routed netlist. This is the post-route producer Step
  23 consumes; it must be BYTE-unchanged. A fix that "forced pre-layout
  everywhere" would break this reverse case — that is what stops the fix from
  being a filter tightened until it swallows the post-route path too.

chip/PDK-AGNOSTIC: no chip, PDK, vendor or corner-name literal — the netlist
and SPEF files are the flow's own `<top>_pnr.v` / `<top>_synth.v` / `<top>.spef`
naming, with a placeholder top.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as P3  # noqa: E402

TOP = "widget"


def _write(p: Path, text: str = "// netlist\n") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _project_with_routed_and_synth(root: Path) -> Path:
    """A re-run dir: routed netlist + extracted SPEF AND the synth netlist all
    present at once — the exact state that triggers the mislabel."""
    _write(P3._pl.synth_dir(root) / f"{TOP}_synth.v")
    _write(P3._pl.pnr_dir(root) / f"{TOP}_pnr.v")
    _write(root / "phase3/stage3/extracted" / f"{TOP}.spef", "*SPEF\n")
    return root


def test_forward_forced_prelayout_ignores_the_routed_netlist(tmp_path):
    """FORWARD: with routed+SPEF present, forcing pre-layout must time the SYNTH
    netlist and stamp PRE_LAYOUT_ESTIMATE. (FAILS pre-fix, PASSES post-fix.)"""
    root = _project_with_routed_and_synth(tmp_path)
    netlist, spef_map, basis, note = P3._multi_corner_sta_inputs(
        root, TOP, force_prelayout=True)
    assert basis == "PRE_LAYOUT_ESTIMATE", (basis, note)
    assert netlist is not None and netlist.name == f"{TOP}_synth.v", netlist
    assert spef_map == {}, spef_map  # a pre-layout estimate carries NO parasitics


def test_reverse_default_still_prefers_the_routed_netlist(tmp_path):
    """REVERSE (must STILL pass): the default call is the POST-route producer
    Step 23 consumes. It must be unchanged — routed netlist + SPEF wins."""
    root = _project_with_routed_and_synth(tmp_path)
    netlist, spef_map, basis, note = P3._multi_corner_sta_inputs(root, TOP)
    assert basis == "POST_ROUTE_SPEF", (basis, note)
    assert netlist is not None and netlist.name == f"{TOP}_pnr.v", netlist
    assert spef_map, "post-route basis must carry the extracted SPEF"


def test_forced_prelayout_never_substitutes_a_routed_stand_in(tmp_path):
    """ANTI-SWALLOW guard: force with a routed netlist but NO synth netlist must
    return MISSING — never a routed-netlist stand-in wearing a pre-layout
    header. This is what a lazy fix ('just relabel the routed report') would
    get wrong."""
    root = tmp_path
    _write(P3._pl.pnr_dir(root) / f"{TOP}_pnr.v")
    _write(root / "phase3/stage3/extracted" / f"{TOP}.spef", "*SPEF\n")
    netlist, spef_map, basis, note = P3._multi_corner_sta_inputs(
        root, TOP, force_prelayout=True)
    assert basis == "MISSING", (basis, note)
    assert netlist is None, netlist


def test_fresh_prelayout_run_only_synth_present(tmp_path):
    """SANITY: the always-worked case (pre-PnR, no routed netlist yet) still
    resolves to a pre-layout estimate on the synth netlist under both the
    default precedence and the forced flag."""
    root = tmp_path
    _write(P3._pl.synth_dir(root) / f"{TOP}_synth.v")
    for force in (False, True):
        netlist, spef_map, basis, note = P3._multi_corner_sta_inputs(
            root, TOP, force_prelayout=force)
        assert basis == "PRE_LAYOUT_ESTIMATE", (force, basis, note)
        assert netlist.name == f"{TOP}_synth.v", (force, netlist)
