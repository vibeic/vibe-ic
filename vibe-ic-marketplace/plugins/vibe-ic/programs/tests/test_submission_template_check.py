#!/usr/bin/env python3
"""Step 0.5ic, the gate — every refusal proven by breaking what it defends.

A gate shown only to PASS on good input has not been shown to discriminate. So
each rule below is asserted in THREE directions:

  1. the clean subject passes, and says what it examined;
  2. one thing is mutated away from that same subject and the gate names the
     rule;
  3. the rule's EFFECT is then removed from a scratch copy of the gate, and the
     verdict changes. A guard whose removal changes nothing is not a guard, and
     a test that would pass against the ungated program pins nothing.

Direction 3 is the one that is usually skipped, and it is the one that catches
the failure mode where some OTHER rule was quietly doing the work and the test
merely happened to be green.

THE TWO SENTENCES THIS GATE EXISTS TO SEPARATE
----------------------------------------------
    "I looked for the operator's template and it is not there."
    "Nobody ever looked."

They produce the same empty directory. The first can be BOUGHT with a stated
reason and then reads NOT_APPLICABLE; the second cannot be bought at all,
because a reason offered for it describes a template no one searched for.
`flow_compliance_check` reaches the same conclusion for an unmet
`condition_files_exist`, and the floor on the reason is READ from that rule
rather than copied, because two hand-kept numbers are two numbers that drift.

NOT_APPLICABLE IS NOT A PASS, AND THIS FILE PINS THAT STRUCTURALLY: the verdict
is a three-valued field with deliberately no boolean beside it, so no reader
grepping one key can turn "I checked no die geometry at all" into a clean run.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _submission_template as ST         # noqa: E402
import submission_template_ingest as ING  # noqa: E402
import submission_template_check as CHK   # noqa: E402


SLOT_A = """\
DIE_AREA: [0, 0, 1000, 2000]
CORE_AREA: [26, 26, 974, 1974]
SEAL_RING_WIDTH: 26
FP_SIZING: absolute
pads: [pad_n0, pad_n1, pad_s0]
"""

SLOT_B = """\
DIE_AREA: [0, 0, 4000, 5000]
CORE_AREA: [26, 26, 3974, 4974]
SEAL_RING_WIDTH: 26
FP_SIZING: absolute
pads: [pad_n0, pad_n1, pad_s0, pad_s1]
"""

GOOD_REASON = ("This design is delivered as a hardmacro to an integrator and "
               "is never submitted to a shuttle, so it has no slot.")


# --------------------------------------------------------------------------- #
# subjects
# --------------------------------------------------------------------------- #
def _template(tmp_path: Path) -> Path:
    root = tmp_path / "operator_template"
    (root / "slots").mkdir(parents=True)
    (root / "slots" / "slot_a.yaml").write_text(SLOT_A)
    (root / "slots" / "slot_b.yaml").write_text(SLOT_B)
    return root


def _ingest(project: Path, *argv) -> None:
    assert ING.main([str(project), *argv]) == 0


def _accepted(tmp_path: Path):
    """The subject the gate ACCEPTS. Every mutation below starts here."""
    tmpl = _template(tmp_path)
    proj = tmp_path / "design"
    proj.mkdir()
    _ingest(proj, "--template", str(tmpl), "--slot", "slot_a")
    return proj, tmpl


def _check(project: Path, write: bool = True):
    """(rc, check block, document). Writes to the step's own report, as the
    flow's gate declaration does."""
    argv = [str(project)]
    if write:
        argv += ["--json", ST.REPORT_REL]
    rc = CHK.main(argv)
    doc = json.loads((project / ST.REPORT_REL).read_text())
    return rc, doc["check"], doc


def _evaluate(module, project: Path):
    """Run one gate module over a project without writing anything."""
    doc, problem = module._load_report(project)
    return module.evaluate(project, doc, problem)


def _rules(check) -> set:
    return {r["rule"] for r in check["refusals"]}


def _mutate_report(project: Path, fn) -> None:
    path = project / ST.REPORT_REL
    doc = json.loads(path.read_text())
    fn(doc["ingest"])
    path.write_text(json.dumps(doc, indent=2) + "\n")


@pytest.fixture()
def clean(tmp_path: Path):
    return _accepted(tmp_path)


