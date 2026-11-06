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

import test_slot_pad_budget_check as T                 # noqa: E402  slot fixture
import _watchdog                                      # noqa: E402


def _supervised(cmd, **kw):
    """`subprocess.run(cmd, capture_output=True, text=True, check=False)` with
    the wall-clock budget REPLACED by forward-progress supervision.

    These call sites used to carry a fixed `timeout=`. That number is not a
    property of the subject — it is a guess about a HOST — and when the guess is
    wrong on a loaded machine `TimeoutExpired` propagates out of the test and is
    recorded as the SUBJECT being broken. The verdict is then manufactured by
    the machine rather than measured on the program; the owner hit exactly that
    on a module nobody had changed.

    `_watchdog.run_host_supervised` bounds NO FORWARD PROGRESS instead — CPU and
    I/O summed over the child's whole /proc tree, plus the growth of its
    captured output — so a child that is merely slow runs to completion however
    long that legitimately takes, while one that is genuinely hung is still
    killed. A kill arrives as rc `_watchdog.RC_STALLED` with WATCHDOG_STALLED on
    stderr: a distinct code none of these subjects produces itself, so a hang
    can never be misread as an ordinary non-zero exit."""
    res = _watchdog.run_host_supervised(cmd, **kw)
    return _watchdog.completed_process(cmd, res)

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


def _project(rtl, with_slots: bool, route: str = "NO_TEMPLATE.txt") -> Path:
    """A project at step 2, with or without an ingested operator slot.

    `route` IS THE CELL PATH, and leaving it out was the defect this fixture
    carried. Step 0.5ic writes exactly ONE router file — a slot list, or
    `NO_TEMPLATE.txt`, or `SELF_TAPEOUT.txt` — so "no slots" has two owners
    that `slot_pad_budget_check` has told apart since v1.15.45:

        slots absent AND a router declaration present -> the design DECLARED
            no operator slot exists. NOT_APPLICABLE / DESIGN_DECLARED_NA,
            which is the disclosed-skip tier.
        slots absent AND no router file at all        -> step 0.5ic has not
            run. UNDECIDED / BLOCKED_BY_UPSTREAM, which #1978 moved OUT of
            the skip tier because it is work outstanding, not a design fact.

    This fixture wrote neither, so a case whose docstring said "no operator,
    so no slot" was actually modelling "the upstream step never ran" and
    followed the second owner into INCOMPLETE. Passing the route makes the
    cell-path cases model the path they name; `route=None` keeps the other
    owner reachable, and `test_no_slots_and_no_route_is_the_OTHER_owner`
    pins it so this fixture repair can never quietly become a relabel.
    """
    # mkdtemp, not tmp_path: a pytest tmp_path carries a newline under the EDA
    # container image and that breaks any tool handed the path.
    d = Path(tempfile.mkdtemp(prefix="wire1347_"))
    if with_slots:
        s = d / "input" / "submission_template" / "slots"
        s.mkdir(parents=True)
        (s / "slot_1x1.json").write_text(json.dumps(T._slot_ingested()))
    elif route is not None:
        t = d / "input" / "submission_template"
        t.mkdir(parents=True)
        (t / route).write_text(
            "no operator template applies to this design\n")
    if rtl is not None:
        r = d / "phase2" / "stage1" / "rtl"
        r.mkdir(parents=True)
        (r / "chip_top.v").write_text(rtl)
    return d




# No per-call wall-clock bound: see `_supervised` below. A number chosen from
# "the slowest child here is ~22s" is a reading of this HOST on the day it was
# taken, and when a busier host exceeds it the resulting `TimeoutExpired` is
# recorded as `slot_pad_budget_check` being broken.

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
    # R-0915-85 — rc 2 is "this design declares no slot template", which is a
    # claim about the INPUT: NOT_APPLICABLE, naming the declaration.
    _row = R.step_slot_pad_budget(no_slot, "chip_top")
    assert _row.status == "NOT_APPLICABLE", (_row.status, _row.detail)
    assert _row.declared_by, "an N/A must name the line that makes it N/A"


def test_the_skip_carries_the_programs_own_reason_not_a_silence():
    """§6 degrade loudly: a decline that printed nothing reads downstream as
    'nothing needed doing'."""
    R = _runner()
    # BOTH owners of "no slots": the design-declared route and the un-run
    # upstream. Each must say WHICH it is — a shared silence would be the
    # exact conflation v1.15.45 split apart.
    declared = R.step_slot_pad_budget(
        _project(T._RTL_FITS, with_slots=False), "chip_top")
    assert declared.status == "NOT_APPLICABLE"
    assert "NOT_APPLICABLE" in declared.detail
    assert "no operator template" in declared.detail
    unrun = R.step_slot_pad_budget(
        _project(T._RTL_FITS, with_slots=False, route=None), "chip_top")
    assert "UNDECIDED" in unrun.detail and "slots" in unrun.detail
    assert declared.detail != unrun.detail


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

    # A module reaches a process through `subprocess`, through `_pr`
    # (`_progress_run`, the progress-supervised drop-in) or through both.
    # Substituting on only one leaves the real launcher answering the
    # question this test is asking about a fake one, and the test then
    # passes or fails for a reason that has nothing to do with its subject.
    for _launcher in (getattr(R, "subprocess", None),
                      getattr(R, "_pr", None)):
        if _launcher is not None:
            monkeypatch.setattr(_launcher, "run", _boom)
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




