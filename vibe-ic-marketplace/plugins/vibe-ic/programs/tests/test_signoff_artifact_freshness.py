"""A phase-3 sign-off report must describe the layout that is actually on disk.

THE DEFECT
----------
`_stale_rtl_vs_netlist` already fixed this disease at the SYNTH boundary: a
PDK-only cache meant "edit RTL -> re-run" silently reused the previous netlist,
so the flow "placed-and-routed the PREVIOUS design and reported a clean PASS for
RTL it had never synthesised". That fix stopped at synth.

Everything downstream of PnR — RC extraction, SPEF-based STA, multi-corner SPEF
STA, multi-corner OCV sign-off STA and their stance JSONs — was guarded by
`not <artifact>.is_file()`. A pure existence test. It has no notion of WHICH
layout the artefact describes, so the identical failure survives one stage
later, where it decides the timing verdict.

MEASURED on `spm x sky130A` (v1.6.4, campaign_v164) — one phase-3 re-run after
an RTL change, same command, same PDK::

    phase3/stage3/pnr/spm_pnr.v             15:03:18   <- built this run
    phase3/stage3/extracted/spm.spef        10:30:04   <- previous design
    phase3/stage3/sta/sta_mcorner_ocv.rpt   10:30:08   <- previous design

119 of 223 phase-3 artefacts predated the layout just built. Synthesis, PnR, DRC
and LVS all re-ran on the new design; Step 23 then reported
`setup -6.550 ns, TNS -75.02, DRV 45/70` — byte-identical to the PREVIOUS
design's numbers — for a netlist those numbers had never seen. Deleting the
stale set and re-running the SAME command gave that layout's real answer:
`setup +3.68 ns, TNS 0.00, DRV 5`.

The direction that matters is the opposite one. Here the stale cache invented a
FAIL over a design that had closed. The identical code invents a PASS whenever
the previous run passed and the new design regressed — silently, with a full set
of sign-off reports to back it up.

BIDIRECTIONAL. The GUARD tests matter as much as the DEFECT tests: sign-off STA
is expensive, and a predicate that regenerates unconditionally would make every
idempotent re-run redo it. The invariant is "older than the layout", not
"exists".
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as P  # noqa: E402

_RUNNER_SRC = _PROGRAMS / "phase3_one_shot_runner.py"

# The artefacts that decide, or feed, the Step-23 timing verdict. Each is a
# local variable name in the sign-off block of `_canonicalize_artefacts`.
_SIGNOFF_ARTIFACT_VARS = [
    "spef_out",        # RC extraction — basis of every SPEF-based report
    "spef_sta_rpt",    # SPEF-based post-route STA
    "mc_stance",       # multi-corner SPEF stance
    "mc_sta_rpt",      # multi-corner SPEF STA
    "mc_ocv_stance",   # multi-corner OCV process stance
    "mc_ocv_rpt",      # multi-corner OCV sign-off STA (Step 23 reads this)
]


def _stamp(p: Path, t: float) -> None:
    os.utime(p, (t, t))


def _pair(tmp_path: Path, *, artifact_age: float, layout_age: float):
    """A real layout file and a real report file with real mtimes."""
    layout = tmp_path / "spm.def"
    artifact = tmp_path / "sta_mcorner_ocv.rpt"
    layout.write_text("DESIGN spm ;\n")
    artifact.write_text("worst slack max 3.68\n")
    now = 1_700_000_000.0
    _stamp(layout, now - layout_age)
    _stamp(artifact, now - artifact_age)
    return artifact, layout


# --------------------------------------------------------------------------
# PREMISE
# --------------------------------------------------------------------------

def test_premise_helper_exists():
    assert hasattr(P, "_signoff_regen"), (
        "the freshness predicate is gone — every test below is vacuous")


# --------------------------------------------------------------------------
# DEFECT — FAIL on the unfixed runner (existence-only guards).
# --------------------------------------------------------------------------

def test_report_older_than_layout_is_regenerated(tmp_path):
    artifact, layout = _pair(tmp_path, artifact_age=3600, layout_age=10)
    assert P._signoff_regen(artifact, layout) is True, (
        "a sign-off report that predates the layout describes a DIFFERENT "
        "design and must not be reused")


def test_every_signoff_artifact_guard_routes_through_the_predicate():
    """The behavioural test above passes even if every CALL SITE still uses
    `not x.is_file()`. This one reads the runner source and fails if any
    sign-off artefact is still gated on existence alone."""
    tree = ast.parse(_RUNNER_SRC.read_text())
    # Scope to the sign-off/canonicalisation step ONLY. Elsewhere
    # `not <artifact>.is_file()` is a legitimate POST-condition ("did the tool
    # actually write it?"), e.g. inside `_emit_spef`. Flagging those would be a
    # guard that fires on correct state, which is a bug, not a guard.
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)
               and n.name == "step_canonicalize_artefacts"), None)
    assert fn is not None, (
        "premise: the sign-off canonicalisation step was renamed — this test "
        "is scanning nothing")
    offenders = []
    for node in ast.walk(fn):
        # match:  not <name>.is_file()
        if not (isinstance(node, ast.UnaryOp)
                and isinstance(node.op, ast.Not)):
            continue
        call = node.operand
        if not (isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "is_file"
                and isinstance(call.func.value, ast.Name)):
            continue
        if call.func.value.id in _SIGNOFF_ARTIFACT_VARS:
            offenders.append((call.func.value.id, node.lineno))
    assert not offenders, (
        "sign-off artefact(s) still regenerated on existence alone — a "
        "re-run will reuse the previous design's report: "
        + ", ".join(f"{n} (line {ln})" for n, ln in offenders))


def test_missing_report_is_produced(tmp_path):
    _, layout = _pair(tmp_path, artifact_age=1, layout_age=1)
    assert P._signoff_regen(tmp_path / "absent.rpt", layout) is True


# --------------------------------------------------------------------------
# GUARD — FAIL if the predicate is widened to "always regenerate".
# --------------------------------------------------------------------------

def test_report_newer_than_layout_is_reused(tmp_path):
    """The load-bearing guard. Sign-off STA is expensive; a report produced
    FROM this layout is exactly what we want to keep. A fix that regenerated
    unconditionally would fail here and would make every idempotent re-run
    redo the full multi-corner sign-off."""
    artifact, layout = _pair(tmp_path, artifact_age=10, layout_age=3600)
    assert P._signoff_regen(artifact, layout) is False


def test_no_layout_leaves_an_existing_report_alone(tmp_path):
    """Nothing downstream can be re-derived without a layout, so an absent DEF
    must not trigger a pointless regeneration attempt."""
    artifact = tmp_path / "sta.rpt"
    artifact.write_text("x\n")
    assert P._signoff_regen(artifact, tmp_path / "no_such.def") is False


# --------------------------------------------------------------------------
# FAIL-CLOSED — matches `_stale_rtl_vs_netlist`'s contract.
# --------------------------------------------------------------------------

def test_unreadable_mtime_regenerates_rather_than_trusting_the_cache(
        tmp_path, monkeypatch):
    artifact, layout = _pair(tmp_path, artifact_age=10, layout_age=3600)

    def boom(self, *a, **k):
        raise OSError("stat failed")

    monkeypatch.setattr(Path, "stat", boom)
    assert P._signoff_regen(artifact, layout) is True, (
        "an unprovable cache must be rebuilt, not trusted")


@pytest.mark.parametrize("same", [True])
def test_equal_mtimes_are_treated_as_fresh(tmp_path, same):
    """A report written in the same second as the layout it came from is the
    normal in-run case and must not loop forever regenerating."""
    artifact, layout = _pair(tmp_path, artifact_age=100, layout_age=100)
    assert P._signoff_regen(artifact, layout) is False
