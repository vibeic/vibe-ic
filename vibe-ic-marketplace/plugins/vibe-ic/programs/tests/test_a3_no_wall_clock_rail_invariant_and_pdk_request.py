"""Three invariants the A3 netlist producer did not hold (czdsm3, 2026-09-07).

Each was MEASURED on 8HD-6 against `4afcf68727bf` (v1.18.36), on the pinned
`vibeic-eda` image, with a real second-order delta-sigma modulator and a real
LDO, and each test below is the smallest thing that goes red on the tree that
carried the defect and green on the tree that does not.

J1 — A WALL CLOCK ON THE SIMULATOR, LANDING ON THE WRONG STATUS.
    `verify_with_ngspice` ran `docker exec ... ngspice` under a CLIENT-side
    `subprocess.run(timeout=900)`. `TimeoutExpired` is a `SubprocessError`, so
    the expiry fell into the handler that answers `NOT_VERIFIED_NO_SIMULATOR`
    — the ONE status that means the binary is not there. MEASURED: the block's
    testbench takes 558 s at load ~26 and was reported at 890 s by another
    lane, i.e. the verdict was a coin toss against a 15-minute clock, and
    losing the toss said a simulator that RAN was ABSENT. With the clock
    lowered to 30 s the same tree reproduces it every time, and leaves the
    simulator running inside the container as an orphan the client can no
    longer see. vibe-ic#2051 removed this clock everywhere else.

D1 — NOBODY EVER READ THE OPERATING POINT.
    The emitted testbench measures the block's OUTPUT, and the operating-point
    table `ngspice -b` prints immediately above those measurements was read by
    no gate in this flow. A converged run whose operating point puts the
    block's own nodes outside its own supply rails has not verified anything:
    every measurement in the same log was computed from a solution the circuit
    does not hold. `dc_op_rail_excursions` reads that table and ADDS NO CARD,
    which is why every emitted deck keeps its content sha byte for byte.

    The ruling that commissioned this also asked for a structural refusal of
    "a floating node with fewer than two DC paths". It is NOT here, and
    deliberately: MEASURED against the shipped suite, both the >=2 form and the
    ==1 form refuse the switched-capacitor summing node and the Miller-
    compensated drain, which four shipped tests exist to protect —
    `test_round17_modulator_interface.
    test_a_summing_node_reached_only_through_capacitors_is_not_refused`,
    `test_analog_a3_netlist_emit.
    test_a_capacitor_terminated_internal_net_is_NOT_rejected`, and both rows of
    `test_analog_a2_delta_sigma_spec_bound.
    test_a_two_terminal_device_is_a_connection`. Those are the defining shapes
    of the analog blocks this flow emits, and no assertion of theirs was
    weakened to make room for the rule.

N1 — AN EXPLICIT `--pdk` THE BLOCK DOES NOT BIND WAS SILENTLY DROPPED.
    MEASURED: one project declaring `sg13g2`, emitted twice — `--pdk sg13g2`
    and `--pdk sky130` — produced netlists with the SAME content sha, and the
    requested family appeared nowhere in the JSON report. rc 0, "EMITTED".

Two open PDK family names appear in the N1 tests as REQUEST STRINGS only: the
predicate under test compares two selectors and binds nothing.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import _plugin_tree  # noqa: F401 — puts programs/ on sys.path
import analog_a3_netlist_emit as A3

PROGRAMS = Path(_plugin_tree.plugin_path("programs"))


# ═══ J1 — the simulator runs under NO wall clock ═══════════════════════════

def _verify_fn_source() -> str:
    return inspect.getsource(A3.verify_with_ngspice)


def test_j1_the_simulator_call_carries_no_wall_clock():
    """NOT a grep for the literal 900: a bigger constant is the same defect
    restated. Every call inside the function is parsed, and NONE of them may
    pass a `timeout=` at all."""
    tree = ast.parse(_verify_fn_source())
    offenders = [
        ast.unparse(node)[:90]
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "timeout"
    ]
    assert offenders == [], offenders


def test_j1_the_simulator_is_entered_through_the_shared_container_primitive():
    """The SAME argv A4's `run_to_completion` uses — `deadline_s=0`, which GNU
    `timeout` documents as "disable the associated timeout" — so there is one
    container-entry shape in the analog track and not two."""
    tree = ast.parse(_verify_fn_source())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and ast.unparse(n.func).endswith("container_deadline_argv")]
    assert len(calls) == 1, ast.unparse(tree)[:400]
    deadlines = [ast.literal_eval(kw.value) for kw in calls[0].keywords
                 if kw.arg == "deadline_s"]
    assert deadlines == [0], deadlines


@pytest.mark.parametrize("status", ["SIMULATION_STALLED",
                                    "SIMULATION_STOPPED_EXTERNALLY",
                                    "SIMULATION_INVOCATION_FAILED"])
def test_j1_a_run_that_did_not_finish_has_its_own_name(status):
    """A simulator that ran and did not finish is a stopped job, and it is owed
    a name of its own. `NOT_VERIFIED_NO_SIMULATOR` is owed ONLY when the binary
    is absent, and this asserts the three not-finished outcomes are spelled and
    are spelled differently from it."""
    src = _verify_fn_source()
    assert f'"{status}"' in src
    assert status != "NOT_VERIFIED_NO_SIMULATOR"


def test_j1_absent_simulator_is_still_reported_as_absent():
    """The paired guard: narrowing what may say NOT_VERIFIED_NO_SIMULATOR must
    not delete the case it is FOR. Only the two pre-run returns may say it."""
    tree = ast.parse(_verify_fn_source())
    # STRING LITERALS ONLY. The prose around this function names the status
    # several times on purpose — a comment cannot answer a caller.
    said = [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value == "NOT_VERIFIED_NO_SIMULATOR"]
    assert len(said) == 2, len(said)
    src = _verify_fn_source()
    assert "no ngspice in the container" in src
    assert "is not reachable" in src


# ═══ D1 — the DC-op rail invariant reads the simulator's own table ═════════

_OP_TABLE = """
Initial Transient Solution
--------------------------

