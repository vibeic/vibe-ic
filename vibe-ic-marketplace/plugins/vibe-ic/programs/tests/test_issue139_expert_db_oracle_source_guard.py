"""issue #139 adjudication (2026-07-14) — the §4.05 ORACLE-SOURCE ban on
IC Expert DB lessons, plus the regression pins for the governance cleanup.

Owner's general-concept test: a lesson is legal ONLY if it is a design
principle a human expert would apply from the spec alone. A lesson keyed on a
hidden-scorer artifact (the scorer-side `.env` TOPLEVEL / VERILOG_SOURCES,
"harness metadata", the golden `output.*`) is only actionable via a forbidden
oracle read — it is benchmark gaming, not experience. Two shipped lessons
violated this (one literally advised reconciling the top-module name "to the
harness TOPLEVEL/VERILOG_SOURCES from .env"); they were cleaned, and
`ic_expert_db_consistency_check` now rejects the whole class structurally.
"""
import copy
import json
import re
from pathlib import Path

import ic_expert_db_capture as CAP
import ic_expert_db_consistency_check as C

PLUGIN = Path(__file__).resolve().parent.parent.parent
DB = PLUGIN / "agents" / "ic_expert_db" / "ic_expert_db.json"


def _trial_db(tmp_path, lesson):
    db = json.loads(DB.read_text())
    db["entries"].append(
        {"ic_class": "trial-class", "lesson_count": 1, "lessons": [lesson]})
    db["classes"] = len(db["entries"])
    db["total_lessons"] = sum(len(e["lessons"]) for e in db["entries"])
    p = tmp_path / "trial_db.json"
    p.write_text(json.dumps(db, ensure_ascii=False))
    return p


# ── the structural gate rejects every oracle-source shape ───────────────────

def test_gate_rejects_env_sourced_lesson(tmp_path):
    p = _trial_db(tmp_path, "When the emitted top name differs, reconcile it "
                            "to the toplevel recorded in the scorer's .env "
                            "file before delivery.")
    rep = C.check(p)
    assert not rep["pass"]
    assert any("ORACLE-SOURCE" in f for f in rep["findings"])


def test_gate_rejects_verilog_sources_keyed_lesson(tmp_path):
    p = _trial_db(tmp_path, "When VERILOG_SOURCES lists multiple paths, fan "
                            "each module into the file that variable names.")
    rep = C.check(p)
    assert not rep["pass"]
    assert any("ORACLE-SOURCE" in f for f in rep["findings"])


def test_gate_rejects_harness_metadata_lesson(tmp_path):
    p = _trial_db(tmp_path, "The mismatch is recoverable from harness "
                            "metadata the pipeline consumes, so rename the "
                            "module to match at integration time.")
    rep = C.check(p)
    assert not rep["pass"]
    assert any("ORACLE-SOURCE" in f for f in rep["findings"])


def test_gate_rejects_golden_output_context_lesson(tmp_path):
    p = _trial_db(tmp_path, "Cross-check the port list against output.context "
                            "when the prompt table is ambiguous about widths.")
    rep = C.check(p)
    assert not rep["pass"]
    assert any("ORACLE-SOURCE" in f for f in rep["findings"])


# ── no false fire on legitimate checker-contract craft ──────────────────────

def test_gate_accepts_checker_binding_craft(tmp_path):
    p = _trial_db(tmp_path, "A hidden/whitebox checker commonly binds "
                            "hierarchically by the design's own internal "
                            "signal names, so keep spec-introduced signal "
                            "identifiers verbatim on top-level nets.")
    assert C.check(p)["pass"]


def test_gate_accepts_input_context_keyed_lesson(tmp_path):
    p = _trial_db(tmp_path, "When input.context supplies N separate RTL "
                            "files, preserve that partition on emit and pass "
                            "the untouched files through unchanged.")
    assert C.check(p)["pass"]


# ── capture tool refuses an oracle-source lesson end-to-end ─────────────────

def test_capture_validate_refuses_oracle_source_lesson():
    db = json.loads(DB.read_text())
    findings = CAP.validate(
        copy.deepcopy(db), "trial-class",
        "Reconcile the generated top-module identifier to the toplevel the "
        "scorer's .env records when they differ from the prompt name.")
    assert any("ORACLE-SOURCE" in f for f in findings)


# ── regression pins: the cleaned DB stays cleaned ───────────────────────────

_BANNED_SHIPPED = [
    re.compile(r"\.env\b"),
    re.compile(r"\bVERILOG_SOURCES\b"),
    re.compile(r"\bharness\s+(?:metadata|TOPLEVEL)\b", re.I),
    re.compile(r"\bproblem-slug\b", re.I),
    re.compile(r"\binput\.json\s+id\b", re.I),
    re.compile(r"\bharness-toplevel-alias rule\b", re.I),
    re.compile(r"\bid-derived name variant", re.I),
    re.compile(r"\boracle silently\b", re.I),
]


def test_shipped_db_carries_no_oracle_sourced_lesson():
    d = json.loads(DB.read_text())
    hits = [(e["ic_class"], l[:80])
            for e in d["entries"] for l in e["lessons"]
            for rx in _BANNED_SHIPPED if rx.search(l)]
    assert not hits, f"oracle-sourced lesson(s) shipped: {hits}"


def test_shipped_db_passes_hardened_gate():
    rep = C.check(DB)
    assert rep["pass"], rep["findings"]


def test_id_slug_naming_lesson_stays_removed():
    """The rejected 'bind the top name to the id/slug convention' rule must
    not return in ANY class — an id-derived name is a dataset naming
    convention, not design experience (owner adjudication, issue #139)."""
    d = json.loads(DB.read_text())
    pat = re.compile(r"bind the emitted TOP module name|design<problem-slug>",
                     re.I)
    hits = [e["ic_class"] for e in d["entries"]
            for l in e["lessons"] if pat.search(l)]
    assert not hits, f"id-slug naming lesson resurfaced in: {hits}"
