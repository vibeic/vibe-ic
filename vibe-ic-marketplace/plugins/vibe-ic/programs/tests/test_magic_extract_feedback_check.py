"""The extraction tool's error channel must be read, and its silence must not
be readable as a clean answer.

WHAT THE PRE-CHANGE TREE DID, AND THE CONTROL THAT PROVES IT
============================================================
Before ``magic_extract_feedback_check`` existed there was NOTHING in this
plugin that opened Magic's ``feedback.txt``. Measured on origin/main
0d7b6428a::

    $ grep -rEil 'illegal.{0,3}overlap' .   # whole plugin, .git excluded
    FILE COUNT: 0
    $ grep -rEil 'feedback\\.txt' vibe-ic-marketplace/plugins/vibe-ic/
    FILE COUNT: 0

``test_the_pre_change_tree_had_no_reader_of_this_channel`` re-runs the first
of those two searches against the SHIPPED tree and asserts the program added
here is what answers it — so the test cannot pass on a tree where the reader
was deleted, and cannot pass vacuously on the tree where it never existed.

BOTH DIRECTIONS, EVERY TIME
===========================
Every predicate below is asserted twice: once on an input that must FAIL and
once on the neighbouring input that must PASS. A gate asserted only on its
failing input is indistinguishable from a gate that always fails, and a gate
asserted only on its clean input is indistinguishable from a gate that always
passes — this repo has landed both mistakes.

The three verdicts are separated by CODE, not only by rc, because the whole
point of the change is that "no extraction happened" (rc 2), "an extraction
happened and its channel is missing" (rc 1, FEEDBACK_ABSENT) and "an
extraction happened and reported overlaps" (rc 1, ILLEGAL_OVERLAP) are three
different states that the pre-change tree collapsed into one silent pass.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "magic_extract_feedback_check.py"
assert PROG.exists(), f"program not found: {PROG}"

sys.path.insert(0, str(PROG.parent))
import magic_extract_feedback_check as mefc  # noqa: E402

PLUGIN_ROOT = PROG.parent.parent

RC_OK, RC_FAIL, RC_NOT_CHECKED = 0, 1, 2

# A minimal Magic ext2spice netlist: enough of the real provenance header for
# `is_extraction_product` to recognise the directory as an extraction run.
EXT2SPICE_NETLIST = (
    "* NGSPICE file created from top.ext - technology: generic\n"
    ".subckt top a b\n"
    ".ends\n"
)

FEEDBACK_TWO_OVERLAPS = (
    'box 100 200 300 400\n'
    'feedback add "Illegal overlap between locali and li1" medium\n'
    'box 500 600 700 800\n'
    'feedback add "Illegal overlap between locali and li1" medium\n'
    'box 900 1000 1100 1200\n'
    'feedback add "Nodes need to be connected" medium\n'
)

FEEDBACK_CLEAN = (
    'box 100 200 300 400\n'
    'feedback add "Nodes need to be connected" medium\n'
)


def _extraction_run(root: Path, feedback: str | None,
                    rel: str = "phase3/stage3/extracted") -> Path:
    """A directory that IS a Magic extraction run, with or without a channel."""
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / "top.spice").write_text(EXT2SPICE_NETLIST)
    (d / "cif_scale.txt").write_text("0.5\n")
    if feedback is not None:
        (d / "feedback.txt").write_text(feedback)
    return d


def _run(project: Path, *args) -> tuple[int, dict]:
    """Invoke through the CLI, so rc and the report are both the real ones."""
    cp = subprocess.run(
        [sys.executable, str(PROG), str(project), *args],
        capture_output=True, text=True)
    doc = json.loads(cp.stdout)
    return cp.returncode, doc


# ══════════════════════════════════════ 1. THE CONTROL: nobody read this file
def test_the_pre_change_tree_had_no_reader_of_this_channel():
    """The whole plugin's answer to `illegal.{0,3}overlap` is THIS change.

    On origin/main 0d7b6428a the search returned 0 files. If the reader added
    here were reverted, the search would return 0 again and this test would
    fail — which is what makes every other test in this module a measurement
    of a change rather than of a coincidence.
    """
    rx = re.compile(r"illegal.{0,3}overlap", re.I)
    hits = set()
    for p in PLUGIN_ROOT.rglob("*"):
        if not p.is_file() or ".git" in p.parts or "__pycache__" in p.parts:
            continue
        try:
            if rx.search(p.read_text(encoding="utf-8", errors="ignore")):
                hits.add(p.name)
        except OSError:
            continue
    assert PROG.name in hits, (
        "the extraction error channel has no reader in this tree — this is "
        "the pre-change state the change exists to leave")


# ══════════════════════════════════════ 2. OVERLAPS FAIL / CLEAN PASSES
def test_a_fixture_extraction_with_illegal_overlaps_fails_the_gate(tmp_path):
    _extraction_run(tmp_path, FEEDBACK_TWO_OVERLAPS)
    rc, doc = _run(tmp_path)
    assert rc == RC_FAIL
    assert doc["verdict"] == "FAIL"
    assert doc["summary"]["illegal_overlap_count"] == 2
    rules = [f["rule"] for f in doc["findings"]]
    assert "ILLEGAL_OVERLAP" in rules


def test_the_same_extraction_without_overlaps_passes(tmp_path):
    """The other direction. Without this the gate above is indistinguishable
    from one that fails on every extraction."""
    _extraction_run(tmp_path, FEEDBACK_CLEAN)
    rc, doc = _run(tmp_path)
    assert rc == RC_OK
    assert doc["verdict"] == "PASS"
    assert doc["summary"]["illegal_overlap_count"] == 0
    assert doc["summary"]["checked"] is True


def test_the_threshold_is_zero_so_one_overlap_is_enough(tmp_path):
    _extraction_run(
        tmp_path,
        'box 1 2 3 4\nfeedback add "Illegal overlap between a and b" medium\n')
    rc, doc = _run(tmp_path)
    assert doc["threshold"] == 0
    assert doc["summary"]["illegal_overlap_count"] == 1
    assert rc == RC_FAIL


# ══════════════════════════════════════ 3. ABSENT IS NOT ZERO
def test_deleting_the_feedback_file_fails_with_a_different_message(tmp_path):
    """The trap this change exists for. Same extraction, channel removed: it
    must fail, and it must NOT fail as if it had found overlaps — a reader who
    cannot tell the two apart will go looking for geometry that is not the
    problem."""
    d = _extraction_run(tmp_path, FEEDBACK_TWO_OVERLAPS)
    (d / "feedback.txt").unlink()

    rc, doc = _run(tmp_path)
    assert rc == RC_FAIL
    rules = [f["rule"] for f in doc["findings"]]
    assert rules == ["FEEDBACK_ABSENT"], rules
    assert "ILLEGAL_OVERLAP" not in rules
    assert doc["summary"]["illegal_overlap_count"] is None, (
        "an unread channel must not publish a number")
    assert doc["summary"]["runs_without_feedback"] == [
        "phase3/stage3/extracted"]


def test_an_absent_channel_and_a_clean_channel_are_different_verdicts(tmp_path):
    """Stated as one assertion because it is the whole defect: the pre-change
    tree gave these two states the same answer."""
    absent = tmp_path / "absent"
    clean = tmp_path / "clean"
    _extraction_run(absent, None)
    _extraction_run(clean, FEEDBACK_CLEAN)

    rc_a, doc_a = _run(absent)
    rc_c, doc_c = _run(clean)
    assert (rc_a, rc_c) == (RC_FAIL, RC_OK)
    assert doc_a["verdict"] != doc_c["verdict"]


def test_an_unreadable_channel_is_not_a_clean_one(tmp_path):
    d = _extraction_run(tmp_path, FEEDBACK_CLEAN)
    fb = d / "feedback.txt"
    fb.unlink()
    fb.mkdir()                       # exists, is not readable as a file
    rc, doc = _run(tmp_path)
    assert rc == RC_FAIL
    assert "FEEDBACK_ABSENT" in [f["rule"] for f in doc["findings"]]


def test_no_extraction_at_all_is_not_checked_and_says_so(tmp_path):
    """rc 2, and the metric is null. A project that never extracted has
    nothing to gate — but it must not be recorded as having extracted
    cleanly."""
    (tmp_path / "phase3/stage3/extracted").mkdir(parents=True)
    (tmp_path / "phase3/stage3/extracted/top.spef").write_text(
        '*SPEF "IEEE 1481-1998"\n*DESIGN "top"\n*D_NET n1 1\n')

    rc, doc = _run(tmp_path)
    assert rc == RC_NOT_CHECKED
    assert doc["verdict"] == "NOT_CHECKED"
    assert doc["summary"]["checked"] is False
    assert doc["summary"]["illegal_overlap_count"] is None
    assert [f["rule"] for f in doc["findings"]] == ["NO_EXTRACTION_RUN"]


def test_a_router_spef_is_not_a_magic_extraction_run(tmp_path):
    """Guards the predicate the rc1/rc2 split rests on. If a `.spef` counted
    as a Magic run, every routed design in the corpus would fail
    FEEDBACK_ABSENT for an error channel that tool never writes."""
    d = tmp_path / "phase3/stage3/extracted"
    d.mkdir(parents=True)
    (d / "top.spef").write_text('*SPEF "IEEE 1481-1998"\n')
    assert mefc.is_extraction_product(d / "top.spef") is False
    # ...and the neighbouring file that IS one:
    (d / "top.spice").write_text(EXT2SPICE_NETLIST)
    assert mefc.is_extraction_product(d / "top.spice") is True


def test_a_named_feedback_path_that_is_absent_fails(tmp_path):
    """`--feedback` names the channel explicitly; a named path that is not on
    disk is the same 'could not look' and must not fall back to discovery."""
    rc, doc = _run(tmp_path, "--feedback", "nowhere/feedback.txt")
    assert rc == RC_FAIL
    assert "FEEDBACK_ABSENT" in [f["rule"] for f in doc["findings"]]


# ══════════════════════════════════════ 4. TWO COUNTS, AND THEY MUST AGREE
def test_the_two_counts_are_both_computed(tmp_path):
    _extraction_run(tmp_path, FEEDBACK_TWO_OVERLAPS)
    _, doc = _run(tmp_path)
    assert doc["summary"]["illegal_overlap_string_count"] == 2
    assert doc["summary"]["illegal_overlap_parsed_count"] == 2


def test_a_disagreement_between_the_two_counts_is_loud(tmp_path):
    """Two `feedback add` records on ONE line. The string count is `grep -c`,
    so it sees 1; the structured walk sees 2. Upstream overwrites one with the
    other and says nothing (steps/magic.py:666)."""
    _extraction_run(
        tmp_path,
        'box 1 2 3 4\n'
        'feedback add "Illegal overlap between a and b" medium '
        'box 5 6 7 8 feedback add "Illegal overlap between a and b" medium\n')
    rc, doc = _run(tmp_path)
    assert rc == RC_FAIL
    rules = [f["rule"] for f in doc["findings"]]
    assert "COUNT_DISAGREEMENT" in rules
    assert doc["summary"]["illegal_overlap_string_count"] == 1
    assert doc["summary"]["illegal_overlap_parsed_count"] == 2
    assert doc["summary"]["illegal_overlap_count"] == 2, (
        "the verdict must take the larger of two irreconcilable counts")
    sev = {f["rule"]: f["severity"] for f in doc["findings"]}
    assert sev["COUNT_DISAGREEMENT"] == "ERROR", (
        "a disagreement reported at a severity that does not move rc is not "
        "loud, it is a log line")


def test_the_verdict_takes_the_larger_count_not_the_parsed_one(tmp_path):
    """The mutation that survives every other assertion in this module.

    Upstream computes the string count, publishes it, then OVERWRITES the
    metric with the parsed count (steps/magic.py:659-666). Where the parsed
    count is the LARGER one that is invisible; where it is the SMALLER one it
    silently shrinks the number the gate is about to compare against zero.

    A rule string that spans two lines is exactly that case: `grep -c` sees
    two lines carrying `Illegal overlap`, the structured walk sees one
    `feedback add` record. 2 vs 1 — and a gate that adopts upstream's
    overwrite reports 1 here while claiming to have read both channels.
    """
    _extraction_run(
        tmp_path,
        'box 1 2 3 4\n'
        'feedback add "Illegal overlap between a and b\n'
        'and also Illegal overlap between c and d" medium\n')
    rc, doc = _run(tmp_path)
    assert rc == RC_FAIL
    assert doc["summary"]["illegal_overlap_string_count"] == 2
    assert doc["summary"]["illegal_overlap_parsed_count"] == 1
    assert doc["summary"]["illegal_overlap_count"] == 2, (
        "the verdict took the parsed count — upstream's silent overwrite")
    sev = {f["rule"]: f["severity"] for f in doc["findings"]}
    assert sev.get("COUNT_DISAGREEMENT") == "ERROR"


def test_agreeing_counts_raise_no_disagreement(tmp_path):
    """The other direction: the disagreement finding must not fire on every
    file that happens to carry overlaps."""
    _extraction_run(tmp_path, FEEDBACK_TWO_OVERLAPS)
    _, doc = _run(tmp_path)
    assert "COUNT_DISAGREEMENT" not in [f["rule"] for f in doc["findings"]]


def test_an_unparseable_channel_does_not_silently_become_the_string_count(
        tmp_path):
    """`feedback add` with no `box` selected is malformed. Upstream catches the
    ValueError, warns, and keeps the string count — a number derived from a
    file it just admitted it could not walk."""
    _extraction_run(
        tmp_path, 'feedback add "Nodes need to be connected" medium\n')
    rc, doc = _run(tmp_path)
    assert rc == RC_FAIL
    assert "FEEDBACK_UNPARSEABLE" in [f["rule"] for f in doc["findings"]]


def test_a_wellformed_channel_parses(tmp_path):
    count, rules = mefc.parse_magic_feedback(FEEDBACK_TWO_OVERLAPS)
    assert count == 2
    assert "Nodes need to be connected" in rules


# ══════════════════════════════════════ 5. THE SCOPE CANNOT BUY SILENCE
def test_a_scope_that_misses_the_extraction_fails_rather_than_passing(tmp_path):
    _extraction_run(tmp_path, FEEDBACK_TWO_OVERLAPS)
    (tmp_path / "reports").mkdir(exist_ok=True)
    rc, doc = _run(tmp_path, "--under", "reports")
    assert rc == RC_FAIL, "a mis-scoped gate must not return rc 2"
    assert "SCOPE_MISSES_EXTRACTION" in [f["rule"] for f in doc["findings"]]


def test_the_declared_scope_finds_the_extraction(tmp_path):
    """The other direction — the scope the flow actually wires."""
    _extraction_run(tmp_path, FEEDBACK_TWO_OVERLAPS)
    rc, doc = _run(tmp_path, "--under", "phase3/stage3")
    assert rc == RC_FAIL
    assert [f["rule"] for f in doc["findings"]] == ["ILLEGAL_OVERLAP"]


def test_an_absent_scope_on_a_project_with_no_extraction_is_not_checked(
        tmp_path):
    rc, doc = _run(tmp_path, "--under", "phase3/stage3")
    assert rc == RC_NOT_CHECKED
    assert doc["summary"]["scope_exists"] is False


# ══════════════════════════════════════ 6. THE METRIC
def test_the_count_is_published_as_a_metric(tmp_path):
    _extraction_run(tmp_path, FEEDBACK_TWO_OVERLAPS)
    _run(tmp_path)
    doc = json.loads((tmp_path / "reports/metrics/31.json").read_text())
    assert doc["31__extraction__illegal_overlap_count"] == 2
    assert doc["31__extraction__illegal_overlap_string_count"] == 2
    assert doc["31__extraction__illegal_overlap_parsed_count"] == 2


def test_an_unmeasured_count_is_published_as_null_and_never_as_zero(tmp_path):
    """A metrics consumer that cannot tell 'no overlaps' from 'no measurement'
    reproduces this whole defect one layer further out."""
    (tmp_path / "phase3").mkdir()
    _run(tmp_path)
    doc = json.loads((tmp_path / "reports/metrics/31.json").read_text())
    assert doc["31__extraction__illegal_overlap_count"] is None
    assert doc["31__extraction__run_count"] == 0


def test_the_report_carries_upstreams_own_metric_key(tmp_path):
    """So the two flows' numbers can be diffed without a translation table."""
    _extraction_run(tmp_path, FEEDBACK_TWO_OVERLAPS)
    _, doc = _run(tmp_path)
    assert doc["metrics"]["magic__illegal_overlap__count"] == 2


