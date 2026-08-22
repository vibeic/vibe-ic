"""slot_pad_budget_check is wired where its verdict can stop a build.

vibe-ic#1347. The program landed with a unit test and nothing else. Nothing
invoked it anywhere it could block, so it produced no verdict and the tree
looked identical whether it passed or failed -- which is exactly the state
`checker_execution_wiring_audit` calls "a fixture the author wrote proves the
logic, never the artefacts".

These tests do not assert that a line exists in a YAML file. A declaration
that cannot be driven to red is the same paper wiring in a different place, so
each tier below is driven through `flow_compliance_check`'s OWN clause runner
and the resulting verdict tier is asserted.

THE FOUR TIERS ARE NOT THREE. `program_exit_zero` folds rc 2 into a passing
result, so "this design cannot be bonded out" (rc 1) and "there was nothing to
ask" (rc 2) MUST stay distinguishable, or the gate's refusal becomes a skip.
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
PLUGIN = PROG.parent
sys.path.insert(0, str(PROG))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow_compliance_check as F                      # noqa: E402
import test_slot_pad_budget_check as T                 # noqa: E402  slot fixture

yaml = pytest.importorskip("yaml")

_FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

# An interface no purchasable slot in the fixture can bond out.
_HOPELESS = ("module chip_top (input wire clk, input wire rst_ni,\n"
             "  input wire [127:0] a, input wire [255:0] k,\n"
             "  output wire [127:0] y, output wire alert);\nendmodule\n")


def _step2() -> dict:
    doc = yaml.safe_load(_FLOW.read_text(encoding="utf-8"))
    return [s for s in doc["steps"] if str(s["id"]) == "2"][0]


def _clause() -> str:
    """The BLOCKING clause that invokes the gate, or fail saying it is absent."""
    for c in _step2().get("gate", {}).get("all_of", []):
        if isinstance(c, dict) and "slot_pad_budget_check" in str(c):
            assert "program_exit_zero" in c, (
                "slot_pad_budget_check is wired, but not in a slot that can "
                f"fail the step: {sorted(c)}")
            return c["program_exit_zero"]
    raise AssertionError(
        "no gate clause on flow step 2 invokes slot_pad_budget_check — the "
        "program is unwired and its verdict cannot reach any build")


def _project(rtl, with_slots: bool) -> Path:
    # mkdtemp, not tmp_path: a pytest tmp_path carries a newline under the EDA
    # container image and that breaks any tool handed the path.
    d = Path(tempfile.mkdtemp(prefix="wire1347_"))
    if with_slots:
        s = d / "input" / "submission_template" / "slots"
        s.mkdir(parents=True)
        (s / "slot_1x1.json").write_text(json.dumps(T._slot_ingested()))
    if rtl is not None:
        r = d / "phase2" / "stage1" / "rtl"
        r.mkdir(parents=True)
        (r / "chip_top.v").write_text(rtl)
    return d


def _drive(rtl, with_slots: bool):
    """`(passed, vacuous, report)` from the real clause runner."""
    p = _project(rtl, with_slots)
    passed, snippet = F._check_program_exit_zero(p, _clause())
    rep_p = p / "reports" / "phase2" / "gates" / "slot_pad_budget.json"
    rep = json.loads(rep_p.read_text()) if rep_p.is_file() else None
    return passed, snippet.startswith(F._VACUOUS_HINT_PREFIX), rep


# --------------------------------------------------------------------------- #
# the wiring exists, and it is in a slot that can fail
# --------------------------------------------------------------------------- #
def test_step_2_blocks_on_the_step_that_ingests_the_slots():
    """Without the 0.5ic edge the graph permits lint to run before the slot
    geometry exists, and the gate would disclose a skip on a chip-path design
    that has an operator."""
    assert "0.5ic" in [str(b) for b in _step2()["blocks_on"]]


def test_the_clause_carries_no_glob():
    """`_resolve_program_cmd` expands a clause glob into separate argv tokens;
    the surplus arrives as extra positionals and argparse exits 2 -- which is
    the VACUOUS_PASS tier. A glob here would make the gate skip on every
    multi-file design and the skip would look like the honest one."""
    assert "*" not in _clause()


# --------------------------------------------------------------------------- #
# and it can actually go red
# --------------------------------------------------------------------------- #
def test_an_unbondable_interface_turns_the_step_RED():
    passed, vacuous, rep = _drive(_HOPELESS, with_slots=True)
    assert (passed, vacuous) == (False, False)
    assert rep["verdict"] == "DOES_NOT_FIT" and rep["rc"] == 1


def test_an_interface_that_fits_passes():
    passed, vacuous, rep = _drive(T._RTL_FITS, with_slots=True)
    assert (passed, vacuous) == (True, False)
    assert rep["verdict"] == "FITS"


def test_the_cell_path_is_a_DISCLOSED_skip_never_a_silent_pass():
    """No operator, so no slot: there is no question to ask. It must land in
    the vacuous tier, where a reader can see it, and not in plain PASS."""
    passed, vacuous, rep = _drive(T._RTL_FITS, with_slots=False)
    assert (passed, vacuous) == (True, True)
    assert rep["verdict"] == "UNDECIDED"


def test_refusal_and_skip_do_not_share_a_tier():
    """The one property the fold of rc 2 into PASS could destroy."""
    red, _, red_rep = _drive(_HOPELESS, with_slots=True)
    skip_passed, skip_vac, skip_rep = _drive(T._RTL_FITS, with_slots=False)
    assert red is False and skip_passed is True and skip_vac is True
    assert red_rep["rc"] == 1 and skip_rep["rc"] == 2


def test_the_program_discovers_step_1_rtl_without_being_handed_a_glob():
    """The clause names no RTL at all, so discovery is load-bearing: if it
    regressed, every tier above would collapse into the skip."""
    import slot_pad_budget_check as S
    p = _project(_HOPELESS, with_slots=True)
    found = S._discover_rtl(str(p))
    assert [Path(f).name for f in found] == ["chip_top.v"]
    assert S._discover_rtl(str(Path(tempfile.mkdtemp(prefix="empty1347_")))) == []


# --------------------------------------------------------------------------- #
# the YAML clause alone CANNOT block — #306
# --------------------------------------------------------------------------- #
# `flow_gate_enforcement_audit`'s founding measurement: the step runners execute
# the flow's `program_exit_zero` gates NOWHERE. They are evaluated only by
# `flow_compliance_check`, which the runner invokes as `final_audit` — the LAST
# step, after every artefact has been written. `cts_quality_check` FAILed on the
# same cell across three plugin versions while the flow shipped a 181 MB
# routed.def every time.
#
# So the clause above is where the verdict is DECLARED, and the runner spawn
# below is what makes it able to refuse. Both are required; neither is enough.

def _runner():
    import design_one_shot_runner as R
    return R


def test_the_runner_spawns_it_and_the_exit_status_decides_the_step():
    """PROVE-BY-RUN, not by reading: drive the runner step itself."""
    R = _runner()
    hopeless = _project(_HOPELESS, with_slots=True)
    fits = _project(T._RTL_FITS, with_slots=True)
    no_slot = _project(T._RTL_FITS, with_slots=False)
    assert R.step_slot_pad_budget(hopeless, "chip_top").status == "FAIL"
    assert R.step_slot_pad_budget(fits, "chip_top").status == "PASS"
    assert R.step_slot_pad_budget(no_slot, "chip_top").status == "SKIP"


def test_the_skip_carries_the_programs_own_reason_not_a_silence():
    """§6 degrade loudly: a decline that printed nothing reads downstream as
    'nothing needed doing'."""
    R = _runner()
    sr = R.step_slot_pad_budget(_project(T._RTL_FITS, with_slots=False),
                                "chip_top")
    assert sr.status == "SKIP"
    assert "UNDECIDED" in sr.detail and "slots" in sr.detail


def test_the_runner_passes_its_own_top_name_not_the_programs_default():
    """A design whose top is not `chip_top` would otherwise answer UNDECIDED
    and disclose a skip for a question that was perfectly askable."""
    R = _runner()
    p = _project(_HOPELESS.replace("chip_top", "my_soc_top"), with_slots=True)
    assert R.step_slot_pad_budget(p, "my_soc_top").status == "FAIL"


def test_the_step_is_APPENDED_TO_THE_PLAN_not_merely_defined():
    """A defined-but-uncalled step is the #884 shape exactly: it looks wired to
    a reader and to the wiring audit (the module still NAMES the program, so
    PROG is still credited), and it runs never.

    Found by mutation: deleting the `plan.append(...)` line left every test in
    this module green, because the previous assertion was the substring
    `step_slot_pad_budget(project` — which the DEFINITION
    `def step_slot_pad_budget(project: Path, ...)` satisfies all by itself. So
    the call is resolved structurally, from the plan-building appends."""
    import ast
    src = (PROG / "design_one_shot_runner.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    appended = set()
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "append"
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "plan"):
            for a in n.args:
                if isinstance(a, ast.Call):
                    try:
                        appended.add(ast.unparse(a.func))
                    except Exception:
                        pass
    assert "step_slot_pad_budget" in appended, (
        "design_one_shot_runner defines the step but never appends it to the "
        f"plan, so it never runs. plan.append targets: {sorted(appended)[:8]}...")


def test_the_audit_proves_it_is_ENFORCED_and_declares_that_intent():
    """The doctrine property itself (§3/§5), pinned so it cannot regress to
    AUDIT_ONLY. A dict `.get(rc, ...)` instead of a branch on `rc` is enough to
    lose it — that spelling reports INLINE_UNPROVEN, and unknown is not yes."""
    import subprocess
    import tempfile as _tf
    out = Path(_tf.mkdtemp(prefix="fga1347_")) / "fga.json"
    subprocess.run([sys.executable,
                    str(PROG / "flow_gate_enforcement_audit.py"),
                    "--json", str(out)],
                   capture_output=True, text=True, timeout=600)
    doc = json.loads(out.read_text())
    mine = [g for g in doc["gates"] if g.get("gate") == "slot_pad_budget_check"]
    assert mine, "the audit does not see the gate at all"
    assert mine[0]["enforcement"] == "ENFORCED", mine[0]
    assert mine[0]["wiring"] == "INLINE_BLOCKING", mine[0]
    assert mine[0]["declared"] == "blocking", mine[0]


# --------------------------------------------------------------------------- #
# the last link: the CLAUSE becomes a STEP VERDICT
# --------------------------------------------------------------------------- #
# The tests above prove the clause runner returns False and the runner step
# returns FAIL. Neither of those is the same statement as "step 2 goes red",
# and the gap between "the check said no" and "the step said no" is precisely
# where #306 lived. So this drives `flow_compliance_check.check_step` itself.
#
# The step is ISOLATED to this one clause on purpose: step 2 carries thirteen
# other clauses, and a FAIL from any of them would make this test pass while
# proving nothing about the gate it claims to be about.

def _isolated_step2() -> dict:
    doc = yaml.safe_load(_FLOW.read_text(encoding="utf-8"))
    step = [s for s in doc["steps"] if str(s["id"]) == "2"][0]
    mine = [c for c in step["gate"]["all_of"]
            if isinstance(c, dict) and "slot_pad_budget_check" in str(c)]
    assert len(mine) == 1, f"expected exactly one clause, got {mine}"
    out = dict(step)
    out["gate"] = {"all_of": mine}
    out["required_outputs"] = []          # not what is under test here
    return out


def _step_status(rtl, with_slots: bool) -> str:
    return F.check_step(_project(rtl, with_slots), _isolated_step2(), {}).status


def test_an_unbondable_interface_makes_step_2_itself_go_FAIL():
    assert _step_status(_HOPELESS, True) == "FAIL"


def test_a_fitting_interface_leaves_step_2_PASS():
    assert _step_status(T._RTL_FITS, True) == "PASS"


def test_the_cell_path_lands_in_VACUOUS_PASS_not_plain_PASS():
    """The disclosed tier is a DIFFERENT verdict from a clean one, which is
    what keeps 'there was nothing to ask' readable as itself rather than as
    'asked and fine'."""
    assert _step_status(T._RTL_FITS, False) == "VACUOUS_PASS"


def test_the_three_step_verdicts_are_three_distinct_values():
    """The property the whole wiring rests on: a refusal, a clean pass and a
    disclosed skip must never collapse into one another."""
    seen = {_step_status(_HOPELESS, True),
            _step_status(T._RTL_FITS, True),
            _step_status(T._RTL_FITS, False)}
    assert len(seen) == 3, seen


# --------------------------------------------------------------------------- #
# the gate this branch exists to close, asked locally
# --------------------------------------------------------------------------- #
# `checker_execution_wiring_audit` is the gate that named this program as one
# nothing but its own test ran. The tests above pin the flow clause and the
# runner spawn INDIVIDUALLY; this pins the audit's own verdict about the
# program, which is the thing that was actually red.
#
# `machine_runners`, NOT absence from `test_only`, and the distinction is the
# whole point: the audit counts a SKILL document as a runner and says in its
# own docstring that this is the weakest form there is. Adding one line to a
# skill would empty `test_only` and satisfy nothing — a skill runs only if an
# agent remembers to. FLOW / PROG / CI / TOOLS fire without anyone choosing.

def _wiring_audit_report() -> dict:
    import subprocess
    import tempfile as _tf
    out = Path(_tf.mkdtemp(prefix="cew1347_")) / "cew.json"
    subprocess.run([sys.executable,
                    str(PROG / "checker_execution_wiring_audit.py"),
                    "--json", str(out)],
                   capture_output=True, text=True, timeout=600)
    return json.loads(out.read_text())


def test_the_wiring_audit_credits_a_machine_runner_not_a_skill_mention():
    rep = _wiring_audit_report()
    runners = rep["machine_runners"].get("slot_pad_budget_check.py")
    assert runners, (
        "checker_execution_wiring_audit credits NO machine runner for "
        "slot_pad_budget_check — a skill mention does not count, because it "
        "runs only if an agent remembers to")
    # Both of this branch's wirings, and they are different venues on purpose.
    assert "FLOW" in runners, f"the flow clause is not credited: {runners}"
    assert "PROG" in runners, f"the runner spawn is not credited: {runners}"


def test_it_is_no_longer_in_the_audits_test_only_population():
    rep = _wiring_audit_report()
    assert "slot_pad_budget_check.py" not in (rep.get("test_only") or [])


# --------------------------------------------------------------------------- #
# the runner step's failure path, and where it writes
# --------------------------------------------------------------------------- #
# Round-4 mutation found three of these unguarded. Two are about a report
# landing where its reader looks; the first is the doctrine one.

def test_a_gate_that_COULD_NOT_RUN_is_FAIL_never_PASS(monkeypatch):
    """"I could not look" and "I looked and it was fine" must never produce
    the same verdict. Mutating this arm to PASS left every test green, which
    means the runner could have lost the ability to run this gate at all and
    reported a clean step forever."""
    R = _runner()

    def _boom(*a, **kw):
        raise OSError("no such executable")

    monkeypatch.setattr(R.subprocess, "run", _boom)
    sr = R.step_slot_pad_budget(_project(_HOPELESS, with_slots=True), "chip_top")
    assert sr.status == "FAIL", (
        f"a gate that could not run reported {sr.status!r} — a check that "
        f"could not look is not a clean check")
    assert "could not run" in sr.detail


def test_the_runner_writes_its_report_INSIDE_THE_PROJECT():
    """Without `cwd=project` the relative `--json` path resolves against the
    caller's working directory, so the record lands outside the project and
    the reader finds nothing. Measured during the mutation run: it wrote into
    the repository root, where only this repo's own suite_write_guard noticed."""
    R = _runner()
    p = _project(_HOPELESS, with_slots=True)
    before = {q for q in Path.cwd().glob("reports")}
    sr = R.step_slot_pad_budget(p, "chip_top")
    assert (p / "reports" / "phase2" / "gates" / "slot_pad_budget.json").is_file(), \
        "the step's record is not inside the project it judged"
    assert {q for q in Path.cwd().glob("reports")} == before, \
        "the step wrote a report outside the project"
    assert sr.output_files and sr.output_files[0].startswith("reports/")


