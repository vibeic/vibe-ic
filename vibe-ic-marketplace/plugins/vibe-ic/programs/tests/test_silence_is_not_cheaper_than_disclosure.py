"""test_silence_is_not_cheaper_than_disclosure.py — the inverted incentive.

WHAT WAS ALREADY TRUE, AND WHY IT WAS NOT ENOUGH
================================================
An artefact whose content came from a library default got its own disposition:
its own tier, its own matrix cell, its own word on the summary line. That is
the right answer to "how should an honest ceiling be scored", and on its own it
created a cheaper answer to a different question — "should I disclose at all?"

Measured on the adversarial round: delete the disclosure fields from a corner
artefact and it CERTIFIED. Disclose honestly and it earned the lesser tier. The
deleted shape is not exotic — it is the shape of EVERY artefact written before
those fields existed, and of every stale one. A gate that pays more for silence
than for disclosure teaches the next producer to be silent, which is the
behaviour the whole disposition exists to remove.

THE RULE UNDER TEST, with no tool, step or block name in it:

    An artefact that declines to say what it contains must not certify the
    step it is the evidence for.

    Declining is not only omitting the field. A record that says it has no
    record is an honest statement of ignorance and still not a statement of
    content; if it certified, a producer could buy a pass by writing that token
    instead of by inheriting the answer, and silence would be cheap again under
    a new name.

THE ORDERING EVERY ASSERTION HERE DEFENDS, end to end:

    design-bound   >   structure-only (disclosed)   >   undisclosed
                                                    >   invented content

Reverse any adjacent pair anywhere in the chain and the chain pays a producer
to say less. Each test below fixes one link in one consumer, and each one is
written so that it fails on a wrong CERTIFICATION or a wrong RENDERING — never
on a missing symbol.

Every fixture is synthetic: invented block names, an open PDK selector, library
nominal geometries, no design content.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

A4_GATE = PROGRAMS / "analog_a4_corner_sweep_check.py"
ANALOG_COMPLIANCE = PROGRAMS / "analog_flow_compliance_check.py"
FINAL_REPORT = PROGRAMS / "final_report_generate.py"

STRUCTURE_ONLY = "structure_only"
SIZED = "structure_and_geometry"
#: The token a producer writes when the upstream shipped no record. It is a
#: non-empty string, so a rule keyed on "is the field present?" accepts it —
#: which is exactly how silence comes back under a new name.
NO_RECORD = "undeclared"


# ── the tree, and the ONE field that varies across it ──────────────────────

def _project(root: Path, design_content, blocks=("blk_alpha",)) -> Path:
    """A complete two-step analog tree. `design_content` is the ONLY thing any
    test varies.

    `None` builds THE PRE-DISCLOSURE SHAPE, and it is built by DELETION on
    purpose: the whole disclosure set goes — the upstream sidecar, the
    `netlist_provenance` claim, `netlist_source`, `design_traceable`,
    `design_content` and its meaning. That is what a pre-fix artefact looks
    like, and what a stale one looks like, and it is what the adversarial round
    produced by hand. Leaving `netlist_provenance` in place would build a
    DIFFERENT tree — one that claims an upstream-derived deck and then says
    nothing about it — which an older, narrower rule already caught; a test
    built on it would prove nothing about the escape that was measured.

    The upstream netlist stays ON DISK in every case, so the rule that is
    decided by the filesystem cannot be the one doing the work.
    """
    adir = root / "phase3" / "analog"
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": b, "type": "ldo"} for b in blocks]}, indent=2))
    for b in blocks:
        d = adir / b
        d.mkdir(parents=True, exist_ok=True)
        (d / "spec.json").write_text(json.dumps({"block": b}))
        (d / "topology.md").write_text("# topology\nlibrary topology\n")
        (d / f"{b}.sp").write_text(
            f"* {b} — synthetic block netlist for this fixture\n"
            f"* every geometry below is a library nominal, on purpose\n"
            f".subckt {b} vdd vss vin vout\n"
            f"xm1 vout vin vss vss nch w=8 l=1\n"
            f"r1 vout vss 100k\n"
            f".ends {b}\n")
        if design_content is not None:
            (d / "netlist_provenance.json").write_text(json.dumps({
                "block": b,
                "_provenance": {"producer": "synthetic-fixture",
                                "design_content": design_content,
                                "spec_bound_params": [],
                                "library_nominal_params": ["m1.w"]}}, indent=2))
        doc = {
            "block": b, "_provenance": "real_ngspice",
            "simulator": "ngspice (docker)", "corners_executed": 1,
            "full_pvt_sweep_executed": True,
            "corners": [{"name": "tt_27c", "simulator_run": True,
                         "vout_v": 1.8}],
            "best_corner": {"name": "tt_27c", "value": 1.8},
            "spec_results": [{"name": "vout", "status": "PASS",
                              "target": None}],
        }
        if design_content is not None:
            doc["netlist_provenance"] = "a3_netlist"
            doc["netlist_source"] = f"phase3/analog/{b}/{b}.sp"
            doc["design_traceable"] = True
            doc["design_content"] = design_content
            doc["design_content_meaning"] = "see the producer record"
        (d / "corner_results.json").write_text(json.dumps(doc, indent=2))
    return root


def _run(prog: Path, project: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(prog), str(project), *args],
                          capture_output=True, text=True, timeout=60)


# ═══ 1. THE GATE OF RECORD — the measured inversion, closed ════════════════

def test_disclosing_a_library_default_certifies_and_saying_nothing_does_not(
        tmp_path):
    """THE HEADLINE, and the exact adversarial move that produced the finding.

    Two trees. One carries the whole disclosure set and says the content came
    from a library default; the other has that set DELETED — simulated corners,
    the upstream netlist present on disk, and nothing anywhere saying which
    circuit produced the numbers.

    Pre-fix the SILENT one was the cheaper of the two: it certified outright,
    while the honest one earned the lesser tier.
    """
    disclosed = _run(A4_GATE, _project(tmp_path / "d", STRUCTURE_ONLY),
                     "--block", "blk_alpha")
    silent = _run(A4_GATE, _project(tmp_path / "s", None),
                  "--block", "blk_alpha")

    assert disclosed.returncode == 0, disclosed.stdout + disclosed.stderr
    assert "STRUCTURE_ONLY:" in disclosed.stdout, (
        "the gate certified and said nothing about what it certified")
    assert silent.returncode == 1, (
        f"the artefact that will not say what circuit it simulated CERTIFIED "
        f"(rc={silent.returncode}) while the one that disclosed a library "
        f"default earned the lesser tier — silence is cheaper than disclosure")
    assert "A4_DESIGN_CONTENT_UNDECLARED" in (silent.stdout + silent.stderr)


def test_a_record_of_having_no_record_is_not_a_record_of_content(tmp_path):
    """Closing the loophole the field itself opens.

    `undeclared` is a non-empty string, so a rule that asks "is the field
    present?" accepts it — and a producer could then buy a pass by writing that
    token instead of by inheriting the answer from upstream. Ranked with
    silence, deliberately, because it says the same amount about the circuit.
    """
    cp = _run(A4_GATE, _project(tmp_path, NO_RECORD), "--block", "blk_alpha")
    assert cp.returncode == 1, (
        f"an artefact recording `design_content: {NO_RECORD!r}` certified — "
        f"silence renamed is still silence")
    assert "A4_DESIGN_CONTENT_UNDECLARED" in (cp.stdout + cp.stderr)


def test_a_design_bound_artefact_still_certifies_as_a_plain_pass(tmp_path):
    """The negative control on the whole rule: it is a DISCLOSURE requirement,
    not a blanket refusal, and it must not have quietly become one."""
    cp = _run(A4_GATE, _project(tmp_path, SIZED), "--block", "blk_alpha")
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "STRUCTURE_ONLY:" not in cp.stdout, (
        "a design-bound artefact was disclosed as a library default")


def test_a_value_failure_is_still_diagnosed_as_a_value_failure(tmp_path):
    """Ordering control at the gate. An artefact that is BOTH silent and
    broken must be reported for the breakage: a reader told "say what it
    contains" about a sweep whose every corner declares no simulator run would
    fix the wrong thing first."""
    root = _project(tmp_path, None)
    crp = root / "phase3" / "analog" / "blk_alpha" / "corner_results.json"
    doc = json.loads(crp.read_text())
    for c in doc["corners"]:
        c["simulator_run"] = False
    crp.write_text(json.dumps(doc, indent=2))
    cp = _run(A4_GATE, root, "--block", "blk_alpha")
    assert cp.returncode == 1
    out = cp.stdout + cp.stderr
    assert "A4_NO_SIMULATOR_RUN" in out, out
    assert "A4_DESIGN_CONTENT_UNDECLARED" not in out, out


def test_a_missing_upstream_is_still_diagnosed_as_a_missing_upstream(tmp_path):
    """The other ordering control: when the netlist the sweep claims to have
    measured does not exist at all, THAT is the finding. It answers "what is in
    the deck?" as a side effect; the reverse is not true."""
    root = _project(tmp_path, None)
    (root / "phase3" / "analog" / "blk_alpha" / "blk_alpha.sp").unlink()
    cp = _run(A4_GATE, root, "--block", "blk_alpha")
    assert cp.returncode == 1
    assert "A4_NETLIST_ABSENT" in (cp.stdout + cp.stderr)


