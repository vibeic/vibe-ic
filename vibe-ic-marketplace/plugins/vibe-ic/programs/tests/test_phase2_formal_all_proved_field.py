"""tests/test_phase2_formal_all_proved_field.py — REWRITTEN for #440.

HISTORY: v1.6.53 introduced (and this file used to pin) a derivation
where `all_proved` was COMPUTED from the simulation verdict
(vectors_passed == vectors_total, or verdict == PASS). ORGANIC-20260606
#440 identified that doctrine as the root cause of "formal is a
re-label of the sim verdict": a TB run is not a proof, so `all_proved`
may only ever be written by an actual proof tool (SymbiYosys).

This file now pins the INVERSE contract:
  * the runner source carries NO sim→all_proved derivation;
  * no placeholder .sby (the old one referenced nonexistent rtl/*.sv
    and an `assertions_l3` top no class generates);
  * a missing proof emits formal_not_run.json with the assertion-gen
    fallback direction and NEVER formal/results.json;
  * an existing (AI-authored, real-proof) results.json is not clobbered;
  * step 5 is a named platform capability gap (cap:formal_property_proof).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flow_compliance_check as F  # noqa: E402

PROGRAMS = Path(__file__).resolve().parent.parent
_SRC = (PROGRAMS / "design_one_shot_runner.py").read_text()


def test_no_sim_to_all_proved_derivation_in_runner():
    # the v1.6.53 derivation shapes are gone from the FORMAL step: the
    # Step-5 window never reads sim results nor computes all_proved
    assert "_derive_all_proved" not in _SRC
    i = _SRC.index("Step 5: formal")
    window = _SRC[i:i + 2600]
    # the copy/derivation shapes are gone: nothing is READ from the sim
    # results and `all_proved` is never WRITTEN by the runner
    assert "json.loads" not in window
    assert '"all_proved": ' not in window


def test_no_placeholder_sby():
    assert "prep -top assertions_l3" not in _SRC
    assert "formal task placeholder" not in _SRC


def test_formal_not_run_manifest_carries_fallback_direction():
    # v1.5.58 — the Step-5 formal engine is now WIRED (formal_harness_gen +
    # abc pdr), so the runner mentions formal_not_run.json first in the block
    # comment and only WRITES it in the FAIL-SAFE tail. Locate the WRITE site
    # (rindex = the `.write_text` call), not the first textual mention, then
    # assert the SKIP manifest STILL carries the same fallback direction.
    i = _SRC.rindex("formal_not_run.json")
    window = _SRC[i - 1800:i + 1400]
    assert '"fallback_skill": "assertion-gen"' in window
    assert "SKIPPED-CONDITION" in window
    assert "all_proved" in window  # documented as proof-run-only
    assert "#440" in window


def test_existing_real_results_not_clobbered():
    i = _SRC.index("NEVER clobber a real proof")
    window = _SRC[i:i + 1200]
    assert 'if not (formal_dir / "results.json").is_file():' in window


def test_step5_no_longer_a_capability_gap():
    # v1.3.99 — formal_property_run (real SymbiYosys, built-in ABC engines)
    # closed the LAST cap-gap: step 5 left the table and gates normally; an
    # absent proof is an honest MISSING unless the runner's formal_not_run.json
    # sentinel self-skips it (#608).
    assert 5 not in F._PLATFORM_CAPABILITY_GAPS
    assert F._PLATFORM_CAPABILITY_GAPS == {}


def test_registry_has_assertion_fallback():
    import json
    reg = json.loads((PROGRAMS / "ic_class_registry.json").read_text())
    for c in reg["classes"]:
        assert c.get("assertion_fallback_skill") == "assertion-gen", c["name"]