# ══════════════════════════════════════ 7. THE WIRING
def _flow_text() -> str:
    return (PLUGIN_ROOT / "flow/phase1_phase2_phase3.yaml").read_text()


def test_the_gate_is_wired_into_the_flow_between_extraction_and_lvs():
    """Position is the point. Upstream runs its equivalent between
    `Magic.SpiceExtraction` and `Checker.LVS`; this clause must precede the
    LVS sign-off gate in step 31's `all_of`, or an extraction that produced
    illegal overlaps still reaches a clean LVS report."""
    text = _flow_text()
    ours = text.find("magic_extract_feedback_check .")
    lvs = text.find('lvs_report_check . --mode lvs')
    assert ours != -1, "the gate is not wired into the flow at all"
    assert lvs != -1
    assert ours < lvs, (
        "the extraction error channel must be read BEFORE the LVS verdict")


def test_the_wired_invocation_is_the_one_the_program_supports():
    """A gate line that argparse rejects is a gate that never runs."""
    m = re.search(r'program_exit_zero: "magic_extract_feedback_check (.+?)"',
                  _flow_text())
    assert m, "no wired invocation found"
    args = m.group(1).split()
    assert args[0] == ".", args
    cp = subprocess.run([sys.executable, str(PROG), "--help"],
                        capture_output=True, text=True)
    assert cp.returncode == 0
    for flag in [a for a in args if a.startswith("--")]:
        assert flag in cp.stdout, f"{flag} is not a flag this program accepts"


