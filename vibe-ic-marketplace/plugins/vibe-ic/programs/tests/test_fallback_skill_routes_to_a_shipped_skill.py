#!/usr/bin/env python3
"""A waive must not tell the agent to invoke a skill the tree does not ship.

MEASURED 2026-08-29 on subservient/gf180mcuD at v1.12.65 (and confirmed on main
at v1.12.67): `design_one_shot_runner` names four skills in `fallback_skill`,
and TWO of them do not exist under `skills/`:

    catalog-glue-author   OK
    spec-to-rtl           OK
    testbench-author      *** no such skill ***  (the shipped one is testbench-gen)
    assertion-gen         *** no such skill ***  (listed under
                          skills/_classification.json -> deprecated_skills,
                          i.e. removed on purpose, but still routed to)

This is the same failure family as the `--entry-step` help/guard drift: a name
the tree advertises that the tree cannot honour. It bites hardest where it did
here -- `step_reference_tb` WAIVES testbench authoring to `testbench-author`,
the agent cannot load it, hand-authors a TB instead, and the hand-authored TB
misses the undocumented `ORACLE_TB_DONE pass=<n>/<m>` contract that
`step_reference_tb` itself hard-FAILs on.

This test is the guard, not the fix: it fails on any future waive that routes
to a skill that is absent or deprecated.
"""
import json
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
RUNNER = PLUGIN / "programs" / "design_one_shot_runner.py"
SKILLS = PLUGIN / "skills"
CLASSIFICATION = SKILLS / "_classification.json"

_FALLBACK_RE = re.compile(r'"fallback_skill":\s*"([A-Za-z0-9\-_]+)"')


def _named_skills():
    return sorted(set(_FALLBACK_RE.findall(RUNNER.read_text(encoding="utf-8"))))


def _shipped_skills():
    return {p.name for p in SKILLS.iterdir() if p.is_dir()}


def _deprecated_skills():
    doc = json.loads(CLASSIFICATION.read_text(encoding="utf-8"))
    return set(doc.get("deprecated_skills", {}).get("skills", []))


def test_the_runner_actually_names_some_fallback_skills():
    """Guard the guard: a regex that matches nothing would pass vacuously."""
    named = _named_skills()
    assert len(named) >= 3, (
        f"expected the runner to name several fallback skills; got {named}. "
        "If the key was renamed, update _FALLBACK_RE -- do not delete this file.")


def test_every_fallback_skill_ships():
    named = _named_skills()
    shipped = _shipped_skills()
    missing = [n for n in named if n not in shipped]
    assert not missing, (
        f"design_one_shot_runner WAIVES to skill(s) that do not exist under "
        f"skills/: {missing}. An agent told to invoke a skill the tree does "
        f"not ship cannot follow the runner's own instruction. Shipped skills "
        f"with a similar name: "
        f"{ {m: sorted(s for s in shipped if m.split('-')[0] in s) for m in missing} }")


def test_no_fallback_skill_is_a_deprecated_one():
    """Absent is one failure; deliberately-removed-and-still-routed-to is worse."""
    named = _named_skills()
    deprecated = _deprecated_skills()
    routed_to_dead = [n for n in named if n in deprecated]
    assert not routed_to_dead, (
        f"design_one_shot_runner WAIVES to skill(s) that skills/"
        f"_classification.json records under deprecated_skills: "
        f"{routed_to_dead}. A skill removed on purpose must not stay the "
        f"routing target of a live waive.")


# --------------------------------------------------------------------------
# CONTROLS -- these hold on main too; the fix must not have moved them.
# --------------------------------------------------------------------------
def test_control_the_two_already_correct_routes_are_untouched():
    named = _named_skills()
    for still in ("catalog-glue-author", "spec-to-rtl"):
        assert still in named, f"{still} must remain a fallback route"
        assert (SKILLS / still).is_dir()


def test_control_the_classification_file_is_readable_and_lists_deprecations():
    dep = _deprecated_skills()
    assert dep, "deprecated_skills must be non-empty, or this guard is vacuous"
    assert "assertion-gen" in dep, (
        "assertion-gen is the recorded deprecation this guard was written "
        "against; if it were un-deprecated the fix would need revisiting")


def test_control_skills_dir_is_populated():
    assert len(_shipped_skills()) > 20


# --------------------------------------------------------------------------
# The registry routes too, and it routed every class at both dead names:
# 13 classes at `assertion-gen` and 12 at `testbench-author`.
# --------------------------------------------------------------------------
REGISTRY = PLUGIN / "programs" / "ic_class_registry.json"

_SKILL_KEY = re.compile(r"skill$")


def _registry_skill_routes():
    """[(class_name, key, skill), ...] for every *_skill key in the registry."""
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    out = []
    for c in reg["classes"]:
        for k, v in c.items():
            if _SKILL_KEY.search(k) and isinstance(v, str) and v:
                out.append((c["name"], k, v))
    return out


def test_the_registry_actually_routes_to_skills():
    """Guard the guard: no routes found would pass vacuously."""
    routes = _registry_skill_routes()
    assert len(routes) >= 10, f"expected many registry skill routes; got {routes}"


def test_every_registry_skill_route_ships():
    shipped = _shipped_skills()
    bad = [(c, k, v) for c, k, v in _registry_skill_routes() if v not in shipped]
    assert not bad, (
        f"ic_class_registry.json routes to skill(s) that do not exist under "
        f"skills/: {sorted({v for _, _, v in bad})} "
        f"(affecting {len(bad)} class/key pair(s))")


def test_no_registry_skill_route_is_deprecated():
    deprecated = _deprecated_skills()
    bad = [(c, k, v) for c, k, v in _registry_skill_routes() if v in deprecated]
    assert not bad, (
        f"ic_class_registry.json routes to DEPRECATED skill(s): "
        f"{sorted({v for _, _, v in bad})} "
        f"(affecting {len(bad)} class/key pair(s))")
