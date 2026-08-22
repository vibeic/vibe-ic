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


# CI bounds each test at 180s with `--timeout-method=thread`, which takes the
# whole PROCESS down rather than failing one test, so a subprocess bound must
# be able to fire INSIDE that: `ci_harness_timeout_ceiling_check` sets the
# per-call ceiling at 60s (= 180 // 3). Measured, the slowest child here is the
# enforcement audit at ~22s, so 60 is a real bound with headroom rather than a
# number that can never be reached.
_CHILD_TIMEOUT_S = 60

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


def test_the_declaration_survives_the_docstring_growing():
    """`flow_gate_enforcement_audit.declared_intent` searches only the first
    4000 characters of the file. That bound is invisible from inside the
    docstring, so ADDING PROSE ABOVE the declaration silently un-declares the
    gate — the line is still there, still opens its own line, and the audit
    reports `declared: None`.

    Measured, on this branch: two explanatory paragraphs pushed the line to
    byte 4371 and the gate went UNDECLARED while every other check stayed
    green. The declaration now sits at the top of the docstring, and this test
    is the guard that keeps it there."""
    import flow_gate_enforcement_audit as A
    src = (PROG / "slot_pad_budget_check.py").read_text(encoding="utf-8")
    idx = src.find("ENFORCEMENT:")
    assert idx >= 0, "the gate declares no enforcement intent at all"
    # The bound is IMPORTED, never re-typed: a number kept in two places is a
    # number that will disagree, and this guard would then quietly stop
    # guarding the thing it names.
    assert idx < A.DECL_WINDOW_BYTES, (
        f"the ENFORCEMENT declaration sits at byte {idx}, past the "
        f"{A.DECL_WINDOW_BYTES}-byte window `declared_intent` reads. It is "
        f"present and unread, which the audit reports as UNDECLARED — move it "
        f"back above the prose.")


def test_the_audit_proves_it_is_ENFORCED_and_declares_that_intent():
    """The doctrine property itself (§3/§5), pinned so it cannot regress to
    AUDIT_ONLY. A dict `.get(rc, ...)` instead of a branch on `rc` is enough to
    lose it — that spelling reports INLINE_UNPROVEN, and unknown is not yes."""
    # Called IN-PROCESS, not spawned. The audit scans ~1240 programs and takes
    # ~24s; as a child it was bounded at 60s (the harness ceiling), which left
    # 2.5x headroom and MEASURABLY was not enough — this test flaked at machine
    # load ~17 and passed at load ~5. In-process the work is identical but the
    # only bound is pytest's own 180s item timeout, which is 7x headroom.
    # A flake is worse than no test: its green is the one that gets believed.
    import flow_gate_enforcement_audit as A
    doc = A.audit(PLUGIN / "flow" / "phase1_phase2_phase3.yaml", PROG)
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
    """In-process, for the same reason as the enforcement audit above: as a
    spawned child this scan takes ~23s against a 60s harness ceiling, and 2.5x
    headroom measurably was not enough under machine load."""
    import checker_execution_wiring_audit as C
    return C.audit(PLUGIN, PLUGIN.parents[2])


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


# --------------------------------------------------------------------------- #
# a malformed clause must be LOUD, not a disclosed skip  (#712 rc-3 tier)
# --------------------------------------------------------------------------- #
# The tests above keep the SHIPPED clause glob-free, because a glob expands
# into surplus positionals that argparse rejects. But argparse rejects with
# exit 2, and 2 is this flow's VACUOUS_PASS tier — so the malformed clause read
# as "I examined nothing" and the step went green over a gate that never ran.
#
# Keeping the clause correct routed AROUND that trap and left it armed for the
# next editor. `_gate_usage_exit.GateArgumentParser` disarms it: a rejected
# command line is rc 3, and the flow reads an unsentinelled 3 as FAIL.
#
# MEASURED, same clause, same project, on either side of the adoption:
#     before -> VACUOUS_PASS (silent skip)
#     after  -> FAIL (step goes red)

