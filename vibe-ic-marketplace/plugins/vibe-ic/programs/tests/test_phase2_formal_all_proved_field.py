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
  * applicable unauthored work emits an INCOMPLETE request with exact IDs and
    a real formal-verify route, never a skip;
  * an existing (AI-authored, real-proof) results.json is not clobbered;
  * step 5 is not a platform/open-source capability gap while sby/yosys ship.
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


def test_formal_authoring_request_carries_real_fallback_not_skip():
    i = _SRC.index("Issue #1974")
    window = _SRC[i:i + 6000]
    m = re.search(r'"fallback_skill": "([A-Za-z0-9\-_]+)"', window)
    assert m, "the INCOMPLETE request must carry a fallback direction"
    _skill = m.group(1)
    _skills_dir = PROGRAMS.parent / "skills"
    assert (_skills_dir / _skill).is_dir(), (
        f"formal_authoring_request routes to {_skill!r}, which does not ship")
    _dep = json.loads((_skills_dir / "_classification.json").read_text()
                      ).get("deprecated_skills", {}).get("skills", [])
    assert _skill not in _dep, (
        f"formal_authoring_request routes to {_skill!r}, a DEPRECATED skill")
    assert '"verdict": "INCOMPLETE"' in window
    assert "formal_not_run.json" not in window
    assert "unresolved_obligations" in window


def test_existing_real_results_not_clobbered():
    i = _SRC.index("Issue #1974")
    window = _SRC[i:i + 6500]
    assert 'if not (formal_dir / "results.json").is_file():' in window
    assert 'written.append("formal/results.json")' in window
    assert '.unlink()' not in window, "a failed proof/counterexample was deleted"


def test_issue1974_runner_never_replaces_formal_failure_with_skip():
    """Compatible pre-fix control: inspect the public Step-5 source window."""
    start = _SRC.index("Step 5: formal")
    end = _SRC.index("Step 6: FPGA", start)
    window = _SRC[start:end]
    assert "formal_not_run.json" not in window
    assert "_rp.unlink()" not in window
    assert "formal_authoring_request.json" in window


def test_step5_no_longer_a_capability_gap():
    # SymbiYosys + Yosys ship in the pinned image. A missing property route is
    # therefore an INCOMPLETE design-to-property obligation, not a platform or
    # open-source-container capability gap.
    assert 5 not in F._PLATFORM_CAPABILITY_GAPS
    assert F._PLATFORM_CAPABILITY_GAPS == {}
    assert 5 not in F._OPEN_SOURCE_CONTAINER_BLOCKED_STEPS


def test_phase2_command_actually_invokes_formal_verify_fallback():
    command = (PROGRAMS.parent / "commands" / "vibe-ic-phase2.md").read_text()
    assert "formal_authoring_request.json" in command
    assert "invoke `formal-verify` now" in command
    assert "invocation_status: INVOKED" in command
    assert "never replace it with a skip" in command


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
