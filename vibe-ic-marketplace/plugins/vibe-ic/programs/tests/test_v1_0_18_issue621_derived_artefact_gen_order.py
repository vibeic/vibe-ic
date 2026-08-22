"""ORGANIC #621 [LOW/P3] — the Phase-3 derived-artefact generator loop ran
tapeout_checklist_gen.py BEFORE foundry_handoff_pack_gen.py. The checklist
snapshot (reports/audit/tapeout_checklist.json) was therefore written before the
foundry handoff JSONs (mask_spec / wat_plan / corner_test_vectors) it grades
existed, so it recorded verdict=BLOCKER_MISSING listing those as missing even
though they are produced tens of ms later in the SAME run. flow_compliance Step
36 re-runs tapeout_signoff_check after the files exist (→ PASS) so the FLOW
verdict is not gated, but a user reading the snapshot is misled.

Fix: foundry_handoff_pack_gen (which PRODUCES the foundry JSONs) must run BEFORE
tapeout_checklist_gen (which GRADES them). The order is now a module constant
`_DERIVED_ARTEFACT_GENERATORS` so it is testable and a future reorder cannot
silently re-break it.

POSITIVE (#621): in the constant's order, the checklist sees the foundry
artefacts as present (present=True), no spurious BLOCKER_MISSING for them.

GUARD (documents the bug): the OLD order (checklist first) leaves the foundry
items present=False — the exact 現象 the reorder fixes.

chip-AGNOSTIC: pure generator-ordering fix; no checklist-logic change, no chip
name.
"""
import json
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import phase3_one_shot_runner as P  # noqa: E402

PROGRAMS = PLUGIN / "programs"
_FOUNDRY_ITEMS = ("foundry_mask_spec", "foundry_wat_plan", "foundry_corner_kit")


def _run(proj, prog, *extra):
    subprocess.run([sys.executable, str(PROGRAMS / prog), str(proj), *extra],
                   capture_output=True, text=True, timeout=60)


def _foundry_present(proj):
    cl = json.loads(
        (proj / "reports/audit/tapeout_checklist.json").read_text())
    return {it["name"]: it.get("present")
            for it in cl["items"] if it.get("name") in _FOUNDRY_ITEMS}


def test_constant_order_foundry_before_checklist():
    order = [g for g, _ in P._DERIVED_ARTEFACT_GENERATORS]
    assert order.index("foundry_handoff_pack_gen.py") \
        < order.index("tapeout_checklist_gen.py")


def test_e2e_fixed_order_checklist_sees_foundry(tmp_path):
    # Run the generators in the module-constant order; the foundry-producing
    # generator runs first, so the checklist grades present artefacts.
    for gen, _kind in P._DERIVED_ARTEFACT_GENERATORS:
        if not (PROGRAMS / gen).is_file():
            continue
        extra = ("--top", "chip_top") if gen == "foundry_handoff_pack_gen.py" else ()
        _run(tmp_path, gen, *extra)
    present = _foundry_present(tmp_path)
    assert present, "checklist must enumerate the foundry items"
    assert all(v is True for v in present.values()), present


def test_e2e_wrong_order_reproduces_missing(tmp_path):
    # GUARD: the pre-#621 order (checklist BEFORE foundry) leaves the foundry
    # items present=False — the 現象 the reorder fixes.
    _run(tmp_path, "tapeout_checklist_gen.py")  # no foundry files yet
    present = _foundry_present(tmp_path)
    assert all(v is False for v in present.values()), present