def test_the_runner_and_the_flow_clause_declare_THE_SAME_report_path():
    """Two producers, one path. If they drift, the flow's re-check writes
    somewhere the runner's reader never looks, and both look fine alone."""
    src = (PROG / "design_one_shot_runner.py").read_text(encoding="utf-8")
    import re
    m = re.search(r'out_rel = "([^"]+slot_pad_budget[^"]*)"', src)
    assert m, "the runner declares no report path for this step"
    assert m.group(1) in _clause(), (
        f"runner writes {m.group(1)!r}, flow clause says {_clause()!r}")


# --------------------------------------------------------------------------- #
# the fourth verdict: a PASS that is CONDITIONAL on a human decision
# --------------------------------------------------------------------------- #
# The program has four verdicts and everything above exercises three. The one
# left out is the subtle one, and it is the only PASS that does not mean what a
# PASS normally means.
#
# FITS_AFTER_FOLD is rc 0, so the step is green — correctly: refusing it would
# block a design a competent bond-out fits. But it means "fits ONLY IF a named
# fold is taken", and the program says in the same breath that whether that
# fold is safe is a PROTOCOL fact it will not decide. So the green must carry
# the condition with it. A bare PASS here would read as "this bonds out" when
# what was measured is "this bonds out if somebody folds two buses and nobody
# has checked that they are never live together".

