#!/usr/bin/env python3
"""A sign-off gate must not certify a design with another run's evidence.

THE FINDING. `adversarial_agent` substitutes a DIFFERENT design's reports into a
published cell (A3), or replays an EARLIER run of the SAME design (A2), and
re-runs each sign-off gate's own CLI. Measured on the cell
`programs/adversarial_findings.json` names, before this check existed:

    A3_CROSS_DESIGN   drc_report_check   rc 0 -> 0   SUCCEEDED
    A3_CROSS_DESIGN   lvs_report_check   rc 0 -> 0   SUCCEEDED
    A2_STALE_REPLAY   drc_report_check   rc 0 -> 0   SUCCEEDED
    A2_STALE_REPLAY   lvs_report_check   rc 0 -> 0   SUCCEEDED

and after it, `13 of 21` forged greens became `9 of 21` -- those four, closed.

A2 is the half that says why design identity is not enough: the artefact really
does belong to this design, so only a check keyed on WHICH RUN wrote it can
object. The run's own `provenance.jsonl` is that witness.

THE DELETION CONTROL, run before any of this was written, because a
substitution attack that swaps files no gate reads is a forged FINDING and would
have sent this work at nothing. For each pair above, the same paths were DELETED
instead of substituted:

    A3  drc_report_check   n=149  rc_after_DELETE=1   -> the gate does read them
    A2  lvs_report_check   n=144  rc_after_DELETE=1   -> the gate does read them

Both reddened, so the greens above were real greens over evidence the gate
genuinely consumed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from _published_corpus import cell_dirs, needs_corpus

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import eda_report_audit as ERA  # noqa: E402


def _sha(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def _project(tmp_path: Path, *, rel: str, written: bytes,
             present: bytes | None, record: bool = True) -> Path:
    """A synthesized run: a ledger claiming `written` at `rel`, and whatever
    bytes are actually there. Nothing here is copied from a real design."""
    proj = tmp_path / "run"
    (proj / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    if present is not None:
        (proj / rel).write_bytes(present)
    if record:
        (proj / "provenance.jsonl").write_text(json.dumps({
            "tool": "synthetic", "exit_code": 0,
            "outputs": {rel: _sha(written)},
        }) + "\n", encoding="utf-8")
    return proj


def _ledger_outputs(cell: Path) -> dict:
    """The run's recorded output digests, read by the TEST.

    Deliberately not `ERA.provenance_outputs`: the CLI control below must run
    the gate and observe its EXIT CODE on the pre-fix tree, and a test that
    reaches for the function the fix introduces fails by absence instead, which
    grades as no control at all.
    """
    led = cell / "provenance.jsonl"
    out: dict = {}
    if not led.is_file():
        return out
    for line in led.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            for rel, dig in (rec.get("outputs") or {}).items():
                if isinstance(rel, str) and isinstance(dig, str) \
                        and dig.startswith("sha256:"):
                    out[rel] = dig
    return out


REL = "reports/phase3/some_report.rpt"
MINE = b"the bytes this run produced\n"
THEIRS = b"the bytes some other run produced\n"


# ===========================================================================
# THE REFUSAL, AND THE PAIR THAT PROVES IT DISCRIMINATES
# ===========================================================================
def test_a_report_the_run_did_not_write_is_REFUSED(tmp_path):
    proj = _project(tmp_path, rel=REL, written=MINE, present=THEIRS)
    findings, summary = ERA.check_evidence_binding(proj, [proj / REL])
    assert [f.rule for f in findings] == ["EVIDENCE_NOT_FROM_THIS_RUN"], findings
    assert findings[0].severity == "ERROR", findings[0]
    assert findings[0].file == REL, findings[0]
    assert summary["evidence_binding"] == "CHECKED", summary
    assert summary["evidence_binding_mismatched"] == 1, summary


def test_PAIRED_the_report_the_run_DID_write_is_accepted(tmp_path):
    """The twin. A binding that refuses everything measures nothing, and would
    turn every honest sign-off red the day it landed."""
    proj = _project(tmp_path, rel=REL, written=MINE, present=MINE)
    findings, summary = ERA.check_evidence_binding(proj, [proj / REL])
    assert findings == [], findings
    assert summary["evidence_binding"] == "CHECKED", summary
    assert summary["evidence_binding_covered"] == 1, summary


# ===========================================================================
# THE THREE WAYS THIS RULE COULD HAVE BEEN A FALSE-POSITIVE MACHINE
# ===========================================================================
def test_a_recorded_output_that_is_ABSENT_does_not_fire(tmp_path):
    """Publishing PRUNES intermediates. Swept over every run root reachable
    here, 31 of them: 117 recorded outputs are present and 179 are recorded but
    ABSENT. A rule that fired on absence would fire on 179 legitimate files, so
    only a PRESENT file whose bytes disagree is refusable."""
    proj = _project(tmp_path, rel=REL, written=MINE, present=None)
    findings, summary = ERA.check_evidence_binding(proj, [proj / REL])
    assert findings == [], findings
    assert summary["evidence_binding_covered"] == 0, summary


def test_no_ledger_is_NOT_DETERMINED_and_says_so(tmp_path):
    """Degrade loudly. A run with no ledger has not answered the question, and
    a silent skip reads downstream as 'nothing was wrong'."""
    proj = _project(tmp_path, rel=REL, written=MINE, present=THEIRS,
                    record=False)
    findings, summary = ERA.check_evidence_binding(proj, [proj / REL])
    assert findings == [], findings
    assert summary["evidence_binding"] == "NO_LEDGER", summary
    assert "NOT DETERMINED" in summary["evidence_binding_note"], summary


def test_a_report_the_ledger_never_mentions_is_NOT_DETERMINED_and_says_so(tmp_path):
    """The honest limit, published rather than implied: on the cell the findings
    ledger names, 5 of 149 substituted artefacts are covered, and `antenna`,
    `em`, `ir_drop` and `sta` read none of them. Their findings stay OPEN, and
    this branch is what stops that reading as a defence."""
    proj = _project(tmp_path, rel=REL, written=MINE, present=MINE)
    other = proj / "reports" / "phase3" / "unmentioned.rpt"
    other.write_bytes(THEIRS)
    findings, summary = ERA.check_evidence_binding(proj, [other])
    assert findings == [], findings
    assert summary["evidence_binding"] == "NO_COVERAGE", summary
    assert "NOT DETERMINED" in summary["evidence_binding_note"], summary


def test_a_malformed_ledger_leaves_the_verdict_alone(tmp_path):
    """A defect in the bookkeeping must never turn a sign-off gate red."""
    proj = _project(tmp_path, rel=REL, written=MINE, present=MINE)
    (proj / "provenance.jsonl").write_text("{not json\n\n[]\n", encoding="utf-8")
    findings, summary = ERA.check_evidence_binding(proj, [proj / REL])
    assert findings == [], findings
    assert summary["evidence_binding"] == "NO_LEDGER", summary


# ===========================================================================
# THROUGH THE REAL CLI — the exit code is what the flow reads
# ===========================================================================
def _run(project: Path, mode: str, out: Path):
    """`(rc, findings rules, summary)` from the gate's OWN CLI."""
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / f"{mode}_report_check.py"), ".",
         "--mode", mode, "--json", str(out)],
        cwd=str(project), capture_output=True, text=True, timeout=300)
    try:
        doc = json.loads(r.stdout[r.stdout.index("{"):])
    except (ValueError, KeyError):
        doc = {"findings": [], "summary": {}}
    return (r.returncode,
            [f.get("rule") for f in doc.get("findings", ())],
            doc.get("summary", {}))


