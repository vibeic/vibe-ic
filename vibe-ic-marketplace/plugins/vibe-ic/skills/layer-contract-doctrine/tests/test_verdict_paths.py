"""Every verdict SKILL.md defines must be reachable through its own gate.

Hand-written (NOT produced by _shared/gen_compliance_tests.py, which only emits
test_compliance.py). It exists because the first cut of this skill shipped a
compliance.yaml that made one of the skill's own three verdicts impossible to
record: `R_producing_layer` / `R_consuming_layer` hard-required an `L<digit>`,
while a NOT_A_LAYER_FACT record — a fact that belongs to no layer, which is the
whole content of that verdict — has no digit to name. A fully-formed record
scored 6/8 and exited 1. The generated test_compliance.py could not catch it:
it builds its "good output" mechanically from the patterns themselves, so a
pattern that is wrong is satisfied by a fixture derived from that same wrong
pattern.

So this file asserts against the SKILL.md verdict list rather than against the
YAML, in both directions:

  * every verdict named in SKILL.md has a hand-written record that PASSes;
  * the relaxation that made NOT_A_LAYER_FACT reachable did not turn `n/a`
    into a way to skip the layer-assignment question.

Adding a fourth verdict to SKILL.md fails `test_every_declared_verdict_has_a_
passing_record` until a fixture for it is added here — which is the intended
cost of adding a verdict.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

THIS = Path(__file__).resolve()
SKILL_DIR = THIS.parent.parent
SKILL_MD = SKILL_DIR / "SKILL.md"
COMPLIANCE = SKILL_DIR / "compliance.yaml"
DRIVER = THIS.parents[3] / "_shared" / "skill_compliance_check.py"


def _run(tmp_path: Path, text: str):
    report = tmp_path / "record.md"
    report.write_text(text, encoding="utf-8")
    out_json = tmp_path / "audit.json"
    res = subprocess.run(
        [sys.executable, str(DRIVER), "--requirements", str(COMPLIANCE),
         "--json", str(out_json), str(report)],
        capture_output=True, text=True)
    data = json.loads(out_json.read_text()) if out_json.is_file() else None
    return res.returncode, data


def _failed_ids(data) -> set:
    return {f["id"] for f in (data or {}).get("findings", [])
            if f["severity"] == "FAIL"}


# ─────────────────────────────────────────────────────────── fixtures
# One fully-formed record per verdict SKILL.md declares. Every line the
# Output/Handoff template calls for is present in each; the ONLY thing that
# differs between them is the verdict and, on the NOT_A_LAYER_FACT path, the
# two layer lines that verdict makes unnameable.
_COMMON_TAIL = """\
Boundary class: structural
Declarative alignment: n/a — neither a register map nor a bus interface
Actionable form required: integer bit width
Bucket A (program) | Bucket B (skill) | Bucket C (expert-DB): Bucket A — the
consumer is identified and the domain is closed
evidence: programs/l_doc_consumer_contract.py:1 — the shared derivation the
consuming gate is built on

**Verdict**: {verdict}

Next: /vibe-ic-phase1
"""

_LAYERED_HEAD = """\
## Layer Contract Decision — a field with an identified L-doc consumer

Producing layer: L1 (L1_DATASHEET.json pin_table[].width)
Consuming layer: L9 (L9_INTEGRATION_SPEC.json module port list)
Consumer program: programs/l_doc_consumer_contract.py — the file that
dereferences it
"""

_NOT_A_LAYER_HEAD = """\
## Layer Contract Decision — a fact that belongs to no layer

Producing layer: n/a — not a layer fact; it is a toolchain/environment property
Consuming layer: n/a — no L-doc consumer dereferences it; the runner does
Consumer program: programs/l_doc_consumer_contract.py — the file that would
have dereferenced it, and does not
"""

RECORDS = {
    "CONTRACT_OK": _LAYERED_HEAD + _COMMON_TAIL.format(verdict="CONTRACT_OK"),
    "DEFECT_CONSUMING_LAYER": (
        _LAYERED_HEAD + _COMMON_TAIL.format(verdict="DEFECT_CONSUMING_LAYER")),
    "NOT_A_LAYER_FACT": (
        _NOT_A_LAYER_HEAD + _COMMON_TAIL.format(verdict="NOT_A_LAYER_FACT")),
}


def declared_verdicts() -> list:
    """The verdict enum SKILL.md's own Output/Handoff template declares."""
    m = re.search(r"\*\*Verdict\*\*:\s*<([^>]+)>", SKILL_MD.read_text(
        encoding="utf-8"))
    assert m, "SKILL.md no longer declares a **Verdict**: <...> template line"
    return [v.strip() for v in m.group(1).split("|") if v.strip()]


# ───────────────────────────────────────────────────────────── tests
def test_skill_md_and_this_file_agree_on_the_verdict_set():
    """A verdict added to SKILL.md needs a fixture here before it can ship."""
    assert set(declared_verdicts()) == set(RECORDS), (
        "SKILL.md declares verdicts with no fixture in this file (or vice "
        f"versa): SKILL.md={declared_verdicts()} fixtures={sorted(RECORDS)}")


@pytest.mark.parametrize("verdict", sorted(RECORDS))
def test_every_declared_verdict_has_a_passing_record(verdict, tmp_path):
    """THE regression. Each verdict must be recordable without the gate
    rejecting the record for taking that verdict's own path."""
    rc, data = _run(tmp_path, RECORDS[verdict])
    assert rc == 0, (
        f"a fully-formed {verdict} record does not pass its own skill's "
        f"compliance gate — that verdict is unreachable. "
        f"Failures: {sorted(_failed_ids(data))}")
    assert data["verdict"] == "PASS"


def test_na_layer_without_the_verdict_is_rejected(tmp_path):
    """The relaxation must not become an escape hatch: `n/a` on a layer line
    is legal only in a record that actually reaches NOT_A_LAYER_FACT."""
    text = _NOT_A_LAYER_HEAD + _COMMON_TAIL.format(verdict="CONTRACT_OK")
    rc, data = _run(tmp_path, text)
    assert rc == 1, "n/a layer lines passed without the NOT_A_LAYER_FACT verdict"
    assert "X_na_layer_requires_not_a_layer_fact" in _failed_ids(data)


def test_a_record_naming_no_layer_at_all_still_fails(tmp_path):
    """The layer requirements were relaxed, not removed."""
    text = _COMMON_TAIL.format(verdict="CONTRACT_OK")
    rc, data = _run(tmp_path, text)
    assert rc == 1
    failed = _failed_ids(data)
    assert {"R_producing_layer", "R_consuming_layer"} <= failed, failed
