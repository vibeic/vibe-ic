"""The synth producer emits `setundef -zero` before `hilomap` — RULE 1.

`yosys_tiecell_recipe_order_check.py` has enforced RULE 1 (`setundef -zero`
MUST precede `hilomap`) since v0.1.98, and has been wired ADVISORY for exactly
one reason, quoted from its own docstring:

    EVERY runner-produced real-PDK synthesis violates RULE 1.
    `phase3_one_shot_runner.py` builds its inline yosys command with a
    `hilomap` clause and never emits `setundef -zero` (grep: the only two
    `setundef` occurrences in that file are comments).

The same docstring argued the violation was not severe, because "the flow
already mitigates the routing symptom downstream" — the PG-net cleanup pass
retyped the resulting `zero_` net to SIGNAL and the run routed:

    phase3/stage3/pnr/openroad.log:278  PG_CLEANUP_SIG: zero_ (GROUND)
    phase3/stage3/pnr/openroad.log:595  [INFO DRT-0199]   Number of violations = 0.

vibe-ic#687 REMOVED that retype — correctly, because it was also hiding
genuinely unrouted supplies. With the mitigation gone the untied-`x` path now
reaches `PG_CLEANUP_UNROUTED_SUPPLY` and hard-FAILs PnR. MEASURED on
caravel_user_project x sky130A, plugin v1.9.65, die 2920x3520:

    synth netlist : assign io_out = { \\mprj.counter.count [15:8],
                                      22'hxxxxxx, \\mprj.counter.count [7:0] };
    openroad.log  : PG_CLEANUP_UNROUTED_SUPPLY: zero_ (GROUND) iterms=0 bterms=44
    pnr verdict   : FAIL  PG_UNROUTED_SUPPLY: 1 POWER/GROUND net(s) ...

44 driverless chip-top output bits, reported as a power/ground rail. So RULE 1's
consequence is no longer "a downstream pass decides the tie value"; it is a hard
PnR FAIL with a misleading finding name, on every design that has an unconnected
top-level output bit.

`hilomap` maps constant 1'b0 / 1'b1 to tie cells. It does NOT map `x`. So the
producer must resolve `x` to 0 FIRST — which is what RULE 1 always said.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod


R = _load("phase3_one_shot_runner")
CHK = _load("yosys_tiecell_recipe_order_check")

_SRC = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")

# The clause the producer builds, in both states. The producer's own
# expression is `f"setundef -zero; {hilomap_directive}; "` when tie cells were
# discovered and `""` when they were not; `_DIRECTIVE` is what
# `_v1_6_596_build_hilomap_directive` returns for a dual-output tie cell
# (sky130 conb_1) — reproduced here so the test does not need a PDK.
_DIRECTIVE = "hilomap -hicell TIEHILO_1 HI -locell TIEHILO_1 LO"
_CLAUSE_POST = f"setundef -zero; {_DIRECTIVE}; "
_CLAUSE_PRE = f"{_DIRECTIVE}; "          # what the producer emitted before


def _recipe(clause: str) -> str:
    """The producer's inline yosys command with `clause` spliced in, reduced
    to the commands the RULE 1 / RULE 2 audit reads."""
    return (
        "yosys -p 'read_verilog -sv top.v; hierarchy -check -top top; "
        "proc; flatten; tribuf -logic; synth -top top -flatten; "
        "dfflibmap -liberty lib.lib; abc -liberty lib.lib; "
        f"{clause}"
        "clean; stat -liberty lib.lib; write_verilog -noattr out.v'"
    )


# ── the producer ──────────────────────────────────────────────────────────
def test_the_producer_emits_setundef_zero_in_the_hilomap_clause():
    """The one-line defect. Putting it INSIDE the clause (rather than at each
    of the four call sites that interpolate it) is what makes the order true
    by construction and un-driftable."""
    assert 'f"setundef -zero; {hilomap_directive}; "' in _SRC


def test_no_tie_cells_means_no_setundef_either():
    """NO-LEAK BOUNDARY (§4.05). `setundef -zero` on its own is NOT an
    improvement: with no tie cell to map to, it converts `x` into a bare 1'b0
    constant net with no driver — the same driverless shape the fix exists to
    remove, just spelled differently. The empty-clause branch must stay empty.
    """
    i = _SRC.index('f"setundef -zero; {hilomap_directive}; "')
    tail = _SRC[i:i + 200]
    assert 'if hilomap_directive else ""' in tail


# ── the rules, driven through the REAL checker ────────────────────────────
def test_NEGATIVE_CONTROL_the_pre_fix_recipe_still_violates_RULE_1():
    """LOAD-BEARING. A test that cannot fail against the pre-fix code proves
    nothing. This drives the SAME checker over the SAME recipe with only the
    clause swapped, and asserts it still reports the violation."""
    rep = CHK.diagnose_inline_command(_recipe(_CLAUSE_PRE))
    rules = [v["rule"] for v in rep["violations"]]
    assert "RULE1_setundef_zero_before_hilomap" in rules, rep


def test_the_post_fix_recipe_is_clean_under_BOTH_rules():
    rep = CHK.diagnose_inline_command(_recipe(_CLAUSE_POST))
    assert rep["violations"] == [], rep


def test_RULE_2_is_not_traded_away_for_RULE_1():
    """RULE 2 — no `opt_clean` / `clean -purge` after `hilomap`, because they
    delete the just-inserted tie cells and re-create the bare constant nets.
    The producer emits plain `clean`, which is fine; assert the fix did not
    quietly introduce an aggressive cleaner, and that the checker would catch
    it if it did."""
    assert CHK.diagnose_inline_command(_recipe(_CLAUSE_POST))["violations"] == []
    bad = _recipe(_CLAUSE_POST).replace("clean; stat", "opt_clean; stat")
    rules = [v["rule"]
             for v in CHK.diagnose_inline_command(bad)["violations"]]
    assert any("RULE2" in r for r in rules)


def test_setundef_zero_precedes_EVERY_hilomap_call_site():
    """The clause is interpolated at four sites. Order-by-construction means
    none of them can regress independently — but only if they all use the
    clause rather than the raw directive."""
    assert _SRC.count("{hilomap_clause}") >= 4
    # the raw directive is referenced only where the clause is built
    assert _SRC.count("{hilomap_directive}") == 1