# --------------------------------------------------------------------------- #
# ONE MUTATION EACH — the subject a rule defends against
#
# Every builder starts from `_accepted` (or, where the rule is about absence,
# from the same ingester on the same tree) and changes exactly ONE thing.
# --------------------------------------------------------------------------- #
def _sub_never_looked(tmp_path):
    proj = tmp_path / "design"
    proj.mkdir()
    # a reason IS stated, and must buy nothing: nobody searched for anything
    _ingest(proj, "--no-template-reason", GOOD_REASON)
    return proj


def _sub_no_reason(tmp_path):
    proj = tmp_path / "design"
    proj.mkdir()
    _ingest(proj, "--template", str(tmp_path / "not_there"))
    return proj


def _sub_no_template_file_missing(tmp_path):
    proj = tmp_path / "design"
    proj.mkdir()
    _ingest(proj, "--template", str(tmp_path / "not_there"),
            "--no-template-reason", GOOD_REASON)
    (proj / ST.NO_TEMPLATE_REL).unlink()
    return proj


def _sub_root_gone(tmp_path):
    proj, tmpl = _accepted(tmp_path)
    shutil.rmtree(tmpl)
    return proj


def _sub_changed_since_ingest(tmp_path):
    proj, tmpl = _accepted(tmp_path)
    (tmpl / "slots" / "slot_a.yaml").write_text(SLOT_A.replace("1000", "1200"))
    return proj


def _sub_ships_no_slots(tmp_path):
    empty = tmp_path / "operator_template"
    (empty / "docs").mkdir(parents=True)
    (empty / "docs" / "readme.yaml").write_text("SOME_TOOL_OPTION: 3\n")
    proj = tmp_path / "design"
    proj.mkdir()
    _ingest(proj, "--template", str(empty), "--slot", "slot_a")
    return proj


def _sub_die_without_core(tmp_path):
    proj, tmpl = _accepted(tmp_path)
    (tmpl / "slots" / "slot_a.yaml").write_text(
        "DIE_AREA: [0, 0, 1000, 2000]\nFP_SIZING: absolute\n")
    _ingest(proj, "--template", str(tmpl), "--slot", "slot_a")
    return proj


def _sub_degenerate_rect(tmp_path):
    proj, tmpl = _accepted(tmp_path)
    (tmpl / "slots" / "slot_a.yaml").write_text(
        "DIE_AREA: [0, 0, 0, 2000]\nCORE_AREA: [26, 26, 974, 1974]\n")
    _ingest(proj, "--template", str(tmpl), "--slot", "slot_a")
    return proj


def _sub_core_outside_die(tmp_path):
    proj, tmpl = _accepted(tmp_path)
    (tmpl / "slots" / "slot_a.yaml").write_text(
        "DIE_AREA: [0, 0, 1000, 2000]\nCORE_AREA: [-5, 26, 974, 1974]\n")
    _ingest(proj, "--template", str(tmpl), "--slot", "slot_a")
    return proj


def _sub_ring_disagrees(tmp_path):
    proj, tmpl = _accepted(tmp_path)
    # one micron off on ONE side; the ring is still declared, the arithmetic is
    # what fails.
    (tmpl / "slots" / "slot_a.yaml").write_text(
        SLOT_A.replace("CORE_AREA: [26, 26, 974, 1974]",
                       "CORE_AREA: [26, 26, 974, 1973]"))
    _ingest(proj, "--template", str(tmpl), "--slot", "slot_a")
    return proj


def _sub_name_collision(tmp_path):
    proj, tmpl = _accepted(tmp_path)
    (tmpl / "other").mkdir()
    (tmpl / "other" / "slot_a.yaml").write_text(SLOT_B)  # same name, other size
    _ingest(proj, "--template", str(tmpl), "--slot", "slot_a")
    return proj


def _sub_slot_not_shipped(tmp_path):
    proj, tmpl = _accepted(tmp_path)
    _ingest(proj, "--template", str(tmpl), "--slot", "slot_z")
    return proj


def _sub_slot_not_declared(tmp_path):
    proj, tmpl = _accepted(tmp_path)
    _ingest(proj, "--template", str(tmpl))
    return proj


def _sub_tree_says_both(tmp_path):
    proj, _ = _accepted(tmp_path)
    (proj / ST.NO_TEMPLATE_REL).write_text("hand-written, not by this step\n")
    return proj


def _sub_tree_disagrees(tmp_path):
    proj, _ = _accepted(tmp_path)
    for f in (proj / ST.SLOTS_DIR_REL).glob("*.yaml"):
        f.unlink()
    return proj


def _sub_report_absent(tmp_path):
    proj = tmp_path / "design"
    proj.mkdir()
    return proj


