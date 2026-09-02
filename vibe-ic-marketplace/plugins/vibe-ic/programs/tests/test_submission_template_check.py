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
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _submission_template as ST         # noqa: E402
import submission_template_ingest as ING  # noqa: E402
import submission_template_check as CHK   # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


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
    r = _pr.run(argv, cwd=proj, env=env, capture_output=True, text=True)
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

    # THE LOAD-BEARING EXCLUSIVITY IS ONE-DIRECTIONAL, and it is the CHIP-ONLY
    # half: a step that asks for a pad ring, a seal ring or a tape-out precheck
    # must not be selected by a design that declared it has no die, because
    # that is a refusal such a design can never answer.
    #
    # 2026-09-02 — THE OTHER DIRECTION WAS RETIRED BY OWNER RULING. It used to
    # read "no step may be selected by both an IP router and a chip router",
    # and it was measured turning a die into a design with NO deliverable kit
    # at all: on spm x gf180mcuD at plugin 1.15.67 a `deliverable=DIE` run
    # recorded `Step 37.5ip ... condition not met` and produced no `.lef`, no
    # `.lib` and no datasheet anywhere. The ruling: an IC runs BOTH terminals —
    # a die is also a block somebody re-uses — and only a pure IP skips the
    # chip one. So overlap on the IP-DELIVERABLE step is now expected, and the
    # exclusivity below is asserted against the CHIP-ONLY steps by name, read
    # out of the flow rather than listed, so a new chip-only step is covered
    # the moment it appears.
    ip = by_file["NO_TEMPLATE.txt"]
    chip_only = set()
    for chip_router in ("*.yaml", "SELF_TAPEOUT.txt"):
        chip_only |= by_file[chip_router]
    chip_only -= ip          # what BOTH select is, by construction, not chip-only
    assert chip_only, (
        "no step is selected by a chip router alone — the chip path has "
        "stopped being distinguishable from the IP path")
    for sid in sorted(chip_only):
        assert sid not in ip, (
            f"{sid} is chip-only yet reachable from the IP router; a design "
            "with no die would be asked for a pad ring")

    # AND THE OVERLAP IS ASSERTED, NOT MERELY TOLERATED. Deleting 37.5ip from
    # the chip routers restores the exact hole the ruling closed, so it fails
    # here with the reason attached rather than passing as a tightening.
    assert "37.5ip" in ip, "37.5ip must still be reachable from the IP router"
    for chip_router in ("*.yaml", "SELF_TAPEOUT.txt"):
        assert "37.5ip" in by_file[chip_router], (
            f"37.5ip is not reachable from the chip router {chip_router}: an "
            "IC would ship no LEF/Liberty/GDS kit and no integration "
            "documents (owner ruling 2026-09-02)")

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


