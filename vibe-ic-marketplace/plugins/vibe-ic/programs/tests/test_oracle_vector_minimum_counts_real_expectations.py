"""MIN_VECTORS_FAIL must count vectors that carry a real expectation.

THE DEFECT, AS SHIPPED
======================
`bit_level_full_stack_tb_oracle_check` refuses a run whose `per_vector` array
holds fewer than `MIN_VECTORS_FAIL` (8) entries — the minimum population for a
credible bit-level oracle. The threshold was applied to `len(per_vector)`, the
count of ENTRIES, while the producer manufactured entries until that count
reached eight:

    # Pad to >=8 vectors so MIN_VECTORS_FAIL=8 passes -- padding
    # vectors are honest UNVERIFIED bring-up steps, not fake PASSes.
    while len(per_vector_skeleton) < 8:
        per_vector_skeleton.append({... "verdict": "UNVERIFIED" ...})

The entries really are marked UNVERIFIED and that is not the point. A guard
that compares a COUNT is blind the moment anyone can add members, so the guard
became unable to refuse: measured over 481 published
`sim_full_stack/results.json` on this fleet, 379 hold exactly 8 entries of
which exactly 0 carry a concrete golden. Every one of them clears the eight-
vector minimum, and not one of them has a bit-level oracle in it.

WHAT THE FIX IS
===============
Both halves, because either alone leaves the hole open:

  * the GATE counts the population the threshold was written about — vectors
    carrying a concrete golden, decided by the gate's own
    `classify_expected_bytes` — so no number of bring-up entries can satisfy
    it. The refusal states BOTH numbers so the reader can see what was added.
  * the PRODUCER stops manufacturing entries to reach a threshold. Bring-up
    entries are not banned; padding a population to clear the guard that
    counts it is.

The threshold is NOT lowered and no vector class is deleted: an entry with no
golden is still emitted and still disclosed, it simply no longer counts toward
a minimum it was never evidence for.

chip-AGNOSTIC: pure population accounting.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import bit_level_full_stack_tb_oracle_check as oc  # noqa: E402


def _proj(tmp_path: Path, results: dict) -> Path:
    proj = tmp_path / "proj"
    sim = proj / "phase2" / "stage1" / "sim" / "sim_full_stack"
    sim.mkdir(parents=True)
    (sim / "results.json").write_text(json.dumps(results))
    return proj


def _results(per_vector: list[dict]) -> dict:
    scored = [v for v in per_vector
              if oc.classify_expected_bytes(v.get("expected_bytes"))]
    return {
        "verdict": "UNVERIFIED",
        "pass": False,
        "per_vector": per_vector,
        "vectors_total": len(per_vector),
        "vectors_passed": len(scored),
        "vectors_failed": len(per_vector) - len(scored),
        "input_doc_evidence": "generated_docs/L3_CMD_PROTOCOL.json#opcodes",
    }


def _bring_up(n: int, start: int = 0) -> list[dict]:
    return [{"vector_id": f"vec_brk_{start + i}", "expected_bytes": None,
             "actual_bytes": None, "verdict": "UNVERIFIED"} for i in range(n)]


def _golden(n: int) -> list[dict]:
    return [{"vector_id": f"vec_{i:02d}",
             "expected_bytes": f"F2,{i:02X},22,33,44",
             "actual_bytes": f"F2,{i:02X},22,33,44",
             "verdict": "PASS"} for i in range(n)]


def _waived(tmp_path: Path, per_vector: list[dict]) -> Path:
    proj = _proj(tmp_path, _results(per_vector))
    (proj / "waivers.json").write_text(json.dumps({
        "functional_unverified_connectivity_only": (
            "Spec ships no byte-level reference vectors for this command set; "
            "functional correctness is verified separately at gate level and "
            "in Phase 3 per the verification plan. Connectivity-only here is "
            "intentional and is recorded as such."),
    }))
    return proj


def _rules(project: Path) -> set[str]:
    sim = project / "phase2" / "stage1" / "sim" / "sim_full_stack"
    res = oc.check(project, sim / "results.json")
    return {f["rule"] for f in res.get("findings", [])}


def test_eight_bring_up_entries_do_not_satisfy_the_eight_vector_minimum(
        tmp_path):
    """THE DEFECT. The exact published shape: 8 entries, 0 real expectations."""
    proj = _proj(tmp_path, _results(_bring_up(8)))
    assert "PER_VECTOR_TOO_FEW" in _rules(proj)


def test_the_refusal_names_the_padded_and_the_counted_population(tmp_path):
    """A count that moved must say which count moved, or the next reader
    re-derives the wrong one."""
    proj = _proj(tmp_path, _results(_bring_up(8)))
    sim = proj / "phase2" / "stage1" / "sim" / "sim_full_stack"
    res = oc.check(proj, sim / "results.json")
    msg = next(f["message"] for f in res["findings"]
               if f["rule"] == "PER_VECTOR_TOO_FEW")
    assert "8" in msg and "0" in msg, msg


def test_a_short_real_population_padded_to_eight_still_refuses(tmp_path):
    """Three real vectors plus five bring-up entries is a three-vector oracle."""
    proj = _proj(tmp_path, _results(_golden(3) + _bring_up(5, start=3)))
    assert "PER_VECTOR_TOO_FEW" in _rules(proj)


def test_the_producer_does_not_manufacture_vectors_to_reach_the_threshold():
    """The cause, asserted on the producer's own syntax tree.

    Any `while len(<vectors>) < 8: <vectors>.append(...)` is a population
    widened to clear a minimum-count guard. Parsed rather than grepped, so a
    reformatting or a renamed variable cannot make the check silently vacuous.
    """
    runner = PROGRAMS / "design_one_shot_runner.py"
    tree = ast.parse(runner.read_text())
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.While):
            continue
        t = node.test
        if not (isinstance(t, ast.Compare) and len(t.ops) == 1
                and isinstance(t.ops[0], (ast.Lt, ast.LtE))):
            continue
        if not (isinstance(t.left, ast.Call)
                and isinstance(t.left.func, ast.Name)
                and t.left.func.id == "len"):
            continue
        rhs = t.comparators[0]
        if not (isinstance(rhs, ast.Constant)
                and rhs.value == oc.MIN_VECTORS_FAIL):
            continue
        appends = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "append" for n in ast.walk(node))
        if appends:
            offenders.append(node.lineno)
    assert not offenders, (
        f"design_one_shot_runner.py pads a vector population up to "
        f"MIN_VECTORS_FAIL={oc.MIN_VECTORS_FAIL} at line(s) {offenders}")


def test_eight_real_vectors_still_clear_the_minimum(tmp_path):
    """PAIRED GUARD — the threshold is not raised and not moved."""
    proj = _proj(tmp_path, _results(_golden(8)))
    assert "PER_VECTOR_TOO_FEW" not in _rules(proj)


def test_seven_real_vectors_still_refuse_exactly_as_before(tmp_path):
    """PAIRED GUARD — the threshold is not lowered, in particular not to 0."""
    proj = _proj(tmp_path, _results(_golden(7)))
    assert "PER_VECTOR_TOO_FEW" in _rules(proj)


def test_a_non_protocol_ic_is_still_not_examined_at_all(tmp_path):
    """PAIRED GUARD — the documented N/A escape is untouched.

    An IC whose L3 honestly declares no command protocol has no command-byte
    oracle to have a population of, and this gate must keep saying so rather
    than acquiring a new way to refuse it.
    """
    res = _results(_bring_up(8))
    res["command_oracle_applicable"] = False
    proj = _proj(tmp_path, res)
    sim = proj / "phase2" / "stage1" / "sim" / "sim_full_stack"
    out = oc.check(proj, sim / "results.json")
    assert out["pass"] is True and out.get("skipped") is True


def test_the_documented_connectivity_waiver_still_does_its_documented_job(
        tmp_path):
    """PAIRED GUARD, and a scope statement.

    `functional_unverified_connectivity_only` is the repo's written channel for
    "this run verifies no function here, on purpose, and says so". Rules 2 and
    9 already downgrade to a disclosed WARN under it. The new population rule
    follows the SAME waiver rather than acquiring a private policy: re-refusing
    the exact fact the waiver discloses, under a new rule name, would make an
    existing human-authored disclosure unable to do its job.

    Measured before choosing: of 1,031 `waivers.json` in the audited corpus,
    ZERO carry this key or `bit_level_oracle_skipped`, so this decision moves
    no published project either way.
    """
    proj = _waived(tmp_path, _bring_up(8))
    sim = proj / "phase2" / "stage1" / "sim" / "sim_full_stack"
    res = oc.check(proj, sim / "results.json")
    rules = {f["rule"] for f in res.get("findings", [])}
    warns = {w["rule"] for w in res.get("warnings", [])}
    assert "PER_VECTOR_TOO_FEW" not in rules
    assert "VECTORS_TOO_FEW_CONNECTIVITY_ONLY" in warns


def test_the_waived_shortfall_is_published_not_swallowed(tmp_path):
    """A downgrade that stops naming the number is a silent green."""
    proj = _waived(tmp_path, _bring_up(8))
    sim = proj / "phase2" / "stage1" / "sim" / "sim_full_stack"
    res = oc.check(proj, sim / "results.json")
    msg = next(w["message"] for w in res["warnings"]
               if w["rule"] == "VECTORS_TOO_FEW_CONNECTIVITY_ONLY")
    assert "8 entries" in msg and "only 0" in msg, msg
    assert res.get("skipped") is not True, "a waiver is not a non-examination"


def test_an_unwaived_run_gets_no_downgrade(tmp_path):
    """The waiver is the ONLY thing that downgrades it."""
    proj = _proj(tmp_path, _results(_bring_up(8)))
    sim = proj / "phase2" / "stage1" / "sim" / "sim_full_stack"
    res = oc.check(proj, sim / "results.json")
    assert "PER_VECTOR_TOO_FEW" in {f["rule"] for f in res["findings"]}
    assert "VECTORS_TOO_FEW_CONNECTIVITY_ONLY" not in {
        w["rule"] for w in res.get("warnings", [])}
