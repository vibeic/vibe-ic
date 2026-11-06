"""IC Expert DB — structured, chip-AGNOSTIC design-class knowledge layer that
feeds the GENERAL Vibe-IC authoring path (design_one_shot_runner spec-to-rtl /
ic-expert) via _lesson_digest, ADVISORY-only (never overrides a gate/program),
and is blindness-clean. Owner directive 2026-07-02.
"""
import json

import pytest
import sys
from pathlib import Path

import ic_expert_db_query as Q
import _lesson_digest

PLUGIN = Path(__file__).resolve().parent.parent.parent
DB = PLUGIN / "agents" / "ic_expert_db" / "ic_expert_db.json"


# ── the shipped DB itself ───────────────────────────────────────────

def test_db_exists_and_parses():
    assert DB.is_file(), "IC Expert DB must ship in agents/ic_expert_db/"
    d = json.loads(DB.read_text())
    assert d.get("entries") and isinstance(d["entries"], list)
    assert d["total_lessons"] >= 1




# ── retrieval (general-core) ────────────────────────────────────────

def test_query_divider_returns_divider_knowledge():
    hits = Q.query("Design a non-restoring divider with dividend, divisor, "
                   "quotient, remainder, valid ports.", k=3)
    assert hits, "should retrieve divider-class lessons"
    blob = " ".join(h["ic_class"] + " " + h["lesson"] for h in hits).lower()
    assert "divid" in blob or "remainder" in blob


def test_query_axi_stream_returns_stream_knowledge():
    hits = Q.query("An AXI-Stream data-width converter with tvalid tready "
                   "tlast tdata tuser.", k=3)
    assert hits
    assert any("axi" in h["ic_class"].lower() or "stream" in h["ic_class"].lower()
               for h in hits)


def test_query_unrelated_prompt_is_bounded():
    # a prompt with no design-family token returns few/no hits, never crashes
    hits = Q.query("the the the and or with value", k=5)
    assert isinstance(hits, list)


# ── consistency gate catches violations ─────────────────────────────

def _tmp_db(tmp_path, lessons):
    p = tmp_path / "db.json"
    p.write_text(json.dumps({"entries": [
        {"ic_class": "x", "lesson_count": len(lessons), "lessons": lessons}]}))
    return p










# ── related[] cross-links (F1 — the lightweight concept graph) ───────

def _tmp_db_entries(tmp_path, entries):
    p = tmp_path / "db.json"
    for e in entries:
        e.setdefault("lesson_count", len(e.get("lessons", [])))
    p.write_text(json.dumps({"entries": entries}))
    return p


def test_shipped_related_links_are_grounded_and_symmetric():
    d = json.loads(DB.read_text())
    by = {e["ic_class"]: e for e in d["entries"]}
    rel = {c: set(e.get("related", [])) for c, e in by.items()}
    for c, rs in rel.items():
        assert c not in rs, f"{c} related self-references"
        for r in rs:
            assert r in by, f"{c} related '{r}' is dangling"
            assert c in rel[r], f"related asymmetry: {c}->{r} but not back"














def test_query_expand_related_null_does_not_crash(tmp_path):
    # an explicit related:null (gate treats it as "absent") must not crash expand
    p = tmp_path / "db.json"
    p.write_text(json.dumps({"entries": [
        {"ic_class": "divider-x", "lesson_count": 1,
         "lessons": ["restoring divider partial remainder register"], "related": None}]}))
    hits = Q.query("restoring divider partial remainder", k=3, db_path=p, expand_related=True)
    assert isinstance(hits, list) and hits  # returned, did not raise


def test_query_expand_related_is_optional_and_superset():
    prompt = ("Design an accumulator / weighted-sum datapath that sums products "
              "into a wide accumulator.")
    base = Q.query(prompt, k=3)
    exp = Q.query(prompt, k=3, expand_related=True)
    # default path is unchanged: no related_to tags, and expand is a prefix-superset
    assert all("related_to" not in h for h in base)
    assert exp[:len(base)] == base
    # the top hit for this prompt is an accumulator class that HAS related links,
    # so the expand view must follow at least one of them
    by = {e["ic_class"]: e for e in json.loads(DB.read_text())["entries"]}
    top = base[0]["ic_class"] if base else None
    if top and by.get(top, {}).get("related"):
        assert any(h.get("related_to") == top for h in exp), "expand should follow links"


# ── general-path integration via _lesson_digest ─────────────────────

def test_db_digest_is_SEPARATE_from_main_digest(tmp_path):
    # DUAL-TRACK: the DB knowledge is a SEPARATE artifact (ic_expert_db.md), NOT
    # folded into lessons.md (measured to dilute a single author 38→31).
    n = _lesson_digest.render_ic_expert_db_digest(
        tmp_path, "Design a non-restoring divider (dividend, divisor, "
        "quotient, remainder, valid).")
    assert n >= 1
    db_md = tmp_path / "ic_expert_db.md"
    assert db_md.is_file()
    txt = db_md.read_text().lower()
    assert "ic expert db" in txt and ("divid" in txt or "remainder" in txt)


def test_main_digest_does_NOT_contain_db_block(tmp_path):
    # the primary lessons digest must stay DB-free (dual-track separation).
    _lesson_digest.render_lesson_digest(tmp_path)
    md = tmp_path / "lessons.md"
    if md.is_file():
        assert "IC Expert DB — relevant design-class knowledge" not in md.read_text()


def test_db_digest_empty_prompt_writes_nothing(tmp_path):
    assert _lesson_digest.render_ic_expert_db_digest(tmp_path, "") == 0
    assert not (tmp_path / "ic_expert_db.md").exists()