def test_a_run_nobody_looked_for_a_template_selects_NO_path(tmp_path):
    """THE ONE THIS STEP EXISTS FOR, now that the outputs are routers.

    MEASURED on the flow at the time this was written: `slots/*.yaml` makes the
    chip-path steps applicable and `NO_TEMPLATE.txt` makes the IP-path step
    applicable, on `files_exist` and nothing else.

    THE SENTENCE THAT USED TO SIT HERE IS NO LONGER TRUE, and it is corrected
    rather than deleted because a reader who believes it reasons wrongly about
    why this step matters. It said "Nothing blocks on this step and nothing
    takes a required_input from it, so ITS OWN FAIL DOES NOT STOP THE ROUTING —
    measured too". Both halves are now false; the 2026-08-20 D5-MISSING-EDGE
    change added the edges, and "measured too" is exactly the phrase that stops
    the next reader from re-measuring.

    NO LIST OF STEP IDS APPEARS HERE ON PURPOSE — enumerating them is how the
    sentence above rotted. The PROPERTY, re-derivable in one read of the flow
    this file already parses:

        every step whose `condition.files_exist` names a submission_template
        router also declares `0.5ic` in its `blocks_on`; the chip-path ones
        additionally take `input/submission_template/tapeout_declaration.json`
        as a `required_input` from it.

    So this step's FAIL now DOES stop the routing. Nothing is asserted here
    about it: `test_matrix_d5_deps_correct.py`, in

        test_d5_blocks_on_covers_the_real_dependency_graph

    derives the edge set from the real dependency graph, one parametrised cell
    per step. NOT quite "every step": measured on this tree it is 68 enforced
    and 1 waived under `xfail(strict=True)`, so a waived cell XPASSes and goes
    red the day its gap closes rather than being skipped. Every step this
    docstring is about is in the ENFORCED set — measured, by dropping `0.5ic`
    from `15.5ic`, `26.5ic` and `37.5ip` in a throwaway tree and watching the
    matching D5 cell redden for each.

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
        raise AssertionError(
            f"no writer for router file {suffix!r} — the flow grew a router "
            f"and this helper did not; add a branch above rather than letting "
            f"the pairs below run over a tree that was never built")

def test_two_routers_at_once_exit_ONE_a_refusal_and_never_TWO_a_skip(tmp_path):
    """The TIER, not just the finding — and the tier is the unguarded half.

    That two coexisting router artefacts are REFUSED is already pinned twice, by
    `test_path_step_matrix_ic_and_ip::test_two_router_files_at_once_are_refused_
    and_the_control_is_not` and by `test_general_precheck::
    test_g8_two_router_files_at_once_are_refused_not_resolved`. Removing the
    refusal reddens both. This does not repeat that.

    What NOTHING pinned is the EXIT TIER the refusal leaves by. MEASURED on
    81cd5321b by demoting it — keeping the ROUTER_CONTRADICTION finding, keeping
    it in the report, and returning 2 instead of 1 for that case alone:

        362 passed, 11 skipped, 3 xfailed        <- nothing noticed

    WHAT THAT DOES AND DOES NOT COST, measured end to end rather than argued —
    because the first version of this docstring claimed more than was true.

    Demoting THIS clause alone changes NOTHING at flow level. 0.5ic's gate is
    `all_of`, and its sibling `submission_template_check` independently refuses
    the same tree with TREE_SAYS_BOTH, so the step still reads FAIL and every
    routed step still reads MISSING. Measured on a properly ingested project
    with a second router added:

        as shipped        clause1 rc=1  clause2 rc=1   0.5ic FAIL
        clause2 demoted   clause1 rc=1  clause2 rc=2   0.5ic FAIL   (unchanged)
        BOTH demoted      clause1 rc=2  clause2 rc=2   0.5ic VACUOUS-PASS

    So the harm needs both, and clause1's tier IS pinned —
    `test_each_refusal_fires_on_the_subject_it_defends` reddens across every
    rule when its exit code moves. Clause2's was the only one of the two that
    was not.

    That is why this exists: the two clauses are meant to be INDEPENDENT
    guards, and an independent guard that can silently become a disclosed skip
    is not independent. This pins the half that was unpinned; it does not
    claim to be closing a live hole.

    It asserts rc == 1 EXACTLY. Not `!= 0`, which 2 also satisfies and which is
    how the tier stayed unguarded.

    The pairs are DERIVED from the flow, never named: which routers exist is
    what a route being added or retired changes.
    """
    import itertools
    import tapeout_declaration_check as TDC

    by_file = _routes_by_router_file()
    routers = sorted(by_file)
    pairs = list(itertools.combinations(routers, 2))
    assert pairs, (
        "fewer than two router files are routed on, so there is no pair to "
        f"put on disk and this rule examined nothing. Routes: {by_file}")

    for a, b in pairs:
        root = tmp_path / f"{a}_{b}".replace("*", "star").replace(".", "_")
        (root / "input/submission_template").mkdir(parents=True)
        _write_router(root, a)
        _write_router(root, b)
        import _tapeout_declaration as TD
        doc, _ig = TD.merge_answers(TD.blank_declaration(),
                                    {"deliverable": "DIE"})
        (root / TD.DECLARATION_REL).write_text(json.dumps(doc, indent=2))
        rep = root / "reports/phase1/tapeout_declaration.json"
        rc = TDC.main([str(root), "--json", str(rep)])
        assert rc == 1, (
            f"a tree carrying {a} AND {b} must exit 1 — a REFUSAL — and this "
            f"exited {rc}. Exit 2 is the flow's disclosed-skip tier. 0.5ic's "
            f"sibling clause refuses this tree too, so the step still fails "
            f"today; what breaks is that this guard has stopped being an "
            f"independent one, and with BOTH clauses at 2 the step reads "
            f"VACUOUS-PASS on a tree that selects two terminals at once")
        assert TDC.RULE_ROUTER_CONTRADICTION in rep.read_text(), (
            f"the refusal for {a}+{b} must be the NAMED rule, not a bare "
            f"non-zero exit")


# ══════════════════════════════════════════════════════════════════════════
# THE STEP IS DISPATCHED, AND DISPATCHING IT DOES NOT BUY A PASS
#
# Until 2026-08-26 nothing in the shipped tree could execute either of step
# 0.5ic's two producers. The step therefore reported MISSING for every design
# ever run, and a real SPM run carried 42 blockers of which the step's own
# absence was the declared root. `phase1_one_shot_runner` now dispatches both,
# before its mode branch and on every path.
#
# The three tests below are the two directions of that change plus the one
# thing it must NOT have done. A wiring that made the step pass by itself would
# be a route this flow picked on a design's behalf — a default wearing a
# declaration's clothes, which is what step 0.5ic exists to refuse.
# ══════════════════════════════════════════════════════════════════════════
_REAL_REASON = (
    "This design targets no shuttle operator; it is a self tape-out. No "
    "operator project template exists to stage, so there is no slot geometry, "
    "no operator fixtures and no per-slot pad list for this step to ingest.")


def _drive_step_0_5ic(project: Path) -> int:
    """Run the SHIPPED runner entry, not a re-implementation of it."""
    import phase1_one_shot_runner as R
    return R._run_step_0_5ic(project)


def _step_0_5ic_verdicts(project: Path):
    """(rc, rc) of the step's OWN two gate clauses, as the flow declares them."""
    import tapeout_declaration_check as TDC
    rc1 = CHK.main([str(project), "--json",
                    str(project / ST.REPORT_REL)])
    import _tapeout_declaration as TD
    rc2 = TDC.main([str(project), "--json", str(project / TD.REPORT_REL)])
    return rc1, rc2