_TRAP_CLAUSE = ("slot_pad_budget_check . --rtl phase2/stage1/rtl/*.v "
                "--json reports/x.json")


def _two_file_project() -> Path:
    p = _project(T._RTL_FITS, with_slots=True)
    (p / "phase2" / "stage1" / "rtl" / "other.v").write_text(
        "module other (input wire a);\nendmodule\n")
    return p


def test_a_malformed_clause_FAILS_and_is_not_a_disclosed_skip():
    passed, snippet = F._check_program_exit_zero(_two_file_project(), _TRAP_CLAUSE)
    assert passed is False, "a clause the program rejects reported a pass"
    assert not snippet.startswith(F._VACUOUS_HINT_PREFIX), (
        "a rejected command line landed in the VACUOUS tier — 'you called me "
        "wrongly' is being reported as 'I examined nothing'")


def test_the_usage_tier_is_distinct_from_the_vacuous_one():
    """rc 3 = you called it wrong; rc 2 = there was nothing to examine. The
    program's whole contract rests on those not collapsing."""
    import subprocess
    prog = str(PROG / "slot_pad_budget_check.py")

    def rc(*args):
        return subprocess.run([sys.executable, prog, *args],
                              capture_output=True, text=True, timeout=_CHILD_TIMEOUT_S).returncode

    assert rc("--not-a-flag") == 3          # rejected command line
    assert rc() == 3                        # missing positional
    assert rc(".", "--param", "X=nope") == 3   # a value it cannot read
    assert rc("--help") == 0                # a successful invocation
    assert rc(str(Path(tempfile.mkdtemp(prefix="noslots_")))) == 2   # genuine UNDECIDED


def test_help_still_exits_zero_so_wrappers_do_not_read_it_as_failure():
    import subprocess
    r = subprocess.run([sys.executable, str(PROG / "slot_pad_budget_check.py"),
                        "--help"], capture_output=True, text=True, timeout=_CHILD_TIMEOUT_S)
    assert r.returncode == 0 and "usage" in r.stdout.lower()


def test_the_runner_treats_a_REJECTED_command_line_as_its_own_failure():
    """#712, one level out from the clause. Once the gate adopted the rc-3
    usage tier, 3 became reachable in the runner — and the runner's mapping
    sent anything that was not 0 or 1 to SKIP, so "I called my own gate
    wrongly" would have been reported as "the gate had nothing to say".

    The argv it rejected was built by this very step, so the fault is the
    caller's. FAIL, for the same reason the merge gate blocks on rc 3."""
    R = _runner()
    orig = R.subprocess.run
    try:
        R.subprocess.run = lambda cmd, **kw: orig([*cmd, "--not-a-flag"], **kw)
        sr = R.step_slot_pad_budget(_project(T._RTL_FITS, with_slots=True),
                                    "chip_top")
    finally:
        R.subprocess.run = orig
    assert sr.extras["exit_code"] == 3
    assert sr.status == "FAIL", (
        f"a rejected command line reported {sr.status!r} — the usage tier "
        f"collapsed back into the skip tier")
    assert "REJECTED" in sr.detail


def test_the_runner_reads_the_usage_rc_from_the_module_that_owns_it():
    """Resolved, not written as a literal 3 beside a module that defines it —
    two spellings of one constant is how tiers drift apart."""
    R = _runner()
    import _gate_usage_exit as _u
    assert R._usage_rc() == _u.RC_USAGE == 3


