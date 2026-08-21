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
from metadata_content_substance_check import (  # noqa: E402
    audit, main, _has_zero_unpromoted_marker, _ZERO_UNPROMOTED_MARKER,
)

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
    needle = _ZERO_UNPROMOTED_MARKER[_AUTO_REL]
    assert needle in companion["_comment"], companion["_comment"]
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
    needle = _ZERO_UNPROMOTED_MARKER[_AUTO_REL]
    assert needle in companion["_comment"], companion["_comment"]
    assert "NOT yet backfilled" in companion["_comment"]
    verdict, findings, summary = audit(project)
    assert verdict == "SKIP", (verdict, findings)
    assert summary[_AUTO_REL]["skipped"] == "ZERO_UNPROMOTED_MARKER"


# ---------------------------------------------------------------------------
# HEADLINE: the real empty-companion shape → SKIP exit 0 (honest N/A).
# ---------------------------------------------------------------------------

def test_real_empty_companion_audits_skip(tmp_path):
    project, _ = _produce_real_empty_companion(tmp_path)
    verdict, findings, summary = audit(project)
    assert verdict == "SKIP", (verdict, findings)
    assert findings == []
    assert summary[_AUTO_REL]["skipped"] == "ZERO_UNPROMOTED_MARKER"


def test_real_empty_companion_cli_exit_zero(tmp_path, capsys):
    project, _ = _produce_real_empty_companion(tmp_path)
    rc = main([str(project)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "SKIP" in out
    assert "ZERO_UNPROMOTED_MARKER" in out


def test_real_empty_companion_json_report_marks_skip(tmp_path):
    project, _ = _produce_real_empty_companion(tmp_path)
    out_json = tmp_path / "report.json"
    rc = main([str(project), "--json", str(out_json)])
    assert rc == 0
    report = json.loads(out_json.read_text())
    assert report["verdict"] == "SKIP"
    assert _AUTO_REL in report["skipped"]
    assert "honest" in report["reason"].lower()


# ---------------------------------------------------------------------------
# NEGATIVE: empty companion WITHOUT the marker still FAILs.
# ---------------------------------------------------------------------------

def test_empty_companion_no_marker_still_fails(tmp_path):
    """A genuinely substance-missing companion (empty, different comment)
    must NOT get the SKIP — it still FAILs min_entries:1."""
    project = tmp_path / "no_marker"
    auto = _pl.phase1_extraction_patterns_auto_file(project)
    auto.parent.mkdir(parents=True, exist_ok=True)
    auto.write_text(json.dumps(
        {"_comment": "placeholder, no patterns yet"}), encoding="utf-8")
    verdict, findings, _ = audit(project)
    assert verdict == "FAIL", verdict
    assert findings[0].rule == "EMPTY_OR_BELOW_MIN"
    assert findings[0].observed_entries == 0
    assert findings[0].min_entries == 1


def test_empty_patterns_array_no_marker_still_fails(tmp_path, capsys):
    """`{"patterns": []}` (the #494 'substance-missing' canonical example)
    still FAILs exit 1."""
    project = tmp_path / "empty_arr"
    auto = _pl.phase1_extraction_patterns_auto_file(project)
    auto.parent.mkdir(parents=True, exist_ok=True)
    auto.write_text(json.dumps({"patterns": []}), encoding="utf-8")
    rc = main([str(project)])
    err = capsys.readouterr().err
    assert rc == 1, err
    assert "EMPTY_OR_BELOW_MIN" in err


# ---------------------------------------------------------------------------
# The marker cannot MASK a real substance gap (anti-gaming).
# ---------------------------------------------------------------------------

def test_marker_pasted_onto_populated_file_runs_normal_path(tmp_path):
    """Marker + a real backfilled entry → NOT honest-N/A; the normal
    substance path runs (and PASSes because it actually has an entry)."""
    project = tmp_path / "marker_plus_entry"
    auto = _pl.phase1_extraction_patterns_auto_file(project)
    auto.parent.mkdir(parents=True, exist_ok=True)
    needle = _ZERO_UNPROMOTED_MARKER[_AUTO_REL]
    auto.write_text(json.dumps({
        "_comment": needle + " (tail)",
        "datasheet.txt": [{"literal": "0xFF", "label": "auto"}],
    }), encoding="utf-8")
    assert not _has_zero_unpromoted_marker(_AUTO_REL, json.loads(
        auto.read_text()))
    verdict, findings, summary = audit(project)
    assert verdict == "PASS", findings
    assert summary[_AUTO_REL]["entries"] == 1


def test_marker_with_nonlist_payload_does_not_skip(tmp_path):
    """A `_comment` marker alongside a non-list payload is NOT the writer's
    honest shape → no SKIP; the normal handler classifies it (BROKEN)."""
    project = tmp_path / "marker_plus_junk"
    auto = _pl.phase1_extraction_patterns_auto_file(project)
    auto.parent.mkdir(parents=True, exist_ok=True)
    needle = _ZERO_UNPROMOTED_MARKER[_AUTO_REL]
    data = {"_comment": needle, "extra": 123}
    auto.write_text(json.dumps(data), encoding="utf-8")
    assert not _has_zero_unpromoted_marker(_AUTO_REL, data)
    verdict, findings, _ = audit(project)
    assert verdict == "FAIL", verdict
    assert findings[0].rule == "BROKEN_SCHEMA"


# ---------------------------------------------------------------------------
# Marker scope: it only applies to the whitelisted companion, and only when
# every OTHER present file also passes.
# ---------------------------------------------------------------------------

def test_marker_does_not_rescue_a_sibling_failure(tmp_path):
    """If the companion is honest-N/A but ANOTHER whitelisted file FAILs,
    the overall verdict is FAIL (the SKIP is per-file, not a free pass)."""
    project = tmp_path / "mixed"
    ph = project / "phase1"
    ph.mkdir(parents=True)
    needle = _ZERO_UNPROMOTED_MARKER[_AUTO_REL]
    (ph / "extraction_patterns.auto.json").write_text(
        json.dumps({"_comment": needle}), encoding="utf-8")
    # Sibling canonical file is genuinely substance-missing.
    (ph / "extraction_patterns.json").write_text(
        json.dumps({"patterns": []}), encoding="utf-8")
    verdict, findings, _ = audit(project)
    assert verdict == "FAIL", verdict
    assert any(f.rel_path == "phase1/extraction_patterns.json"
               for f in findings)


def test_marker_unit_helper_true_on_real_shape(tmp_path):
    _, companion = _produce_real_empty_companion(tmp_path)
    assert _has_zero_unpromoted_marker(_AUTO_REL, companion) is True


def test_marker_unit_helper_false_on_other_slot():
    """The marker is scoped to the companion slot; the same text on a
    DIFFERENT whitelisted rel path does NOT grant a SKIP."""
    needle = _ZERO_UNPROMOTED_MARKER[_AUTO_REL]
    data = {"_comment": needle}
    assert _has_zero_unpromoted_marker(
        "phase1/extraction_patterns.json", data) is False
