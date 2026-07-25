#!/usr/bin/env python3
"""FINAL REPORT (physical verification) — a CLEAN sign-off must not be
under-reported, and a PRESENT report must never be called "missing".

ORGANIC subservient x sky130A, re-derived from raw artefacts of
`converge_1.5.69_sky130A` whose GDS was DRC-clean (KLayout sky130A runset, empty
`<items/>`) and LVS-matched (netgen: "Circuits match uniquely", power-aware over
25304 PG-patched instances) — yet the headline summary printed:

    drc_signoff=`(report missing)`, lvs=`?`

because the resolver consulted ONLY `{kind}.json` and ONLY the string keys
`verdict`/`status`:

  * `lvs.json` states its outcome as `"passed": true` (no `verdict` key) -> "?"
  * no `drc_signoff.json` is ever written (the artefact is the KLayout
    report-database `drc_signoff.rpt`) -> "(report missing)", which is a FALSE
    statement about the run: the report is present, merely unsummarised.

The resolver must never MANUFACTURE a pass: silence stays unresolved, and an
unsummarised artefact is named rather than scored.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import final_report_generate as F  # noqa: E402


def _mk(project: Path, name: str, payload) -> None:
    d = project / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    if isinstance(payload, (dict, list)):
        p.write_text(json.dumps(payload))
    else:
        p.write_text(str(payload))


def test_boolean_passed_is_honoured(tmp_path: Path) -> None:
    """An audit-shaped record states its outcome as a BOOLEAN, not a string."""
    _mk(tmp_path, "lvs.json",
        {"program": "eda_report_audit:lvs", "passed": True,
         "summary": {"terminal_verdict": "MATCH"}})
    assert F._pv_verdict(tmp_path, "lvs") == "PASS"


def test_boolean_failure_is_not_laundered_into_pass(tmp_path: Path) -> None:
    _mk(tmp_path, "lvs.json", {"passed": False})
    assert F._pv_verdict(tmp_path, "lvs") == "FAIL"


def test_verdict_json_sibling_is_consulted(tmp_path: Path) -> None:
    """`{kind}_verdict.json` is the authoritative sibling for some steps."""
    _mk(tmp_path, "lvs_verdict.json", {"status": "PASS"})
    assert F._pv_verdict(tmp_path, "lvs") == "PASS"


def test_present_but_unsummarised_report_is_not_called_missing(
        tmp_path: Path) -> None:
    """A sign-off artefact with no JSON verdict must be NAMED, not denied."""
    _mk(tmp_path, "drc_signoff.rpt", "<report-database><items/></report-database>")
    got = F._pv_verdict(tmp_path, "drc_signoff")
    assert "report missing" not in got, (
        f"a PRESENT sign-off report was reported as missing: {got!r}"
    )
    assert "drc_signoff.rpt" in got, got
    # and it must NOT be scored as a pass on the strength of existing
    assert "PASS" not in got.upper()


def test_genuinely_absent_report_still_reports_missing(tmp_path: Path) -> None:
    """No artefact at all must still be reported as missing (no false PASS)."""
    (tmp_path / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    assert F._pv_verdict(tmp_path, "drc_signoff") == "(report missing)"


def test_explicit_verdict_key_still_wins(tmp_path: Path) -> None:
    """Pre-existing behaviour: an explicit string verdict is used verbatim."""
    _mk(tmp_path, "erc.json", {"verdict": "PASS", "clean": True})
    assert F._pv_verdict(tmp_path, "erc") == "PASS"
