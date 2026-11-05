"""vibe-ic#2183, secondary finding — Step DT1 read a `pdk` Step 11 had not bound.

WHAT WAS MEASURED, ON LIVE MAIN, BEFORE THIS WAS WRITTEN
========================================================
`step_dft_lec_chain` binds `pdk` at exactly one place — inside the Step-11
branch, which is the `else` of `if not full_chip: ... elif not clk: ...`. Step
DT1 (transition-delay-fault ATPG), 500 lines further down, reads it at FUNCTION
scope. DT1's own preconditions are different and weaker: a derivable clock and
`phase2/stage2/dft/cut_netlist.v` on disk. Both survive an earlier full run, and
neither implies Step 11 ran this time.

So on a `--skip-phase3` run (`full_chip=False`) over a tree that already has a
cut netlist, driving the REAL step at b6a73c0aa3 raised:

    File ".../design_one_shot_runner.py", line 19582, in step_dft_lec_chain
        if pdk and pdk == _cpdk.COMMERCIAL_PDK_ID:
    UnboundLocalError: cannot access local variable 'pdk'

Nothing catches it. `main()` calls this through `_spf.gate` and then
`plan.extend(...)`, so the exception leaves the runner and the whole phase-2 run
dies at steps 11-13 — after step 9 has already written its artefacts.

WHY THE REPAIR IS A SNIFF AND NOT A DEFAULT
===========================================
`""` is `_dft_atpg_sniff_pdk`'s OWN answer for a generic / unmapped netlist.
Initialising `pdk = ""` would have made the crash go away while publishing
"there are no library-mapped cells" on a run that never looked — a zero nobody
measured, which is the shape this tree keeps repairing. `None` means NOT
SNIFFED, and DT1 sniffs when it sees it, using the same call on the same
netlist as Step 11 so the two branches can never name different PDKs.

`test_the_binding_is_at_function_scope` is the guard for the CLASS: the
behavioural tests below cover the one path measured, and re-nesting the binding
inside any conditional re-opens it for whichever path is added next.
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as R        # noqa: E402

_NETLIST_REL = "phase2/stage2/synth/netlist.v"










# --------------------------------------------------------------------------- #
# 1. THE DEFECT
# --------------------------------------------------------------------------- #




# --------------------------------------------------------------------------- #
# 2. THE REPAIR IS A MEASUREMENT, NOT A DEFAULT
# --------------------------------------------------------------------------- #






# --------------------------------------------------------------------------- #
# 3. THE CLASS, NOT ONLY THE PATH
# --------------------------------------------------------------------------- #
def test_the_binding_is_at_function_scope():
    """`pdk` must be bound in the function's OWN body, not inside a branch.

    The behavioural tests above cover the one path that was measured. This is
    the claim that survives the next path somebody adds: every read of `pdk` in
    this function is reachable from a binding that always runs."""
    tree = ast.parse(inspect.getsource(R))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "step_dft_lec_chain")

    def _binds(stmt) -> bool:
        """The STATEMENT ITSELF, never its subtree.

        Descending would count the `if not full_chip: ... else: pdk = ...`
        block as a top-level binding — which is precisely the defect, and this
        assertion then passes on the tree it is supposed to fail on. It did:
        measured against live main before the walk was narrowed."""
        targets = []
        if isinstance(stmt, ast.Assign):
            targets = list(stmt.targets)
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets = [stmt.target]
        else:
            return False
        for tgt in targets:
            for n in ([tgt] + list(getattr(tgt, "elts", []))):
                if isinstance(n, ast.Name) and n.id == "pdk":
                    return True
        return False

    top_level = [s for s in fn.body if _binds(s)]
    assert top_level, (
        "`pdk` is bound only inside a branch of `step_dft_lec_chain`. Every "
        "later reader of it — Step DT1 is one — then depends on that branch "
        "having been taken, and raises UnboundLocalError when it was not. "
        "See vibe-ic#2183's secondary finding.")
    first_read = min(
        (n.lineno for n in ast.walk(fn)
         if isinstance(n, ast.Name) and n.id == "pdk"
         and isinstance(n.ctx, ast.Load)), default=None)
    assert first_read is not None
    assert min(s.lineno for s in top_level) < first_read, (
        "the unconditional binding comes after the first read")