Node                                   Voltage
----                                   -------
vdd                                        1.2
blk.n_inner                           0.412399
blk.n_stack                                {v}
v_vdd#branch                      -0.000190038
"""

#: A TESTBENCH node — no instance prefix. MEASURED: driving the declared
#: reference to 5 V put the source itself out of range first and six nodes
#: INSIDE the block after it, so scoping to the block is what keeps a design
#: whose stimulus legitimately sits in another domain from being refused.
_TB_NODE_TABLE = _OP_TABLE.replace("blk.n_stack", "vrefp_alpha")


def test_d1_a_node_inside_the_rails_is_not_an_excursion():
    assert A3.dc_op_rail_excursions(_OP_TABLE.format(v="1.054578"), 1.2) == []


def test_d1_a_node_above_the_rail_is_named():
    got = A3.dc_op_rail_excursions(_OP_TABLE.format(v="3.33717"), 1.2)
    assert [n for n, _ in got] == ["blk.n_stack"]
    assert got[0][1] == pytest.approx(3.33717)


def test_d1_a_node_below_ground_is_named():
    got = A3.dc_op_rail_excursions(_OP_TABLE.format(v="-2.99411"), 1.2)
    assert [n for n, _ in got] == ["blk.n_stack"]


def test_d1_a_testbench_node_is_not_an_internal_node():
    """The invariant is about the BLOCK. A bare name is a testbench node and is
    judged by nobody here — an I/O rail, a boost node or a reference above the
    core is a legitimate stimulus, not a defect in the netlist under test."""
    assert A3.dc_op_rail_excursions(_TB_NODE_TABLE.format(v="5.0"), 1.2) == []
    # ... and the SAME voltage inside the block still is one.
    got = A3.dc_op_rail_excursions(_OP_TABLE.format(v="5.0"), 1.2)
    assert [n for n, _ in got] == ["blk.n_stack"]


def test_d1_a_branch_current_is_not_a_node_voltage():
    """`v_vdd#branch` is amperes. Reading it as a volt would report an
    excursion on every deck that draws more current than the supply."""
    got = A3.dc_op_rail_excursions(_OP_TABLE.format(v="0.5"), 0.001)
    assert all("#branch" not in n for n, _ in got), got


def test_d1_the_reader_actually_parses_the_table():
    """A reader that matches NOTHING also returns []. Drop the rail far enough
    and every real node row must come back — otherwise the two green tests
    above are green for the wrong reason."""
    got = A3.dc_op_rail_excursions(_OP_TABLE.format(v="0.5"), 0.01)
    assert {n for n, _ in got} == {"blk.n_inner", "blk.n_stack"}


def test_d1_no_supply_is_not_measured_rather_than_clean():
    """"Could not check" is not "checked and clean". With no supply to judge
    against the reader returns nothing, and the caller records which of the two
    that was — see `rail_invariant`."""
    assert A3.dc_op_rail_excursions(_OP_TABLE.format(v="9.9"), None) == []
    assert "NOT_MEASURED_NO_SUPPLY" in _verify_fn_source()


# ═══ D1 — the `_NOT_PROSE` claim, re-measured rather than asserted ═════════

#: The operating-point row `dc_op_rail_excursions` reads, with a value that IS
#: an excursion — the real 3.33717 V this lane measured on the pre-`.options`
#: deck. A value INSIDE the rails would make "no match" and "matched, nothing
#: wrong" the same empty answer, and the falsifier below would then pass
#: against a regex that matches nothing.
_OP_HEADER = "Node                                   Voltage\n"
_EXCURSION_V = "3.33717"

#: Every position a denial token can reach in that production: before the node,
#: between node and value, after the value, around the `=` form, indented,
#: label-prefixed, AS the whole node name, and INSIDE the node name.
_DENIAL_POSITIONS = (
    "{t} xdut.nn1                            {v}",
    "xdut.nn1 {t}                            {v}",
    "xdut.nn1                            {t} {v}",
    "xdut.nn1                            {v} {t}",
    "xdut.nn1 = {t} {v}",
    "xdut.nn1 = {v} {t}",
    "  {t}  xdut.nn1                         {v}",
    "{t}: xdut.nn1                           {v}",
    "{t}                                     {v}",
    "xdut.{t}                                {v}",
)


def _denial_vocabulary() -> list:
    """`_prose_polarity`'s OWN denial words, read out of its own patterns.

    Read rather than re-typed: a hand-copied list would agree with the module
    by coincidence and would stop tracking it the first time a word is added.
    The `\\b` anchors leave a leading `b` on each alternative, which is
    stripped here — the words, not the regex escapes, are the vocabulary.
    """
    import re
    import _prose_polarity as PP
    raw = PP._DENIAL_CORE + "|" + PP._DENIAL_RETIRED
    out = set()
    for m in re.findall(r"([A-Za-z][A-Za-z' -]{2,})", raw):
        m = m.strip()
        out.add(m[1:] if m.startswith("b") and len(m) > 3 else m)
    return sorted(w for w in out if len(w) >= 2 and not w.startswith("b"))


def test_the_op_table_reader_reads_the_grammar_at_all():
    """THE CONTROL FOR THE FALSIFIER BELOW. If this row did not come back, the
    "no denial inverted a value" result would be a statement about a regex that
    matches nothing, not about a grammar."""
    got = A3.dc_op_rail_excursions(
        _OP_HEADER + f"xdut.nn1                            {_EXCURSION_V}\n", 1.2)
    assert got == [("xdut.nn1", pytest.approx(3.33717))]


def test_the_not_prose_claim_for_the_op_table_reader_is_falsifiable():
    """THE ARGUMENT BEHIND THE `_NOT_PROSE` ENTRY, RE-MEASURED HERE.

    `dc_op_rail_excursions` is registered in
    `prose_polarity_consulted_check._NOT_PROSE` as reading a formal grammar
    rather than prose. That claim is only worth anything if it can be checked,
    so this checks it: every denial token of `_prose_polarity`'s OWN vocabulary,
    in every position reachable in the one production the function parses.

    THE PROPERTY: the grammar's only alternative to a value is SILENCE. A denial
    can stop the row from parsing — and then the node simply is not reported,
    which is the same thing that happens when the simulator prints no row at all
    — but no denial can make the function publish a DIFFERENT voltage. That is
    what makes a polarity consult here a branch that can never fire.

    THE ONE CASE THAT IS NOT SILENCE is the token appearing INSIDE a node name
    (`xdut.never`): the voltage is carried through unchanged and a node so named
    really is a node so named. It is counted separately below rather than
    hidden, because a claim that quietly reclassifies its own counter-examples
    is not falsifiable.

    THE CONTRAST is the other half of the claim: the IDENTICAL strings, read as
    prose, are full of denials. The vocabulary is not inert; this grammar is."""
    import _prose_polarity as PP
    tokens = _denial_vocabulary()
    assert len(tokens) >= 10, "the vocabulary was not read"

    inverted = refused = renamed = trials = 0
    for tok in tokens:
        for shape in _DENIAL_POSITIONS:
            trials += 1
            got = A3.dc_op_rail_excursions(
                _OP_HEADER + shape.format(t=tok, v=_EXCURSION_V) + "\n", 1.2)
            if not got:
                refused += 1
            elif {round(v, 5) for _, v in got} != {3.33717}:
                inverted += 1
            elif {n for n, _ in got} != {"xdut.nn1"}:
                renamed += 1

    assert trials >= 100
    assert inverted == 0, ("a denial token changed the voltage this grammar "
                           "publishes — the _NOT_PROSE entry for "
                           "analog_a3_netlist_emit::dc_op_rail_excursions is "
                           "false; delete the entry rather than this assertion")
    assert refused > 0, ("no denial could even disturb the parse; the "
                         "falsifier is not exercising the grammar")
    # DERIVED, never a hard-coded count: exactly those tokens that are legal
    # inside a node name at all. `does not apply`, `no longer` and `non-` are
    # not — they carry a space or a hyphen — so those rows are refused like any
    # other denial, and the expected number falls out of the grammar rather
    # than out of this test.
    nameable = [tok for tok in tokens if A3._OP_ROW_RE.match(
        f"xdut.{tok}                                {_EXCURSION_V}")]
    assert renamed == len(nameable) > 0, (
        "the only non-silent outcome must be the token INSIDE the node name, "
        f"one per nameable token; got {renamed} of {len(nameable)}")
    assert refused == trials - renamed

    prose = sum(1 for t in tokens for s in _DENIAL_POSITIONS
                if PP.is_denied(s.format(t=t, v=_EXCURSION_V)))
    assert prose > 0, ("the vocabulary found no denial in ANY of these "
                       "strings, so this test proves nothing about the "
                       "grammar — it would pass against an empty vocabulary")


def test_the_op_table_reader_is_handed_stdout_not_the_deck():
    """The other half of the entry: the only natural language anywhere near
    this reader is the `* condition:` commentary A3 writes into the testbench it
    emits, and that never reaches here. Asserted at the CALL SITE, over the
    AST — the argument is the simulator's combined output, never `tb_text`."""
    tree = ast.parse(_verify_fn_source())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and ast.unparse(n.func).endswith("dc_op_rail_excursions")]
    assert len(calls) == 1, ast.unparse(tree)[:400]
    assert [ast.unparse(a) for a in calls[0].args] == ["out", "supply_v"]


