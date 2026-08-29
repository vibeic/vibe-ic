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
    FLOW,
    PLUGIN,
    SKILLS,
    deprecated_skills as _deprecated_skills,
    flow_doc as _flow_doc,
    flow_skill_routes as _flow_skill_routes,
    iter_flow_steps as _iter_flow_steps,
    routing_sources,
    shipped_skills as _shipped_skills,
    unbuilt_skills as _unbuilt,
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


# --------------------------------------------------------------------------
# THE THIRD ROUTING TABLE, AND THE BIGGEST ONE.
#
# v1.12.76 guarded the runner. v1.12.89 widened that to every production
# program, for the reason it names: the rename "missed the messages the agent
# actually reads". The canonical FLOW was still outside both, and it is the
# largest table of the three. MEASURED on main at v1.12.82:
#
#     flow/phase1_phase2_phase3.yaml names 56 skills. ONLY 25 SHIP. 31 DO NOT.
#
# and the flow's own `stage:` field says WHICH PART OF THE FLOW each hole is in
# -- which matters, because "31 scattered names" and "stage2 is missing four of
# its AI half" are different statements and only the second is actionable:
#
#     stage_phase1        17   the whole "Entry B" per-layer doc-gen chain (D1)
#     stage1               4   assertion-gen cdc-check fpga-test-harness
#                              rdc-check
#     stage2               4   atpg constraint-gen dft-insert sdc-validator
#     stage3               4   cts-plan em-check perc-check placement-optimize
#     stage4               2   fpga-test-harness power-analysis
#     stage_mixed_signal   1   flow-orchestrate
#
# so `test_every_flow_skill_ships` reports BY STAGE, not as a flat list.
FLOW_STAGE_HINT = "grouped by the flow's own `stage:` field"


def test_the_flow_actually_routes_to_skills():
    """Guard the guard: no routes found would pass vacuously."""
    routes = _flow_skill_routes()
    assert len(routes) >= 25, (
        f"expected the canonical flow to name many skills; got {len(routes)}. "
        "If `skills:` was renamed, update _skill_routes -- do not delete this.")


def test_the_flow_parser_sees_both_yaml_list_spellings():
    """The blind spot that made this hole first measure 14 instead of 31.

    `skills:` is written BOTH inline (`skills: [a, b]`) and block-style
    (`skills:` then `- name`) in ONE file. A reader that sees only one spelling
    under-reports silently and confidently -- and the spelling it missed held
    the 17 largest. This pins that the parser reaches both, so nobody can
    regress it back into a line matcher.
    """
    text = FLOW.read_text(encoding="utf-8")
    assert re.search(r"^\s*skills:\s*\[", text, re.M), (
        "expected at least one INLINE `skills: [...]` list in the flow")
    assert re.search(r"^\s*skills:\s*$", text, re.M), (
        "expected at least one BLOCK-STYLE `skills:` list in the flow; if the "
        "last one was converted to inline, relax this DELIBERATELY -- do not "
        "let the reader quietly become a line matcher again")
    assert [sid for sid, _, _ in _flow_skill_routes() if sid == "D1"], (
        "step D1 writes its `skills:` list in block style and the parser must "
        "see it; a reader that misses it under-reports this guard by 17 names")


def test_every_flow_skill_ships():
    shipped = _shipped_skills()
    bad = [(sid, stage, sk) for sid, stage, sk in _flow_skill_routes()
           if sk not in shipped]
    by_stage = {}
    for _sid, stage, sk in bad:
        by_stage.setdefault(stage or "(no stage)", set()).add(sk)
    assert not bad, (
        f"flow/phase1_phase2_phase3.yaml routes to skill(s) that do not exist "
        f"under skills/, {FLOW_STAGE_HINT}: "
        f"{ {k: sorted(v) for k, v in sorted(by_stage.items())} }. "
        f"A step whose AI half names a skill the tree does not ship cannot be "
        f"followed: the agent hand-authors instead, and the hand-authored "
        f"artefact misses contracts the step hard-FAILs on. If the skill "
        f"genuinely should exist, record it under `unbuilt_skills` in "
        f"skills/_classification.json and remove it from the flow -- an "
        f"explicit gap, NEVER an empty stub authored to make this test green.")


