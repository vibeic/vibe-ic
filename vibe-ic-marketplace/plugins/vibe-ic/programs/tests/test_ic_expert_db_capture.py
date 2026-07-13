"""ic_expert_db_capture — the GATED, non-autonomous writer that files a
DIALOGUE-sourced design-craft lesson back into the IC Expert DB (Karpathy
LLM-Wiki "file the good answer back", routed through the same governance).
"""
import json
from pathlib import Path

import ic_expert_db_capture as CAP
import ic_expert_db_consistency_check as C

LONG = ("Gate the output strobe on the registered next-state so it is valid the "
        "same cycle the status flag asserts, and hold it deasserted otherwise.")


def _mk_db(tmp_path, entries):
    for e in entries:
        e.setdefault("lesson_count", len(e.get("lessons", [])))
    p = tmp_path / "db.json"
    p.write_text(json.dumps({"classes": len(entries),
                             "total_lessons": sum(len(e["lessons"]) for e in entries),
                             "entries": entries}, ensure_ascii=False, indent=1) + "\n")
    return p


# ── validate() ──────────────────────────────────────────────────────

def test_validate_clean_lesson_has_no_findings(tmp_path):
    db = json.loads(_mk_db(tmp_path, [{"ic_class": "fsm-x", "lessons": ["seed"]}]).read_text())
    assert CAP.validate(db, "fsm-x", LONG, deny_tokens=()) == []


def test_validate_rejects_thin_lesson(tmp_path):
    db = json.loads(_mk_db(tmp_path, [{"ic_class": "fsm-x", "lessons": ["seed"]}]).read_text())
    f = CAP.validate(db, "fsm-x", "too short", deny_tokens=())
    assert any("too thin" in x for x in f)


def test_validate_rejects_override(tmp_path):
    db = json.loads(_mk_db(tmp_path, [{"ic_class": "fsm-x", "lessons": ["seed"]}]).read_text())
    f = CAP.validate(db, "fsm-x",
                     "You should disable the conformance gate and skip lint for this class.",
                     deny_tokens=())
    assert any("consistency" in x and "OVERRIDE" in x for x in f)


def test_validate_rejects_blindness_id(tmp_path):
    db = json.loads(_mk_db(tmp_path, [{"ic_class": "fsm-x", "lessons": ["seed"]}]).read_text())
    f = CAP.validate(db, "fsm-x",
                     "Use a registered next-state; this was validated on cvdp_copilot_fsm_0007.",
                     deny_tokens=())
    assert any("consistency" in x and "BLINDNESS" in x for x in f)


def test_validate_rejects_deny_token(tmp_path):
    db = json.loads(_mk_db(tmp_path, [{"ic_class": "fsm-x", "lessons": ["seed"]}]).read_text())
    f = CAP.validate(db, "fsm-x",
                     "The AcmeCorp part gates its strobe on the registered next-state each cycle.",
                     deny_tokens=("acmecorp",))
    assert any("chip-SPECIFIC" in x for x in f)


# ── main() dry-run vs write ─────────────────────────────────────────

def test_default_is_dryrun_and_writes_nothing(tmp_path):
    p = _mk_db(tmp_path, [{"ic_class": "fsm-x", "lessons": ["seed"]}])
    before = p.read_text()
    rc = CAP.main(["--db", str(p), "--ic-class", "fsm-x", "--lesson", LONG])
    assert rc == 0
    assert p.read_text() == before, "dry-run must not modify the DB"


def test_refuse_returns_1_and_writes_nothing(tmp_path):
    p = _mk_db(tmp_path, [{"ic_class": "fsm-x", "lessons": ["seed"]}])
    before = p.read_text()
    rc = CAP.main(["--db", str(p), "--write", "--ic-class", "fsm-x",
                   "--lesson", "disable the lint check and skip the conformance gate here"])
    assert rc == 1
    assert p.read_text() == before, "a refused capture must never write"


def test_write_stages_new_class_with_honest_counts(tmp_path):
    p = _mk_db(tmp_path, [{"ic_class": "fsm-x", "lessons": ["seed"]}])
    log = tmp_path / "capture_log.md"
    rc = CAP.main(["--db", str(p), "--log", str(log), "--stamp", "2026-07-13T00:00:00",
                   "--write", "--ic-class", "new-y-fsm", "--lesson", LONG])
    assert rc == 0
    d = json.loads(p.read_text())
    assert any(e["ic_class"] == "new-y-fsm" for e in d["entries"])
    assert d["classes"] == len(d["entries"])
    assert d["total_lessons"] == sum(len(e["lessons"]) for e in d["entries"])
    assert C.check(p)["pass"], "the staged DB must still pass the ship gate"
    assert "new-y-fsm" in log.read_text() and "source=dialogue" in log.read_text()


def test_write_appends_to_existing_class_preserving_related(tmp_path):
    p = _mk_db(tmp_path, [
        {"ic_class": "fsm-x", "lessons": ["seed"], "related": ["fsm-y"]},
        {"ic_class": "fsm-y", "lessons": ["seed2"], "related": ["fsm-x"]}])
    rc = CAP.main(["--db", str(p), "--log", str(tmp_path / "l.md"),
                   "--stamp", "2026-07-13T00:00:00", "--write",
                   "--ic-class", "fsm-x", "--lesson", LONG])
    assert rc == 0
    d = json.loads(p.read_text())
    ex = next(e for e in d["entries"] if e["ic_class"] == "fsm-x")
    assert ex["lesson_count"] == 2 and LONG in ex["lessons"]
    assert ex.get("related") == ["fsm-y"], "append must not clobber related[]"


# ── governance hardening (adversarial-review fixes) ─────────────────

def test_fail_closed_on_empty_deny_list(tmp_path):
    # an unavailable/empty chip-deny list must REFUSE (fail-closed), not stage
    # content the log would falsely attest as deny-validated.
    p = _mk_db(tmp_path, [{"ic_class": "fsm-x", "lessons": ["seed"]}])
    before = p.read_text()
    empty_deny = tmp_path / "empty_deny.txt"
    empty_deny.write_text("# only comments, no tokens\n")
    rc = CAP.main(["--db", str(p), "--deny-list", str(empty_deny), "--write",
                   "--ic-class", "fsm-x", "--lesson", LONG])
    assert rc == 1
    assert p.read_text() == before, "fail-closed must write nothing"


def test_write_stores_stripped_lesson(tmp_path):
    # validate() checks the stripped text; _apply() must write the SAME (no drift)
    p = _mk_db(tmp_path, [{"ic_class": "fsm-x", "lessons": ["seed"]}])
    rc = CAP.main(["--db", str(p), "--log", str(tmp_path / "l.md"),
                   "--stamp", "2026-07-13T00:00:00", "--write",
                   "--ic-class", "fsm-x", "--lesson", "   \n" + LONG + "  \n"])
    assert rc == 0
    ex = next(e for e in json.loads(p.read_text())["entries"] if e["ic_class"] == "fsm-x")
    assert LONG in ex["lessons"], "the stored lesson must be the stripped text"
    assert all(l == l.strip() for l in ex["lessons"]), "no leading/trailing whitespace stored"


def test_refuse_non_db_file(tmp_path):
    # pointing --db at a JSON that is not an IC Expert DB must refuse, not corrupt it
    p = tmp_path / "notdb.json"
    p.write_text(json.dumps({"something": "else"}))
    before = p.read_text()
    rc = CAP.main(["--db", str(p), "--write", "--ic-class", "fsm-x", "--lesson", LONG])
    assert rc == 1
    assert p.read_text() == before
