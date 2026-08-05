#!/usr/bin/env python3
"""Two producers write `reports/extraction_coverage_report.json` and they
do not compute the same ratio, so whichever ran last decided a gate whose
own docstring says "100% required, NO waiver allowed".

  * phase1_doc_one_shot_runner.py — universe = literals curated from the
    INPUT documents. Emits overall.{denominator,numerator,pct}, per_l_doc.
  * phase1_coverage_report_gen.py — universe = the project's OWN
    extraction_patterns.json. Emits overall.{hit,total,pct}, per_doc.

Measured on one project with byte-identical L docs and input docs, only
the producer differing: runner 285/287 = 99.3% -> exit 1; gen
285/285 = 100.0% -> exit 0.

These tests are chip-AGNOSTIC: every fixture is synthesised here and
names no design, vendor, process or part number.

DIRECTION OF THE FIX — tightening only. `test_self_referential_*` is the
negative control (it FAILS against the pre-fix file). The three
`test_reverse_*` cases are the anti-over-tightening controls: they must
STILL hold after the fix, so the filter cannot have been narrowed until
the count hit zero.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_PROG_DIR = Path(__file__).resolve().parent.parent
_GATE = _PROG_DIR / "phase1_coverage_report_present_check.py"


def _mkproject(tmp_path: Path, report: dict) -> Path:
    """Minimal project that clears every pre-ratio guard in the gate, so
    the only thing under test is how the ratio itself is read."""
    proj = tmp_path / "proj"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "spec_a.md").write_text(
        "# spec a\nthe widget counts to four.\n")
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({"x": 1}))
    rep = proj / "reports" / "phase1"
    rep.mkdir(parents=True)
    (rep / "extraction_coverage_report.md").write_text("# coverage\n")
    (rep / "extraction_coverage_report.json").write_text(
        json.dumps(report, indent=2))
    return proj


def _run(proj: Path):
    r = subprocess.run(
        [sys.executable, str(_GATE), str(proj)],
        capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


# --- schema fixtures -------------------------------------------------

def _gen_schema(hit, total, pct, pattern_source):
    """phase1_coverage_report_gen.py shape."""
    return {
        "schema_version": 3,
        "pattern_source": pattern_source,
        "pattern_source_path": "/x/phase1/extraction_patterns.json",
        "overall": {"hit": hit, "total": total, "pct": pct},
        "per_doc": [
            {"doc": "spec_a.md", "hit": hit, "total": total, "pct": pct}
        ],
    }


def _runner_schema(numerator, denominator, pct):
    """phase1_doc_one_shot_runner.py shape — note: no `per_doc`, and
    `total` is the vendor-token count, NOT the denominator `pct` came
    from."""
    return {
        "layer_demand": {"probes_run": 1, "layers": {}, "silent_empty": []},
        "overall": {
            "denominator": denominator,
            "total": 169,
            "numerator": numerator,
            "pct": pct,
            "target_pct": 80.0,
            "status": "PASS",
            "input_documents_visited": 1,
            "input_documents_extracted": 1,
            "input_documents_unread": 0,
            "layers_demanded_but_empty": [],
        },
        "unread_input_documents": [],
        "curated": {"denominator": denominator,
                    "numerator": numerator, "pct": pct},
        "per_l_doc": [
            {"name": "L1_DATASHEET", "evidence_count": 3, "todo_count": 0}
        ],
    }


# --- NEGATIVE CONTROL: must FAIL against the byte-identical pre-fix file

def test_self_referential_hundred_percent_is_refused(tmp_path):
    """A 100% whose denominator is the project's OWN pattern file must
    NOT certify input coverage.

    PRE-FIX this exits 0 (PASS) and this assertion fails — that is the
    control. POST-FIX it exits 1.
    """
    proj = _mkproject(tmp_path, _gen_schema(
        285, 285, 100.0, "phase1/extraction_patterns.json"))
    rc, out = _run(proj)
    assert rc == 1, (
        "a self-referential 100% was accepted as input coverage; "
        f"rc={rc} out={out}")
    assert "SELF-REFERENTIAL" in out.upper()


def test_absent_per_doc_is_not_reported_as_no_gaps(tmp_path):
    """The front-door report has no `per_doc`. Rendering that as
    "(none below threshold)" asserts a per-document examination that
    never happened, in the same message as a failing aggregate.

    PRE-FIX the output contains "none below threshold" — control.
    """
    proj = _mkproject(tmp_path, _runner_schema(285, 287, 99.3))
    rc, out = _run(proj)
    assert rc == 1, f"expected FAIL at 99.3%; rc={rc} out={out}"
    assert "none below threshold" not in out, (
        "gate claimed no document is below threshold while reading a "
        f"report that carries no per-document breakdown at all: {out}")
    assert "UNAVAILABLE" in out


def test_failing_message_quotes_the_ratio_pct_came_from(tmp_path):
    """Pre-fix the gate printed hit=None/total=169 beside pct=99.3,
    numbers that do not divide to the percentage shown."""
    proj = _mkproject(tmp_path, _runner_schema(285, 287, 99.3))
    rc, out = _run(proj)
    assert rc == 1
    assert "285/287" in out, (
        f"gate did not quote the numerator/denominator pct came from: {out}")
    assert "None/169" not in out


# --- REVERSE CONTROLS: must STILL hold after the fix -----------------
# These are what catch a filter narrowed until the count reaches zero.

def test_reverse_input_anchored_hundred_percent_still_passes(tmp_path):
    """A genuine 100% from the input-anchored producer must still PASS.
    If the fix swallowed this, it over-tightened."""
    proj = _mkproject(tmp_path, _runner_schema(287, 287, 100.0))
    rc, out = _run(proj)
    assert rc == 0, f"legitimate input-anchored 100% was rejected: {out}"


def test_reverse_auto_discovered_hundred_percent_still_passes(tmp_path):
    """`pattern_source=auto-discovered` is not project-authored, so it is
    NOT self-referential and must keep passing. This keeps the tightening
    narrow — it fires on the project-authored denominator only."""
    proj = _mkproject(tmp_path, _gen_schema(
        100, 100, 100.0, "auto-discovered"))
    rc, out = _run(proj)
    assert rc == 0, f"auto-discovered 100% was wrongly rejected: {out}"


def test_reverse_below_threshold_still_fails(tmp_path):
    """The pre-existing FAIL path must be untouched in both directions."""
    for report in (_runner_schema(285, 287, 99.3),
                   _gen_schema(90, 100, 90.0, "auto-discovered")):
        proj_root = tmp_path / f"c{abs(hash(json.dumps(report)))}"
        proj_root.mkdir()
        proj = _mkproject(proj_root, report)
        rc, _ = _run(proj)
        assert rc == 1, "a sub-threshold coverage stopped failing"


def test_reverse_unparseable_and_missing_report_still_fail(tmp_path):
    """Guards the fix did not touch must keep behaving."""
    proj = _mkproject(tmp_path, _runner_schema(285, 287, 99.3))
    js = proj / "reports" / "phase1" / "extraction_coverage_report.json"
    js.write_text("{not json")
    rc, out = _run(proj)
    assert rc == 1 and "unparseable" in out

    js.unlink()
    rc, out = _run(proj)
    assert rc == 1 and "missing" in out.lower()


if __name__ == "__main__":
    raise SystemExit(subprocess.call(
        [sys.executable, "-m", "pytest", "-q", __file__]))
