"""Step-2.7 §4.05 guard for PR #13 benchmark_triage_absorption_audit.

The audit exempts a TRUE_FLOOR/DATASET_DEFECT record from the absorption
requirement. `extract_bool` collapsed an ABSENT blind result and a
PRESENT-BUT-UNPARSEABLE one (e.g. `independent_blind_passes: "solved on retry"`)
both to None, so a DATASET_DEFECT whose AI blind solve actually PASSED — but was
written as a free-text string — was laundered to an exempt PASS, while the bool
`true` form correctly FAILed (Step-2.7 MED: a parse-asymmetry false-clean that
masks a solved-but-unabsorbed gap).

FIX: a blind field that is PRESENT but unparseable cannot certify any exempt
verdict → hard violation `exempt_blind_unparseable` (fail-safe, never launder).
An ABSENT blind on a DATASET_DEFECT stays exempt; TRUE_FLOOR absent still fails.

chip-AGNOSTIC: generic convergence-record audit, no chip/vendor literal.
"""
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import benchmark_triage_absorption_audit as A  # noqa: E402


def _audit(records):
    # audit_records returns (verdict-ish, ...) — use the public entry the CLI uses.
    return A.audit_records(records)


def _violations(records):
    res = _audit(records)
    # locate the violations list in the returned structure (tuple/dict tolerant)
    if isinstance(res, tuple):
        for part in res:
            if isinstance(part, list) and all(isinstance(x, dict) for x in part):
                return part
    if isinstance(res, dict):
        return res.get("violations", [])
    return getattr(res, "violations", [])


@pytest.mark.parametrize("blind_str", [
    "solved on retry", "yes it passed", "AI got it", "recovered"])
def test_dataset_defect_with_unparseable_passing_blind_fails(blind_str):
    recs = [{"id": "d", "verdict": "DATASET_DEFECT",
             "independent_blind_passes": blind_str,
             "floor_evidence": "golden fails own TB"}]
    rules = {v["rule"] for v in _violations(recs)}
    assert "exempt_blind_unparseable" in rules


def test_true_floor_with_unparseable_blind_also_fails():
    recs = [{"id": "t", "verdict": "TRUE_FLOOR",
             "independent_blind_passes": "tried, ambiguous",
             "floor_evidence": "no spec basis"}]
    rules = {v["rule"] for v in _violations(recs)}
    assert "exempt_blind_unparseable" in rules


def test_dataset_defect_blind_false_is_still_exempt():
    recs = [{"id": "d", "verdict": "DATASET_DEFECT",
             "independent_blind_passes": False,
             "floor_evidence": "golden fails own TB"}]
    assert _violations(recs) == []


def test_dataset_defect_blind_absent_is_still_exempt():
    recs = [{"id": "d", "verdict": "DATASET_DEFECT",
             "floor_evidence": "golden fails own TB"}]
    assert _violations(recs) == []


def test_bool_true_blind_still_flags_unabsorbed():
    recs = [{"id": "d", "verdict": "DATASET_DEFECT",
             "independent_blind_passes": True, "floor_evidence": "x"}]
    assert _violations(recs) != []


def test_endstate_unparseable_blind_blocks_via_program(tmp_path):
    import subprocess
    p = tmp_path / "rec.json"
    p.write_text(json.dumps(
        [{"id": "d", "verdict": "DATASET_DEFECT",
          "independent_blind_passes": "solved on retry",
          "floor_evidence": "golden fails own TB"}]))
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "benchmark_triage_absorption_audit.py"),
         str(p)], capture_output=True, text=True)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "exempt_blind_unparseable" in (r.stdout + r.stderr)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