def _sub_report_schema(tmp_path):
    proj, _ = _accepted(tmp_path)
    path = proj / ST.REPORT_REL
    doc = json.loads(path.read_text())
    doc["schema"] = "something/else"
    path.write_text(json.dumps(doc))
    return proj


def _sub_unknown_status(tmp_path):
    proj, _ = _accepted(tmp_path)
    _mutate_report(proj, lambda rec: rec.__setitem__("status", "FINE"))
    return proj


def _sub_invented_root(tmp_path):
    proj, _ = _accepted(tmp_path)
    _mutate_report(proj, lambda rec: rec["lookup"].__setitem__(
        "template_root", str(tmp_path / "invented")))
    return proj


SUBJECTS = [
    ("NEVER_LOOKED", _sub_never_looked),
    ("NO_TEMPLATE_WITHOUT_REASON", _sub_no_reason),
    ("NO_TEMPLATE_FILE_MISSING", _sub_no_template_file_missing),
    ("TEMPLATE_NOT_ON_DISK", _sub_root_gone),
    ("TEMPLATE_NOT_ON_DISK", _sub_invented_root),
    ("TEMPLATE_CHANGED_SINCE_INGEST", _sub_changed_since_ingest),
    ("TEMPLATE_SHIPS_NO_SLOTS", _sub_ships_no_slots),
    ("SLOT_GEOMETRY_INCOMPLETE", _sub_die_without_core),
    ("SLOT_GEOMETRY_DEGENERATE", _sub_degenerate_rect),
    ("CORE_NOT_INSIDE_DIE", _sub_core_outside_die),
    ("RING_DISAGREES", _sub_ring_disagrees),
    ("SLOT_NAME_COLLISION", _sub_name_collision),
    ("SLOT_NOT_SHIPPED", _sub_slot_not_shipped),
    ("SLOT_NOT_DECLARED", _sub_slot_not_declared),
    ("TREE_SAYS_BOTH", _sub_tree_says_both),
    ("TREE_DISAGREES_WITH_REPORT", _sub_tree_disagrees),
    ("REPORT_ABSENT", _sub_report_absent),
    ("REPORT_SCHEMA", _sub_report_schema),
    ("REPORT_SCHEMA", _sub_unknown_status),
]
IDS = [f"{rule}:{fn.__name__[5:]}" for rule, fn in SUBJECTS]


# --------------------------------------------------------------------------- #
# 1 — the gate ACCEPTS, and discloses its denominator
# --------------------------------------------------------------------------- #
def test_the_clean_subject_passes_and_says_what_it_examined(clean):
    proj, _ = clean
    rc, check, _ = _check(proj)
    assert rc == 0
    assert check["verdict"] == ST.VERDICT_PASS
    assert check["refusals"] == []
    # a check that ran over nothing and one that ran over everything must not
    # produce the same sentence
    assert check["examined"]["slots_in_record"] == 2
    assert check["examined"]["slot_files_on_disk"] == 2
    assert check["examined"]["template_files_rehashed"] == 2


def test_the_verdict_is_three_valued_and_carries_no_boolean_beside_it(clean):
    proj, _ = clean
    _, check, doc = _check(proj)
    assert check["verdict"] in (ST.VERDICT_PASS, ST.VERDICT_FAIL,
                                ST.VERDICT_NOT_APPLICABLE)
    assert "passed" not in check and "passed" not in doc, (
        "a NOT_APPLICABLE folded into a boolean `true` is exactly the sentence "
        "this gate exists to refuse")


def test_the_gate_merges_its_verdict_beside_the_record_it_judged(clean):
    proj, _ = clean
    before = json.loads((proj / ST.REPORT_REL).read_text())["ingest"]
    _, _, doc = _check(proj)
    assert doc["ingest"] == before, (
        "the gate's own --json target IS the step's declared report; the "
        "record it judged must survive being judged")
    rc2, check2, _ = _check(proj)          # and it is idempotent
    assert (rc2, check2["verdict"]) == (0, ST.VERDICT_PASS)


def test_two_files_agreeing_on_one_slot_name_are_not_refused(clean):
    """The other half of SLOT_NAME_COLLISION: a duplicate is only a defect when
    the two copies DISAGREE. A gate that is loud on agreement is a gate people
    route around."""
    proj, tmpl = clean
    (tmpl / "other").mkdir()
    (tmpl / "other" / "slot_a.yaml").write_text(SLOT_A)
    _ingest(proj, "--template", str(tmpl), "--slot", "slot_a")
    rc, check, _ = _check(proj)
    assert "SLOT_NAME_COLLISION" not in _rules(check)
    assert rc == 0


