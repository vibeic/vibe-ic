"""A demand probe's ZERO must carry the evidence that it was measured.

THE MEASURED DEFECT
-------------------
A fleet Phase-1 run printed::

    Layer demand:        0 layer(s) demanded by the input, 0 silently empty
    overall.pct = 100.0%   status = PASS

while `L21_POWER_INTENT.json` was a byte-empty skeleton
(`extraction_status: NOT_YET_EXTRACTED`, every field an empty container) and
four of the design's own input documents stated its power domains outright.

The zero was reached from ``stated["count"] == 0`` alone. The extractor behind
that count already returns ``docs_read`` / ``tables_seen`` / ``tables_qualified``
and the probe threw them away, so one printed 0 covered three different worlds:
a measured zero, a zero over zero documents, and a zero whose table parser did
not admit the shape the design used while the documents state the subject in
plain sight.

WHAT EACH DIRECTION OF THIS FILE IS FOR
---------------------------------------
The FIRE cases below (``test_a_contradicted_zero_*``, ``test_a_zero_over_no_
documents_*``, ``test_the_summary_line_*``) fail against the byte-identical
pre-fix program: it has no ``zero_unexamined`` key, no ``examined`` record, no
``zero_is_measured`` stamp, and it reports ``NOT_DEMANDED`` for the contradicted
project.

The QUIET cases are the half that keeps this from being a rule that fires on
everything. Each one is a project where the property legitimately holds, and
each one is drawn from a shape actually present in the tracked corpus:

* a document that states no supply at all                  (13 projects)
* a document that MENTIONS volts in prose without stating a supply
  ("the supply voltage is reduced from 2.5 to 1.8 V" and two more like it, in
  three projects; an earlier draft of the scan fired on all three)
* a layer holding its content under a different key vocabulary (29 projects) --
  a real and separate defect, but not an empty skeleton
* a layer that is satisfied

Chip-agnostic throughout: every fixture uses conventional supply-net spellings
and generic protocol prose, no design's or PDK's literals.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
PROG = _PROGRAMS / "phase1_layer_demand_probe.py"

import phase1_layer_demand_probe as P  # noqa: E402

# ── fixtures ─────────────────────────────────────────────────────────────────

#: The measured shape: the design STATES its rails, but not inside a markdown
#: table the sibling producer's table parser admits, so the extractor returns 0.
_DOC_STATES_RAILS_IN_PROSE = """\
# Product Metadata

The block is a peripheral on the system bus.

- **Power domains:** vdd_core/vss_core (core logic, 1.2 V digital).
- **Power domains:** vdd_io/vss_io (pad ring, 3.3 V).

VDDA    Analog supply, nominal 1.8 V.
"""

#: Volts are MENTIONED, no supply is STATED. Three real corpus projects have
#: this shape; an earlier draft of the corroborating scan fired on all three.
_DOC_MENTIONS_VOLTS_IN_PROSE = """\
# Protocol Overview

Most significantly, the supply voltage is reduced from 2.5 to 1.8 V in the
later revision of the standard, which lowers link power.

The connector is sometimes confused with the 12V auxiliary connector used by
other add-in cards.

Signalling uses a differential pair; VBUS and ground return on the shell.

Ground bounce is limited to 100 mV at the pad ring.
"""

#: No supply, no volts.
_DOC_STATES_NOTHING_ABOUT_POWER = """\
# Timing

| Parameter | Value |
|---|---|
| Temp | 27 C |
| Clock | 100 MHz |
"""

#: The shape the extractor DOES admit: a qualifying supply table.
_DOC_STATES_RAILS_IN_TABLE = """\
# Constraints

## Supplies / levels

