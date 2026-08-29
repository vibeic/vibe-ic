#!/usr/bin/env python3
"""_skill_routes.py — shared helper for SKILL-ROUTING tests.

A `fallback_skill` value is a ROUTE: the flow hands that name to an agent and
tells it to invoke that skill. A route that names a skill the tree does not
ship is not cosmetic — the agent cannot load it, so it improvises, and the
improvised artefact misses contracts the step hard-FAILs on (measured on a
benchmark IC at v1.12.65, fixed as v1.12.76).

Own module, not conftest.py, for the reason `_source_pin.py` records: there
are TWO conftest.py files on the path, so a bare `from conftest import ...`
resolves to whichever pytest imported first.

WHY THIS EXISTS AT ALL — the lesson from v1.12.76. Four tests asserted

    registry.tb_fallback_skill == "testbench-author"

and were GREEN for the entire time that routing was broken, because
`testbench-author` is a string, and a string is always equal to itself. A test
that pins the NAME of a route cannot tell you whether the route LEADS anywhere.
Prefer `assert_route_ships(...)` — it pins the property (the agent can follow
this instruction) instead of the literal (the instruction reads exactly so).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
SKILLS = PLUGIN / "skills"
CLASSIFICATION = SKILLS / "_classification.json"

# A `fallback_skill` key whose value is a plain string literal.
FALLBACK_LITERAL_RE = re.compile(r'"fallback_skill":\s*"([A-Za-z0-9\-_]+)"')
# Every `fallback_skill` key, literal-valued or not. The difference between the
# two counts is this helper's own BLIND SPOT, and callers assert it is zero.
FALLBACK_KEY_RE = re.compile(r'"fallback_skill":')


def shipped_skills() -> set[str]:
    """Skill names the tree actually ships (a directory under skills/)."""
    return {p.name for p in SKILLS.iterdir() if p.is_dir()}


def deprecated_skills() -> set[str]:
    """Skills the tree records as removed on purpose."""
    doc = json.loads(CLASSIFICATION.read_text(encoding="utf-8"))
    return set(doc.get("deprecated_skills", {}).get("skills", []))


def routing_sources() -> list[Path]:
    """Every non-test program source that could emit a route.

    v1.12.76 guarded ONE file (design_one_shot_runner.py). Three live routes in
    three OTHER programs kept naming skills that do not ship, and the guard
    could not see them because it never opened those files.
    """
    return sorted(p for p in PROGRAMS.rglob("*.py") if "tests" not in p.parts)


def assert_route_ships(skill: str | None, where: str) -> None:
    """The property the four v1.12.76-era literal pins should have asserted.

    `skill` may be None only where the caller has already established that a
    null route is the contract; pass a non-None value otherwise.
    """
    shipped = shipped_skills()
    assert skill, f"{where}: expected a fallback skill route, got {skill!r}"
    assert skill in shipped, (
        f"{where}: routes at skill {skill!r}, which does not exist under "
        f"{SKILLS}. An agent told to invoke a skill the tree does not ship "
        f"cannot follow the instruction. Similarly-named shipped skills: "
        f"{sorted(s for s in shipped if skill.split('-')[0] in s)}")
    assert skill not in deprecated_skills(), (
        f"{where}: routes at skill {skill!r}, which _classification.json "
        f"records under deprecated_skills. A skill removed on purpose must "
        f"not stay the target of a live route.")


# ---------------------------------------------------------------------------
# THE THIRD ROUTING TABLE, AND THE BIGGEST ONE: the canonical flow.
#
# v1.12.76 guarded the runner; v1.12.89 widened that to every production
# program and factored this module so there would be ONE answer to "which
# names must ship". `flow/phase1_phase2_phase3.yaml` was still outside it, and
# it is the largest table of the three. MEASURED at v1.12.82:
#
#     the flow names 56 skills across its steps. ONLY 25 SHIP. 31 DO NOT.
#
# A flow `skills:` entry is a route in exactly the sense this module's
# docstring defines: the step hands the name to an agent and tells it to invoke
# that skill. Same defect, same damage, one more table -- so it belongs here
# rather than in a fourth copy of "which names must ship".
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"


def flow_doc():
    import yaml  # already a test dependency -- flow_compliance_check.py uses it
    return yaml.safe_load(FLOW.read_text(encoding="utf-8"))


def iter_flow_steps(node):
    """Every step-shaped mapping in the canonical flow, at any nesting depth."""
    if isinstance(node, dict):
        if "id" in node and ("name" in node or "stage" in node):
            yield node
        for v in node.values():
            yield from iter_flow_steps(v)
    elif isinstance(node, list):
        for v in node:
            yield from iter_flow_steps(v)


def flow_skill_routes():
    """[(step_id, stage, skill), ...] for every skill the canonical flow names.

    PARSES the YAML; never pattern-matches it. That is not a style preference,
    it is the finding: `skills:` is written BOTH inline (`skills: [a, b]`) and
    BLOCK-style (`skills:` then `- name`) in one file, and the first
    measurement of this hole reported FOURTEEN ghosts because it matched only
    the inline spelling. The seventeen it missed were the single largest
    cluster, all on step D1. One file, two spellings, and a line pattern sees
    one of them -- confidently, and with no way to know it is under-reporting.
    """
    out = []
    for s in iter_flow_steps(flow_doc()):
        for skill in (s.get("skills") or []):
            if isinstance(skill, str) and skill:
                out.append((str(s.get("id")), str(s.get("stage") or ""), skill))
    return out


def unbuilt_skills() -> dict:
    """Names a routing table named that were NEVER AUTHORED.

    Distinct from `deprecated_skills`, which were built and archived on
    purpose. Recorded rather than silently deleted so that a step advertising
    work the tree cannot do stays visible and cannot quietly return.
    """
    doc = json.loads(CLASSIFICATION.read_text(encoding="utf-8"))
    return doc.get("unbuilt_skills", {}).get("skills", {})