# --------------------------------------------------------------------------- #
# 2 — the gate REFUSES, and names the rule
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rule,build", SUBJECTS, ids=IDS)
def test_each_refusal_fires_on_the_subject_it_defends(rule, build, tmp_path):
    proj = build(tmp_path)
    rc, check, _ = _check(proj)
    assert rc == 1
    assert rule in _rules(check), (
        f"expected {rule}, got {sorted(_rules(check))}")
    assert check["verdict"] == ST.VERDICT_FAIL


# --------------------------------------------------------------------------- #
# 3 — the rule is LOAD-BEARING: remove its effect, the verdict changes
# --------------------------------------------------------------------------- #
def _gate_mutant(rule: str, tmp_path: Path):
    """A scratch copy of the gate with exactly one rule's effect removed.

    The refusal is still BUILT — only its power to decide is taken away — so
    the mutant differs from the real gate in precisely the property under test
    and in nothing else.
    """
    src = (PROGRAMS / "submission_template_check.py").read_text()
    anchor = "    if refusals:\n        verdict = ST.VERDICT_FAIL"
    assert src.count(anchor) == 1, "the mutation site moved; fix this test"
    src = src.replace(
        anchor,
        f"    refusals = [_r for _r in refusals if _r['rule'] != {rule!r}]\n"
        + anchor)
    path = tmp_path / f"gate_mutant_{rule.lower()}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("rule,build", SUBJECTS, ids=IDS)
def test_each_refusal_is_load_bearing(rule, build, tmp_path):
    proj = build(tmp_path)
    real = _evaluate(CHK, proj)
    # EACH SUBJECT MUST ISOLATE ITS RULE. If a second rule co-fires, removing
    # the first leaves the verdict at FAIL and the mutation proves nothing —
    # so the isolation is asserted rather than worked around.
    assert _rules(real) == {rule}, (
        f"this subject raises {sorted(_rules(real))}; it must raise {rule} "
        f"alone or the mutation below cannot show the rule is load-bearing")

    mutant = _gate_mutant(rule, tmp_path)
    mutated = _evaluate(mutant, proj)
    assert _rules(mutated) == set()
    assert mutated["verdict"] != ST.VERDICT_FAIL, (
        f"{rule} is the only refusal the real gate raises here, so the gate "
        f"without it must not still say FAIL — something else is doing the "
        f"work and this rule pins nothing")


def test_every_rule_the_gate_can_raise_is_proven_by_a_subject():
    """No rule may exist that nothing here breaks.

    The rule names are read out of the gate's own docstring refusal table, so a
    rule added tomorrow without a subject fails this test rather than shipping
    unproven.
    """
    doc = CHK.__doc__
    table = doc.split("WHAT IT REFUSES")[1].split("NOT_APPLICABLE IS NOT A PASS")[0]
    declared = {tok for tok in table.replace("/", " ").split()
                if tok.isupper() and "_" in tok and len(tok) > 6}
    proven = {rule for rule, _ in SUBJECTS} | {"REPORT_UNREADABLE"}
    assert declared - proven == set(), (
        f"declared but never broken: {sorted(declared - proven)}")


# --------------------------------------------------------------------------- #
# absence, bought and unbought
# --------------------------------------------------------------------------- #
def test_an_absent_template_with_a_reason_is_not_applicable_and_not_a_pass(tmp_path):
    proj = tmp_path / "design"
    proj.mkdir()
    _ingest(proj, "--template", str(tmp_path / "not_there"),
            "--no-template-reason", GOOD_REASON)
    rc, check, _ = _check(proj)
    assert rc == 0, "a declared not-applicable does not stop the flow"
    assert check["verdict"] == ST.VERDICT_NOT_APPLICABLE
    assert check["verdict"] != ST.VERDICT_PASS
    assert check["not_applicable_reason"] == GOOD_REASON
    assert check["examined"]["slots_in_record"] == 0, (
        "and the record says so: no slot contract was pinned")


def test_a_reason_too_short_to_be_checkable_buys_nothing(tmp_path):
    proj = tmp_path / "design"
    proj.mkdir()
    _ingest(proj, "--template", str(tmp_path / "not_there"),
            "--no-template-reason", "N/A")
    rc, check, _ = _check(proj)
    assert rc == 1
    r = next(x for x in check["refusals"]
             if x["rule"] == "NO_TEMPLATE_WITHOUT_REASON")
    assert r["floor"] == ST.MIN_REASON_CHARS
    assert r["stated_chars"] == 3


