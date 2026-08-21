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


def _sub_slot_file_edited(tmp_path):
    proj, _ = _accepted(tmp_path)
    f = proj / ST.SLOTS_DIR_REL / "slot_a.yaml"
    d = json.loads(f.read_text())
    d["die_area"]["rect"][2] = "1200"          # the die grows after the fact
    f.write_text(json.dumps(d, indent=2))
    return proj


def _sub_slot_file_unreadable(tmp_path):
    proj, _ = _accepted(tmp_path)
    (proj / ST.SLOTS_DIR_REL / "slot_a.yaml").write_text("{ not json")
    return proj


def _sub_pad_list_unread(tmp_path):
    """A real operator template spells its pad lists PER DIE SIDE. This subject
    spells one under a name the pattern does not claim, which is the shape that
    produced a silent `pads: null` the first time this ingester met real input.
    """
    proj, tmpl = _accepted(tmp_path)
    (tmpl / "slots" / "slot_a.yaml").write_text(
        "DIE_AREA: [0, 0, 1000, 2000]\n"
        "CORE_AREA: [26, 26, 974, 1974]\n"
        "FP_SIZING: absolute\n"
        "PAD_RING: [pad_n0, pad_n1]\n")
    _ingest(proj, "--template", str(tmpl), "--slot", "slot_a")
    return proj


def _sub_report_absent(tmp_path):
    proj = tmp_path / "design"
    proj.mkdir()
    return proj


def _sub_report_unreadable(tmp_path):
    proj, _ = _accepted(tmp_path)
    (proj / ST.REPORT_REL).write_text("{ this is not json")
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
    ("SLOT_FILE_DISAGREES_WITH_RECORD", _sub_slot_file_edited),
    ("SLOT_FILE_DISAGREES_WITH_RECORD", _sub_slot_file_unreadable),
    ("PAD_LIST_UNREAD", _sub_pad_list_unread),
    ("REPORT_ABSENT", _sub_report_absent),
    ("REPORT_UNREADABLE", _sub_report_unreadable),
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
    check = _evaluate(CHK, proj)
    assert rule in _rules(check), (
        f"expected {rule}, got {sorted(_rules(check))}")
    assert check["verdict"] == ST.VERDICT_FAIL
    # and the CLI the flow's gate actually spawns agrees with the evaluation
    assert CHK.main([str(proj), "--json", ST.REPORT_REL]) == 1


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
    proven = {rule for rule, _ in SUBJECTS}
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


