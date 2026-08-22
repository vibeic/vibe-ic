"""vibe-ic#900 + #901 — a ratchet that counts, and a disclosure nobody reads.

#900: "may only shrink" was enforced as `len(new) > len(old)`. Count is not
membership, so any write removing as many entries as it added passed, and the
register admitted unlimited NEW debt at constant size while its own comment
asserted it could only shrink. The bypass sat on the NORMAL workflow: the read
path catches the swap and tells you to re-baseline; the write path it sends you
to did not check membership.

#901: six gates exited 0 on an empty project without the consumer seeing a
disclosure — and the two sharpest were self-aware, writing
`{"verdict": "NOT_APPLICABLE"}` into a report the consumer never opened. One of
them was `vacuous_testbench_check`: the gate against vacuous passes, itself
consumed as a substantive pass.

Chip-AGNOSTIC: synthetic registers and synthetic JSON reports throughout.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import flow_compliance_check as F  # noqa: E402


# --------------------------------------------------------------- #901
def _cmd(p: Path) -> str:
    return f"python3 some_check.py . --json {p}"


@pytest.mark.parametrize("verdict", [
    "NOT_APPLICABLE", "SKIPPED", "VACUOUS", "NO_BUILD", "NOT_RUN",
    "not_applicable",           # case must not decide it
])
def test_a_gate_that_declares_it_examined_nothing_is_read_as_vacuous(
        tmp_path, verdict):
    p = tmp_path / "g.json"
    p.write_text(json.dumps({"gate": "g", "verdict": verdict}))
    assert F._json_report_signals_vacuous(tmp_path, _cmd(p)) is True


@pytest.mark.parametrize("verdict", ["PASS", "FAIL", "PASS_WITH_WAIVERS"])
def test_a_substantive_verdict_is_not_read_as_vacuous(tmp_path, verdict):
    """The polarity control. A helper that answered True to everything would
    satisfy the tests above and silently convert every real pass into a
    vacuous one — a worse defect than the one being fixed."""
    p = tmp_path / "g.json"
    p.write_text(json.dumps({"verdict": verdict}))
    assert F._json_report_signals_vacuous(tmp_path, _cmd(p)) is False


def test_status_is_honoured_as_well_as_verdict(tmp_path):
    p = tmp_path / "g.json"
    p.write_text(json.dumps({"status": "NOT_APPLICABLE"}))
    assert F._json_report_signals_vacuous(tmp_path, _cmd(p)) is True


@pytest.mark.parametrize("body", ["", "{not json", "[]", "null"])
def test_an_unreadable_report_is_not_silently_vacuous(tmp_path, body):
    """Unparseable must not become a free vacuous pass — that would hand every
    gate an easy way out of being judged."""
    p = tmp_path / "g.json"
    p.write_text(body)
    assert F._json_report_signals_vacuous(tmp_path, _cmd(p)) is False


def test_no_json_flag_and_missing_file_are_both_false(tmp_path):
    assert F._json_report_signals_vacuous(tmp_path, "python3 g.py .") is False
    assert F._json_report_signals_vacuous(
        tmp_path, _cmd(tmp_path / "absent.json")) is False


def test_a_relative_json_path_resolves_against_the_project(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "g.json").write_text(
        json.dumps({"verdict": "SKIPPED"}))
    assert F._json_report_signals_vacuous(
        tmp_path, "python3 g.py . --json reports/g.json") is True


# --------------------------------------------------------------- #900
def _audit_mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "fgea", PROGRAMS / "flow_gate_enforcement_audit.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run_audit(m, baseline: Path, *extra) -> int:
    return m.main(["--flow", str(PROGRAMS.parent / "flow"
                                 / "phase1_phase2_phase3.yaml"),
                   "--programs", str(PROGRAMS),
                   "--baseline", str(baseline),
                   "--write-baseline", *extra])


def _craft(tmp_path: Path, *, drop: int, add: int) -> Path:
    """A prev register with `drop` real entries removed and `add` names that do
    not exist in the tree — so the recomputed set has `add` genuine NEW members
    while the SIZE moves by (add - drop)."""
    real = json.loads(
        (PROGRAMS / "flow_gate_enforcement_baseline.json").read_text())
    kept = real["undeclared_known"][: len(real["undeclared_known"]) - drop]
    real["undeclared_known"] = sorted(
        kept + [f"undeclared::ghost_{i}_check" for i in range(add)])
    out = tmp_path / "prev.json"
    out.write_text(json.dumps(real, indent=2))
    return out


def test_a_constant_size_swap_is_refused(tmp_path):
    """THE #900 defect, behaviourally: same count, 40 genuinely new members.
    The old guard compared len() and let this through with no reason recorded."""
    m = _audit_mod()
    assert _run_audit(m, _craft(tmp_path, drop=40, add=40)) == 1


def test_a_shrink_is_still_allowed(tmp_path):
    """The control that keeps the fix from being 'refuse everything'."""
    m = _audit_mod()
    # prev holds MORE than the tree now reports and nothing new -> pure paydown
    real = json.loads(
        (PROGRAMS / "flow_gate_enforcement_baseline.json").read_text())
    real["undeclared_known"] = sorted(
        real["undeclared_known"] + ["undeclared::ghost_only_check"])
    p = tmp_path / "prev.json"
    p.write_text(json.dumps(real, indent=2))
    assert _run_audit(m, p) == 0


def test_a_padded_reason_is_refused_and_a_naming_reason_is_accepted(tmp_path):
    """`'a' * 34` satisfied the old >=30-char test. A reason must NAME an entry
    it excuses — checkable, and not satisfiable by padding."""
    m = _audit_mod()
    # drop=1 removes a REAL entry from prev, so the recomputed set has one
    # genuinely NEW member. (Adding a ghost to prev is a SHRINK, not growth —
    # the tree no longer reports it.)
    real = json.loads(
        (PROGRAMS / "flow_gate_enforcement_baseline.json").read_text())
    dropped = real["undeclared_known"][-1].split("::", 1)[-1]

    assert _run_audit(m, _craft(tmp_path, drop=1, add=0),
                      "--scope-expanded", "a" * 40) == 1, \
        "a 40-character reason that names nothing was accepted"
    assert _run_audit(
        m, _craft(tmp_path, drop=1, add=0), "--scope-expanded",
        f"wider scope after the ENFORCED tightening: {dropped} was always "
        f"undeclared, the audit simply could not see it") == 0