| Rail | Voltage | Note |
|---|---|---|
| VDDA | 1.8 V | analog supply |
| VSS  | 0 V   | common ground |
"""

#: A byte-empty L21, exactly as `phase1_post_process.emit_l_doc_skeleton`
#: writes it.
_EMPTY_SKELETON = {
    "doc_id": "L21",
    "doc_name": "L21_POWER_INTENT",
    "applicability": "APPLICABLE",
    "fields": {"power_domains": [], "isolation_cells": [],
               "level_shifters": [], "upf_path": None},
    "extraction_status": "NOT_YET_EXTRACTED",
    "extraction_evidence": {},
}

#: A layer holding real content, but under keys `layer_holds` does not count.
#: 29 tracked projects look like this. It is NOT an empty skeleton.
_FILLED_UNDER_OTHER_KEYS = {
    "doc_id": "L21",
    "doc_name": "L21_POWER_INTENT",
    "applicability": "APPLICABLE",
    "fields": {
        "power_domains": [], "isolation_cells": [], "level_shifters": [],
        "upf_path": None,
        "power_domains_summary": [
            {"rail": "VDD", "domain": "core", "purpose": "core supply"},
            {"rail": "VSS", "domain": "ground", "purpose": "common ground"},
        ],
        "supplies": {"VDD": 1.2, "VDDA": 1.8},
    },
    "extraction_status": "NOT_YET_EXTRACTED",
    "extraction_evidence": {},
}


def _project(tmp_path, doc_text, l21=None, write_docs=True):
    if write_docs:
        d = tmp_path / "input" / "docs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "L1_PRODUCT.md").write_text(doc_text, encoding="utf-8")
    g = tmp_path / "phase1" / "generated_docs"
    g.mkdir(parents=True, exist_ok=True)
    (g / "L21_POWER_INTENT.json").write_text(
        json.dumps(l21 if l21 is not None else _EMPTY_SKELETON),
        encoding="utf-8")
    return tmp_path


def _l21(res):
    return res["layers"][0]


def _run(project, *extra):
    return subprocess.run([sys.executable, str(PROG), str(project), *extra],
                          capture_output=True, text=True, timeout=60)


# ── FIRE: the defect ─────────────────────────────────────────────────────────
def test_a_contradicted_zero_is_a_fail_not_a_silent_pass(tmp_path):
    """The whole rule, in one case.

    The extractor returns zero (the rails are not in a table it admits), the
    layer is a byte-empty NOT_YET_EXTRACTED skeleton, and the design's own
    input document states its power domains. Pre-fix this was `NOT_DEMANDED`,
    exit 0, and "0 layers demanded by the input" in the SUMMARY.
    """
    proj = _project(tmp_path, _DOC_STATES_RAILS_IN_PROSE)
    res = P.evaluate(proj)
    layer = _l21(res)
    assert layer["status"] == "SILENT_EMPTY", layer
    assert layer["demand_source"] == "input_corpus_scan", layer
    assert res["silent_empty"] == ["L21_POWER_INTENT"], res
    assert _run(proj).returncode == 1


def test_the_contradiction_is_quoted_back_with_file_and_line(tmp_path):
    """A FAIL that does not say which line contradicted it is not actionable —
    and cannot be told apart from a rule that fires on a hunch."""
    layer = _l21(P.evaluate(_project(tmp_path, _DOC_STATES_RAILS_IN_PROSE)))
    items = layer["stated_items"]
    assert items, layer
    for it in items:
        assert it["evidence"]["file"], it
        assert isinstance(it["evidence"]["line"], int), it
        assert it["evidence"]["text"], it
    assert layer["corroboration"]["documents"] >= 1, layer
    assert layer["corroboration"]["statements"] == len(items) or \
        layer["corroboration"]["items_truncated"], layer


def test_a_zero_over_zero_documents_is_not_a_measured_zero(tmp_path):
    """No input document exists. The probe may not call that NOT_DEMANDED.

    Not a FAIL either: a corpus that does not exist cannot state a demand. It
    is disclosed, and it is kept out of the measured-zero count.
    """
    proj = _project(tmp_path, "", write_docs=False)
    res = P.evaluate(proj)
    layer = _l21(res)
    assert layer["status"] == "ZERO_UNEXAMINED", layer
    assert layer["zero_is_measured"] is False, layer
    assert res["zero_unexamined"] == ["L21_POWER_INTENT"], res
    assert res["silent_empty"] == [], res
    assert _run(proj).returncode == 0


def test_every_zero_carries_the_examination_record_it_was_read_from(tmp_path):
    """The counters the extractor already returned and the probe discarded."""
    layer = _l21(P.evaluate(_project(tmp_path,
                                     _DOC_STATES_NOTHING_ABOUT_POWER)))
    ex = layer["examined"]
    assert ex["documents_read"] == 1, ex
    assert ex["tables_seen"] == 1, ex
    assert ex["tables_qualified"] == 0, ex
    assert layer["zero_is_measured"] is True, layer


def test_a_probe_that_could_not_run_is_not_a_measured_zero(tmp_path,
                                                           monkeypatch):
    """`PROBE_UNAVAILABLE` is the absence of an answer, not the answer 0."""
    import l21_doc_supply_rail_synth as S
    monkeypatch.setattr(S, "derive", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("synth is broken")))
    res = P.evaluate(_project(tmp_path, _DOC_STATES_RAILS_IN_TABLE))
    layer = _l21(res)
    assert layer["status"] == "PROBE_UNAVAILABLE", layer
    assert layer["zero_is_measured"] is False, layer
    assert res["zero_unexamined"] == ["L21_POWER_INTENT"], res


# ── FIRE: the line a reader actually sees ────────────────────────────────────
def test_the_summary_line_never_renders_a_bare_zero(tmp_path):
    """"0 layer(s) demanded by the input, 0 silently empty" was true and was
    not a measurement. Every zero now carries its denominator."""
    line = P.summary_line(P.evaluate(
        _project(tmp_path, _DOC_STATES_NOTHING_ABOUT_POWER)))
    assert "0 silently empty" in line, line
    assert "measured over 1 input document" in line, line


def test_the_summary_line_says_UNEXAMINED_when_nothing_was_read(tmp_path):
    line = P.summary_line(P.evaluate(_project(tmp_path, "", write_docs=False)))
    assert "UNEXAMINED" in line, line
    assert "L21_POWER_INTENT" in line, line


def test_the_stdout_names_the_empty_skeleton_and_the_document(tmp_path):
    out = _run(_project(tmp_path, _DOC_STATES_RAILS_IN_PROSE)).stdout
    assert "EMPTY SKELETON" in out, out
    assert "input_corpus_scan" in out, out
    assert "L1_PRODUCT.md" in out, out
    assert "consumer:" in out, out


# ── QUIET: the reverse cases, which must STILL pass ──────────────────────────
def test_a_document_that_states_no_supply_stays_not_demanded(tmp_path):
    """The ordinary case. If this ever fires the field becomes noise and gets
    switched off — which is how the original percentage stopped being read."""
    res = P.evaluate(_project(tmp_path, _DOC_STATES_NOTHING_ABOUT_POWER))
    assert _l21(res)["status"] == "NOT_DEMANDED", res
    assert res["silent_empty"] == [], res


def test_prose_that_merely_mentions_volts_is_not_a_stated_supply(tmp_path):
    """The narrowing that took the corpus sweep from 6 fires to 3.

    Three tracked projects carry exactly these sentences. A mention is not a
    statement: the subject has to be what the line is ABOUT, not a noun that
    happens to appear in it.

    The last line ("Ground bounce is limited to 100 mV") is the one shape that
    DOES lead with the subject and still is not a rail declaration. It is why
    the bare English word `ground` is not an accepted subject token — a noise
    spec is not a power intent.
    """
    res = P.evaluate(_project(tmp_path, _DOC_MENTIONS_VOLTS_IN_PROSE))
    assert _l21(res)["status"] == "NOT_DEMANDED", _l21(res)
    assert res["silent_empty"] == [], res


def test_a_layer_filled_under_other_keys_is_not_an_empty_skeleton(tmp_path):
    """The narrowing that took the sweep from 3 fires to 2.

    29 tracked projects hold their power content under keys `layer_holds` does
    not count. That is a key-vocabulary defect and a different rule's business;
    calling it "an empty skeleton" would make this rule fire on a filled layer.
    """
    proj = _project(tmp_path, _DOC_STATES_RAILS_IN_PROSE,
                    l21=_FILLED_UNDER_OTHER_KEYS)
    res = P.evaluate(proj)
    layer = _l21(res)
    assert layer["status"] == "NOT_DEMANDED", layer
    assert layer["layer_is_empty_skeleton"] is False, layer
    assert layer["corroboration"]["asked"] is False, layer
    assert res["silent_empty"] == [], res
    assert _run(proj).returncode == 0


def test_a_layer_that_claims_extraction_is_not_an_empty_skeleton(tmp_path):
    """`extraction_status` says the producer RAN and found nothing. That is a
    claim, not a skeleton; second-guessing it is a different check's job."""
    ran = dict(_EMPTY_SKELETON)
    ran["extraction_status"] = "EXTRACTION_FOUND_NOTHING"
    res = P.evaluate(_project(tmp_path, _DOC_STATES_RAILS_IN_PROSE, l21=ran))
    assert _l21(res)["status"] == "NOT_DEMANDED", _l21(res)
    assert res["silent_empty"] == [], res


