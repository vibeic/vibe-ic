#!/usr/bin/env python3
"""A duplicate rule id must be refused at IMPORT, not discovered three layers away.

`emit_test` names the emitted regression `test_<rule_id>.py`, and two stages can
share an `emit_test_dir`: stage1 and stage2 both write to
`reports/phase2/gates/on_pass_review`, stage3 and stage4 both to
`reports/phase3/gates/on_pass_review`. So two rules with one id would have one
silently overwrite the other's proof — the proof being the only thing that makes
a rejection actionable.

WHAT IT USED TO COST. The tables were three dict LITERALS, and a duplicate key in
a literal is silent by construction: Python keeps the last value. MEASURED on
v1.13.70 by retargeting stage2's entry to stage1's id — `_EMITTERS` went from 9
written keys to 8 held keys and the module imported without a murmur. The failure
surfaced as five red tests and a census finding, all of them blaming STAGE1,
which is not where the rename was.

The MECHANISM here was first authored on `fix/on-pass-registry-stage-owns-a-file`
as a `programs/on_pass_rules/` package. That branch forked at v1.13.28 and its
package registers SIX rules; this tree has NINE, because stage_phase1's three
(#1845, #1887, #1891, #1892, #1898) all landed after it. Its files were therefore
NOT taken — they would have deleted a third of the rule population and dropped
`stage_phase1` out of `_RULES` entirely. The refusal is re-authored against the
rules this tree actually has, and this module is what holds it to them.
"""
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROG = PLUGIN / "programs" / "stage_on_pass_review.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def S():
    sys.path.insert(0, str(PLUGIN / "programs"))
    return _load(PROG, "sopr_registry_under_test")


# ─────────────────────────────────────────────────────────────────────────────
# the control: the shipped registry
# ─────────────────────────────────────────────────────────────────────────────
def test_every_registered_rule_has_a_unique_id(S):
    ids = [rid for table in (S._RULES, S._DECLARED_NOT_ENABLED)
           for rules in table.values() for rid, _fn in rules]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"rule ids are global, not per-stage: {dupes}"


def test_the_three_tables_are_bijective_with_the_rule_set(S):
    """A rule with no printer renders nothing; an emitter with no rule is dead."""
    ids = {rid for table in (S._RULES, S._DECLARED_NOT_ENABLED)
           for rules in table.values() for rid, _fn in rules}
    assert set(S._EMITTERS) == ids, (
        f"missing an emitter: {sorted(ids - set(S._EMITTERS))}; "
        f"emitter with no rule: {sorted(set(S._EMITTERS) - ids)}")
    assert set(S._PRINTERS) == ids, (
        f"missing a printer: {sorted(ids - set(S._PRINTERS))}; "
        f"printer with no rule: {sorted(set(S._PRINTERS) - ids)}")


def test_stage_phase1_carries_the_three_rules_the_registry_branch_never_saw(S):
    """The branch this mechanism came from has no stage_phase1.py at all.

    Pinned by IDENTITY so that porting the file-per-stage split on top of this
    cannot quietly drop them: a count stays green through a swap.
    """
    assert {rid for rid, _ in S._RULES.get("stage_phase1", [])} == {
        "R1_CITED_CONSTANT_NOT_IN_ITS_SOURCE",
        "R2_TOP_MODULE_PROVENANCE_REFUTED",
        "R1_CITED_INPUT_ABSENT"}


# ─────────────────────────────────────────────────────────────────────────────
# the falsifier: the same duplicate that was SILENT before
# ─────────────────────────────────────────────────────────────────────────────
def test_a_duplicate_rule_id_raises_at_import_naming_both_sites(tmp_path):
    src = PROG.read_text(encoding="utf-8")
    victim = 'register(stage="stage2", rule_id="R2_INTENT_PIN_NOT_IN_NETLIST",'
    assert victim in src, "the registration this test collides was not found"
    clashed = src.replace(
        victim, 'register(stage="stage2", rule_id="R1_INTENT_TOP_NOT_BUILT",', 1)
    maimed = tmp_path / "maimed.py"
    maimed.write_text(clashed, encoding="utf-8")
    r = subprocess.run([sys.executable, str(maimed), ".", "--stage", "stage1",
                        "--stage-verdict", "PASS"],
                       capture_output=True, text=True,
                       env={"PYTHONPATH": str(PLUGIN / "programs"),
                            "PATH": "/usr/bin:/bin",
                            "PYTHONDONTWRITEBYTECODE": "1"})
    assert r.returncode != 0, r.stdout
    assert "DuplicateRuleId" in r.stderr, r.stderr[-1200:]
    # BOTH sites, because "one of these two is wrong" is not actionable without
    # knowing which two.
    assert "rule_intent_top_not_built" in r.stderr, r.stderr[-1200:]
    assert "rule_intent_pin_not_in_netlist" in r.stderr, r.stderr[-1200:]


def test_the_pre_registry_shape_would_have_been_silent(tmp_path):
    """The negative control for the MECHANISM, not for the current tree.

    A dict literal with a duplicate key is accepted by Python and holds one
    fewer entry than it was written with. Asserted here so the reason this
    refusal exists is measured rather than described.
    """
    ns = {}
    exec("D = {'A': 1, 'B': 2, 'A': 3}", ns)   # nosec — the point of the test
    assert len(ns["D"]) == 2 and ns["D"]["A"] == 3


def test_a_rule_declared_not_enabled_must_say_why(S):
    with pytest.raises(ValueError, match="not_enabled_reason"):
        S.register(stage="stage_x", rule_id="R_NEW_UNIQUE_ID_FOR_THIS_TEST",
                   rule=lambda *a, **k: {}, enabled=False)


def test_the_shipped_not_enabled_rule_carries_its_measurement(S):
    reason = S._NOT_ENABLED_REASON["R5_PACKAGE_CANNOT_BOND_DESIGN"]
    assert "silicon_received.json" in reason and "105" in reason, reason
