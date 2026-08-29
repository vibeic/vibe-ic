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

WIDENED (this change). The guard as landed opened exactly TWO files -- the
runner and the registry -- so three live routes in three OTHER programs kept
naming skills that do not ship and stayed green:

    oracle_tb_gen.py:154        testbench-author  (absent)
    arith_oracle_tb_gen.py:1154 testbench-author  (absent)
    formal_property_run.py:1050 assertion-gen     (absent AND deprecated)

It now scans every non-test program source. COVERAGE ARGUMENT: of the 19
`fallback_skill` sites in those sources, 10 carry a string literal and are read
directly here; 2 are an explicit None (a deliberate no-route); 2 forward a value
they were handed; and the remaining 5 resolve from `ic_class_registry.json`
(`config.get("fallback_skill")` / `_rtl_repair_inert_fallback` ->
`_lookup_class`), which the registry half of this file already checks. Both
channels are asserted non-empty below, so neither can go blind silently.
"""
import json
import re

from _skill_routes import (
    FALLBACK_KEY_RE,
    FALLBACK_LITERAL_RE,
    PLUGIN,
    SKILLS,
    deprecated_skills as _deprecated_skills,
    routing_sources,
    shipped_skills as _shipped_skills,
)

RUNNER = PLUGIN / "programs" / "design_one_shot_runner.py"

_FALLBACK_RE = FALLBACK_LITERAL_RE


def _named_routes():
    """[(source_path, skill), ...] over EVERY non-test program source."""
    out = []
    for src in routing_sources():
        for skill in _FALLBACK_RE.findall(src.read_text(encoding="utf-8",
                                                        errors="replace")):
            out.append((src, skill))
    return out


def _named_skills():
    return sorted({s for _, s in _named_routes()})


def test_the_runner_actually_names_some_fallback_skills():
    """Guard the guard: a regex that matches nothing would pass vacuously."""
    named = _named_skills()
    assert len(named) >= 3, (
        f"expected the runner to name several fallback skills; got {named}. "
        "If the key was renamed, update _FALLBACK_RE -- do not delete this file.")


def test_every_fallback_skill_ships():
    shipped = _shipped_skills()
    missing = sorted({f"{p.name}:{n}" for p, n in _named_routes()
                      if n not in shipped})
    assert not missing, (
        f"program source(s) WAIVE to skill(s) that do not exist under "
        f"skills/: {missing}. An agent told to invoke a skill the tree does "
        f"not ship cannot follow the runner's own instruction. Shipped skills "
        f"with a similar name: "
        f"{missing}")


def test_no_fallback_skill_is_a_deprecated_one():
    """Absent is one failure; deliberately-removed-and-still-routed-to is worse."""
    deprecated = _deprecated_skills()
    routed_to_dead = sorted({f"{p.name}:{n}" for p, n in _named_routes()
                             if n in deprecated})
    assert not routed_to_dead, (
        f"program source(s) WAIVE to skill(s) that skills/"
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


# --------------------------------------------------------------------------
# CONTROLS ON THE WIDENING ITSELF.
# The guard's original blind spot was its FILE SET, not its regex, so the
# thing that must not silently revert is the file set.
# --------------------------------------------------------------------------
def test_the_scan_is_strictly_wider_than_the_runner_alone():
    """The widening must not collapse back to one file."""
    srcs = routing_sources()
    assert RUNNER in srcs, "the runner must still be scanned"
    files = {p for p, _ in _named_routes()}
    assert len(files) >= 3, (
        f"only {sorted(p.name for p in files)} carry a literal fallback_skill "
        f"route. Three programs beyond the runner carried one when this "
        f"widening was written; if a route moved, follow it -- do not narrow "
        f"the scan back to design_one_shot_runner.py alone.")
    assert len(srcs) > 100, f"routing_sources() collapsed to {len(srcs)} files"


def test_the_variable_valued_routes_are_covered_by_the_registry_channel():
    """Both channels must be non-empty, or the coverage argument is vacuous.

    A `fallback_skill` whose value is not a string literal is invisible to
    FALLBACK_LITERAL_RE. Those sites resolve from ic_class_registry.json, which
    the registry tests above check. This asserts the two channels actually
    carry traffic -- if either emptied, the guard would still be green while
    covering nothing.
    """
    keys = literals = 0
    for src in routing_sources():
        text = src.read_text(encoding="utf-8", errors="replace")
        keys += len(FALLBACK_KEY_RE.findall(text))
        literals += len(FALLBACK_LITERAL_RE.findall(text))
    assert literals >= 5, f"literal channel carries only {literals} route(s)"
    assert keys > literals, (
        "no non-literal fallback_skill site remains; if every route became a "
        "literal the registry channel is no longer load-bearing here -- "
        "re-read the coverage argument in this module's docstring.")
    assert len(_registry_skill_routes()) >= 10, "registry channel is empty"