def test_the_conditional_pass_is_DISCLOSED_and_not_a_bare_green():
    """The operator-visible line must name the verdict, not just the status —
    otherwise the condition is lost at exactly the moment somebody reads
    'PASS' and stops looking."""
    R = _runner()
    sr = R.step_slot_pad_budget(_foldable_project(), "chip_top")
    assert "FITS_AFTER_FOLD" in sr.detail, (
        f"the step passed without naming the condition: {sr.detail!r}")








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




def test_the_usage_tier_is_distinct_from_the_vacuous_one():
    """rc 3 = you called it wrong; rc 2 = there was nothing to examine. The
    program's whole contract rests on those not collapsing."""
    prog = str(PROG / "slot_pad_budget_check.py")

    def rc(*args):
        return _supervised([sys.executable, prog, *args]).returncode

    assert rc("--not-a-flag") == 3          # rejected command line
    assert rc() == 3                        # missing positional
    assert rc(".", "--param", "X=nope") == 3   # a value it cannot read
    assert rc("--help") == 0                # a successful invocation
    assert rc(str(Path(tempfile.mkdtemp(prefix="noslots_")))) == 2   # genuine UNDECIDED


def test_help_still_exits_zero_so_wrappers_do_not_read_it_as_failure():
    r = _supervised([sys.executable, str(PROG / "slot_pad_budget_check.py"),
                     "--help"])
    assert r.returncode == 0 and "usage" in r.stdout.lower()


def test_the_runner_treats_a_REJECTED_command_line_as_its_own_failure():
    """#712, one level out from the clause. Once the gate adopted the rc-3
    usage tier, 3 became reachable in the runner — and the runner's mapping
    sent anything that was not 0 or 1 to SKIP, so "I called my own gate
    wrongly" would have been reported as "the gate had nothing to say".

    The argv it rejected was built by this very step, so the fault is the
    caller's. FAIL, for the same reason the merge gate blocks on rc 3."""
    R = _runner()
    # The launcher moved from `subprocess` to `_pr`; see the note at the
    # other substitution sites in this file.
    orig = R._pr.run
    try:
        R._pr.run = lambda cmd, **kw: orig([*cmd, "--not-a-flag"], **kw)
        sr = R.step_slot_pad_budget(_project(T._RTL_FITS, with_slots=True),
                                    "chip_top")
    finally:
        R._pr.run = orig
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
    # The launcher moved from `subprocess` to `_pr`; see the note at the other
    # substitution sites in this file.
    orig = R._pr.run
    try:
        R._pr.run = lambda cmd, **kw: orig([*cmd, "--not-a-flag"], **kw)
        usage = R.step_slot_pad_budget(_project(T._RTL_FITS, True), "chip_top").status
    finally:
        R._pr.run = orig
    fits = R.step_slot_pad_budget(_project(T._RTL_FITS, True), "chip_top").status
    red = R.step_slot_pad_budget(_project(_HOPELESS, True), "chip_top").status
    skip = R.step_slot_pad_budget(_project(T._RTL_FITS, False), "chip_top").status
    # R-0915-85 — FOUR READINGS, and they are still four. The skip is
    # NOT_APPLICABLE (the input declares no slot template) and the rejected
    # command line is FAIL (this step's own bug, #712) — the collision the rc-3
    # tier exists to end is still ended, and the assertion below still says so.
    assert (fits, red, skip, usage) == ("PASS", "FAIL", "NOT_APPLICABLE",
                                        "FAIL")
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
#
# AND SCOPED TO THE PROGRAM'S HEADER, via the audit's own
# `program_declaration_offset`. Anchoring alone was not enough: a `ENFORCEMENT:
# blocking` line inside a NESTED function's docstring is a note about that
# step, and searching the whole file reads it as the program's declaration.
# MEASURED at 2010063c1 — `design_one_shot_runner.py`, one anchored match, at
# byte 361904, inside `step_step4_functional_evidence` in a 950 KB file. This
# survey named it "present, correctly spelt and unread" and advised moving it
# above the prose, which would have made a 44-step runner declare, as a whole
# program, something one of its steps says. The same measurement found the one
# REAL instance the anchored survey was written to catch:
# `on_pass_review_declared_command_runs_check` declared blocking at byte 10336,
# 6336 bytes past the reader — repaired at the source, in the same change as
# this scope.
#
# The header and the reader's 4000-byte window agree on all 99 programs that
# declare (measured), so this is one rule and not a second number.



@pytest.mark.consistency
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
