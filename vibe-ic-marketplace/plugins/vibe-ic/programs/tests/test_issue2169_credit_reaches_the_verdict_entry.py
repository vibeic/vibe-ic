"""vibe-ic#2169 — an import is not an invocation, and ONE resolver decides it.

Two instruments audit the same question in this tree. `gate_is_wired_check`
asks whether any automatic verdict invokes a gate; `checker_execution_wiring_
audit` asks whether anything but a checker's own unit test runs it. Their
POPULATIONS had to be reconciled once already (vibe-ic#1130). #2169 is the same
divergence one level in, on the RULE:

    gate_is_wired      refused a DEAD import since `invocation.v1`, and since
                       vibe-ic#2141 credits only what reaches the gate's
                       VERDICT.
    _py_evidence       added the name to `invoked` on the IMPORT STATEMENT
                       ALONE — `checker_execution_wiring_audit.py:519` as
                       shipped through v1.19.32.

The fix is not a third copy of the rule: it is `_invocation_credit`, the one
definition site both call. So this file asks two kinds of question — does the
RULE decide correctly, and do BOTH INSTRUMENTS get their answer from it.

EVERY DENIAL HERE IS TWO-DIRECTIONAL. A rule that only ever refuses is
indistinguishable from a broken parser, so each denial is paired with the same
fixture put through `_invocation_credit.RULES[PRIOR_RULE_ID]` — the superseded
credit-on-import rule — which must CREDIT it. If a control ever stops
crediting, the fixture has stopped reaching the code and the denial beside it
proves nothing.
"""
import ast
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
ROOT = PLUGIN.parent.parent.parent
sys.path.insert(0, str(PROGRAMS))

import checker_execution_wiring_audit as A  # noqa: E402
import _invocation_credit as C  # noqa: E402

BASELINE = PROGRAMS / "checker_execution_wiring_baseline.json"
_LEGACY = C.RULES[C.PRIOR_RULE_ID]

#: A gate with every shape that matters: a `main` that composes the verdict out
#: of an input-preparation stage and a core, plus a `_`-private helper and a
#: module CONSTANT a library user can reach without running any check.
_GATE_SRC = '''
GRID_DEFAULT = 5
def _round(v):
    return v
def read_input(path):
    return _round(path)
def classify(text):
    return {"verdict": "CLEAN"}
def main(argv=None):
    return 0 if classify(read_input(argv))["verdict"] == "CLEAN" else 1
'''

_STEM = "fake_gate_check"


def _stages_of(stem):
    return C.verdict_path(_GATE_SRC) if stem == _STEM else (set(), True)


def _invoked(caller_src, rule=None):
    inv, _ = A._py_evidence(ast.parse(caller_src), _stages_of, rule, {_STEM})
    return inv


# ── the fixture gate's own verdict path ────────────────────────────────────
def test_the_verdict_path_is_the_public_composition_and_nothing_else():
    stages, composed = C.verdict_path(_GATE_SRC)
    assert composed is True, "the fixture defines `main`, so it composes"
    assert stages == {"classify", "read_input"}, (
        f"`_round` is private and `GRID_DEFAULT` is a constant, so neither is "
        f"a stage; got {sorted(stages)}")


# ── credit ─────────────────────────────────────────────────────────────────
def test_a_caller_that_reaches_the_verdict_entry_credits():
    assert _STEM in _invoked(f"import {_STEM} as g\ng.main([])")


def test_a_caller_that_runs_the_core_and_takes_its_answer_credits():
    """One stage call, nothing chained: the gate composed the answer and the
    caller took it."""
    assert _STEM in _invoked(f"from {_STEM} import classify\nclassify('x')")


def test_input_prep_plus_the_core_whose_verdict_is_read_credits():
    """vibe-ic#2141's ruling 2, which #2169 inherits by sharing the resolver.
    `phase3_one_shot_runner` reads the grid and then classifies with it —
    two stages — and reads `["verdict"]` out of the second. The gate produced
    that verdict; one input-preparation call does not change who produced it."""
    assert _STEM in _invoked(
        f"import {_STEM} as g\n"
        f"grid = g.read_input('x')\n"
        f"rep = g.classify(grid)\n"
        f"answer = rep['verdict']\n")


# ── no credit, each with the control that proves the fixture is seen ───────
@pytest.mark.parametrize("caller,why", [
    (f"import {_STEM}\n", "a DEAD import - bound and never referenced"),
    (f"import {_STEM} as g\nx = g._round(1)\n", "a `_`-private helper"),
    (f"import {_STEM} as g\nx = g.GRID_DEFAULT\n", "a module CONSTANT"),
    (f"import {_STEM} as g\nf = getattr(g, 'GRID_DEFAULT', None)\n",
     "a bare alias handed to getattr - it names nothing in particular"),
    (f"from {_STEM} import _round\n_round(1)\n", "a private helper by name"),
    (f"import {_STEM} as g\n"
     f"def f(p):\n"
     f"    raw = g.read_input(p)\n"
     f"    data = g.classify(raw)\n"
     f"    return [k for k in data]\n",
     "two stages CHAINED with no verdict read - the caller re-implemented "
     "`main` instead of asking the gate for its answer"),
])
def test_library_use_credits_nothing_and_the_superseded_rule_credited_it(
        caller, why):
    assert _STEM not in _invoked(caller), f"{why}: this must not credit"
    assert _STEM in _invoked(caller, _LEGACY), (
        f"{why}: the control did not credit either, so this fixture never "
        f"reached the rule and the assertion above proves nothing")


