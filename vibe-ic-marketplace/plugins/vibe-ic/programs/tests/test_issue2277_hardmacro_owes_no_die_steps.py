"""A macro somebody else places has no die edge, so it owes no die steps.

vibe-ic#2277, flow steps 15.5ic / 26.5ic / 37.5ic and step 31. MEASURED on live
main 79506306d (lane icspm4, run1).

DIE STEPS (class a, ABSENT SUBJECT). All three rows condition on ROUTER FILES --
`input/submission_template/slots/*.yaml` OR `SELF_TAPEOUT.txt` -- and the only
N/A a hardmacro was offered is `NO_TEMPLATE.txt`. Since 0.5ic's fetch was wired,
a PDK with a LIVE shuttle in the registry has the operator's whole CATALOGUE
ingested as `slots/*.yaml` whether or not the design bought a slot, and no
`NO_TEMPLATE.txt` is written. So a delivery whose own input declares
`deliverable=HARDMACRO` with `operator_template.path/.slot` null matched the
`any_of`, all three rows were judged APPLICABLE, every output was owed, the
producers correctly wrote nothing (`tapeout_precheck` step_applies=false,
`tapeout_docs_gen` NOT_APPLICABLE, `die_finishing_gen._hardmacro_skip`), and the
rows read MISSING -- failing stage3 and stage4 compliance. RULINGS R12
(2026-09-07): a hardmacro exposes pins, gets no pad ring and no die ring.

STEP 31 (class c, PRODUCER GAP). `reports/phase3/perc_sweep.json` is a step-31
`required_output` and `perc_corpus_sweep` is named under its `programs:`, but no
clause invoked it -- the reach clause only READS the document. 8 of 9 outputs
were produced and the ninth was owed by nobody. `flow_declared_producer_run`
could not adopt it either: it matched only `--json`, and this producer writes
through `--report` because its own `--json` is a boolean.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROGRAMS = HERE.parent
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(HERE))




_FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
_DIE_STEPS = ("15.5ic", "26.5ic", "37.5ic")




def _project(tmp_path, *, deliverable="HARDMACRO", **kwargs):
    root = tmp_path / "run"
    report = root / "reports/flow_engine.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    target = "ip_hardmacro" if deliverable == "HARDMACRO" else "gds"
    report.write_text(json.dumps({"route": {"delivery_target": target}}))
    return root




# --------------------------------------------------------------------------- #
# the die steps stand down BY DECLARATION
# --------------------------------------------------------------------------- #






# --------------------------------------------------------------------------- #
# negative controls: a design WITH a die keeps every row live
# --------------------------------------------------------------------------- #












# --------------------------------------------------------------------------- #
# step 31: the producer gap
# --------------------------------------------------------------------------- #






























# --------------------------------------------------------------------------- #
# the consumer the new condition key reaches: _ppa.delivery_path
# --------------------------------------------------------------------------- #
# MEASURED after the condition landed on the branch: `_ppa/delivery_path.py`
# refuses LOUDLY (by design) any key on a terminal's condition it has not been
# taught -- `_ROUTE_CONDITION_KEYS` -- and every route it resolved came back
# UNREADABLE, reddening 13 tests across two modules. That guard is right and
# stays; `delivery_declares` is now IN the set because it answers this module's
# OWN question from a better source, and the same predicate `resolve` already
# runs evaluates it.
import _ppa.delivery_path as DP                           # noqa: E402




def test_a_declared_hardmacro_resolves_to_the_IP_ROUTE(tmp_path):
    """Neither terminal's `files_exist` is met on this tree -- the chip
    terminal stands down BY DECLARATION and `NO_TEMPLATE.txt` was never
    written because a live shuttle existed on the target PDK. Reporting
    NOT_DETERMINED here would say "this tree carries no router artefact"
    about a tree that carries one, which is the one thing this module
    promises never to do."""
    r = DP.resolve(_project(tmp_path))
    assert r["path"] == DP.PATH_IP


def test_a_DIE_on_the_same_tree_still_resolves_to_the_CHIP_ROUTE(tmp_path):
    r = DP.resolve(_project(tmp_path, deliverable="DIE"))
    assert r["path"] == DP.PATH_CHIP


def test_a_tree_with_no_router_and_no_declaration_stays_NOT_DETERMINED(tmp_path):
    """The honest unknown is preserved: nothing to read is not an IP finding."""
    bare = tmp_path / "bare"
    (bare / "input" / "submission_template").mkdir(parents=True)
    assert DP.resolve(bare)["path"] == DP.PATH_NOT_DETERMINED
