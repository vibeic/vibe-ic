"""ic_expert_db_health_audit — the periodic MAINTENANCE lint over the IC Expert
DB (Karpathy LLM-Wiki "lint" idea). ADVISORY by default; --strict to enforce.
Distinct from the ship-blocking ic_expert_db_consistency_check gate.
"""
import json
from pathlib import Path

import ic_expert_db_health_audit as H
import ic_expert_db_query as Q

PLUGIN = Path(__file__).resolve().parent.parent.parent
DB = PLUGIN / "agents" / "ic_expert_db" / "ic_expert_db.json"
PROGRAMS = Path(__file__).resolve().parent.parent


def _db(tmp_path, entries):
    for e in entries:
        e.setdefault("lesson_count", len(e.get("lessons", [])))
    p = tmp_path / "db.json"
    p.write_text(json.dumps({"entries": entries}))
    return p


# ── shipped DB runs + is advisory ───────────────────────────────────

def test_shipped_db_audit_runs_and_reports():
    rep = H.audit(DB, programs_dir=PROGRAMS)
    assert "dimensions" in rep and "counts" in rep
    # every dimension key is present even when empty
    for dim in ("low_retrievability", "near_duplicate", "stale_program_ref", "related_graph"):
        assert dim in rep["dimensions"]


def test_advisory_mode_exit_zero_even_with_findings():
    # shipped DB has low-retrievability advisories, but advisory mode never fails
    assert H.main(["--db", str(DB), "--programs-dir", str(PROGRAMS)]) == 0


def test_strict_mode_reflects_findings():
    # a DB engineered to have exactly one finding fails under --strict
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "db.json"
        p.write_text(json.dumps({"entries": [
            {"ic_class": "zzz-block", "lesson_count": 1, "lessons": ["clean advisory"]}]}))
        assert H.main(["--db", str(p), "--programs-dir", str(PROGRAMS), "--strict"]) == 1
        assert H.main(["--db", str(p), "--programs-dir", str(PROGRAMS)]) == 0  # advisory


# ── dimension 1: low retrievability ─────────────────────────────────

def test_low_retrievability_flags_stemless_class(tmp_path):
    assert not Q._fn("zzz-block some advice"), "guard: class+lesson must be stem-free"
    db = _db(tmp_path, [
        {"ic_class": "zzz-block", "lessons": ["some advice"]},
        {"ic_class": "divider-unit", "lessons": ["divider advice"]}])  # has 'divid'
    rep = H.audit(db, programs_dir=tmp_path)
    assert "zzz-block" in rep["dimensions"]["low_retrievability"]
    assert "divider-unit" not in rep["dimensions"]["low_retrievability"]


def test_low_retrievability_uses_lessons_not_just_name(tmp_path):
    # a stemless NAME but a lesson carrying a family stem IS retrievable (the
    # retriever scores via _fn(cls + " " + lesson)) -> must NOT be flagged
    db = _db(tmp_path, [
        {"ic_class": "zzz-block", "lessons": ["This block is a shift-register based divider."]}])
    rep = H.audit(db, programs_dir=tmp_path)
    assert "zzz-block" not in rep["dimensions"]["low_retrievability"]


# ── dimension 2: near-duplicate lessons ─────────────────────────────

def test_near_duplicate_lessons_flagged(tmp_path):
    a = ("The restoring divider keeps a partial remainder register wider than the "
         "operands, shifting each iteration and correcting the final sign.")
    b = ("The restoring divider keeps a partial remainder register wider than the "
         "operands, shifting every iteration and correcting the final sign.")
    db = _db(tmp_path, [
        {"ic_class": "divider-a", "lessons": [a]},
        {"ic_class": "divider-b", "lessons": [b]}])
    rep = H.audit(db, programs_dir=tmp_path)
    assert rep["dimensions"]["near_duplicate"], "near-identical lessons should be flagged"


def test_distinct_lessons_not_flagged_as_duplicate(tmp_path):
    db = _db(tmp_path, [
        {"ic_class": "divider-a", "lessons": ["Non-restoring division needs a W+1 remainder."]},
        {"ic_class": "fifo-a", "lessons": ["A dual-clock FIFO needs Gray-coded pointers."]}])
    rep = H.audit(db, programs_dir=tmp_path)
    assert not rep["dimensions"]["near_duplicate"]