def test_a_satisfied_layer_is_still_quiet(tmp_path):
    """The extractor path is untouched by this change."""
    proj = _project(tmp_path, _DOC_STATES_RAILS_IN_TABLE, l21={
        "doc_id": "L21",
        "fields": {"power_domains": [{"name": "VDDA"}, {"name": "VSS"}]},
        "extraction_status": "NOT_YET_EXTRACTED"})
    res = P.evaluate(proj)
    assert _l21(res)["status"] == "SATISFIED", res
    assert res["silent_empty"] == [], res
    assert res["zero_unexamined"] == [], res
    assert _run(proj).returncode == 0


def test_the_pre_existing_extractor_finding_is_unchanged(tmp_path):
    """The original defect this program was written for still reports through
    the extractor, and still says so."""
    proj = _project(tmp_path, _DOC_STATES_RAILS_IN_TABLE)
    res = P.evaluate(proj)
    layer = _l21(res)
    assert layer["status"] == "SILENT_EMPTY", layer
    assert layer["demand_source"] == "extractor", layer
    assert layer["input_states"] == 2, layer
    assert _run(proj).returncode == 1


def test_the_json_written_still_matches_the_returned_result(tmp_path):
    proj = _project(tmp_path, _DOC_STATES_RAILS_IN_PROSE)
    out = tmp_path / "demand.json"
    proc = _run(proj, "--json", str(out))
    assert proc.returncode == 1
    assert json.loads(out.read_text(encoding="utf-8")) == P.evaluate(proj)
