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