def test_the_flow_engine_itself_fails_the_step_on_a_dirty_extraction(tmp_path):
    """Prove-by-run, through `flow_compliance_check`'s OWN gate evaluator.

    The tests above measure the program. This one measures the WIRING: it
    takes the clause verbatim out of the flow definition and hands it to the
    function the flow engine uses to decide whether a `program_exit_zero`
    clause passed. A gate that fails on its own but is credited by the engine
    is a gate that stops nothing.

    All four states are asserted, because the pass side is what proves the
    fail side is not simply "this clause always fails":

        dirty extraction  -> FAIL
        clean extraction  -> PASS
        feedback deleted  -> FAIL, on a DIFFERENT finding
        no extraction     -> PASS, disclosed vacuous (rc 2)
    """
    yaml = pytest.importorskip("yaml")
    sys.path.insert(0, str(PLUGIN_ROOT / "programs"))
    fcc = pytest.importorskip("flow_compliance_check")

    flow = yaml.safe_load(
        (PLUGIN_ROOT / "flow/phase1_phase2_phase3.yaml").read_text())
    steps = flow["steps"] if isinstance(flow, dict) else flow
    step31 = [s for s in steps if str(s.get("id")) == "31"][0]
    clauses = [c for c in step31["gate"]["all_of"] if isinstance(c, dict)]
    mine = [c["program_exit_zero"] for c in clauses
            if "magic_extract_feedback_check" in str(
                c.get("program_exit_zero", ""))]
    assert len(mine) == 1, mine
    cmd = mine[0]

    dirty = tmp_path / "dirty"
    clean = tmp_path / "clean"
    nofb = tmp_path / "nofb"
    norun = tmp_path / "norun"
    _extraction_run(dirty, FEEDBACK_TWO_OVERLAPS)
    _extraction_run(clean, FEEDBACK_CLEAN)
    _extraction_run(nofb, None)
    (norun / "phase3/stage3").mkdir(parents=True)

    ok_dirty, why_dirty = fcc._check_program_exit_zero(dirty, cmd)
    ok_clean, _ = fcc._check_program_exit_zero(clean, cmd)
    ok_nofb, why_nofb = fcc._check_program_exit_zero(nofb, cmd)
    ok_norun, why_norun = fcc._check_program_exit_zero(norun, cmd)

    assert ok_dirty is False, "the flow engine credited an extraction with overlaps"
    assert ok_clean is True, "the clause fails a clean extraction too — it gates nothing"
    assert ok_nofb is False, "a deleted error channel was credited as clean"
    assert ok_norun is True, "a project that never extracted must not be failed"

    assert "ILLEGAL_OVERLAP" in why_dirty
    assert "FEEDBACK_ABSENT" in why_nofb
    assert "ILLEGAL_OVERLAP" not in why_nofb, (
        "the two failures must be distinguishable in what the engine records")
    assert "VACUOUS" in why_norun.upper(), (
        "an rc-2 pass must be disclosed as vacuous, not recorded as a clean "
        "extraction")


def test_the_clause_runs_before_the_lvs_clause_in_the_declared_order(tmp_path):
    """The same ordering claim as the textual test above, read out of the
    parsed gate list rather than out of the file's bytes."""
    yaml = pytest.importorskip("yaml")
    flow = yaml.safe_load(
        (PLUGIN_ROOT / "flow/phase1_phase2_phase3.yaml").read_text())
    steps = flow["steps"] if isinstance(flow, dict) else flow
    step31 = [s for s in steps if str(s.get("id")) == "31"][0]
    names = [str(c.get("program_exit_zero", "")).split()[0]
             for c in step31["gate"]["all_of"] if isinstance(c, dict)]
    names = [n for n in names if n]
    assert "magic_extract_feedback_check" in names
    assert (names.index("magic_extract_feedback_check")
            < names.index("lvs_report_check"))
