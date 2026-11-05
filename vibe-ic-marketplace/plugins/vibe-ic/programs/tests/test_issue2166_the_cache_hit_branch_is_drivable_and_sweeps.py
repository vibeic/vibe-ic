"""vibe-ic#2166 — the PnR/GDS cache-hit decision is a FUNCTION, and it is DRIVEN here.

THE DEFECT, MEASURED (lane cz2157, #2157, 8HD-9).  #2157's sweep of unreadable
0-byte `antenna_iter_*.rpt` lives inside `step_pnr`'s approach loop.  There is a
second route to the same escape that never reaches it: `main()`'s cache-hit
branch (`DEF already present … skipped re-run`) does not call `step_pnr` AT ALL,
so a cached PnR directory carrying `antenna_iter_0.rpt` at 0 bytes ships it to
`eda_report_audit`, which then reports NOT_MEASURED over evidence nobody could
open.  The GDS stage has the same shape.

WHY THE FIX IS AN EXTRACTION AND NOT A LINE.  The decision used to be written
twice INLINE in `main()`, and `main()` is not reachable from a test with a
prepared directory — so the only assertion anyone could write about it was a
grep of the source.  #2157 measured exactly what that is worth: four
source-grep assertions were ALL GREEN on the tree that carried the escape they
existed to prevent.  So the decision moved into `_cached_stage_decision`, whose
whole point is that everything below this line DRIVES it against a directory on
disk and asserts on the ARTEFACT.

MUTATIONS THESE MUST KILL (all run, all caught — see the lane's MEASUREMENTS.md):
  * removing the sweep from the accept path;
  * moving the sweep onto the REJECT path (a rejected directory is about to be
    rebuilt by `step_pnr`, whose own sweep owns it);
  * sweeping unconditionally, i.e. dropping the `accept` test;
  * dropping the `blocked_by` conjunct the GDS site uses for `_pnr_reran`;
  * re-inlining either call site back into `main()`.
"""

import ast
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))


SRC = (PROGRAMS / "phase3_one_shot_runner.py").read_text()

DIE = "200x200"
UTIL = 0.4























# ── the branch is reachable at all ─────────────────────────────────────────







# ── THE ARTEFACT ASSERTION — the escape #2166 was filed for ────────────────











# ── the GDS twin, same door ────────────────────────────────────────────────







# ── the cheap sibling: the decision must stay OUT of main() ────────────────

def test_both_cache_hit_sites_call_the_extracted_decision():
    """A SIBLING, not the guard — the driven tests above are the guard. Read
    with `ast`: if either site re-inlines the decision, `main()` becomes
    undrivable again and every assertion above stops describing the flow."""
    tree = ast.parse(SRC)
    main = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    called = [n for n in ast.walk(main)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    names = [c.func.id for c in called]
    assert names.count("_cached_stage_decision") == 2, (
        "both the PnR and the GDS cache-hit site must go through the one "
        "drivable decision; found %d call(s)"
        % names.count("_cached_stage_decision"))
    assert "_pnr_cache_valid_for" not in names, (
        "the geometry key is being read inline in main() again — that is the "
        "shape #2166 removed")


def test_the_sweep_is_reached_from_the_decision():
    """The decision is the only thing standing between a cached directory and
    the audit, so it must be what calls the sweep."""
    tree = ast.parse(SRC)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "_cached_stage_decision")
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "_drop_empty_antenna_reports"
               for n in ast.walk(fn))