def test_related_graph_is_symmetric_after_the_nvm_fuse_array_entry(  # noqa: E501
):
    """Regression pin for a RED test on main, not a new capability.

    A newly added `nvm-fuse-array` entry linked out to three classes and none
    linked back, so `test_shipped_related_links_are_grounded_and_symmetric`
    failed on `origin/main` itself. The graph is undirected by construction —
    a one-way edge means one of the two entries cannot be found from the other,
    which is the entire point of the links.
    """
    d = json.loads(DB.read_text())
    by = {e["ic_class"]: e for e in d["entries"]}
    rel = {c: set(e.get("related", [])) for c, e in by.items()}
    one_way = [(c, r) for c, rs in rel.items() for r in rs
               if r in by and c not in rel[r]]
    assert one_way == [], one_way
    # ...and the specific edges that were missing are present in BOTH directions
    for other in ("command-driven-memory-controller-fsm",
                  "register-file-with-bist", "secure-register-bank-fsm"):
        if other in rel and "nvm-fuse-array" in rel:
            assert other in rel["nvm-fuse-array"], other
            assert "nvm-fuse-array" in rel[other], other


def test_plain_fifo_consumer_keeps_safety_and_capacity_together():
    hits = Q.query(
        "Design a dual-clock asynchronous FIFO with Gray pointers, full empty "
        "flags, and accepted write/read transfers.",
        k=5, ic_class=None, expand_related=False)
    row = next(e for e in json.loads(DB.read_text())["entries"]
               if e["ic_class"] == "async-fifo-cdc")
    assert len(hits) == 5
    assert hits[0]["ic_class"] == row["ic_class"]
    assert hits[0]["lesson"] == "\n\n".join(row["lessons"][:2])
    assert "TOP TWO bits inverted" in hits[0]["lesson"]
    assert "same accepted position" in hits[0]["lesson"]
    assert "extra Gray-pointer lag" in hits[0]["lesson"]




def test_grouping_is_symmetric_when_companion_ranks_first(tmp_path):
    path = tmp_path / "db.json"
    path.write_text(json.dumps({"entries": [{"ic_class": "arithmetic",
        "lesson_count": 2, "lessons": ["unsigned operands", "divider quotient"],
        "lesson_groups": [[0, 1]]}]}))
    hits = Q.query("divider quotient", k=5, db_path=path)
    assert len(hits) == 1
    assert hits[0]["lesson"] == "unsigned operands\n\ndivider quotient"




def test_related_only_fifo_hit_keeps_both_grouped_lessons():
    prompt = "Design a CDC mux synchronizer level handshake."
    normal = Q.query(prompt, k=1, expand_related=False)
    expanded = Q.query(prompt, k=1, expand_related=True)
    row = next(e for e in json.loads(DB.read_text())["entries"]
               if e["ic_class"] == "async-fifo-cdc")
    assert [h["ic_class"] for h in normal] == ["cdc-mux-synchronizer"]
    assert expanded[0] == normal[0]
    assert len(expanded) == 2
    assert expanded[1] == {"ic_class": "async-fifo-cdc", "score": 0.0,
        "lesson": "\n\n".join(row["lessons"][:2]),
        "related_to": "cdc-mux-synchronizer"}


def test_related_expansion_deduplicates_an_already_grouped_fifo_hit():
    prompt = "Design a CDC mux synchronizer level handshake."
    normal = Q.query(prompt, k=5, expand_related=False)
    expanded = Q.query(prompt, k=5, expand_related=True)
    assert [h["ic_class"] for h in normal] == [
        "cdc-mux-synchronizer", "glitch-free-clock-mux", "async-fifo-cdc",
        "axi-mmio-cdc-datapath", "handshake-valid-ready"]
    assert expanded[:5] == normal
    assert [h["ic_class"] for h in expanded] == [
        h["ic_class"] for h in normal] + ["edge-interval-monitor"]
    assert expanded[-1]["score"] == 0.0
    assert expanded[-1]["related_to"] == "cdc-mux-synchronizer"
    assert len([h for h in expanded if h["ic_class"] == "async-fifo-cdc"]) == 1


def test_grouped_lessons_use_one_slot_and_keep_original_ranking(tmp_path):
    db = {"entries": [
        {"ic_class": "divider", "lesson_count": 3,
         "lessons": ["divider quotient", "unsigned operands", "divider remainder"],
         "lesson_groups": [[0, 1]]},
        {"ic_class": "adder", "lesson_count": 1, "lessons": ["adder sum"]}]}
    path = tmp_path / "db.json"
    path.write_text(json.dumps(db))
    hits = Q.query("divider adder quotient", k=3, db_path=path)
    assert [h["ic_class"] for h in hits] == ["divider", "adder", "divider"]
    assert hits[0]["lesson"] == "divider quotient\n\nunsigned operands"
    assert hits[2]["lesson"] == "divider remainder"
    assert hits[0]["score"] == Q.rank_lessons("divider adder quotient", db["entries"])[0][0]


@pytest.mark.parametrize("groups", [None, [[0]], [[0, 9]], [[0, 0]],
                                    [[0, True]], [[0, 1], [1, 2]]])
def test_invalid_lesson_groups_are_refused(tmp_path, groups):
    path = _tmp_db(tmp_path, ["divider quotient", "unsigned operands", "remainder"])
    db = json.loads(path.read_text())
    db["entries"][0]["lesson_groups"] = groups
    path.write_text(json.dumps(db))
    with pytest.raises(ValueError, match="lesson_groups"):
        Q.query("divider", db_path=path)