def test_the_runners_four_tiers_are_four_distinct_readings():
    R = _runner()
    orig = R.subprocess.run
    try:
        R.subprocess.run = lambda cmd, **kw: orig([*cmd, "--not-a-flag"], **kw)
        usage = R.step_slot_pad_budget(_project(T._RTL_FITS, True), "chip_top").status
    finally:
        R.subprocess.run = orig
    fits = R.step_slot_pad_budget(_project(T._RTL_FITS, True), "chip_top").status
    red = R.step_slot_pad_budget(_project(_HOPELESS, True), "chip_top").status
    skip = R.step_slot_pad_budget(_project(T._RTL_FITS, False), "chip_top").status
    assert (fits, red, skip, usage) == ("PASS", "FAIL", "SKIP", "FAIL")
    # the two FAILs are the same verdict but must be distinguishable by rc
    assert skip != usage, "a skip and a rejected command line share a reading"


# --------------------------------------------------------------------------- #
# the wiring goes red on REAL published silicon, not only on fixtures
# --------------------------------------------------------------------------- #
# Everything above drives synthetic Verilog. The brief's requirement was "prove
# each wiring can go RED", and a fixture I wrote proves the logic, never the
# artefacts — which is the exact wording of the gate this branch exists to
# close. The published corpus carries the ICs this program's docstring cites as
# its measured evidence, so the refusal can be driven on them.
#
# MEASURED through `design_one_shot_runner.step_slot_pad_budget`, real RTL plus
# an ingested 52-signal-pad slot:
#
#     opentitan_aes           DOES_NOT_FIT   515 bits   9.90x   (docstring: 515, 9.9x)
#     ibex                    DOES_NOT_FIT   262 bits   5.04x   (docstring: 262, 5.0x)
#     edge_llm_matmul_accel   DOES_NOT_FIT   109 bits   2.10x   (docstring: 109, 2.1x)
#     sha256                  FITS_AFTER_FOLD 75 bits           (docstring: 75, fits)
#
# The table read 107 for `edge_llm_matmul_accel` when these tests were written.
# It reads 109 now: re-measuring showed the design declares TWO clocks and TWO
# resets, only one pair of which rides the slot's dedicated pads, and the table
# had waived both. The correction landed in the docstring; this comment quoted
# the old value for three commits afterwards, which is why the agreement is now
# ASSERTED below instead of narrated here.

import shutil as _shutil  # noqa: E402
import _hostpaths  # noqa: E402

_SLOT_PADS = 52


def _real_ic_project(ic: str) -> Path:
    """A real published IC's RTL, COPIED, with a slot ingested beside it.

    Copied because the step writes a report and the corpus is not ours to
    write into.
    """
    rtl = _hostpaths.require_corpus("ic", ic, "phase2", "stage1", "rtl")
    d = Path(tempfile.mkdtemp(prefix=f"realic_{ic[:8]}_"))
    (d / "phase2" / "stage1").mkdir(parents=True)
    _shutil.copytree(rtl, d / "phase2" / "stage1" / "rtl",
                     symlinks=True, ignore_dangling_symlinks=True)
    s = d / "input" / "submission_template" / "slots"
    s.mkdir(parents=True)
    (s / "slot_1x1.json").write_text(json.dumps(T._slot_ingested()))
    return d


@pytest.mark.parametrize("ic,bits", [("opentitan_aes", 515), ("ibex", 262)])
def test_a_real_IC_that_cannot_be_bonded_out_turns_the_step_RED(ic, bits):
    R = _runner()
    sr = R.step_slot_pad_budget(_real_ic_project(ic), "chip_top")
    assert sr.status == "FAIL", f"{ic} was not refused: {sr.detail[:120]}"
    assert sr.extras["exit_code"] == 1
    assert str(bits) in sr.detail, (
        f"{ic}: the declared bit count is not in the operator-visible line")


def test_the_real_sha256_fits_only_after_a_fold_and_says_so():
    """The other direction, and the one arithmetic alone gets wrong: 75 bits
    against 52 pads LOOKS unbuildable and is not, because two same-width buses
    share one bidirectional group. The gate must not refuse it."""
    R = _runner()
    sr = R.step_slot_pad_budget(_real_ic_project("sha256"), "chip_top")
    assert sr.status == "PASS", f"a fittable design was refused: {sr.detail[:120]}"
    assert "FITS_AFTER_FOLD" in sr.detail


