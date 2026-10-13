"""ONE LEC recipe for pre- AND post-layout, and a RECORDED step budget (#2151).

WHAT WAS WRONG
==============
This plugin shipped TWO independent LEC recipes:

  * `lec_run.build_equiv_script`               — pre-layout (RTL vs synth)
  * `lec_post_layout_check.build_yosys_equiv_script` — post-layout (reference
    netlist vs the ROUTED netlist)

The v1.18.0 LEC-recipe fix — `stat`, the SAT-free `equiv_struct` pre-reduction
ahead of any SAT spend, the `equiv_simple -short` first rung and the
`-encfile` / conditional-`splitnets` FSM-re-encoding rule — landed in the first
one only.  `lec_post_layout_check.py` stayed blob `0d65d9b89eb2` from v1.17.98
through v1.18.98: byte-identical across every bump, still running the
pre-v1.18.0 strategy on the step that proves the routed netlist.

MEASURED, on the sha256 post-route netlist (host 8HD-8, the pinned image,
yosys 0.68+ aa4f0d7d6): the post-layout first pass ran **43289.65 s** — 12
hours — with **99% of it inside three `equiv_induct` rungs** and 17.7 GB peak,
to arrive at 134 unproven points, because every structurally identical cone was
handed to the SAT engine instead of being collapsed by `equiv_struct` first.
Nothing in the step announced a budget while that happened; the only bound it
had was the shared 24 h supervised ceiling.

WHAT IS PINNED HERE
===================
1.  BOTH builders derive their proof tail from ONE function,
    `lec_run.equiv_proof_tail`.  Pinned BEHAVIOURALLY (monkeypatch the function
    and both scripts move), not by grepping for a name — a second local copy
    of the recipe cannot pass that.
2.  The pre-layout text did NOT move: the shared tail is byte-for-byte the
    lines `build_equiv_script` used to spell inline.
3.  The post-layout recipe now carries `stat`, `equiv_struct` and the shipped
    rung ladder.
4.  The FSM-encfile rule is the same one on both paths: `-encfile` present and
    `splitnets` dropped together, or neither.
5.  The post-layout step has its OWN RECORDED budget, and it is NOT a kill:
    it is passed as `hard_ceiling_s` (which since vibe-ic#2051 records,
    announces and CONTINUES), and the step wraps nothing in `timeout`.

chip-AGNOSTIC: synthetic file names only; no PDK, design or vendor name.
"""
import ast
import inspect
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lec_post_layout_check as LP  # noqa: E402
import lec_run as LR  # noqa: E402


_POST_KW = dict(gold_v="gold.v", gate_v="gate.v", lib="x.lib", top="top")
_PRE_KW = dict(gold_files=["gold.v"], gate_netlist="gate.v", top="top",
               liberty="x.lib")


# --------------------------------------------------------------------------
# (1) ONE FUNCTION, PROVEN BY SUBSTITUTION
# --------------------------------------------------------------------------
@pytest.mark.parametrize("functional_lib", [True, False])
def test_post_layout_tail_comes_from_lec_run(monkeypatch, functional_lib):
    """Replace `lec_run.equiv_proof_tail` and the POST-layout script moves.

    A local copy of the strategy in `lec_post_layout_check` could not contain
    the sentinel, so this fails on the pre-fix tree.
    """
    sentinel = "vibeic_one_recipe_sentinel\n"
    monkeypatch.setattr(LR, "equiv_proof_tail", lambda *a, **k: sentinel)
    ys = LP.build_yosys_equiv_script(functional_lib=functional_lib, **_POST_KW)
    assert sentinel in ys
    # ...and the strategy it replaced is GONE — i.e. the tail is not emitted
    # twice, once shared and once locally.
    assert "equiv_induct" not in ys
    assert "equiv_status" not in ys


def test_pre_layout_tail_comes_from_the_same_function(monkeypatch):
    sentinel = "vibeic_one_recipe_sentinel\n"
    monkeypatch.setattr(LR, "equiv_proof_tail", lambda *a, **k: sentinel)
    ys = LR.build_equiv_script(**_PRE_KW)
    assert sentinel in ys
    assert "equiv_induct" not in ys


def test_both_builders_call_the_shared_tail_by_ast():
    """The call graph, not the prose: each builder CALLS `equiv_proof_tail`."""
    def _calls(fn):
        tree = ast.parse(inspect.getsource(fn))
        return {
            (node.func.attr if isinstance(node.func, ast.Attribute)
             else getattr(node.func, "id", None))
            for node in ast.walk(tree) if isinstance(node, ast.Call)
        }
    assert "equiv_proof_tail" in _calls(LR.build_equiv_script)
    assert "equiv_proof_tail" in _calls(LP.build_yosys_equiv_script)


