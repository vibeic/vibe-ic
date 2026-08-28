#!/usr/bin/env python3
"""A field a checker READS must have a PRODUCER (the #312 family).

The same shape was measured five times in one campaign — #309/#348
(`declared_rails`, 3 of 30), #366 (`.sby`, 0 tracked), #369
(`carried`/`decided`, computed then ignored), #365 (`duration_ms`, a
hardcoded 0), #312 (`ai_patches`, 4 readers 0 writers). Three of the five
were "the producer never existed", and the consequence is always silent: a
checker reading a field nobody fills sees an EMPTY value, and an empty value
is indistinguishable from a clean one.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from _published_corpus import corpus_root, needs_corpus

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "l_doc_field_producer_check.py"


# NOTE: field names in fixtures must be >= 4 chars. The program's reader
# regex enforces that minimum deliberately, to stop short names (`id`, `x`)
# matching half the codebase. Two tests here first used `g1`/`g2` and failed
# for that reason — the fixture was wrong, not the program.
def _mk_checker(progs: Path, name: str, field: str):
    (progs / f"{name}_check.py").write_text(
        f'def go(l):\n    fields = l.get("fields") or {{}}\n'
        f'    return fields.get("{field}")\n')


def _mk_doc(corpus: Path, rel: str, fields: dict):
    p = corpus / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"fields": fields}))


def _run(corpus: Path, progs: Path, bl: Path, *extra):
    return _pr.run(
        [sys.executable, str(_PROG), str(corpus), "--programs", str(progs),
         "--baseline", str(bl), *extra],
        capture_output=True, text=True)


def test_reader_with_no_producer_fails(tmp_path):
    """THE defect: the key exists in real documents, a checker reads it, and
    no document ever carries a value."""
    progs, corpus = tmp_path / "p", tmp_path / "c"
    progs.mkdir(); corpus.mkdir()
    _mk_checker(progs, "a", "never_filled")
    _mk_doc(corpus, "L1_X.json", {"never_filled": None})
    _mk_doc(corpus, "L2_Y.json", {"never_filled": []})
    r = _run(corpus, progs, tmp_path / "bl.json")
    assert r.returncode == 1, r.stdout
    assert "never_filled" in r.stdout


def test_one_populated_document_is_enough(tmp_path):
    """NO-LEAK: a producer that fills it even ONCE clears the finding. The
    gate asks 'does anything write this', not 'is it always written'."""
    progs, corpus = tmp_path / "p", tmp_path / "c"
    progs.mkdir(); corpus.mkdir()
    _mk_checker(progs, "a", "sometimes")
    _mk_doc(corpus, "L1_X.json", {"sometimes": None})
    _mk_doc(corpus, "L2_Y.json", {"sometimes": ["v"]})
    assert _run(corpus, progs, tmp_path / "bl.json").returncode == 0


def test_field_absent_everywhere_is_inconclusive_not_a_finding(tmp_path):
    """The scanner's own blind spot must not become a defect. A field that
    appears in NO document may be nested beyond this flat scan — reporting
    it would be inventing a finding out of the scan's limits."""
    progs, corpus = tmp_path / "p", tmp_path / "c"
    progs.mkdir(); corpus.mkdir()
    _mk_checker(progs, "a", "nested_elsewhere")
    _mk_doc(corpus, "L1_X.json", {"other": 1})
    r = _run(corpus, progs, tmp_path / "bl.json")
    assert r.returncode == 0, r.stdout
    assert "inconclusive" in r.stdout


def test_the_blind_spot_is_printed_not_hidden(tmp_path):
    """Silence about a blind spot reads as 'nothing else is wrong'."""
    progs, corpus = tmp_path / "p", tmp_path / "c"
    progs.mkdir(); corpus.mkdir()
    _mk_checker(progs, "a", "nested_elsewhere")
    _mk_doc(corpus, "L1_X.json", {"other": 1})
    r = _run(corpus, progs, tmp_path / "bl.json")
    assert "inconclusive (absent from every doc" in r.stdout


def test_baseline_admits_known_debt_and_blocks_a_new_one(tmp_path):
    progs, corpus = tmp_path / "p", tmp_path / "c"
    progs.mkdir(); corpus.mkdir()
    _mk_checker(progs, "a", "old_gap")
    _mk_doc(corpus, "L1_X.json", {"old_gap": None})
    bl = tmp_path / "bl.json"
    assert _run(corpus, progs, bl, "--write-baseline").returncode == 0
    assert _run(corpus, progs, bl).returncode == 0
    _mk_checker(progs, "b", "new_gap")
    _mk_doc(corpus, "L2_Y.json", {"old_gap": None, "new_gap": None})
    r = _run(corpus, progs, bl)
    assert r.returncode == 1 and "new_gap" in r.stdout