# ── the two instruments now answer from the same place ─────────────────────
def _audit_says(caller: str, stem: str, rule=None) -> bool:
    src = (PROGRAMS / caller).read_text(errors="replace")
    inv, _ = A._py_evidence(ast.parse(src), C.Stages(PROGRAMS), rule, {stem})
    return stem in inv


#: (caller, gate, must credit) — read one at a time from the real files on the
#: day this landed. The first three are the call sites vibe-ic#2141's own
#: commit body names as CONSUMED; the last two are the library uses that made
#: the audit's register grow.
_SHIPPED = [
    ("phase3_one_shot_runner.py", "def_manufacturing_grid_check", True),
    ("phase3_one_shot_runner.py", "extraction_input_capability_check", True),
    ("design_one_shot_runner.py", "lesson_consumption_check", True),
    ("l15_encoding_tables_contract_check.py",
     "opcode_field_width_consistency_check", False),
    ("l13_bringup_contract_check.py", "hardware_pass_attestation_check", False),
]


def test_the_denials_are_not_vacuous():
    """The paired half of the two `False` rows above: under the superseded
    rule the audit credited both, so the rows measure the RULE and not a
    fixture that stopped reaching it."""
    for caller, stem, credits in _SHIPPED:
        if not credits:
            assert _audit_says(caller, stem, _LEGACY), (
                f"{caller} no longer imports {stem}; that row is now vacuous")


# ── ONE resolver: neither instrument may keep a copy ───────────────────────
@pytest.mark.parametrize("prog", ["checker_execution_wiring_audit.py"])
def test_neither_instrument_defines_its_own_copy_of_the_rule(prog):
    """The defect #2169 names is not the old rule, it is that there were TWO
    of them. A second implementation diverges again the next time either file
    is touched."""
    tree = ast.parse((PROGRAMS / prog).read_text(errors="replace"))
    own = {n.name for n in tree.body
           if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    copies = own & {"verdict_path", "_credits", "credits",
                    "_verdict_consumers", "_scope_consumers", "_called_gate",
                    "_is_verdict_word", "credited", "bindings"}
    assert not copies, (
        f"{prog} re-implements the rule instead of calling "
        f"_invocation_credit: {sorted(copies)}")
    assert "_invocation_credit" in {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import)
        for a in n.names}, f"{prog} does not import the shared resolver"


@pytest.mark.parametrize("prog", ["checker_execution_wiring_audit.py"])
def test_the_superseded_rule_is_reachable_only_from_the_migration(prog):
    """`credit_on_import` exists so a migration can attribute an addition to
    the rule change. A gate path that reached it would restore the defect."""
    tree = ast.parse((PROGRAMS / prog).read_text(errors="replace"))
    holders = []
    for top in tree.body:
        name = (top.name if isinstance(top, (ast.FunctionDef, ast.ClassDef))
                else "<module level>")
        for n in ast.walk(top):
            if (isinstance(n, ast.Attribute)
                    and n.attr in ("credit_on_import", "RULES")):
                holders.append(name)
                break
    assert set(holders) <= {"_migrate"}, (
        f"{prog}: the superseded credit-on-import rule is reachable from "
        f"{holders}; only the one-shot --migrate-rule-id path may name it")


# ── the register records the rule it was measured under ────────────────────
@pytest.mark.consistency
def test_the_register_is_stamped_with_the_rule_that_produced_it():
    d = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert d.get("measured_under") == C.RULE_ID


def test_the_named_addition_is_in_the_register_with_a_reason():
    d = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert "opcode_field_width_consistency_check.py" in d["known"]
    assert "program_path_load_check.py" not in d["known"], (
        "that checker is unwired under the OLD rule too — it is unrecorded "
        "debt, not a population change, and the migration must leave it "
        "failing rather than absorb it")
    assert d["triage"].get("opcode_field_width_consistency_check.py")


# ── --migrate-rule-id: it may only ADD, and it refuses every other shape ───
def _register(tmp_path, known, stamp=None):
    d = {"_comment": "x", "previous_size": len(known), "known": sorted(known),
         "triage": {"kept.py": "a reason a migration must not delete"},
         "unwired_by_decision": {}}
    if stamp is not None:
        d["measured_under"] = stamp
    p = tmp_path / "reg.json"
    p.write_text(json.dumps(d, indent=2) + "\n")
    return p


def _canned(monkeypatch, before):
    monkeypatch.setattr(A, "audit", lambda *a, **k: {
        "test_only": sorted(before), "no_runner_at_all": []})