# ── dimension 3: stale program references ───────────────────────────

def test_stale_program_ref_flagged(tmp_path):
    (tmp_path / "real_check.py").write_text("# exists")
    db = _db(tmp_path, [
        {"ic_class": "a", "lessons": ["run ghost_check.py to fix this"]},
        {"ic_class": "b", "lessons": ["run real_check.py to fix this"]}])
    rep = H.audit(db, programs_dir=tmp_path)
    refs = {r["ref"] for r in rep["dimensions"]["stale_program_ref"]}
    assert "ghost_check.py" in refs        # plugin-like + missing -> stale
    assert "real_check.py" not in refs     # exists under programs_dir -> not stale


def test_stale_ignores_external_tool_names(tmp_path):
    # setup.py / make.py are NOT vibe-ic programs; naming them must not false-fire
    db = _db(tmp_path, [
        {"ic_class": "a", "lessons": ["configure via setup.py then run make.py to build"]}])
    rep = H.audit(db, programs_dir=tmp_path)
    assert rep["dimensions"]["stale_program_ref"] == []


# ── dimension 4: related[] concept-graph health ─────────────────────

def test_related_dangling_flagged(tmp_path):
    db = _db(tmp_path, [{"ic_class": "a", "lessons": ["la"], "related": ["ghost"]}])
    rep = H.audit(db, programs_dir=tmp_path)
    issues = {i["issue"] for i in rep["dimensions"]["related_graph"]}
    assert "dangling" in issues


def test_related_asymmetric_flagged(tmp_path):
    db = _db(tmp_path, [
        {"ic_class": "a", "lessons": ["la"], "related": ["b"]},
        {"ic_class": "b", "lessons": ["lb"]}])  # b does not link back
    rep = H.audit(db, programs_dir=tmp_path)
    issues = {i["issue"] for i in rep["dimensions"]["related_graph"]}
    assert "asymmetric" in issues


def test_related_symmetric_is_clean(tmp_path):
    db = _db(tmp_path, [
        {"ic_class": "a", "lessons": ["la"], "related": ["b"]},
        {"ic_class": "b", "lessons": ["lb"], "related": ["a"]}])
    rep = H.audit(db, programs_dir=tmp_path)
    assert not rep["dimensions"]["related_graph"]


def test_no_related_field_is_noop(tmp_path):
    db = _db(tmp_path, [{"ic_class": "spi-x", "lessons": ["clean"]}])
    rep = H.audit(db, programs_dir=tmp_path)
    assert rep["dimensions"]["related_graph"] == []


# ── robustness: malformed entries are REPORTED, not crashed on ──────

def test_malformed_entries_do_not_crash(tmp_path):
    # a lint over ROT must survive the rot it audits (non-dict entry, missing
    # ic_class, non-list lessons) — report each, never raise, never fatal
    p = tmp_path / "db.json"
    p.write_text(json.dumps({"entries": [
        "i am not an object",
        {"lessons": ["no ic_class here"]},
        {"ic_class": "bad", "lessons": "not-a-list"},
        {"ic_class": "spi-good", "lessons": ["a clean spi lesson"]}]}))
    rep = H.audit(p, programs_dir=tmp_path)         # must not raise
    assert not rep.get("fatal")
    assert sum("malformed" in f for f in rep["findings"]) == 3  # the 3 bad entries
    assert rep["classes"] == 1                                   # only spi-good indexed
    assert H.main(["--db", str(p), "--programs-dir", str(tmp_path)]) == 0  # advisory, non-fatal


# ── fatal: unparseable / structurally-broken DB is a hard error ─────

def test_unparseable_db_is_hard_error(tmp_path):
    p = tmp_path / "db.json"
    p.write_text("{ not json")
    rep = H.audit(p, programs_dir=tmp_path)
    assert rep.get("fatal") is True
    assert H.main(["--db", str(p), "--programs-dir", str(tmp_path)]) == 1


def test_empty_entries_is_fatal(tmp_path):
    p = tmp_path / "db.json"
    p.write_text(json.dumps({"entries": []}))
    rep = H.audit(p, programs_dir=tmp_path)
    assert rep.get("fatal") is True
    # fatal beats advisory: exit 1 even without --strict
    assert H.main(["--db", str(p), "--programs-dir", str(tmp_path)]) == 1