def test_a_reason_cannot_buy_a_search_that_never_happened(tmp_path):
    proj = _sub_never_looked(tmp_path)
    _, check, _ = _check(proj)
    msg = next(r for r in check["refusals"]
               if r["rule"] == "NEVER_LOOKED")["message"]
    assert "describes a template nobody searched for" in msg


def test_the_same_project_passes_once_a_path_is_actually_searched(tmp_path):
    """The other direction of NEVER_LOOKED: the only thing that changed is that
    somebody looked."""
    tmpl = _template(tmp_path)
    proj = tmp_path / "design"
    proj.mkdir()
    _ingest(proj)
    assert _check(proj)[0] == 1
    _ingest(proj, "--template", str(tmpl), "--slot", "slot_a")
    assert _check(proj)[0] == 0


def test_the_reason_floor_is_read_from_the_flows_own_rule_not_copied():
    """Two hand-kept numbers are two numbers that drift."""
    import flow_condition_reachability_check as fcr
    import flow_compliance_check as fcc
    assert ST.MIN_REASON_CHARS == fcr.MIN_ABSENT_CONDITION_REASON
    assert ST.MIN_REASON_CHARS == fcc._MIN_ABSENT_CONDITION_REASON


# --------------------------------------------------------------------------- #
# the record itself
# --------------------------------------------------------------------------- #
def test_a_missing_report_makes_the_gate_write_one_saying_so(tmp_path):
    proj = tmp_path / "design"
    proj.mkdir()
    assert CHK.main([str(proj), "--json", ST.REPORT_REL]) == 1
    doc = json.loads((proj / ST.REPORT_REL).read_text())
    assert doc["check"]["verdict"] == ST.VERDICT_FAIL
    assert "REPORT_ABSENT" in {r["rule"] for r in doc["check"]["refusals"]}


def test_an_unreadable_report_is_refused_and_is_not_overwritten(clean):
    proj, _ = clean
    path = proj / ST.REPORT_REL
    path.write_text("{ this is not json")
    assert CHK.main([str(proj), "--json", ST.REPORT_REL]) == 1
    assert path.read_text() == "{ this is not json", (
        "the only evidence of what the step produced must not be destroyed by "
        "the program complaining about it")


# --------------------------------------------------------------------------- #
# invocation and declaration
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("prog", ["submission_template_ingest",
                                  "submission_template_check"])
def test_the_program_runs_as_the_flow_spawns_it(prog, clean):
    """`flow_compliance_check` builds `[python3, <programs>/<name>.py, ...]` and
    runs it with cwd set to the PROJECT. A sibling import that only resolves
    when the programs directory happens to be on `sys.path` dies exactly there,
    and no in-process test would see it."""
    proj, _ = clean
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    argv = [sys.executable, str(PROGRAMS / f"{prog}.py"), "."]
    if prog == "submission_template_check":
        argv += ["--json", ST.REPORT_REL]
    r = subprocess.run(argv, cwd=proj, env=env, capture_output=True, text=True,
                       timeout=180)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert prog in r.stdout


def test_the_flow_declares_this_gate_exactly_as_it_is_invoked():
    """The gate is what the flow SAYS it is, or the wiring is decoration."""
    import yaml
    flow = yaml.safe_load(
        (PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml").read_text())
    step = next(s for s in flow["steps"] if str(s.get("id")) == "0.5ic")
    assert step["programs"] == ["submission_template_ingest"]
    assert step["gate"]["program_exit_zero"] == (
        f"submission_template_check . --json {ST.REPORT_REL}")
    outs = step["required_outputs"]
    assert f"{ST.SLOTS_DIR_REL}/*.yaml OR {ST.NO_TEMPLATE_REL}" in outs
    assert ST.REPORT_REL in outs


@pytest.mark.parametrize("mod", ["submission_template_ingest.py",
                                 "submission_template_check.py",
                                 "_submission_template.py"])
def test_the_programs_carry_no_vendor_sku_or_node_literal(mod):
    """Chip-AGNOSTIC: the operator's name may appear in a research note; it must
    not be a code literal. Slot names, geometry, pads and fixture cell names are
    read out of whatever template the caller points at."""
    src = (PROGRAMS / mod).read_text().lower()
    for token in ("wafer.space", "wafer-space", "waferspace", "efabless",
                  "caravel", "gf180", "sky130", "asap7", "ihp-sg13", "tsmc",
                  "180nm", "130nm"):
        assert token not in src, f"{mod} carries the literal {token!r}"