def test_it_adds_only_what_the_rule_change_made_visible(tmp_path, monkeypatch,
                                                        capsys):
    bl = _register(tmp_path, ["old.py"])
    _canned(monkeypatch, ["old.py", "already_unwired.py"])
    rc = A._migrate(bl, ["old.py"],
                    ["old.py", "already_unwired.py", "newly_visible.py"],
                    PLUGIN, ROOT, C.PRIOR_RULE_ID, set())
    assert rc == 0
    out = capsys.readouterr().out
    d = json.loads(bl.read_text())
    assert d["known"] == ["newly_visible.py", "old.py"], (
        "`already_unwired.py` is unwired under BOTH rules — unrecorded debt, "
        "not a population change")
    assert d["measured_under"] == A._RULE_ID
    assert d["triage"] == {"kept.py": "a reason a migration must not delete"}
    assert "+ newly_visible.py" in out, "every addition is printed BY NAME"
    assert "already_unwired.py" in out, (
        "the debt it declined to absorb has to be named too, or the operator "
        "cannot tell it was left behind on purpose")


def test_it_refuses_to_migrate_from_the_rule_it_already_measures(tmp_path):
    bl = _register(tmp_path, ["old.py"], stamp=A._RULE_ID)
    assert A._migrate(bl, ["old.py"], ["old.py", "new.py"], PLUGIN, ROOT,
                      A._RULE_ID, set()) == 1
    assert json.loads(bl.read_text())["known"] == ["old.py"]


def test_it_refuses_a_rule_this_build_cannot_evaluate(tmp_path):
    bl = _register(tmp_path, ["old.py"], stamp="invented.v9")
    assert A._migrate(bl, ["old.py"], ["old.py", "new.py"], PLUGIN, ROOT,
                      "invented.v9", set()) == 1


def test_it_refuses_when_the_stamp_on_disk_names_another_rule(tmp_path):
    bl = _register(tmp_path, ["old.py"], stamp="something_else.v1")
    assert A._migrate(bl, ["old.py"], ["old.py", "new.py"], PLUGIN, ROOT,
                      C.PRIOR_RULE_ID, set()) == 1


def test_it_refuses_when_a_recorded_name_would_lose_its_unwired_status(
        tmp_path, monkeypatch):
    """A paid debt leaves through the gate's own shrink report, where a human
    reads it — never silently through a migration."""
    bl = _register(tmp_path, ["old.py", "paid.py"])
    _canned(monkeypatch, ["old.py", "paid.py"])
    assert A._migrate(bl, ["old.py", "paid.py"], ["old.py"], PLUGIN, ROOT,
                      C.PRIOR_RULE_ID, set()) == 1
    assert json.loads(bl.read_text())["known"] == ["old.py", "paid.py"]


def test_it_refuses_when_the_new_rule_credits_what_the_old_one_denied(
        tmp_path, monkeypatch):
    """Then the change is not a tightening, and this door only records one."""
    bl = _register(tmp_path, ["old.py"])
    _canned(monkeypatch, ["old.py", "was_unwired_now_credited.py"])
    assert A._migrate(bl, ["old.py"], ["old.py"], PLUGIN, ROOT,
                      C.PRIOR_RULE_ID, set()) == 1


def test_it_refuses_when_there_is_no_register_to_migrate(tmp_path):
    assert A._migrate(tmp_path / "absent.json", None, ["new.py"], PLUGIN, ROOT,
                      C.PRIOR_RULE_ID, set()) == 1


# ── the mutation, against the SHIPPED source ───────────────────────────────
def test_restoring_credit_on_import_in_the_shipped_source_is_caught(tmp_path):
    """The controls above run the superseded RULE through the shipped code.
    This one runs the shipped code MUTATED, which is the failure a future edit
    actually produces: `_py_evidence` goes back to crediting the import
    statement. If the mutant does not credit a dead import, the line this fix
    turns on is not the line that decides it, and every denial in this file is
    measuring something else."""
    src = (PROGRAMS / "checker_execution_wiring_audit.py").read_text()
    needle = ("    invoked |= set(_credit.credited(tree, names, stages_of, "
              "rule))\n")
    assert src.count(needle) == 1, "the credit call moved; re-aim this mutation"
    mutant_dir = tmp_path / "mutant"
    mutant_dir.mkdir()
    (mutant_dir / "cewa_mutant.py").write_text(src.replace(
        needle,
        "    invoked |= set(_credit.credited(tree, names, stages_of,\n"
        "                                    _credit.RULES["
        "_credit.PRIOR_RULE_ID]))  # MUTANT\n"))
    sys.path.insert(0, str(mutant_dir))
    try:
        import cewa_mutant  # noqa: PLC0415
    finally:
        sys.path.remove(str(mutant_dir))
    inv, _ = cewa_mutant._py_evidence(ast.parse(f"import {_STEM}\n"),
                                      _stages_of, None, {_STEM})
    assert _STEM in inv, (
        "the mutant did NOT credit a bare import, so the line this fix turns "
        "on is not the line that decides it")
    assert _STEM not in _invoked(f"import {_STEM}\n")