# ═══ 2. THE A1-A9 MATRIX — the cell must not outrank the gate ══════════════

def _matrix(project: Path) -> dict:
    out = project / "afcc.json"
    _run(ANALOG_COMPLIANCE, project, "--json", str(out))
    return (json.loads(out.read_text()).get("summary") or {}).get("matrix") or {}


def test_the_matrix_cell_cannot_sign_off_what_the_gate_refuses(tmp_path):
    """The matrix delegates A4 to the gate's own certification predicates, so
    the two can never disagree about the same artefact. Without the third
    predicate the cell read a signed-off A4 for a corner result the gate itself
    declines to certify."""
    silent = _matrix(_project(tmp_path / "s", None))["blk_alpha"]
    assert silent["A4"] != "PASS", (
        f"the A1-A9 matrix signed off A4 from an artefact that will not say "
        f"what circuit it measured: {silent}")


def test_the_disclosed_ceiling_outranks_the_silent_one_in_the_matrix(tmp_path):
    """The ordering, stated where a reviewer reads it. The disclosed tree gets
    a cell that says what it is; the silent one does not get a better one."""
    so = _matrix(_project(tmp_path / "d", STRUCTURE_ONLY))["blk_alpha"]
    silent = _matrix(_project(tmp_path / "s", None))["blk_alpha"]
    assert so["A4"] == "PASS_STRUCTURE_ONLY", so
    assert silent["A4"] not in ("PASS", "PASS_STRUCTURE_ONLY"), silent
    assert so["A5"] == "MISSING", (
        "PRECONDITION: an obligation that really is unmet must still read "
        "MISSING, or the new cells have simply replaced the old one")