@needs_corpus
def test_a_real_published_cell_is_NOT_reddened_by_this_rule():
    """Criterion 2, on real data rather than on fixtures written beside it.

    Every reachable published cell carrying a ledger, every sign-off mode:
    9 cells x 6 modes = 54 runs, 18 reached CHECKED, 36 NO_COVERAGE, 0
    mismatches, and 0 runs changed rc against the pre-change tree. A gate that
    fires on a legitimately complete design is a bug in the gate.
    """
    cells = [c for c in cell_dirs() if (c / "provenance.jsonl").is_file()]
    if not cells:
        pytest.skip("no published cell here carries a provenance ledger")
    checked = 0
    for cell in cells:
        outs = _ledger_outputs(cell)
        present = [cell / r for r in outs if (cell / r).is_file()]
        if not present:
            continue
        findings, summary = ERA.check_evidence_binding(cell, present)
        checked += summary["evidence_binding_covered"]
        assert findings == [], (
            f"{cell.name}: this rule fires on a PRISTINE published cell, which "
            f"makes it a bug in the rule and not a finding: "
            f"{[f.file for f in findings]}")
    assert checked > 0, (
        "no published cell here has a single ledger-covered report present, so "
        "this check measured nothing — do not read it as a clean sweep")


@needs_corpus
def test_the_CLI_REFUSES_a_cell_whose_report_was_swapped(tmp_path):
    """Prove-by-run, BLOCKING, THROUGH THE GATE'S OWN CLI.

    Reading the code is not evidence that a gate stops anything — 62 of 72 gates
    in this repo once could not.

    IT ASSERTS THE RULE AND NOT ONLY THE EXIT CODE, and that is not fussiness.
    The first version of this test asserted `rc == 1` alone and PASSED on the
    pre-fix tree: appending a line to a DRC report reddens the mode's own
    content checks for reasons that have nothing to do with whose report it is.
    A control that passes is not a control, so the assertion names the refusal
    it is here to prove.
    """
    cells = [c for c in cell_dirs()
             if any((c / r).is_file() and "drc" in r and r.endswith(".rpt")
                    for r in _ledger_outputs(c))]
    if not cells:
        pytest.skip("no published cell here has a ledger-covered drc report")
    src = cells[0]
    proj = tmp_path / "proj"
    subprocess.run(["cp", "-r", str(src), str(proj)], check=True)
    covered = [r for r in _ledger_outputs(proj)
               if (proj / r).is_file() and "drc" in r and r.endswith(".rpt")]

    rc0, rules0, summary0 = _run(proj, "drc", tmp_path / "a.json")
    assert "EVIDENCE_NOT_FROM_THIS_RUN" not in rules0, (
        f"the pristine cell already trips the binding, so the mutation below "
        f"would prove nothing: {rules0}")
    assert summary0.get("evidence_binding") == "CHECKED", (
        f"the binding did not reach a decision on the pristine cell "
        f"({summary0.get('evidence_binding')!r}), so this test cannot tell a "
        f"defence from a gap")

    for r in covered:
        (proj / r).write_bytes(
            (proj / r).read_bytes() + b"\n# these bytes came from elsewhere\n")

    rc1, rules1, summary1 = _run(proj, "drc", tmp_path / "b.json")
    assert "EVIDENCE_NOT_FROM_THIS_RUN" in rules1, (
        f"the gate read {len(covered)} report(s) whose bytes its own run never "
        f"wrote and did not object. Findings were {rules1}. A sign-off gate "
        f"that cannot tell whose report it read is signing a statement about a "
        f"design it never examined.")
    assert rc1 == 1, (
        f"the gate NAMED the foreign evidence and still exited {rc1}. A gate "
        f"that notices and does not block differs from no gate only in being "
        f"auditable afterwards.")