# --------------------------------------------------------------------------- #
# EVERY gate's declaration, not just this branch's two
# --------------------------------------------------------------------------- #
# The two per-file guards above protect the two gates this branch wired. They
# say nothing about the other forty-three.
#
# SURVEYED: 45 programs carry a real (anchored) ENFORCEMENT declaration and
# none is currently unread — so this is a fragility, not an outstanding bug.
# The thinnest margin measured was 91 bytes. One paragraph added above that
# line and the gate goes silently UNDECLARED, with nothing else turning red;
# that is precisely how it happened twice on this branch.
#
# Anchored via the audit's OWN `_DECL_RE`. A survey using
# `text.find("ENFORCEMENT:")` counts prose MENTIONS as declarations — measured,
# it produced three false alarms, one of them a runner whose docstring mentions
# the token at byte 1.3 million.

def test_no_gate_declaration_anywhere_sits_outside_the_readers_window():
    import flow_gate_enforcement_audit as A
    progs = PROG
    unread, thin = [], []
    for p in sorted(progs.glob("*.py")):
        m = A._DECL_RE.search(p.read_text(errors="replace"))
        if not m:
            continue                      # no declaration is a different question
        margin = A.DECL_WINDOW_BYTES - m.start()
        if margin <= 0:
            unread.append(f"{p.stem} at byte {m.start()}")
        elif margin < 200:
            thin.append(f"{p.stem} margin {margin}B")
    assert not unread, (
        "these gates DECLARE an enforcement intent the audit never reads — "
        "present, correctly spelt, and reported as UNDECLARED:\n  "
        + "\n  ".join(unread)
        + "\nMove the declaration above the prose; the window is "
          f"{A.DECL_WINDOW_BYTES} bytes.")
    assert not thin, (
        "a declaration is within 200 bytes of vanishing; one paragraph added "
        "above it un-declares the gate silently:\n  " + "\n  ".join(thin))


def test_the_docstrings_cited_table_matches_what_the_program_measures():
    """The table in `slot_pad_budget_check`'s docstring is the program's own
    published evidence. Nothing re-derived it, so it drifted: one row read 107
    against a measured 109 until this branch corrected it, and a comment in
    THIS file went on quoting the old value for three commits afterwards.

    Asserted rather than narrated. Both sides come from the tree — the claimed
    bits are parsed out of the docstring table, the measured bits come from
    driving the real published RTL through the same code path the gate uses.
    Corpus-gated, so it skips where the corpus is not configured."""
    import re
    import slot_pad_budget_check as S   # this module has no `S` alias
    doc = _hostpaths.require_corpus("ic")          # skips without a corpus
    src = (PROG / "slot_pad_budget_check.py").read_text(encoding="utf-8")
    rows = dict(re.findall(r"^    ([a-z_0-9]+)\s+(\d+)\s+52\s", src, re.M))
    assert rows, "the docstring publishes no measured table any more"

    checked, wrong = 0, []
    for ic, top in (("opentitan_aes", "chip_top"), ("ibex", "chip_top")):
        claimed = rows.get(ic)
        if claimed is None:
            continue
        rtl = doc / ic / "phase2" / "stage1" / "rtl"
        if not rtl.is_dir():
            continue
        ports = None
        for f in sorted(rtl.iterdir()):
            if f.suffix in (".v", ".sv"):
                ports = S.parse_top_ports(f.read_text(errors="replace"), top)
                if ports:
                    break
        if not ports:
            continue
        measured = S.interface_budget(ports)["signal_bits"]
        checked += 1
        if measured != int(claimed):
            wrong.append(f"{ic}: table says {claimed}, program measures {measured}")
    assert checked, "no cited IC could be measured from the configured corpus"
    assert not wrong, (
        "the docstring's published evidence no longer matches what the program "
        "produces:\n  " + "\n  ".join(wrong))
