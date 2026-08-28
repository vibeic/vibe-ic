"""#559 — the L9 spec explains its own empty sections, and the checker ignored it.

The L9 emitter records absence explicitly: alongside each section it writes
`no_<section>_in_input`, true when the INPUT carried none.  Measured across the
193 canonical `phase1/generated_docs/L9_INTEGRATION_SPEC.json` files in
benchmark-data, the marker is live rather than decorative — it varies:

    no_top_module_in_input   true on 165, false on 28
    no_submodules_in_input   true on 162, false on 31

and for `internal_wires` the cross-tabulation is:

    empty + marker true     186    honest, and explained by the document
    filled + marker false     4    honest, and explained
    filled + marker true      3    CONTRADICTION — one of the two is wrong

`l9_completeness_check` errored on the first group.  That is the inverse of the
usual defect in this repo: the artefact DID disclose why it was empty, and the
checker did not read the disclosure.  It is also why the gate failed 120 of 120
corpus files — a universal FAIL carries no information about any single one.

Three behaviours are pinned below: an explained emptiness is INFO, an
unexplained one is still ERROR, and a section whose content contradicts its own
marker is a new ERROR that nothing reported before.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "l9_completeness_check.py"


def _run(doc: dict, tmp_path: pathlib.Path):
    f = tmp_path / "L9_INTEGRATION_SPEC.json"
    f.write_text(json.dumps(doc), encoding="utf-8")
    proc = _pr.run(
        [sys.executable, str(PROG), "--l9-file", str(f)],
        capture_output=True, text=True)
    try:
        return json.loads(proc.stdout), proc.returncode
    except ValueError:
        pytest.fail(f"non-JSON output: {proc.stdout[:400]}{proc.stderr[:400]}")


def _categories(report: dict):
    return {(f.get("severity"), f.get("category")) for f in report.get("findings", [])}


BASE = {
    "schema_version": "1.0",
    "doc_class": "L9_INTEGRATION_SPEC",
    "ic_name": "fixture",
    "top_module": "fixture_top",
    "ports": [{"name": "clk", "dir": "input", "width": 1}],
    "top_ports": [{"name": "clk", "dir": "input", "width": 1}],
    "submodules": [{"name": "u_sub", "module": "sub"}],
}


def test_empty_section_with_marker_is_not_an_error(tmp_path):
    """186 of 193 corpus files are this case."""
    doc = dict(BASE, internal_wires=[], no_internal_wires_in_input=True)
    report, _ = _run(doc, tmp_path)
    cats = _categories(report)
    assert ("ERROR", "EMPTY_SECTION") not in cats, report.get("findings")
    assert ("INFO", "EMPTY_SECTION_EXPLAINED") in cats, report.get("findings")


def test_empty_section_without_marker_is_still_an_error(tmp_path):
    """The relaxation must not swallow an unexplained emptiness.

    Without this, deleting the marker check entirely would satisfy the test
    above and the gate would stop reporting real gaps.
    """
    doc = dict(BASE, internal_wires=[])
    report, _ = _run(doc, tmp_path)
    assert ("ERROR", "EMPTY_SECTION") in _categories(report), report.get("findings")


def test_marker_true_with_content_present_is_an_error(tmp_path):
    """The finding that did not exist before: the document contradicts itself.

    3 corpus files carry a non-empty `internal_wires` with
    `no_internal_wires_in_input: true`, and 13 such contradictions across all
    sections. Whichever half is wrong, both cannot be right.
    """
    doc = dict(BASE,
               internal_wires=[{"name": "w0", "width": 1}],
               no_internal_wires_in_input=True)
    report, _ = _run(doc, tmp_path)
    assert ("ERROR", "ABSENCE_MARKER_CONTRADICTS_CONTENT") in _categories(report), \
        report.get("findings")


def test_marker_false_with_content_present_is_clean(tmp_path):
    """The accept case — 4 corpus files are this, and they are correct.

    Without it, a rule that fired on every non-empty section would pass every
    other assertion here.
    """
    doc = dict(BASE,
               internal_wires=[{"name": "w0", "width": 1}],
               no_internal_wires_in_input=False)
    report, _ = _run(doc, tmp_path)
    cats = _categories(report)
    assert ("ERROR", "ABSENCE_MARKER_CONTRADICTS_CONTENT") not in cats, \
        report.get("findings")
    assert ("INFO", "EMPTY_SECTION_EXPLAINED") not in cats, report.get("findings")


def test_the_report_still_states_its_denominator(tmp_path):
    """A verdict over `sections_checked` must keep saying how many that was."""
    doc = dict(BASE, internal_wires=[], no_internal_wires_in_input=True)
    report, _ = _run(doc, tmp_path)
    summary = report.get("summary", {})
    assert summary.get("sections_checked", 0) > 0, report
    assert "sections_present" in summary, report
