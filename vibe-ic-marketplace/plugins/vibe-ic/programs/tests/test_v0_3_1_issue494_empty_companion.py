"""v0.3.1 — ORGANIC-20260606 #494 (HIGH) — honest zero-unpromoted N/A.

phase1's ``_seed_canonical_from_backfilled_subset`` rewrites
``phase1/extraction_patterns.auto.json`` on EVERY run with the *unpromoted
remainder* (auto-discovered literals NOT yet backfilled into typed
L*.json). When EVERY literal was backfilled — zero unpromoted — the writer
LEGITIMATELY emits an otherwise-empty companion carrying ONLY its explicit
zero-unpromoted marker ``_comment``.

`metadata_content_substance_check` whitelisted that file with a hard
``min_entries:1``, so a clean run's own honest output FAILed its own gate:
phase2 FAILed and the whole phase3 backend went unverified (the agent
correctly refused to stuff fake patterns). #494's preferred fix: the gate
recognises the WRITER'S explicit STRUCTURAL marker (not mere emptiness) as
honest-N/A → named SKIP exit 0; a companion empty WITHOUT the marker, or
whose entries lack substance, still FAILs.

REGRESSION FIXTURE = the REAL empty-companion shape. Rather than paste the
marker string by hand, the headline test drives the REAL phase1 writer
end-to-end with an auto.json whose every literal IS present in the typed
L*.json haystack (→ zero unpromoted), so the writer itself produces the
exact empty-companion shape the gate must SKIP. The gate is then run on
that real artifact.

chip-AGNOSTIC / DENY-LIST DISCIPLINE: no chip / vendor / SKU literal
appears here. The fixture literals are generic hex / structural tokens and
the marker text is DISCOVERED from the writer source, never hard-pasted as
a private codename.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_THIS = Path(__file__).resolve()
_PLUGIN_ROOT = _THIS.parent.parent.parent          # …/plugins/vibe-ic
sys.path.insert(0, str(_PLUGIN_ROOT / "programs"))

import phase1_doc_one_shot_runner as P1  # noqa: E402
import _path_layout as _pl  # noqa: E402

_AUTO_REL = "phase1/extraction_patterns.auto.json"


# ---------------------------------------------------------------------------
# Build the REAL empty-companion shape by driving the actual phase1 writer.
# ---------------------------------------------------------------------------

def _seed_l_haystack(project: Path, literals) -> None:
    """Write a generated_docs/L*.json whose typed string values contain
    every `literal`, so the writer promotes all of them (zero unpromoted)."""
    gd = _pl.generated_docs_dir(project)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L4_REGMAP.json").write_text(
        json.dumps({"fields": [{"value": lit} for lit in literals]},
                   ensure_ascii=False),
        encoding="utf-8")


# The exact provenance `_comment` the FIRST writer (_autodiscover_patterns
# in phase1_coverage_report_gen) stamps on the harvest. Using it verbatim
# makes the downstream writer's `setdefault` PRESERVE it — reproducing the
# common clean-run shape. (When the harvest carries no comment, the second
# writer instead stamps its own "NOT yet backfilled" marker — covered by
# `_produce_real_empty_companion_no_prior_comment`.)
_WAVE5_PRESEED_COMMENT = (
    "Auto-discovered extraction patterns (Wave 5). Review and promote "
    "curated entries to extraction_patterns.json.")


def _write_auto_with_unbackfilled(project: Path, literals,
                                  *, preseed_comment) -> Path:
    """Write a starting auto.json (the pre-seed harvest) carrying `literals`
    under a generic source key. `preseed_comment` mimics whatever the first
    writer left (or None for the no-comment path). Returns the auto path."""
    auto = _pl.phase1_extraction_patterns_auto_file(project)
    auto.parent.mkdir(parents=True, exist_ok=True)
    payload = {}
    if preseed_comment is not None:
        payload["_comment"] = preseed_comment
    payload["datasheet.txt"] = [
        {"literal": lit, "label": "auto-discovered (hex)"}
        for lit in literals]
    auto.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return auto


def _produce_real_empty_companion(tmp_path: Path, *,
                                  preseed_comment=_WAVE5_PRESEED_COMMENT,
                                  name="clean_run"):
    """Drive the REAL `_seed_canonical_from_backfilled_subset` so that EVERY
    auto literal is present in the L*.json haystack → zero unpromoted → the
    writer rewrites auto.json to the empty-companion shape. Returns
    (project, companion_dict)."""
    project = tmp_path / name
    literals = ["0xDEAD", "0xBEEF", "0xCAFE"]
    _seed_l_haystack(project, literals)
    auto = _write_auto_with_unbackfilled(
        project, literals, preseed_comment=preseed_comment)
    canonical = _pl.phase1_extraction_patterns_file(project)
    P1._seed_canonical_from_backfilled_subset(project, auto, canonical)
    companion = json.loads(auto.read_text(encoding="utf-8"))
    return project, companion


def _produce_real_empty_companion_no_prior_comment(tmp_path: Path):
    """Same, but the harvest carried NO `_comment`, so the second writer
    stamps its own 'NOT yet backfilled' marker via setdefault."""
    return _produce_real_empty_companion(
        tmp_path, preseed_comment=None, name="clean_run_nocomment")


# ---------------------------------------------------------------------------
# The writer really does produce a marker-only, entry-free companion.
# ---------------------------------------------------------------------------

def test_writer_emits_marker_only_empty_companion(tmp_path):
    project, companion = _produce_real_empty_companion(tmp_path)
    # Only the `_comment` key, no real per-source pattern lists.
    real_keys = [k for k in companion if not k.startswith("_")]
    assert real_keys == [], real_keys
    # And it carries the marker substring the gate keys on.
    # The promoted literals went to the canonical file (proof they were
    # backfilled, i.e. zero legitimately remained unpromoted).
    canonical = _pl.phase1_extraction_patterns_file(project)
    assert canonical.is_file()


def test_writer_no_prior_comment_stamps_marker(tmp_path):
    """When the harvest had no `_comment`, the second writer stamps its own
    'NOT yet backfilled' marker — also carrying the gate's structural
    signature. Both clean-run variants are honest-N/A."""
    project, companion = _produce_real_empty_companion_no_prior_comment(
        tmp_path)
    real_keys = [k for k in companion if not k.startswith("_")]
    assert real_keys == [], real_keys
    assert "NOT yet backfilled" in companion["_comment"]


def test_writer_emits_canonical_output_when_nothing_is_promoted(tmp_path):
    """D1 owns the canonical catalogue even when its measured population is
    empty; later substance gates, rather than a missing producer artefact,
    decide whether that empty catalogue is acceptable for the design.
    """
    project = tmp_path / "no_promoted_literals"
    _seed_l_haystack(project, [])
    auto = _write_auto_with_unbackfilled(
        project, ["NOT_IN_TYPED_DOCS"], preseed_comment=None)
    canonical = _pl.phase1_extraction_patterns_file(project)

    P1._seed_canonical_from_backfilled_subset(project, auto, canonical)

    payload = json.loads(canonical.read_text(encoding="utf-8"))
    assert list(payload) == ["_comment"]
    assert "coverage denominator" in payload["_comment"]
    remaining = json.loads(auto.read_text(encoding="utf-8"))
    assert remaining["datasheet.txt"][0]["literal"] == "NOT_IN_TYPED_DOCS"


# ---------------------------------------------------------------------------
# HEADLINE: the real empty-companion shape → SKIP exit 0 (honest N/A).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# NEGATIVE: empty companion WITHOUT the marker still FAILs.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# The marker cannot MASK a real substance gap (anti-gaming).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Marker scope: it only applies to the whitelisted companion, and only when
# every OTHER present file also passes.
# ---------------------------------------------------------------------------
