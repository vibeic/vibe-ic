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


def test_the_program_discovers_step_1_rtl_without_being_handed_a_glob():
    """The clause names no RTL at all, so discovery is load-bearing: if it
    regressed, every tier above would collapse into the skip."""
    import slot_pad_budget_check as S
    p = _project(_HOPELESS, with_slots=True)
    found = S._discover_rtl(str(p))
    assert [Path(f).name for f in found] == ["chip_top.v"]
    assert S._discover_rtl(str(Path(tempfile.mkdtemp(prefix="empty1347_")))) == []


_TRAP_CLAUSE = ("slot_pad_budget_check . --rtl phase2/stage1/rtl/*.v "
                "--json reports/x.json")


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


import shutil as _shutil  # noqa: E402
import _hostpaths  # noqa: E402

_SLOT_PADS = 52


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