def _answers(project: Path, doc) -> None:
    import _tapeout_declaration as TD
    doc = dict(doc)
    doc.setdefault(TD.SYNTHESIS_AREA_BUDGET_KEY, {
        "status": TD.AREA_BUDGET_NOT_APPLICABLE,
        "rationale": (
            "This route-only fixture does not exercise implementation area; "
            "the declaration gate still requires an explicit disposition."),
    })
    path = project / ST.DESIGN_ANSWERS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")


def test_a_declared_self_tapeout_is_produced_by_the_flow_and_passes(tmp_path):
    """The POSITIVE direction: a die that declares itself gets its route.

    Both producers run in the order the flow declares them, the ingest's own
    `NO_TEMPLATE.txt` is retired by its sibling because a die must not select
    the IP terminal, and exactly one router file is left on disk.
    """
    import _tapeout_declaration as TD
    proj = tmp_path / "declared"
    proj.mkdir()
    _answers(proj, {"operator_template": {"absent_reason": _REAL_REASON},
                    "answers": {"deliverable": TD.DELIVERABLE_DIE}})

    assert _drive_step_0_5ic(proj) == 0
    assert (proj / TD.SELF_TAPEOUT_REL).is_file()
    assert not (proj / ST.NO_TEMPLATE_REL).exists(), (
        "the IP terminal's router survived beside a die's — the step's output "
        "would select two delivery paths at once")
    assert (proj / ST.REPORT_REL).is_file()
    assert (proj / TD.DECLARATION_REL).is_file()

    rc1, rc2 = _step_0_5ic_verdicts(proj)
    assert (rc1, rc2) == (0, 0)
    doc = json.loads((proj / ST.REPORT_REL).read_text())
    assert doc["check"]["verdict"] == ST.VERDICT_NOT_APPLICABLE, (
        "an absent template that was BOUGHT reads NOT_APPLICABLE, never PASS")


