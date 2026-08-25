"""`skill inventory fresh` — a skill folder that the committed inventory does
not know about.

WHAT THE GATE IS ASKING: `SKILL_INVENTORY.json` is DERIVED — its own `_comment`
says "generated from the skills/ folders ... Do NOT hand-edit; the website skill
count must read `total` from here". `--check` re-derives the list from the
folders and refuses when the committed file disagrees.

THE MUTATION IS THE GATE'S OWN DOCUMENTED DEFECT, named in the generator's first
paragraph: "that number drifts whenever a skill is added/removed (it is now 57
after benchmark-verify + design-for-eco landed)". A skill lands as a directory
with a `SKILL.md`, the inventory is not regenerated, and the published total is
one behind — silently, because a stale count and a correct one are the same
bytes to every reader.

BOTH ARMS HAVE THE SAME DENOMINATOR, and here that matters more than usual,
because the cheap way to redden this gate is to delete a skill folder or the
inventory itself. Neither would prove anything about the predicate: the
generator refuses a tree with no `skills/` directory outright, and a missing
inventory is its own separate refusal. So both arms carry the SAME THREE skill
folders and a committed inventory that is present and well-formed. What moves is
one row inside it: `can_pass` lists all three, `can_fail` lists two, which is
exactly the state a landing leaves behind when the folder is added and the
generator is not re-run.

THE SUBJECT IS A PLUGIN DIRECTORY because the declaration passes
`--plugin "$PLUGIN"`, and that flag is the reason this pair can exist at all —
the generator used to derive its subject from its own `__file__`, so the gate
and the tree it judges could not be pointed apart and no mutation was reachable.

chip-AGNOSTIC: three invented skill names, no IC, vendor, PDK or process.
"""
import json
from pathlib import Path

GATE = "skill inventory fresh"

#: Invented names. They must not collide with real skills, because the point is
#: that the gate reads THIS tree and not the repository's own.
_SKILLS = ("alpha-probe", "beta-probe", "gamma-probe")


def _tree(work: Path, leaf: str, committed) -> Path:
    root = work / leaf
    skills = root / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    for name in _SKILLS:
        d = skills / name
        d.mkdir(exist_ok=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\n---\n\nSynthetic fixture skill.\n",
            encoding="utf-8")
    (skills / "_classification.json").write_text(
        json.dumps({"tiers": {"verification": {"skills": list(_SKILLS)}}},
                   indent=2) + "\n", encoding="utf-8")
    (root / "SKILL_INVENTORY.json").write_text(
        json.dumps({
            "schema_version": 1,
            "_comment": "AUTHORITATIVE AI-skill inventory — generated from the "
                        "skills/ folders by programs/gen_skill_inventory.py.",
            "total": len(committed),
            "by_tier": {"verification": len(committed)},
            "skills": list(committed),
            "detail": [{"name": n, "frontmatter_name": n,
                        "tier": "verification"} for n in committed],
        }, indent=2) + "\n", encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """Three skill folders, and the committed inventory names all three: rc 0."""
    return _tree(work, "accepted", _SKILLS)


def can_fail(work: Path):
    """The same three folders on disk, with the third never written back into
    the inventory — a skill added and the generator not re-run. Same
    denominator, opposite answer."""
    root = _tree(work, "refused", _SKILLS[:2])
    return root, "on disk but not committed: ['%s']" % _SKILLS[2]