def test_post_layout_module_imports_lec_run_unguarded():
    """The import must not be wrapped in a try/except that could fall back to
    a private recipe — that is exactly how the two paths drifted apart."""
    tree = ast.parse(Path(LP.__file__).read_text())
    imports_at_module_level = {
        alias.name
        for node in tree.body if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "lec_run" in imports_at_module_level


# --------------------------------------------------------------------------
# (2) THE PRE-LAYOUT TEXT DID NOT MOVE
# --------------------------------------------------------------------------
def test_shared_tail_is_the_shipped_ladder_verbatim():
    assert LR.equiv_proof_tail() == (
        "stat\n"
        "equiv_struct\n"
        "equiv_simple -short\n"
        "equiv_induct -seq 16\n"
        "equiv_simple\n"
        "equiv_induct -seq 4\n"
        "equiv_induct -seq 16\n"
        "equiv_induct -seq 64\n"
        "equiv_status\n"
    )


def test_default_seq_depths_reproduce_the_ladder_exactly():
    """The post-layout default (4, 16, 64) IS the shipped ladder — so moving
    the post-layout step onto the shared tail changed the STRATEGY, never the
    depth schedule."""
    assert LR.equiv_proof_tail(list(LP.DEFAULT_SEQ_DEPTHS)) == \
        LR.equiv_proof_tail()


def test_custom_depths_are_ascending_deduplicated_and_positive():
    tail = LR.equiv_proof_tail([32, 8, 8, 0, -1])
    assert "equiv_induct -seq 8\n" in tail and "equiv_induct -seq 32\n" in tail
    assert "-seq 0" not in tail and "-seq -1" not in tail
    assert tail.index("-seq 8") < tail.index("-seq 32")
    assert tail.count("-seq 8") == 1


def test_checkpoints_are_refused_for_caller_chosen_depths():
    """Checkpoint files are named by LEC_LADDER rung names; a caller-chosen
    depth has none. Refuse loudly rather than write one no resume can select."""
    with pytest.raises(ValueError):
        LR.equiv_proof_tail([8], checkpoint_dir="/c/dir")


# --------------------------------------------------------------------------
# (3) THE POST-LAYOUT RECIPE CARRIES THE v1.18.0 STRATEGY
# --------------------------------------------------------------------------
@pytest.mark.parametrize("functional_lib", [True, False])
def test_post_layout_recipe_is_structural_first(functional_lib):
    ys = LP.build_yosys_equiv_script(functional_lib=functional_lib, **_POST_KW)
    lines = ys.splitlines()
    assert "stat" in lines
    assert "equiv_struct" in lines
    # ...and the pre-reduction happens BEFORE any SAT is spent.
    assert lines.index("equiv_struct") < lines.index("equiv_simple -short")
    assert lines.index("equiv_simple -short") < lines.index("equiv_induct -seq 4")
    assert lines.index("equiv_make gold gate equiv") < lines.index("stat")
    assert lines[-1] == "equiv_status"


# --------------------------------------------------------------------------
# (4) THE FSM-ENCFILE RULE IS THE SAME ONE ON BOTH PATHS
# --------------------------------------------------------------------------
@pytest.mark.parametrize("functional_lib", [True, False])
def test_encfile_pairs_with_dropping_splitnets(functional_lib):
    with_enc = LP.build_yosys_equiv_script(functional_lib=functional_lib,
                                           fsm_encfile="/f/enc.txt",
                                           **_POST_KW)
    assert "equiv_make -encfile /f/enc.txt gold gate equiv" in with_enc
    assert "splitnets" not in with_enc
    # The pre-layout path states the SAME pairing.
    pre = LR.build_equiv_script(fsm_encfile="/f/enc.txt", **_PRE_KW)
    assert "-encfile /f/enc.txt" in pre and "splitnets" not in pre


@pytest.mark.parametrize("functional_lib", [True, False])
def test_no_encfile_keeps_splitnets_on_both_arms(functional_lib):
    ys = LP.build_yosys_equiv_script(functional_lib=functional_lib, **_POST_KW)
    assert "-encfile" not in ys
    assert ys.count("splitnets -ports\n") == 2   # gold arm and gate arm


def test_encfile_and_blacklist_compose():
    ys = LP.build_yosys_equiv_script(functional_lib=True,
                                     fsm_encfile="/f/enc.txt",
                                     blacklist="/f/bl.txt", **_POST_KW)
    assert "equiv_make -encfile /f/enc.txt -blacklist /f/bl.txt gold gate equiv" \
        in ys


# --------------------------------------------------------------------------
# (5) A RECORDED STEP BUDGET THAT IS NOT A KILL
# --------------------------------------------------------------------------
def _runner():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import phase3_one_shot_runner as P3
    return P3


def test_step_budget_defaults_to_the_pre_layout_lec_budget(monkeypatch):
    monkeypatch.delenv("VIBEIC_POST_LAYOUT_LEC_BUDGET_S", raising=False)
    monkeypatch.delenv("VIBEIC_LEC_YOSYS_TIMEOUT_S", raising=False)
    assert _runner()._post_layout_lec_step_budget_s() == \
        float(LR.DEFAULT_YOSYS_TIMEOUT_S)


def test_step_budget_env_override(monkeypatch):
    monkeypatch.setenv("VIBEIC_POST_LAYOUT_LEC_BUDGET_S", "1234")
    assert _runner()._post_layout_lec_step_budget_s() == 1234.0
    # A non-numeric value does not silently become a default of its own: the
    # next source in the chain answers.
    monkeypatch.setenv("VIBEIC_POST_LAYOUT_LEC_BUDGET_S", "not-a-number")
    monkeypatch.setenv("VIBEIC_LEC_YOSYS_TIMEOUT_S", "4321")
    assert _runner()._post_layout_lec_step_budget_s() == 4321.0


def test_the_budget_is_recorded_never_terminating():
    """`hard_ceiling_s` is the RECORDING bound (#2051): the supervisor notes the
    crossing once and the job runs on. The post-layout LEC must pass its budget
    THERE, and must not wrap the tool in a `timeout`."""
    P3 = _runner()
    src = inspect.getsource(P3._emit_lec_post_layout)
    assert "hard_ceiling_s=_lec_budget_s" in src
    # the LEC invocation itself
    lec_cmd = [ln for ln in src.splitlines() if "yosys -s {ys_c}" in ln]
    assert lec_cmd, "the LEC yosys invocation moved — re-point this pin"
    assert not any("timeout" in ln for ln in lec_cmd)
    # and the run is SUPERVISED (marker=...), which is what makes the ceiling
    # a recorded observation rather than a wall clock.
    assert "marker=ys_c" in src


def test_watchdog_hard_ceiling_does_not_kill():
    """The property the budget relies on, asserted against the supervisor
    itself rather than assumed from its docstring."""
    import _watchdog as WD
    src = inspect.getsource(WD.supervise)
    # the crossing is RECORDED...
    assert "hard_ceiling_exceeded" in src
    # ...and the loop does not break or kill on it.
    marker = src.index("hard_ceiling_s")
    window = src[marker:marker + 1500]
    assert "kill(" not in window


# --------------------------------------------------------------------------
# (6) THE PERMUTATION SCREEN — RUNG 0, AND NEVER A VERDICT
# --------------------------------------------------------------------------
def test_screen_is_rung_zero_with_no_induction():
    assert LR.equiv_proof_tail(induction=False) == (
        "stat\n"
        "equiv_struct\n"
        "equiv_simple -short\n"
        "equiv_simple\n"
        "equiv_status\n"
    )


@pytest.mark.parametrize("functional_lib", [True, False])
def test_post_layout_screen_runs_no_induction(functional_lib):
    ys = LP.build_yosys_equiv_script(screen_only=True,
                                     functional_lib=functional_lib, **_POST_KW)
    assert "equiv_induct" not in ys
    # ...but it is still the SAME recipe up to the ladder: the pre-reduction
    # that makes the survivor list cheap is present.
    assert "equiv_struct" in ys.splitlines()
    assert ys.rstrip().endswith("equiv_status")


def test_screen_and_full_differ_only_in_the_induction_rungs():
    screen = LP.build_yosys_equiv_script(screen_only=True, functional_lib=True,
                                         **_POST_KW).splitlines()
    full = LP.build_yosys_equiv_script(functional_lib=True,
                                       **_POST_KW).splitlines()
    removed = [ln for ln in full if ln not in screen]
    assert removed == ["equiv_induct -seq 16", "equiv_induct -seq 4", "equiv_induct -seq 16",
                       "equiv_induct -seq 64"]
    assert [ln for ln in screen if ln not in full] == []


def test_a_screen_writes_no_checkpoint():
    with pytest.raises(ValueError):
        LR.equiv_proof_tail(induction=False, checkpoint_dir="/c/dir")


def test_the_authoritative_pass_is_a_full_ladder():
    """The screen may only ADD renames; the verdict must still come from a run
    that ran the induction ladder."""
    P3 = _runner()
    src = inspect.getsource(P3._emit_lec_post_layout)
    # the screen call is explicitly a screen...
    assert "screen_only=True" in src
    # ...and the run `parsed` is taken from is NOT.
    auth = src[src.index("rc, log_text = _run_lec("):]
    auth = auth[:auth.index("parsed = mod.parse_equiv_log(log_text)")]
    assert "screen_only" not in auth
    # and the record says a screen is not a verdict.
    assert '"is_a_verdict": False' in src


def test_the_crossing_is_announced_not_only_recorded():
    """"Recorded" must reach a reader. The shared supervised dispatch writes one
    stderr line at the crossing and marks the telemetry sidecar; the action it
    names is `recorded_and_continued`, not a stop."""
    import _docker_watchdog as DWD
    src = inspect.getsource(DWD)
    assert "WATCHDOG_HARD_CEILING" in src
    assert '"action": "recorded_and_continued"' in src
    assert '"event": "hard_ceiling"' in src