def test_baseline_may_not_grow(tmp_path):
    """A field LOSING its producer is a regression, not a fact to record."""
    progs, corpus = tmp_path / "p", tmp_path / "c"
    progs.mkdir(); corpus.mkdir()
    _mk_checker(progs, "a", "gap_one")
    _mk_doc(corpus, "L1_X.json", {"gap_one": None})
    bl = tmp_path / "bl.json"
    _run(corpus, progs, bl, "--write-baseline")
    _mk_checker(progs, "b", "gap_two")
    _mk_doc(corpus, "L2_Y.json", {"gap_one": None, "gap_two": None})
    r = _run(corpus, progs, bl, "--write-baseline")
    assert r.returncode == 1 and "refusing to GROW" in r.stdout


def test_paid_debt_must_leave_the_baseline(tmp_path):
    progs, corpus = tmp_path / "p", tmp_path / "c"
    progs.mkdir(); corpus.mkdir()
    _mk_checker(progs, "a", "gap_one")
    _mk_doc(corpus, "L1_X.json", {"gap_one": None})
    bl = tmp_path / "bl.json"
    _run(corpus, progs, bl, "--write-baseline")
    _mk_doc(corpus, "L2_Y.json", {"gap_one": ["now filled"]})   # producer appears
    r = _run(corpus, progs, bl)
    assert r.returncode == 1 and "now HAVE a producer" in r.stdout


@needs_corpus
def test_shipped_tree_passes_against_its_recorded_debt():
    """The recorded debt, re-measured against the L-doc corpus it was recorded
    over.

    THE CORPUS IS NAMED EXPLICITLY. It used to be left to the program's own
    default — `benchmark-data/ic` relative to the repo — and that default is now
    a directory of design INPUTS with no L-document in it. The program then read
    0 L-docs, found nothing populating `isolation_cells`, `level_shifters` or
    `tables`, and reported those three as "now HAVE a producer", i.e. as debt
    that had been PAID. Read over an empty corpus every recorded gap resolves
    itself, and the register empties by attrition rather than by repair — the
    exact inversion this gate exists to stop. So the corpus this asserts over is
    the published one, wherever it is, and where there is none the honest answer
    is a skip rather than a verdict about a register nobody could re-derive.
    """
    r = _pr.run([sys.executable, str(_PROG), str(corpus_root() / "ic")],
                       capture_output=True, text=True)
    if r.returncode == 2:
        return
    assert r.returncode == 0, r.stdout + r.stderr


def test_triage_survives_a_baseline_rewrite(tmp_path):
    """A register of bare names invites the worst possible repair —
    fabricating a producer so an entry disappears. Triage recorded against an
    entry must survive a `--write-baseline`, or the investigation is lost the
    first time the register is regenerated."""
    progs, corpus = tmp_path / "p", tmp_path / "c"
    progs.mkdir(); corpus.mkdir()
    _mk_checker(progs, "a", "gap_one")
    _mk_doc(corpus, "L1_X.json", {"gap_one": None})
    bl = tmp_path / "bl.json"
    _run(corpus, progs, bl, "--write-baseline")
    d = json.loads(bl.read_text())
    d["triage"] = {"gap_one": "investigated: real"}
    bl.write_text(json.dumps(d))
    _run(corpus, progs, bl, "--write-baseline")          # regenerate
    assert json.loads(bl.read_text())["triage"]["gap_one"] == \
        "investigated: real"


def test_triage_for_a_vanished_entry_is_dropped(tmp_path):
    """Triage for an entry that no longer exists is stale annotation; keeping
    it would make the register describe a state that is gone."""
    progs, corpus = tmp_path / "p", tmp_path / "c"
    progs.mkdir(); corpus.mkdir()
    _mk_checker(progs, "a", "gap_one")
    _mk_doc(corpus, "L1_X.json", {"gap_one": None})
    bl = tmp_path / "bl.json"
    _run(corpus, progs, bl, "--write-baseline")
    d = json.loads(bl.read_text())
    d["triage"] = {"gap_one": "real", "long_gone": "stale"}
    bl.write_text(json.dumps(d))
    _run(corpus, progs, bl, "--write-baseline")
    t = json.loads(bl.read_text())["triage"]
    assert "gap_one" in t and "long_gone" not in t


def test_shipped_register_entries_all_carry_triage():
    """Every recorded entry must say what was found when it was
    investigated — including the one proven to be a FALSE POSITIVE of this
    gate's own rule, so nobody 'repairs' it by inventing a producer."""
    bl = _PROGRAMS / "l_doc_field_producer_baseline.json"
    if not bl.is_file():
        return
    d = json.loads(bl.read_text())
    for field in d.get("known", []):
        assert d.get("triage", {}).get(field), \
            f"{field} is recorded as debt with no triage"
