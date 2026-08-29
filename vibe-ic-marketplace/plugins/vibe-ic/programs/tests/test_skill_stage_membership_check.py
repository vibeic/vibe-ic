#!/usr/bin/env python3
"""The stage axis must be able to go RED, or it is not a classification.

MEASURED on main at v1.12.93: 70 shipped skills, a stage named 29, and FORTY-ONE
belonged to no stage -- including seven of the eight `verification`-tier skills,
the tier whose own description is "Run AFTER program PASS to spot-check the
deterministic output". Two stages named ZERO skills while carrying real steps:
stage_phase1 (2) and stage5_manufacturing (5).

The point of this file is the FIXTURE tests. A checker that only ever runs
against the real tree, where everything is declared, cannot demonstrate that it
would refuse anything -- that is the "place to put everything" failure. Each
rule below is proved on a purpose-built tree that VIOLATES it, and the real
tree is the control that must stay green.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAM = PLUGIN / "programs" / "skill_stage_membership_check.py"
CLASSIFICATION = PLUGIN / "skills" / "_classification.json"


def _run(plugin: Path):
    r = subprocess.run([sys.executable, str(PROGRAM), "--plugin", str(plugin)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def _axis():
    return json.loads(CLASSIFICATION.read_text(encoding="utf-8"))["stage_axis"]


# ---------------------------------------------------------------------------
# ASSERTIONS ON THE SHIPPED TREE. These are NOT the controls: removing the
# declaration SHOULD turn them red, and measured, it turns exactly these six
# red while naming all 41 skills. The CONTROLS are the fixture tests at the
# bottom -- they must hold whether or not the shipped declaration exists, and
# measured, all seven stay green in both arms. That asymmetry is what makes
# the six reds mean something.
# ---------------------------------------------------------------------------
def test_the_real_tree_places_every_shipped_skill():
    rc, out = _run(PLUGIN)
    assert rc == 0, f"expected exit 0 on the shipped tree, got {rc}:\n{out}"
    assert "no unplaced skill" in out


def test_shipped_axis_actually_places_a_lot():
    """Guard the guard: a near-empty declaration would pass vacuously."""
    axis = _axis()
    total = sum(len(axis[b]) for b in ("stages", "stage_all", "off_flow"))
    assert total >= 35, f"the declaration places only {total} skills"


def test_shipped_stage_all_stayed_a_claim_not_a_bucket():
    """The trap the value was named to avoid."""
    n = len(_axis()["stage_all"])
    assert n <= 6, (
        f"stage_all holds {n}. It asserts a skill is useful at EVERY stage; at "
        f"this size it is a dumping ground and the axis carries no information.")
    assert n >= 1, "an empty stage_all makes the ceiling test vacuous"


def test_shipped_two_previously_empty_stages_now_name_skills():
    """stage_phase1 and stage5_manufacturing carried real steps and named zero
    skills. That is the gap this axis was built to make visible."""
    declared = {}
    for bucket in ("stages", "stage_all", "off_flow"):
        declared.update(_axis()[bucket])
    for stage in ("stage_phase1", "stage5_manufacturing"):
        holders = [s for s, e in declared.items() if stage in e["stages"]]
        assert holders, f"{stage} still names no skill"


def test_shipped_every_entry_says_why():
    """A classification without evidence is an opinion."""
    for bucket in ("stages", "stage_all", "off_flow"):
        for name, entry in _axis()[bucket].items():
            assert entry.get("stages"), f"{name} declares no stage"
            assert len(entry.get("why", "")) >= 40, (
                f"{name} has no substantive `why`; the axis must be "
                f"falsifiable by reading what the skill reads")


def test_shipped_no_declared_skill_is_unbuilt_or_deprecated():
    doc = json.loads(CLASSIFICATION.read_text(encoding="utf-8"))
    dead = set(doc.get("deprecated_skills", {}).get("skills", [])) | set(
        doc.get("unbuilt_skills", {}).get("skills", {}))
    declared = set()
    for bucket in ("stages", "stage_all", "off_flow"):
        declared |= set(_axis()[bucket])
    assert not (declared & dead), (
        f"{sorted(declared & dead)} are placed on the stage axis but are "
        f"recorded as deprecated or never-built. Only SHIPPED skills belong.")


# ---------------------------------------------------------------------------
# FIXTURES -- THE CONTROLS. Each proves the checker REFUSES something, on a
# purpose-built tree, independently of what the shipped tree declares. Without
# these the green above says only "nothing was tried"; with them, a checker
# that had quietly stopped refusing anything would be caught here.
# ---------------------------------------------------------------------------
_FLOW = """
stages:
  - id: stage1
    name: "RTL"
  - id: stage3
    name: "Physical"