def _routed_conditions():
    """Every step the FLOW routes on this step's output, read from the flow."""
    import yaml
    flow = yaml.safe_load(
        (PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml").read_text())
    out = {}
    for s in flow["steps"]:
        cond = s.get("condition")
        if not isinstance(cond, dict):
            continue
        pats = cond.get("files_exist") or []
        if any("submission_template" in str(x) for x in pats):
            out[str(s["id"])] = cond
    return out


def _selected(project: Path) -> set:
    """The routed steps this project's tree makes applicable, by the flow's own
    predicate — not a re-implementation of it."""
    import flow_compliance_check as FCC
    return {sid for sid, cond in _routed_conditions().items()
            if FCC._check_condition(project, cond)}


def _routes_by_router_file():
    """router-file suffix -> the step ids the FLOW selects with it.

    THREE ROUTER FILES, TWO TERMINALS. The step's outputs were a binary —
    `slots/*.yaml` or `NO_TEMPLATE.txt` — which routed a design to the
    operator's container or to the IP/hardmacro terminal. A CHIP doing its OWN
    tape-out is neither: it has no operator template, so the container step's
    condition excluded it, and it is a die rather than an IP, so the hardmacro
    terminal is the wrong end for it. `SELF_TAPEOUT.txt` is its router.

    2026-08-20 — THE THIRD ROUTER STOPPED BEING A THIRD TERMINAL. It briefly
    selected a step of its own (`37.5self`, the general precheck). The owner
    retired that step: the general precheck is a second ARM of `37.5ic`, not an
    alternative to it. So `slots/*.yaml` and `SELF_TAPEOUT.txt` now BOTH select
    `37.5ic` — they are the two markers of the one CHIP path — and the file
    that still selects a terminal of its own is `NO_TEMPLATE.txt`, the IP one.

    Read out of the flow rather than listed here, so a route that appears or
    disappears shows up as a change in this mapping instead of quietly
    satisfying a hard-coded pair.
    """
    routed = _routed_conditions()
    out = {}
    for sid, cond in routed.items():
        for pat in cond["files_exist"]:
            key = str(pat).rsplit("/", 1)[-1]
            out.setdefault(key, set()).add(sid)
    return out


def test_the_outputs_of_this_step_are_what_the_flow_routes_on():
    """If nothing routes on them any more, every assertion below is vacuous."""
    routed = _routed_conditions()
    assert routed, (
        "no flow step is conditional on this step's output — either the wiring "
        "moved or this test has stopped measuring anything")
    by_file = _routes_by_router_file()
    assert set(by_file) == {"*.yaml", "NO_TEMPLATE.txt", "SELF_TAPEOUT.txt"}, (
        "three router files are still what the flow routes on; got "
        f"{sorted(by_file)}")

    # THE LOAD-BEARING EXCLUSIVITY IS CHIP-vs-IP, and it is the one that has to
    # hold: `files_exist` cannot express "and not", so a step reachable from
    # both a chip router and the IP router would be selected on two
    # incompatible deliveries at once.
    ip = by_file["NO_TEMPLATE.txt"]
    for chip_router in ("*.yaml", "SELF_TAPEOUT.txt"):
        assert not (ip & by_file[chip_router]), (
            f"{sorted(ip & by_file[chip_router])} is selected by BOTH the IP "
            f"router and the chip router {chip_router}")

    # THE TWO CHIP ROUTERS DO OVERLAP, AND THAT IS THE POINT. `37.5ic` is
    # selected by both, because a chip gets that step whether or not there is
    # an operator — the operator's container is an ARM of it, not a different
    # route. Asserted rather than tolerated, so re-splitting them into two
    # terminals fails HERE with the reason attached.
    assert "37.5ic" in by_file["*.yaml"] & by_file["SELF_TAPEOUT.txt"], (
        "37.5ic must be reachable from BOTH chip routers; a self tape-out that "
        "cannot reach it passes no tape-out precheck at all — the exact hole "
        f"the retired 37.5self was created to plug. Got: {by_file}")

    # AND IT MUST BE `any_of`. With the default ALL-of reading, a condition
    # listing two MUTUALLY EXCLUSIVE router files can never be satisfied by any
    # tree — `tapeout_declaration_check` refuses the tree carrying both — so
    # the step would be silently skipped for every design on the chip path.
    routed = _routed_conditions()
    assert routed["37.5ic"].get("any_of") is True, (
        "37.5ic lists two mutually exclusive router files; without `any_of` "
        "its condition is unsatisfiable and the step is dead for every design")


def _write_router(root: Path, suffix: str) -> None:
    """Put ONE of step 0.5ic's router files on disk, by its suffix."""
    import _tapeout_declaration as TD
    if suffix == "*.yaml":
        (root / ST.SLOTS_DIR_REL).mkdir(parents=True, exist_ok=True)
        (root / ST.SLOTS_DIR_REL / "slot_a.yaml").write_text(
            "DIE_AREA: [0, 0, 2000, 2000]\n"
            "CORE_AREA: [100, 100, 1900, 1900]\nFP_SIZING: absolute\n")
    elif suffix == "NO_TEMPLATE.txt":
        (root / ST.NO_TEMPLATE_REL).parent.mkdir(parents=True, exist_ok=True)
        (root / ST.NO_TEMPLATE_REL).write_text(
            ST.NO_TEMPLATE_MARKER + "\nfixture\n")
    elif suffix == "SELF_TAPEOUT.txt":
        (root / TD.SELF_TAPEOUT_REL).parent.mkdir(parents=True, exist_ok=True)
        (root / TD.SELF_TAPEOUT_REL).write_text(
            TD.SELF_TAPEOUT_MARKER + "\nfixture\n")
    else:                                                   # pragma: no cover
        raise AssertionError(f"no writer for router file {suffix!r}")


def test_two_routers_at_once_is_refused_by_a_PROGRAM_because_the_flow_cannot(
        tmp_path):
    """WHERE THE EXCLUSIVITY ACTUALLY LIVES — measured, not assumed.

    This file used to assert "no step is selected by more than one router",
    while the harm its comment named is TWO TERMINALS SELECTED AT ONCE. Those
    are not the same statement, and the gap between them is the point. MEASURED
    on the flow BEFORE `37.5self` was retired, on a tree carrying both chip
    routers:

        flow_compliance_check._check_condition
            37.5ic    selected=True    |  TWO TERMINALS
            37.5self  selected=True    |

    and each of those steps named EXACTLY ONE router file — so the assertion
    was satisfied by construction on the very tree that exhibited the defect it
    existed to prevent, while failing on steps that are legitimately on more
    than one route. It measured step-to-router MULTIPLICITY, adjacent to
    terminal-to-terminal COLLISION, which is the claim.

    Retiring `37.5self` (867de42892) removed THAT instance and nothing more.
    Which pair collides is exactly what a route being added or retired changes,
    so it is DERIVED from the flow below and named NOWHERE — including here: a
    sentence in this docstring saying which pair collides today would be a
    hand-written fact that goes stale silently while the test stays green,
    because the test reads the mapping and the sentence does not.

    And the flow cannot hold the property: `files_exist` has no "and not", so
    two steps on different routers select together whenever both files are on
    disk, whatever any test asserts about how many routers a step names. This
    is not a gap in the grammar to be filled; it is a property the flow is the
    wrong place for.

    A PROGRAM holds it, wired into step 0.5ic's own gate, and this pins all
    three halves — the harm is REACHABLE, the guard REFUSES it by a named rule,
    and the guard IS WIRED, because one that exists and is not wired guards
    nothing.

    IT IS GUARDED TWICE, AND THIS PINS ONE OF THE TWO. Measured on a properly
    ingested single-router project (both clauses rc 0) with a second router
    added and nothing else changed, BOTH of 0.5ic's gate clauses refuse it, by
    different named rules:

        submission_template_check   TREE_SAYS_BOTH
        tapeout_declaration_check   ROUTER_CONTRADICTION   <- what this pins

    Said here because it changes how a red in this test should be read: the
    property is not lost the moment this one assertion fails, and conversely a
    green here is not evidence that the sibling clause still works. Note too
    that `all_of` reports the FIRST failing clause, so at flow level the visible
    rule is TREE_SAYS_BOTH and ROUTER_CONTRADICTION stops at 0.5ic's own report.
    """
    import itertools
    import tapeout_declaration_check as TDC

    by_file = _routes_by_router_file()
    routers = sorted(by_file)

    # 1. THE HARM IS REACHABLE — some pair of routers selects steps the other
    #    does not, i.e. two different terminals at once.
    harmful = [(a, b) for a, b in itertools.combinations(routers, 2)
               if (by_file[a] - by_file[b]) and (by_file[b] - by_file[a])]
    assert harmful, (
        "no pair of router files selects two different sets of steps any more, "
        f"so the guard below is guarding nothing. Routes: {by_file}")

    # 2. EVERY pair is refused by the program, by a NAMED rule — not just the
    #    harmful ones, because which pair is harmful moves with the flow.
    for a, b in itertools.combinations(routers, 2):
        root = tmp_path / f"{a}_{b}".replace("*", "star").replace(".", "_")
        (root / "input/submission_template").mkdir(parents=True)
        _write_router(root, a)
        _write_router(root, b)
        import _tapeout_declaration as TD
        doc, _ig = TD.merge_answers(TD.blank_declaration(),
                                    {"deliverable": "DIE"})
        (root / TD.DECLARATION_REL).write_text(json.dumps(doc, indent=2))
        rep = root / "reports/phase1/tapeout_declaration.json"
        assert TDC.main([str(root), "--json", str(rep)]) != 0, (
            f"a tree carrying {a} AND {b} selects more than one delivery path "
            f"and must not pass")
        assert "ROUTER_CONTRADICTION" in rep.read_text(), (
            f"the refusal for {a}+{b} must be a named rule, not a bare "
            f"non-zero exit")

    # 3. ...and that program is a CLAUSE OF STEP 0.5ic'S OWN GATE.
    import yaml
    flow = yaml.safe_load(
        (PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml").read_text())
    step = next(s for s in flow["steps"] if str(s["id"]) == "0.5ic")
    assert "tapeout_declaration_check" in json.dumps(step["gate"]), (
        "the only thing that can hold this property is not wired into the "
        "step that writes the router files")


def test_a_step_on_both_chip_routes_declares_any_of():
    """Otherwise it is unreachable, and silently so.

    `files_exist` defaults to ALL-of (`flow_compliance_check._check_condition`),
    and the three router files are mutually exclusive on disk — so a step
    listing two of them WITHOUT `any_of` demands a tree that cannot exist and
    can never run for any design. That is indistinguishable from the step
    having been deleted, and it is the failure this asserts against.
    """
    routed = _routed_conditions()
    multi = {sid: c for sid, c in routed.items()
             if len([x for x in (c.get("files_exist") or [])]) > 1}
    # THE DENOMINATOR, because the loop below only fires for steps that list
    # more than one router and would otherwise report GREEN having examined
    # NOTHING. Measured: reverting 15.5ic and 26.5ic to `slots/*.yaml` alone —
    # the regression that shipped dies with no pad ring and no seal ring — takes
    # this population to a size the loop skips entirely, and the assertion below
    # then passes silently. That revert IS caught, loudly, by
    # test_pad_and_seal_ring_on_the_chip_path.py (6 reds, two of them named
    # `..._conditioned_on_the_chip_path_and_not_on_the_operator`), so nothing is
    # unguarded — but a test that goes quiet on the exact change it was written
    # for should say so rather than look clean.
    assert multi, (
        "no routed step lists more than one router file, so the rule below "
        f"examined nothing. Routed steps and their conditions: {routed}")
    for sid, cond in multi.items():
        pats = [str(x) for x in (cond.get("files_exist") or [])]
        assert cond.get("any_of") is True, (
            f"step {sid} lists {len(pats)} router files {pats} and does not "
            f"declare `any_of`, so its condition is an AND over files that are "
            f"mutually exclusive — it can never run")


def test_a_run_nobody_looked_for_a_template_selects_NO_path(tmp_path):
    """THE ONE THIS STEP EXISTS FOR, now that the outputs are routers.

    MEASURED on the flow at the time this was written: `slots/*.yaml` makes the
    chip-path steps applicable and `NO_TEMPLATE.txt` makes the IP-path step
    applicable, on `files_exist` and nothing else.

    THE SENTENCE THAT USED TO SIT HERE IS NO LONGER TRUE, and it is corrected
    rather than deleted because a reader who believes it reasons wrongly about
    why this step matters. It said "Nothing blocks on this step and nothing
    takes a required_input from it, so ITS OWN FAIL DOES NOT STOP THE ROUTING".
    Both halves are now false — the 2026-08-20 D5-MISSING-EDGE change added the
    edges.

    NO LIST OF STEP IDS APPEARS HERE ON PURPOSE. Enumerating them is how the
    sentence above rotted: a hand-written fact in prose is correct until the
    flow moves and then silently is not. The PROPERTY, and how to re-derive it
    in one read of the flow this file already parses:

        every step whose `condition.files_exist` names a submission_template
        router also declares `0.5ic` in its `blocks_on`; the chip-path ones
        additionally take `input/submission_template/tapeout_declaration.json`
        as a `required_input` from it.

    So this step's FAIL now DOES stop the routing. That is not re-asserted
    here, because a broader guard already holds it, in
    `test_matrix_d5_deps_correct.py`:

        test_d5_blocks_on_covers_the_real_dependency_graph

    which derives the edge set from the real dependency graph and pins it for
    every step in the flow. Measured, by dropping `0.5ic` from `26.5ic` and then
    from `37.5ip` in a throwaway tree and watching D5 redden for each. A third
    copy of an invariant a broader guard already holds is maintenance surface
    pretending to be coverage.

    THE CONCLUSION IS UNCHANGED, because it never rested on that clause: the
    router file must not be written by a run that did not look, because the
    routers select terminals by `files_exist` and nothing else.

    A run that searched and found nothing and SAID SO, and a run where nobody
    looked, produce the same empty directory. If both wrote the router, both
    would select the IP path and the three states this step keeps apart would
    be collapsed back to two by the flow, whatever the report said.
    """
    by_file = _routes_by_router_file()
    ip = by_file["NO_TEMPLATE.txt"]
    # The shuttle route only. `SELF_TAPEOUT.txt` is written by this step's
    # sibling `tapeout_declaration_gen`, not by the ingest under test here, so
    # an ingest-only run must select the operator's terminal and nothing else.
    chip = by_file["*.yaml"]
    tmpl = _template(tmp_path)
    reason = ("Delivered as a hardmacro to an integrator and never submitted "
              "to a shuttle, so this design has no slot.")

    outcomes = {}
    for name, argv in (
            ("ingested", ("--template", str(tmpl), "--slot", "slot_a")),
            ("declared", ("--template", str(tmp_path / "gone"),
                          "--no-template-reason", reason)),
            ("undeclared", ("--template", str(tmp_path / "gone"),)),
            ("never", ())):
        proj = tmp_path / f"r_{name}"
        proj.mkdir()
        _ingest(proj, *argv)
        outcomes[name] = (_selected(proj), _evaluate(CHK, proj)["verdict"])

    assert outcomes["ingested"] == (chip, ST.VERDICT_PASS)
    assert outcomes["declared"] == (ip, ST.VERDICT_NOT_APPLICABLE)
    assert outcomes["undeclared"] == (set(), ST.VERDICT_FAIL)
    assert outcomes["never"] == (set(), ST.VERDICT_FAIL)

    # and the load-bearing inequality, stated as its own assertion so a future
    # change that re-collapses them fails HERE with the reason attached
    assert outcomes["never"][0] != outcomes["declared"][0], (
        "a run nobody looked at selects the same path as one that searched and "
        "declared — the router has collapsed the two absences back together")


def test_a_router_file_nobody_declared_is_named_in_the_refusal(tmp_path):
    """The gate cannot delete a stray router, but it must not stay quiet about
    one: a FAILED ingest does not stop the flow selecting on the file."""
    proj = tmp_path / "design"
    proj.mkdir()
    _ingest(proj)                                   # nobody looked
    (proj / ST.NO_TEMPLATE_REL).write_text("put here by some other hand\n")
    check = _evaluate(CHK, proj)
    assert check["verdict"] == ST.VERDICT_FAIL
    assert check["examined"]["path_router_on_disk"] is True
    msg = next(r for r in check["refusals"]
               if r["rule"] == "NEVER_LOOKED")["message"]
    assert "currently choosing a delivery path" in msg


def test_the_flow_declares_this_gate_exactly_as_it_is_invoked():
    """The gate is what the flow SAYS it is, or the wiring is decoration.

    STEP 0.5ic HAS TWO HALVES, and this pins both. `submission_template_ingest`
    records what the OPERATOR published; `tapeout_declaration_gen` records what
    the DESIGN declares about itself — the 18 questions a self-tape-out has
    nobody else to answer for it. Both belong to the step that decides the
    route, and each has its own gate clause, so neither can be added as a
    program nobody judges.
    """
    import yaml
    import _tapeout_declaration as TD
    flow = yaml.safe_load(
        (PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml").read_text())
    step = next(s for s in flow["steps"] if str(s.get("id")) == "0.5ic")
    assert step["programs"] == ["submission_template_ingest",
                                "tapeout_declaration_gen"]

    # `all_of`, and the CONTAINER is pinned as hard as the clauses inside it.
    # MEASURED: `flow_compliance_check._evaluate_gate` handed a bare LIST of the
    # same two mappings returns `(False, ['gate spec unrecognized'])` — it runs
    # NEITHER program, so writing the two clauses as a plain list would take the
    # pre-existing `submission_template_check` gate out of service and leave this
    # step unable to pass for any tree at all. Asserting the container name is
    # what stops that shape coming back.
    assert set(step["gate"]) == {"all_of"}, (
        f"0.5ic's gate must be an `all_of` container; got {list(step['gate'])}")
    clauses = [c["program_exit_zero"] for c in step["gate"]["all_of"]]
    assert clauses == [
        f"submission_template_check . --json {ST.REPORT_REL}",
        f"tapeout_declaration_check . --json {TD.REPORT_REL}",
    ]
    # And the shape is not merely well-formed, it is EXECUTED: the enforcer
    # names the program it invoked rather than declining to parse the gate.
    import flow_compliance_check as FCC
    import tempfile
    _ok, _why = FCC._evaluate_gate(Path(tempfile.mkdtemp()), step["gate"])
    assert any("__RAN_HINT__" in r for r in _why), (
        f"the enforcer did not invoke either clause of 0.5ic's gate: {_why}")

    outs = step["required_outputs"]
    # The OR is now THREE-way. Pinned verbatim so the third alternative cannot
    # be dropped without this failing: without it a chip doing its own
    # tape-out has no router file and reaches tape-out unchecked.
    assert (f"{ST.SLOTS_DIR_REL}/*.yaml OR {ST.NO_TEMPLATE_REL} "
            f"OR {TD.SELF_TAPEOUT_REL}") in outs
    assert ST.REPORT_REL in outs
    assert TD.DECLARATION_REL in outs
    assert TD.REPORT_REL in outs
    # And the step still has NO condition: it is the step that decides the
    # route, so every design passes through it — including the ones with no
    # shuttle, which are exactly the ones that need it most.
    assert step.get("condition") is None


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
