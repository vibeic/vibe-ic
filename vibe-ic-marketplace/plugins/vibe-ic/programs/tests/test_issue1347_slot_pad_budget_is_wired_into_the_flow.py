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


def test_the_step_is_in_the_runners_plan():
    import ast
    src = (PROG / "design_one_shot_runner.py").read_text(encoding="utf-8")
    assert "step_slot_pad_budget(project" in src, \
        "the runner defines the step but never puts it in the plan"
    ast.parse(src)


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
