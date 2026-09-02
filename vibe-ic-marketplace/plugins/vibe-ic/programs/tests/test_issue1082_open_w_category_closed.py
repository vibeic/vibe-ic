"""No declared report destination is written through `open(..., "w")`. #1082.

This pins a FORM, not a file list, and that is the point. The two tranches
before it (#1110's ten verdict-bearing programs, #1138's forty gates) each
pinned the names they converted, which stops those names regressing and says
nothing about the next file someone adds. This one closes a whole shape: after
it, a declared report destination opened with `open(dest, "w")` anywhere in the
shipped tree is a test failure, whoever writes it and whenever.

WHY THIS SHAPE WAS LEFT UNTIL LAST. `.write_text(...)` is a single expression
and converts by substitution. `open(..., "w")` is a context manager whose body
is arbitrary — the writer streams into `fh` across many statements — so the
faithful conversion is `_atomic_artefact.writing()`, which yields the same
handle, propagates exceptions unchanged, and renames only after `fsync`. #1138
deliberately skipped these rather than convert them with a line rewriter that
could not see the block it was editing.

MEASURED. Before: 16 sites across 10 programs. After: 0. The count is asserted
below rather than described, so this docstring cannot drift away from the tree.

A CORRECTION TO THE RECORD. #1138 said "95 files whose offending site is
`open(..., 'w')`". That was wrong — those 95 were files its line rewriter
skipped because the `.write_text` call was not a bare single-line statement,
which is a different and still-open category. The real `open(..., "w")`
population was 10 files, and it is now empty.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import atomic_artifact_write_check as G  # noqa: E402

PROGRAMS = Path(__file__).resolve().parent.parent
BASELINE = PROGRAMS / "_atomic_artefact_residual.json"

#: The ten programs whose declared report destination used the context-manager
#: form. Pinned by name as well as by shape: the shape assertion below would
#: also pass if someone simply deleted them.
CONVERTED = [
    "_spef_coupling", "agent_checkin_scope_guard", "asap7_finfet_lvs",
    "fastercap_extract", "fix_fault_cut_names", "gate_verilog_to_spice",
    "klayout_pdk_lvs", "metal_fill_config_gen", "pdk_dielectric_fit",
    "spec_complete_extract",
]


def _open_w_sites():
    """Every non-`write_text` site the gate still finds, keyed by program."""
    out = {}
    for py in sorted(PROGRAMS.glob("*.py")):
        sites = [s for s in (G.scan_program(py) or [])
                 if s.get("form") != ".write_text(...)"]
        if sites:
            out[py.name] = sites
    return out


_SYNTHETIC = '''\
import argparse
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args()
    with open(a.json_out, "w") as fh:
        fh.write("{}")
'''


def test_the_detector_actually_finds_this_shape(tmp_path):
    """POSITIVE CONTROL, and it is load-bearing.

    Every other assertion in this file is of the form "zero sites found". All
    of them pass vacuously if `scan_program` is broken and returns nothing —
    MEASURED: mutating it to `return []` killed ZERO of them. A file that can
    only say "I found nothing" cannot distinguish a converted tree from a blind
    detector, which is the exact empty-tree shape #1082 is about, one level up.

    So: hand the detector a program that unambiguously has the defect and
    require it to say so. Now "zero in the shipped tree" is a measurement.
    """
    p = tmp_path / "synthetic_offender.py"
    p.write_text(_SYNTHETIC)
    sites = G.scan_program(p) or []
    assert sites, "the detector found nothing in a program that plainly has the defect"
    assert any(s.get("form") != ".write_text(...)" for s in sites), sites


def test_no_declared_report_is_written_through_open_w():
    """THE CATEGORY. Zero sites of this form anywhere in the shipped tree."""
    bad = _open_w_sites()
    assert not bad, (
        'a declared report destination is opened with `open(dest, "w")` — use '
        "`_atomic_artefact.writing()`, which yields the same handle and renames "
        f"only on success: {bad}")


def test_the_ten_converted_programs_are_still_converted():
    """The names, so deleting a file cannot masquerade as converting it."""
    missing = [s for s in CONVERTED if not (PROGRAMS / f"{s}.py").is_file()]
    assert not missing, f"program(s) vanished rather than being converted: {missing}"
    still = {s: G.scan_program(PROGRAMS / f"{s}.py") for s in CONVERTED}
    assert not any(still.values()), {k: v for k, v in still.items() if v}


def _tree_offenders():
    """Every program the detector still finds an offending site in, NOW."""
    return {py.name for py in sorted(PROGRAMS.glob("*.py"))
            if (G.scan_program(py) or [])}


def _recorded_but_converted(recorded, tree):
    """Ratchet slots no program can ever pay off — the hole this test closes."""
    return sorted(set(recorded) - set(tree))


def test_the_recorded_baseline_followed_the_tree_down():
    """The ratchet tightened to match. `--strict` only fails on GROWTH, so a
    converted tree passes either way; leaving a stale row would leave a hole
    through which the program it names could return still green.

    THE ASSERTION IS A SUBSET TEST, NOT A COUNT, AND THAT IS THE FIX.
    This test used to read `assert len(recorded) == 514`. A ratchet whose
    guard is an ABSOLUTE COUNT goes RED WHEN THE TREE IS TIGHTENED, which is
    the one direction a ratchet exists to reward: main converted three more
    programs (`eda_report_audit`, `lec_run`, `power_total_vs_budget_check`)
    and correctly pulled the record 514 -> 511, and this line turned red for
    it. A guard that punishes the fix is a broken guard, and the number was
    never the property anyway.

    The property is: NO RECORDED ROW NAMES A PROGRAM THE DETECTOR NO LONGER
    FLAGS. That is exactly the hole (`recorded - tree` must be empty), it is
    defined by the detector's own behaviour over `programs/*.py` rather than
    by a hand-kept number, and it can only ever be satisfied by the record
    coming DOWN to the tree — it cannot be satisfied by the tree regressing
    up to the record, because growth is `--strict`'s job in
    `test_no_new_offender_and_the_ratchet_holds` beside it. Sister precedent,
    in this repo's own words: "RATCHET ON MEMBERSHIP, NOT ON COUNT"
    (vibe-ic#900, quoted in `prose_polarity_consulted_check`).
    """
    recorded = set(json.loads(BASELINE.read_text())["offenders"])
    assert recorded, "an empty record cannot distinguish a clean tree from a blind gate"
    stale = _recorded_but_converted(recorded, _tree_offenders())
    assert not stale, (
        "recorded-but-converted ratchet slot(s) — each one is a hole the named "
        f"program can regress back through with the ratchet still green: {stale}")
    for s in CONVERTED:
        assert f"{s}.py" not in recorded, f"{s} converted but still recorded residual"


def test_the_subset_assertion_can_itself_fail():
    """NEGATIVE CONTROL for the test above, and it is load-bearing.

    `assert not stale` passes vacuously if `_recorded_but_converted` ever
    stops finding anything — the same vacuity `test_the_detector_actually_
    finds_this_shape` exists to rule out one level down. Hand it a record
    carrying a name the tree does not flag and require it to say so.
    """
    tree = _tree_offenders()
    assert tree, "the detector flags nothing at all — the subset test is vacuous"
    ghost = "__a_program_that_was_converted_or_never_existed__.py"
    assert ghost not in tree
    assert _recorded_but_converted(tree | {ghost}, tree) == [ghost]
    assert _recorded_but_converted(tree, tree) == []


def test_no_new_offender_and_the_ratchet_holds():
    assert G.main([str(PROGRAMS)]) == 0
    assert G.main([str(PROGRAMS), "--strict"]) == 0


def test_the_converted_programs_still_import():
    """`writing()` is a drop-in for the context-manager form, but a rewrite
    that broke a module would be invisible to a gate that only greps for the
    old shape. Compile each converted program."""
    import py_compile
    import tempfile
    for s in CONVERTED:
        with tempfile.NamedTemporaryFile(suffix=".pyc") as t:
            py_compile.compile(str(PROGRAMS / f"{s}.py"), cfile=t.name, doraise=True)