# ===========================================================================
# AN ERROR FINDING MUST FAIL THE AUDIT
#
# THE FINDING. `adversarial_agent`'s A1 overwrites every `*.rpt` in a published
# cell with "TAMPERED BY THE ADVERSARY". Six of seven gates flip rc 0 -> 1
# because they need their evidence to pass. Measured on the cell the ledger
# names, 23 reports overwritten:
#
#     ir_drop_report_check   rc=0   passed: True
#       ERROR IR_DROP_REPORT_TOO_SMALL    reports/phase3/ir_drop.rpt
#       ERROR IR_DROP_NO_TOOL_SIGNATURE   reports/phase3/ir_drop.rpt
#
# It named the destroyed report twice, at ERROR, and signed the step off.
# ===========================================================================
def _result(passed: bool, *severities: str):
    return ERA.AuditResult(
        program="eda_report_audit:test", passed=passed,
        findings=[ERA.Finding(rule=f"R{i}", severity=sev, message="m")
                  for i, sev in enumerate(severities)],
        summary={})


def test_a_PASS_beside_an_ERROR_finding_is_downgraded():
    out = ERA.enforce_error_findings(_result(True, "ERROR"))
    assert out.passed is False
    assert out.summary["passed_downgraded_by"] == ["R0"], out.summary
    assert "differs from no gate" in out.summary["passed_downgraded_note"]


