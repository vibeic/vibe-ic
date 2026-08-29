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

import json
import re
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
    # The DIRECTION is what this pins, not a particular name. It used to pin
    # the literal "assertion-gen", which skills/_classification.json records
    # under `deprecated_skills` -- so the assertion held while the manifest
    # sent operators to a skill the tree does not ship. Pin the property
    # instead, which is strictly stronger: a fallback direction is present AND
    # it names a skill that actually exists and is not deprecated.
    m = re.search(r'"fallback_skill": "([A-Za-z0-9\-_]+)"', window)
    assert m, "the SKIP manifest must still carry a fallback direction"
    _skill = m.group(1)
    _skills_dir = PROGRAMS.parent / "skills"
    assert (_skills_dir / _skill).is_dir(), (
        f"formal_not_run.json routes to skill {_skill!r}, which does not ship")
    _dep = json.loads((_skills_dir / "_classification.json").read_text()
                      ).get("deprecated_skills", {}).get("skills", [])
    assert _skill not in _dep, (
        f"formal_not_run.json routes to {_skill!r}, a DEPRECATED skill")
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
    """Every class carries an assertion fallback, and it must be a REAL skill.

    This used to pin the literal "assertion-gen" for all 13 classes. That skill
    is recorded under `deprecated_skills` in skills/_classification.json, so
    the pin was holding the registry to a name the tree deliberately removed.
    The requirement it was protecting -- every class states where assertion
    work goes -- is kept and strengthened.
    """
    reg = json.loads((PROGRAMS / "ic_class_registry.json").read_text())
    skills_dir = PROGRAMS.parent / "skills"
    deprecated = json.loads((skills_dir / "_classification.json").read_text()
                            ).get("deprecated_skills", {}).get("skills", [])
    assert reg["classes"], "registry must list classes"
    for c in reg["classes"]:
        skill = c.get("assertion_fallback_skill")
        assert skill, f"{c['name']}: no assertion_fallback_skill"
        assert (skills_dir / skill).is_dir(), (
            f"{c['name']}: assertion_fallback_skill {skill!r} does not ship")
        assert skill not in deprecated, (
            f"{c['name']}: assertion_fallback_skill {skill!r} is DEPRECATED")