def _foldable_project() -> Path:
    return _project(T._RTL_FOLDABLE, with_slots=True)


def test_a_design_that_fits_only_after_folding_is_not_BLOCKED():
    """The direction that matters first: a legitimate design must not be
    refused by arithmetic that a real pin-out would have solved."""
    R = _runner()
    assert R.step_slot_pad_budget(_foldable_project(), "chip_top").status == "PASS"
    passed, vacuous, rep = _drive(T._RTL_FOLDABLE, with_slots=True)
    assert (passed, vacuous) == (True, False)
    assert rep["verdict"] == "FITS_AFTER_FOLD"


def test_the_conditional_pass_is_DISCLOSED_and_not_a_bare_green():
    """The operator-visible line must name the verdict, not just the status —
    otherwise the condition is lost at exactly the moment somebody reads
    'PASS' and stops looking."""
    R = _runner()
    sr = R.step_slot_pad_budget(_foldable_project(), "chip_top")
    assert "FITS_AFTER_FOLD" in sr.detail, (
        f"the step passed without naming the condition: {sr.detail!r}")


def test_the_record_names_the_fold_and_refuses_to_call_it_safe():
    """The fold is an INVITATION to a human decision, recorded with the
    signals that could drive it. If the gate ever claimed the fold was safe it
    would be inventing a pin-out."""
    _, _, rep = _drive(T._RTL_FOLDABLE, with_slots=True)
    cands = rep["fold_candidates"]
    assert cands, "a FITS_AFTER_FOLD verdict that names no fold is unactionable"
    assert cands[0]["input_bus"] and cands[0]["output_bus"] and cands[0]["width"]
    assert "NOT DECIDED HERE" in cands[0]["safety"]
    assert any("protocol-safe" in s for s in rep["does_not_decide"])


def test_the_fold_does_not_rewrite_the_declared_number():
    """The DECLARED count is what the design actually asks for; the folded one
    is a hypothetical. Reporting only the second would launder a decision
    nobody took into a measurement."""
    _, _, rep = _drive(T._RTL_FOLDABLE, with_slots=True)
    assert rep["declared_signal_bits"] == 75
    assert rep["signal_bits_after_folding_every_candidate"] == 43
    assert rep["declared_signal_bits"] != rep["signal_bits_after_folding_every_candidate"]


def test_all_four_verdicts_are_reachable_through_the_wiring():
    """Coverage stated as an assertion rather than assumed from the tests that
    happen to exist: every verdict the program can return must have been driven
    through the clause at least once."""
    seen = set()
    for rtl, slots in ((_HOPELESS, True), (T._RTL_FITS, True),
                       (T._RTL_FOLDABLE, True), (T._RTL_FITS, False)):
        seen.add(_drive(rtl, slots)[2]["verdict"])
    assert seen == {"DOES_NOT_FIT", "FITS", "FITS_AFTER_FOLD", "UNDECIDED"}, seen