def test_PAIRED_a_PASS_with_no_ERROR_finding_survives():
    """The twin. A rule that downgrades everything is not a gate, it is an
    outage, and WARNING / INFO exist in this program precisely so a finding can
    be recorded without gating."""
    out = ERA.enforce_error_findings(_result(True, "WARNING", "INFO"))
    assert out.passed is True
    assert out.summary["error_findings"] == [], out.summary
    assert "passed_downgraded_by" not in out.summary


def test_it_only_ever_DOWNGRADES():
    """A mode that already failed must not be turned green by the rule meant to
    make gates stricter."""
    out = ERA.enforce_error_findings(_result(False))
    assert out.passed is False


def test_the_downgrade_is_never_silent():
    """Degrade loudly: the rules responsible are named, so a reader can see WHY
    a gate that used to pass no longer does."""
    out = ERA.enforce_error_findings(_result(True, "ERROR", "WARNING", "ERROR"))
    assert out.summary["passed_downgraded_by"] == ["R0", "R2"], out.summary


@needs_corpus
def test_no_published_cell_relies_on_an_ERROR_being_IGNORED():
    """Criterion 2, and the measurement that made this rule safe to write:
    every reachable published cell carrying a ledger, every sign-off mode,
    9 x 6 = 54 runs -> passed=True while carrying an ERROR finding: 0."""
    cells = [c for c in cell_dirs() if (c / "provenance.jsonl").is_file()]
    if not cells:
        pytest.skip("no published cell here carries a provenance ledger")
    runs = 0
    for cell in cells:
        for mode in ("drc", "antenna", "em", "lvs", "ir_drop", "sta"):
            r = subprocess.run(
                [sys.executable, str(PROGRAMS / f"{mode}_report_check.py"),
                 ".", "--mode", mode],
                cwd=str(cell), capture_output=True, text=True, timeout=600)
            try:
                doc = json.loads(r.stdout[r.stdout.index("{"):])
            except (ValueError, KeyError):
                continue
            runs += 1
            assert not doc["summary"].get("passed_downgraded_by"), (
                f"{cell.name} --mode {mode}: this rule downgrades a PRISTINE "
                f"published cell on "
                f"{doc['summary']['passed_downgraded_by']}, which makes it a "
                f"bug in the rule and not a finding")
    assert runs > 0, "no mode run completed, so this measured nothing"


@needs_corpus
def test_the_CLI_REFUSES_a_cell_whose_tool_report_was_DESTROYED(tmp_path):
    """Prove-by-run for A1, through the gate's own CLI.

    Distinct from the substitution proof above: nothing is swapped in, the
    tool's own output is simply replaced with a line of nonsense. The gate must
    not be able to reach a PASS from the runner's JSON summary alone.
    """
    cells = [c for c in cell_dirs()
             if (c / "reports" / "phase3" / "ir_drop.rpt").is_file()
             and (c / "reports" / "phase3" / "ir_drop.json").is_file()]
    if not cells:
        pytest.skip("no published cell here carries both halves of the "
                    "ir_drop measurement")
    src = cells[0]
    proj = tmp_path / "proj"
    subprocess.run(["cp", "-r", str(src), str(proj)], check=True)

    rc0, rules0, _ = _run(proj, "ir_drop", tmp_path / "a.json")
    if rc0 != 0:
        pytest.skip(f"{src.name} --mode ir_drop is not green pristine "
                    f"(rc={rc0}); there is no green here to forge")

    n = 0
    for f in sorted(proj.rglob("*.rpt")):
        if f.is_file():
            f.write_text("TAMPERED BY THE ADVERSARY\n", encoding="utf-8")
            n += 1
    assert n > 0, "nothing was overwritten, so this proved nothing"

    rc1, rules1, summary1 = _run(proj, "ir_drop", tmp_path / "b.json")
    assert rc1 == 1, (
        f"{n} report(s) replaced with a line of nonsense and the gate still "
        f"exited {rc1}. Findings were {rules1}, downgrade "
        f"{summary1.get('passed_downgraded_by')}. Its PASS rests on the JSON "
        f"summary the RUNNER wrote, not on the output the TOOL produced.")