steps:
  - id: 1
    name: "author"
    stage: stage1
    skills: [wired-skill]
  - id: 2
    name: "route"
    stage: stage3
"""


def _tree(root: Path, skills, axis) -> Path:
    plugin = root / "plug"
    (plugin / "flow").mkdir(parents=True)
    (plugin / "flow" / "phase1_phase2_phase3.yaml").write_text(_FLOW)
    for s in skills:
        d = plugin / "skills" / s
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {s}\n---\n")
    (plugin / "skills" / "_classification.json").write_text(
        json.dumps({"stage_axis": axis}))
    return plugin


def _entry(stages):
    return {"stages": stages, "why": "fixture entry, long enough to satisfy the why rule"}


def test_fixture_an_undeclared_skill_is_RED(tmp_path):
    """THE STATE THE AXIS MUST BE ABLE TO REACH. A skill in no stage, not
    stage_all and not off_flow, is a reportable gap."""
    plugin = _tree(tmp_path, ["wired-skill", "orphan-skill"],
                   {"stages": {}, "stage_all": {}, "off_flow": {}})
    rc, out = _run(plugin)
    assert rc == 1, f"an unplaced skill must be RED, got {rc}:\n{out}"
    assert "P1 UNPLACED" in out and "orphan-skill" in out
    assert "wired-skill" not in out.split("P1 UNPLACED")[1].split("]")[0], (
        "wired-skill is named by a step and must be DERIVED, not reported")


def test_fixture_declaring_a_flow_wired_skill_is_RED(tmp_path):
    """P4 -- the second declaration. One premise, one place."""
    plugin = _tree(tmp_path, ["wired-skill"],
                   {"stages": {"wired-skill": _entry(["stage1"])},
                    "stage_all": {}, "off_flow": {}})
    rc, out = _run(plugin)
    assert rc == 1 and "P4 DOUBLE DECLARATION" in out, out


def test_fixture_an_invented_stage_is_RED(tmp_path):
    """P2 -- a typo must not silently create a stage nobody runs."""
    plugin = _tree(tmp_path, ["wired-skill", "x"],
                   {"stages": {"x": _entry(["stage_typo"])},
                    "stage_all": {}, "off_flow": {}})
    rc, out = _run(plugin)
    assert rc == 1 and "P2 UNKNOWN STAGE" in out, out


def test_fixture_stage_all_mixed_with_a_named_stage_is_RED(tmp_path):
    """P5 -- stage_all is a whole-skill verdict. 'all, and also stage1' is
    the blur the rename from stage_general was meant to prevent."""
    plugin = _tree(tmp_path, ["wired-skill", "x"],
                   {"stages": {}, "off_flow": {},
                    "stage_all": {"x": _entry(["stage_all", "stage1"])}})
    rc, out = _run(plugin)
    assert rc == 1 and "P5" in out, out


def test_fixture_a_bloated_stage_all_is_RED(tmp_path):
    """P6 -- the dumping-ground trap, made mechanical."""
    names = [f"s{i}" for i in range(12)]
    plugin = _tree(tmp_path, ["wired-skill"] + names,
                   {"stages": {}, "off_flow": {},
                    "stage_all": {n: _entry(["stage_all"]) for n in names}})
    rc, out = _run(plugin)
    assert rc == 1 and "has become a bucket" in out, out


def test_fixture_unreadable_input_is_rc2_not_a_pass(tmp_path):
    """A missing input must never read as 'no findings'."""
    rc, out = _run(tmp_path / "nope")
    assert rc == 2, f"expected rc 2 for an unreadable tree, got {rc}:\n{out}"
    assert "PASS" not in out


def test_fixture_a_clean_tree_is_GREEN(tmp_path):
    """Falsify the other way: the fixtures above must fail for their RULE, not
    because any fixture tree fails."""
    plugin = _tree(tmp_path, ["wired-skill", "x", "y"],
                   {"stages": {"x": _entry(["stage3"])},
                    "stage_all": {}, "off_flow": {"y": _entry(["off_flow"])}})
    rc, out = _run(plugin)
    assert rc == 0, f"a fully-declared fixture must be green, got {rc}:\n{out}"


# ---------------------------------------------------------------------------
# A NAME IS NOT A PLACEMENT.
#
# P1 used to test membership by KEY PRESENCE -- `s in declared` -- so an entry
# whose `stages` was absent or `[]` still counted as placed. MEASURED on the
# shipped file: deleting `spec-review`'s entire `stages` list returned rc 0 and
# "70 skills placed ... no unplaced skill". Once every name was written down,
# no edit to the stages themselves could produce the only state P1 could see:
# a guard that could not say no about its own subject.
#
# `spec-review` is the right probe because it is SHIPPED and the flow names it
# NOWHERE, so it cannot fall back to derivation and hide the bug.
# ---------------------------------------------------------------------------
def test_fixture_a_declared_entry_with_no_stages_key_is_RED(tmp_path):
    plugin = _tree(tmp_path, ["wired-skill", "x"],
                   {"stages": {"x": {"why": "a why, but no stages key at all"}},
                    "stage_all": {}, "off_flow": {}})
    rc, out = _run(plugin)
    assert rc == 1, f"an entry with no `stages` key must be RED, got {rc}:\n{out}"
    assert "P1 UNPLACED" in out and "naming NO stage" in out and "'x'" in out


def test_fixture_a_declared_entry_with_an_empty_stages_list_is_RED(tmp_path):
    plugin = _tree(tmp_path, ["wired-skill", "x"],
                   {"stages": {"x": _entry([])}, "stage_all": {}, "off_flow": {}})
    rc, out = _run(plugin)
    assert rc == 1, f"an empty `stages` list must be RED, got {rc}:\n{out}"
    assert "P1 UNPLACED" in out and "naming NO stage" in out and "'x'" in out


def test_fixture_the_message_separates_never_declared_from_declared_but_empty(tmp_path):
    """They are fixed differently, so they must not read the same."""
    plugin = _tree(tmp_path, ["wired-skill", "listed", "absent"],
                   {"stages": {"listed": _entry([])}, "stage_all": {}, "off_flow": {}})
    rc, out = _run(plugin)
    assert rc == 1
    assert "not declared at all: ['absent']" in out, out
    assert "declared but naming NO stage: ['listed']" in out, out


def test_fixture_the_derived_side_never_starts_demanding_declarations(tmp_path):
    """THE CONTROL FOR THE P1 FIX. Tightening placement must not make the
    checker demand a declaration for the skills the FLOW already places -- that
    would recreate the second declaration P4 exists to forbid.

    Measured on the shipped tree: with ALL 41 declarations deleted the program
    reports exactly 41 unplaced, never 70. The 29 the flow names stay placed.
    """
    plugin = _tree(tmp_path, ["wired-skill"],
                   {"stages": {}, "stage_all": {}, "off_flow": {}})
    rc, out = _run(plugin)
    assert rc == 0, (
        f"`wired-skill` is named by a step and must stay placed with NO "
        f"declaration; got {rc}:\n{out}")