def test_dispatching_the_producers_cannot_buy_a_pass_on_its_own(tmp_path):
    """THE CONTROL, and it is the one that matters.

    A project where the flow ran everything it can dispatch and the DESIGN
    declared nothing must still FAIL step 0.5ic, and must fail it by the named
    rule — not by an exit code with no sentence attached. If the wiring made
    the step green on its own it would be a waiver with a different filename.
    """
    proj = tmp_path / "undeclared"
    proj.mkdir()
    assert _drive_step_0_5ic(proj) == 0, (
        "the producers must RUN for a design that declared nothing — a step "
        "that produced no record is indistinguishable from one that never ran")

    rc1, _rc2 = _step_0_5ic_verdicts(proj)
    assert rc1 == 1, (
        "wiring the producers made step 0.5ic pass for a design that stated no "
        "reason for its absent template")
    doc = json.loads((proj / ST.REPORT_REL).read_text())
    assert [r["rule"] for r in doc["check"]["refusals"]] == \
        ["NO_TEMPLATE_WITHOUT_REASON"]


@pytest.mark.parametrize("reason,why", [
    ("", "an empty reason"),
    ("no operator", "a reason below the floor"),
])
def test_a_reason_that_is_not_a_reason_still_fails(tmp_path, reason, why):
    """Between the two arms above: the declaration exists and is not enough."""
    import _tapeout_declaration as TD
    proj = tmp_path / "thin"
    proj.mkdir()
    _answers(proj, {"operator_template": {"absent_reason": reason},
                    "answers": {"deliverable": TD.DELIVERABLE_DIE}})
    assert _drive_step_0_5ic(proj) == 0
    rc1, _rc2 = _step_0_5ic_verdicts(proj)
    assert rc1 == 1, why
    doc = json.loads((proj / ST.REPORT_REL).read_text())
    assert [r["rule"] for r in doc["check"]["refusals"]] == \
        ["NO_TEMPLATE_WITHOUT_REASON"]
    # AND THE ROUTER IS STILL WRITTEN, which is not a contradiction and is
    # worth pinning so nobody "fixes" it. Which route a design is on is decided
    # by its `deliverable` answer alone; whether its absent template was BOUGHT
    # is a different question, and `submission_template_check` is the thing
    # that answers it. This gate's own docstring says as much — "THIS GATE'S
    # OWN FAIL DOES NOT STOP EITHER PATH FROM BEING SELECTED". The step-level
    # verdict is what refuses here, and it does.
    assert (proj / TD.SELF_TAPEOUT_REL).is_file()


def test_a_design_with_an_operator_template_must_still_supply_its_slot(tmp_path):
    """The OPERATOR's answer wins, and self-tape-out is not an escape from it.

    A design that stages a real template cannot reach the self-tape-out route
    by declaring `deliverable=DIE`: `_tapeout_declaration.route_of` gives the
    operator priority, no `SELF_TAPEOUT.txt` is written, and the step refuses
    because no slot was DECLARED. Declaring the slot is what clears it — the
    positive control, so "refused" cannot be read as "refuses everything".
    """
    import _tapeout_declaration as TD
    staged = tmp_path / "tmpl" / "slots"
    staged.mkdir(parents=True)
    (staged / "s1.yaml").write_text(SLOT_A)

    proj = tmp_path / "shuttle"
    proj.mkdir()
    _answers(proj, {"operator_template": {"path": str(staged.parent),
                                          "absent_reason": _REAL_REASON},
                    "answers": {"deliverable": TD.DELIVERABLE_DIE}})
    assert _drive_step_0_5ic(proj) == 0
    assert not (proj / TD.SELF_TAPEOUT_REL).exists(), (
        "a design carrying an operator's slot files was routed to the "
        "self-tape-out terminal on its own say-so")
    rc1, _rc2 = _step_0_5ic_verdicts(proj)
    assert rc1 == 1
    doc = json.loads((proj / ST.REPORT_REL).read_text())
    assert [r["rule"] for r in doc["check"]["refusals"]] == ["SLOT_NOT_DECLARED"]

    # POSITIVE CONTROL — the same tree with the slot declared.
    _answers(proj, {"operator_template": {"path": str(staged.parent),
                                          "slot": "s1",
                                          "absent_reason": _REAL_REASON},
                    "answers": {"deliverable": TD.DELIVERABLE_DIE}})
    assert _drive_step_0_5ic(proj) == 0
    rc1, rc2 = _step_0_5ic_verdicts(proj)
    assert (rc1, rc2) == (0, 0)