# ═══ 3. THE RUN RECORD — the disclosure has to reach a consumer ════════════

def test_the_runner_records_the_tier_instead_of_a_plain_pass(tmp_path):
    """`grep -c STRUCTURE` over this runner's own report was 0 on a project
    whose every A3/A4 artefact disclosed a library default: the gate printed
    the disclosure and the runner dropped it, recording `PASS` with empty
    extras. A signal that exists and is not read is the same defect one layer
    down."""
    import analog_one_shot_runner as R

    project = _project(tmp_path, STRUCTURE_ONLY)
    res = R.step_for_block(project, {"name": "blk_alpha", "type": "ldo"},
                           "A4_corner_sweep")
    assert res.status == "PASS_STRUCTURE_ONLY", (res.status, res.detail)
    assert res.extras.get("design_content") == STRUCTURE_ONLY, res.extras
    assert res.extras.get("structure_only") is True, res.extras
    assert (res.extras.get("design_content_source") or "").endswith(
        "corner_results.json"), res.extras


def test_the_runner_still_records_a_design_bound_step_as_a_plain_pass(
        tmp_path):
    """Negative control for the branch above."""
    import analog_one_shot_runner as R

    project = _project(tmp_path, SIZED)
    res = R.step_for_block(project, {"name": "blk_alpha", "type": "ldo"},
                           "A4_corner_sweep")
    assert res.status == "PASS", (res.status, res.detail)
    assert res.extras.get("design_content") == SIZED, res.extras
    assert res.extras.get("structure_only") is False, res.extras


# ═══ 4. THE RENDERED GRID — two projects that must not look the same ═══════

def _grid_row(project: Path, block: str) -> str:
    cp = _run(FINAL_REPORT, project, "--no-audit")
    assert cp.returncode == 0, cp.stdout + cp.stderr
    text = (project / "reports" / "final_summary.md").read_text()
    rows = [ln for ln in text.splitlines()
            if f"`{block}`" in ln and ln.count("|") >= 9]
    assert rows, f"no A1-A9 grid row for {block}:\n{text[:1500]}"
    return rows[0]


def test_the_grid_does_not_render_a_library_default_as_a_designed_one(
        tmp_path):
    """THE NEGATIVE CONTROL for the rendering, and the proof the task asks for.

    Two trees identical in every artefact except the one recorded value. If the
    two rendered ROWS are equal, the distinction does not exist for anyone
    reading the summary — which is the document a reviewer reads first.
    """
    so = _grid_row(_project(tmp_path / "d", STRUCTURE_ONLY), "blk_alpha")
    sized = _grid_row(_project(tmp_path / "z", SIZED), "blk_alpha")
    assert so != sized, (
        f"a structure-only A3/A4 and a design-bound A3/A4 render the SAME "
        f"A1-A9 row:\n  {so}")
    assert "◐" in so, so
    assert "◐" not in sized, sized
    # ...and the cells that really are absent still read absent, so the new
    # glyph has not simply replaced the old one.
    assert "—" in so, so


def test_the_resource_line_does_not_count_a_default_as_a_designed_artefact(
        tmp_path):
    """`artefacts present: 8/18` said the same number for a design sized to its
    spec and for a topology library. The subset is named beside the total."""
    root = _project(tmp_path, STRUCTURE_ONLY)
    _run(FINAL_REPORT, root, "--no-audit")
    text = (root / "reports" / "final_summary.md").read_text()
    line = [ln for ln in text.splitlines() if "artefacts present:" in ln]
    assert line, text[:1500]
    assert "library default" in line[0], line[0]


def test_a_project_with_no_such_record_renders_no_new_glyph(tmp_path):
    """Absence of the record is NOT read as a library default. `undeclared` is
    a third answer, the per-step gate owns it, and the grid must not invent a
    content claim the producer did not make."""
    row = _grid_row(_project(tmp_path, None), "blk_alpha")
    assert "◐" not in row, row


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