# ═══ N1 — an explicit --pdk the block does not bind ════════════════════════

def test_n1_a_request_for_another_family_is_not_bound():
    assert A3.pdk_request_is_bound("sky130", "sg13g2", None) is False


def test_n1_a_request_for_the_bound_family_is_bound():
    assert A3.pdk_request_is_bound("sg13g2", "sg13g2", None) is True


def test_n1_a_vendor_prefix_on_one_side_only_is_the_same_family():
    """The predicate catches a request for a DIFFERENT FOUNDRY, not a
    difference in spelling — the registry name and the bare family are one."""
    assert A3.pdk_request_is_bound("ihp-sg13g2", "sg13g2", None) is True
    assert A3.pdk_request_is_bound("sky130", "sky130A", None) is True


def test_n1_asking_for_nothing_is_never_a_refusal():
    """`--pdk` has a historical default. A caller who named no family must keep
    the behaviour they have always had, or every project in the repo that
    declares a family other than that default refuses on the next run."""
    assert A3.pdk_request_is_bound(None, "sg13g2", None) is True
    assert A3.pdk_request_is_bound("", "sg13g2", None) is True


def test_n1_an_unresolvable_binding_is_not_reported_as_a_mismatch():
    """Nothing was bound, so nothing DISAGREES with the request. Refusing here
    would charge a caller for a resolver that could not answer."""
    assert A3.pdk_request_is_bound("sky130", None, None) is True


def test_n1_the_default_family_is_declared_outside_the_argument_parser():
    """`--pdk` defaulting to a family name made "the caller asked for this" and
    "nobody asked for anything" the same string, which is why the request could
    never have been checked."""
    src = Path(PROGRAMS / "analog_a3_netlist_emit.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and ast.unparse(node.func).endswith("add_argument")
                and node.args and ast.literal_eval(node.args[0]) == "--pdk"):
            defaults = [ast.literal_eval(kw.value) for kw in node.keywords
                        if kw.arg == "default"]
            assert defaults == [None], defaults
            break
    else:                                                  # pragma: no cover
        pytest.fail("no --pdk argument found")
    assert A3.DEFAULT_PDK


def test_n1_the_refusal_has_its_own_name():
    assert A3.PDK_NOT_BOUND_BY_BLOCK == "PDK_NOT_BOUND_BY_BLOCK"