def test_no_flow_skill_is_a_deprecated_one():
    """Absent is one failure; removed-on-purpose-and-still-routed-to is worse."""
    deprecated = _deprecated_skills()
    bad = [(sid, stage, sk) for sid, stage, sk in _flow_skill_routes()
           if sk in deprecated]
    assert not bad, (
        f"the canonical flow routes to DEPRECATED skill(s): {bad}. A skill "
        f"archived on purpose must not stay the routing target of a live step.")


# --------------------------------------------------------------------------
# The gap record. A ghost deleted and written down NOWHERE is a flow that got
# quietly narrower; these keep the record honest and stop it rotting.
# --------------------------------------------------------------------------
def test_the_unbuilt_record_is_populated():
    """Guard the guard: an empty record makes the three below vacuous."""
    assert len(_unbuilt()) >= 20, (
        f"unbuilt_skills must record the names removed from the routing; got "
        f"{sorted(_unbuilt())}")


def test_no_unbuilt_skill_is_still_routed_to_anywhere():
    """The record describes names that are GONE -- from ALL THREE tables."""
    unbuilt = set(_unbuilt())
    still = sorted(
        {sk for _, _, sk in _flow_skill_routes() if sk in unbuilt}
        | {v for _, _, v in _registry_skill_routes() if v in unbuilt}
        | {n for n in _named_skills() if n in unbuilt})
    assert not still, (
        f"{still} are recorded as never-built yet are still routed to. The "
        f"record documents a REMOVED route; it does not license keeping one.")


def test_no_unbuilt_skill_secretly_ships():
    """If one gets built, its record must go -- or the gap list lies."""
    both = sorted(set(_unbuilt()) & _shipped_skills())
    assert not both, (
        f"{both} ship under skills/ but are still recorded as unbuilt. Delete "
        f"the entry in the same change that builds the skill.")


def test_unbuilt_and_deprecated_are_disjoint():
    """Never-authored and built-then-archived are different facts."""
    both = sorted(set(_unbuilt()) & _deprecated_skills())
    assert not both, (
        f"{both} are recorded as BOTH never-built and deprecated. A name is "
        f"one or the other; deprecated means it was built, then archived.")


def test_every_unbuilt_entry_declares_its_stage_and_status():
    bad = [n for n, e in _unbuilt().items()
           if not e.get("stages") or not e.get("note")
           or e.get("status") not in ("gap", "covered")]
    assert not bad, (
        f"every unbuilt_skills entry needs `stages`, a `status` of "
        f"gap|covered, and a `note` giving the evidence; malformed: {bad}")


# --------------------------------------------------------------------------
# CONTROLS for the flow half -- these hold on main too and MUST NOT MOVE.
# --------------------------------------------------------------------------
def test_control_the_flow_still_names_the_skills_that_always_shipped():
    """Repointing must not have emptied the flow of its working routes."""
    named = {sk for _, _, sk in _flow_skill_routes()}
    for still in ("drc-fix", "lvs-triage", "formal-verify", "fpga-signaltap",
                  "analog-flow-orchestrate", "sta-review", "phase1"):
        assert still in named, (
            f"{still} ships and was a correct flow route before this fix; it "
            f"must remain one")
        assert (SKILLS / still).is_dir()


def test_control_every_stage_that_named_skills_still_names_some():
    """A stage silently emptied of its AI half is the failure this guard
    PREVENTS, not a way to pass it."""
    per_stage = {}
    for _sid, stage, sk in _flow_skill_routes():
        per_stage.setdefault(stage, set()).add(sk)
    for stage in ("stage_analog", "stage_mixed_signal", "stage_phase1",
                  "stage3", "stage4"):
        assert per_stage.get(stage), f"{stage} must still name at least one skill"
    assert len(per_stage["stage_analog"]) >= 11, (
        "stage_analog named 11 shipping skills and this fix does not touch it")


def test_control_the_flow_file_is_the_canonical_one():
    assert FLOW.is_file()
    doc = _flow_doc()
    assert isinstance(doc, dict) and doc, "flow yaml must parse to a mapping"
    assert len(list(_iter_flow_steps(doc))) >= 70, (
        "expected the full canonical step set; a truncated parse would make "
        "every assertion above vacuous")
