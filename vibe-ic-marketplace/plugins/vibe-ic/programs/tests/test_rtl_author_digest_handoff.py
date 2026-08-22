"""`step_rtl_gen` must give the captured-knowledge digests to EVERY branch that
hands authoring to an LLM — not only to the one branch that happened to stage
them inline.

THE DEFECT (measured on the tree before the fix, all three branches that name
an author skill):

    unreg   skill=spec-to-rtl          lessons=False  expert_db=False
    vendor  skill=catalog-glue-author  lessons=False  expert_db=False
    reg     skill=spec-to-rtl          lessons=True   expert_db=True

Two of three authoring handoffs told the AI to author and staged NOTHING for it
to author from. The staging lived inside the registered-class branch's body, so
which knowledge an author received depended on which branch noticed it rather
than on the fact that authoring was happening at all.

This matters beyond tidiness: the corpus carries chip-AGNOSTIC anti-pattern
rules (e.g. "for a serial-parallel multiplier do NOT author the behavioural
accumulate-then-shift form; it puts a full DATA_WIDTH carry-propagate adder in
the register-to-register path"). An author that never receives that rule
re-invents the anti-pattern, and the cost lands at post-route STA — far away
from the branch that dropped it.

These tests drive the REAL registry, the REAL lesson corpus and the REAL IC
Expert DB — no fixtures — so they degrade loudly rather than silently if any of
those move. `test_premise_*` exists to guarantee that: without it, an empty
corpus would make the GUARD tests pass for the wrong reason.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as R  # noqa: E402
import _lesson_digest as LD  # noqa: E402

# A class name that must never be in the registry. Asserted, not assumed.
_UNREGISTERED = "zzz_class_not_in_registry_probe"

_SPEC_SOURCE = Path(__file__).resolve().parent / "_spec_fixture_docs"


def _spec_text() -> str:
    """Prose with enough design-class signal for the IC Expert DB to match.

    Deliberately generic: a serial/bit-serial arithmetic datapath, which is a
    design CLASS, not this or any other specific chip.
    """
    return (
        "# Serial-parallel multiplier\n\n"
        "A bit-serial arithmetic datapath. One operand `x` is parallel and held\n"
        "stable; the multiplier operand `y` arrives one bit per clock; the\n"
        "product `p` is emitted serially, LSB first. Computes p = (x * y) mod\n"
        "2^N on an N-bit datapath. Synchronous active-high reset. Target clock\n"
        "10 ns, multi-corner sign-off across SS, TT and FF.\n"
    )


def _mk_project(tmp_path: Path, name: str, *, vendor_rtl: bool = False) -> Path:
    """A project laid out the way `_gather_spec_text` actually reads it."""
    proj = tmp_path / name
    doc = proj / "phase1" / "input_doc"
    doc.mkdir(parents=True)
    (doc / "L2_architecture.md").write_text(_spec_text())
    if vendor_rtl:
        v = proj / "input" / "vendor_rtl"
        v.mkdir(parents=True)
        (v / "vendor_top.v").write_text("module vendor_top(); endmodule\n")
    return proj


def _staged(proj: Path) -> tuple[bool, bool]:
    s1 = proj / "phase2" / "stage1"
    return (s1 / "lessons.md").is_file(), (s1 / "ic_expert_db.md").is_file()


def _registered_no_generator_class() -> str:
    """A class the registry HAS but with no deterministic generator — the
    branch that already worked. Read from the real registry so a registry edit
    surfaces here instead of silently re-pointing the test."""
    reg = json.loads((PROGRAMS / "ic_class_registry.json").read_text())
    entries = reg.get("classes", reg)
    for c in entries:
        if isinstance(c, dict) and not c.get("rtl_gen") and c.get("name"):
            return c["name"]
    pytest.skip("registry has no class without a deterministic generator")


def _generator_class() -> str:
    """A class that routes to a DETERMINISTIC generator — no LLM authors, so
    no digest should ever be staged for it."""
    reg = json.loads((PROGRAMS / "ic_class_registry.json").read_text())
    entries = reg.get("classes", reg)
    for c in entries:
        if isinstance(c, dict) and c.get("rtl_gen") and c.get("name"):
            return c["name"]
    pytest.skip("registry has no class with a deterministic generator")


# ---------------------------------------------------------------------------
# PREMISE — without these the GUARD tests below could pass vacuously.
# ---------------------------------------------------------------------------

def test_premise_unregistered_probe_is_really_unregistered():
    reg = json.loads((PROGRAMS / "ic_class_registry.json").read_text())
    entries = reg.get("classes", reg)
    names = {c.get("name") for c in entries if isinstance(c, dict)}
    synonyms = {s for c in entries if isinstance(c, dict)
                for s in (c.get("synonyms") or [])}
    assert _UNREGISTERED not in names | synonyms


def test_premise_lesson_corpus_is_live(tmp_path):
    """If the corpus were empty, `lessons.md` would never be written and the
    DEFECT tests would fail for a reason that has nothing to do with routing."""
    assert LD.render_lesson_digest(tmp_path) > 0, (
        "lesson corpus rendered 0 lessons — the digest-routing tests below "
        "would be measuring an empty corpus, not the routing fix")


def test_premise_ic_expert_db_matches_this_spec(tmp_path):
    """Same guarantee for the second track."""
    assert LD.render_ic_expert_db_digest(tmp_path, _spec_text()) > 0, (
        "IC Expert DB returned no hits for a generic bit-serial arithmetic "
        "spec — the expert-db assertions below would be vacuous")


# ---------------------------------------------------------------------------
# DEFECT — these FAIL on the unfixed tree.
# ---------------------------------------------------------------------------

def test_unregistered_class_handoff_stages_digests(tmp_path):
    """UNREGISTERED class → `spec-to-rtl`. The author with the LEAST
    scaffolding must not be the one that receives the least knowledge."""
    proj = _mk_project(tmp_path, "unreg")
    res = R.step_rtl_gen(proj, _UNREGISTERED)
    assert (res.extras or {}).get("fallback_skill") == "spec-to-rtl"
    lessons, expert_db = _staged(proj)
    assert lessons, "unregistered-class handoff staged no lessons.md"
    assert expert_db, "unregistered-class handoff staged no ic_expert_db.md"


def test_vendor_rtl_handoff_stages_digests(tmp_path):
    """Pre-staged vendor RTL → `catalog-glue-author`, which still hand-authors
    the chip_top wrapper, so it is an authoring handoff like any other."""
    proj = _mk_project(tmp_path, "vendor", vendor_rtl=True)
    res = R.step_rtl_gen(proj, _registered_no_generator_class())
    assert (res.extras or {}).get("fallback_skill") == "catalog-glue-author"
    lessons, expert_db = _staged(proj)
    assert lessons, "catalog-glue handoff staged no lessons.md"
    assert expert_db, "catalog-glue handoff staged no ic_expert_db.md"


def test_every_authoring_handoff_agrees(tmp_path):
    """The property, stated directly: any branch that names an author skill
    stages both digests. Comparing the branches against EACH OTHER catches a
    future branch that forgets, which per-branch assertions would miss."""
    cases = [
        ("unreg", _UNREGISTERED, False),
        ("vendor", _registered_no_generator_class(), True),
        ("reg", _registered_no_generator_class(), False),
    ]
    starved = []
    for name, cls, vendor in cases:
        proj = _mk_project(tmp_path, name, vendor_rtl=vendor)
        res = R.step_rtl_gen(proj, cls)
        if not (res.extras or {}).get("fallback_skill"):
            continue  # not an authoring handoff
        lessons, expert_db = _staged(proj)
        if not (lessons and expert_db):
            starved.append(f"{name}(lessons={lessons}, expert_db={expert_db})")
    assert not starved, f"authoring handoffs that staged no knowledge: {starved}"


# ---------------------------------------------------------------------------
# GUARD — these FAIL if the fix over-applies.
# ---------------------------------------------------------------------------

def test_deterministic_generator_path_does_not_stage_digests(tmp_path):
    """A class with a deterministic generator emits RTL with NO LLM. Staging an
    author digest there would be pure noise — and would prove the fix had been
    hoisted to the top of the function instead of attached to the handoffs."""
    proj = _mk_project(tmp_path, "gen")
    R.step_rtl_gen(proj, _generator_class())
    lessons, expert_db = _staged(proj)
    assert not lessons and not expert_db, (
        "deterministic-generator path staged an author digest "
        f"(lessons={lessons}, expert_db={expert_db}) — no LLM authors there")


def test_registered_no_generator_handoff_unchanged(tmp_path):
    """The branch that already worked must keep working — this is the
    regression half of the fix."""
    proj = _mk_project(tmp_path, "reg")
    res = R.step_rtl_gen(proj, _registered_no_generator_class())
    lessons, expert_db = _staged(proj)
    assert lessons and expert_db
    assert (res.extras or {}).get("lessons_count", 0) > 0
    assert "MANDATORY before authoring" in (res.detail or "")


def test_helper_is_best_effort_and_never_raises(tmp_path):
    """Contract: the staging decorates a WAIVE and must never be able to turn
    it into an exception. A project with no spec sources at all is the cheapest
    way to exercise the empty path."""
    empty = tmp_path / "empty"
    empty.mkdir()
    hint, extras = R._stage_author_knowledge_digests(empty)
    assert isinstance(hint, str) and isinstance(extras, dict)
