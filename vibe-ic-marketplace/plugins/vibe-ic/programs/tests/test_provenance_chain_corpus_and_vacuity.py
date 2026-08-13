#!/usr/bin/env python3
"""`provenance_chain_check` over a CORPUS, and the vacuous PASS it used to print.

BATCH IDX group (a): this checker was reachable only from its own test — a
fixture the author wrote proves the logic, never the artefacts. Wiring it into
the corpus run is the remedy, and measuring the corpus first is what turned up
the defect these tests pin.

MEASURED 2026-08-14 on `fix/1116-provenance-ledger-is-inside-the-producers-reach`:
22 tracked `provenance.jsonl`, of which **13 were single-record**. The verdict
guard read

    if len(recs) > 1 and chained == 0:      # NOT_CHECKED

so those 13 fell through to `[PASS] chain intact across 0 chained record(s)`.
A chain over zero records is vacuously intact. Wiring the checker as it stood
would have published 13 green lines for ledgers whose chain was never verified —
the exact shape of "a gate that has never met an artefact reporting success".

Fixtures are synthesized: neutral step ids, neutral paths, no design, PDK or
vendor literal.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PLUGIN = _HERE.parent.parent


def _gate():
    path = _PLUGIN / "programs" / "provenance_chain_check.py"
    spec = importlib.util.spec_from_file_location("_pcc", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_pcc"] = mod
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True          # never write into the shipped tree
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


G = _gate()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _ledger(root: Path, records: list[dict]) -> Path:
    """Write a ledger whose chain_prev links are internally consistent."""
    root.mkdir(parents=True, exist_ok=True)
    lines, prev = [], None
    for rec in records:
        r = dict(rec)
        if prev is not None:
            r["chain_prev"] = _sha(prev)
        line = json.dumps(r, sort_keys=True)
        lines.append(line)
        prev = line
    (root / G.LEDGER_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def test_a_single_record_ledger_is_NOT_CHECKED_not_a_pass(tmp_path, capsys):
    """THE REGRESSION. One record cannot carry `chain_prev` at all.

    `chain_prev` is written on the records AFTER the first, so a lone record is
    structurally unchainable. The honest verdict is NOT_CHECKED; the old guard
    printed `[PASS] chain intact across 0 chained record(s)`.
    """
    root = _ledger(tmp_path / "run", [{"step": "s1", "outputs": []}])
    rc = G.main([str(root)])
    assert rc == G.RC_UNRUNNABLE, "a chain over ZERO records is not an intact chain"
    assert rc != G.RC_OK
    err = capsys.readouterr().err
    assert "NOT_CHECKED" in err and "structurally unchainable" in err


def test_many_records_none_chained_is_NOT_CHECKED(tmp_path, capsys):
    """The pre-#1116 ledger: several records, no chain written."""
    root = tmp_path / "run"
    root.mkdir(parents=True)
    lines = [json.dumps({"step": f"s{i}", "outputs": []}, sort_keys=True)
             for i in range(3)]
    (root / G.LEDGER_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert G.main([str(root)]) == G.RC_UNRUNNABLE
    assert "predates" in capsys.readouterr().err


def test_an_intact_chain_over_REAL_links_still_passes(tmp_path):
    """The fix must not make the checker unable to say yes.

    Paired with the two above: without this, "return RC_UNRUNNABLE always" would
    satisfy them and the checker would assert nothing.
    """
    root = _ledger(tmp_path / "run", [{"step": "s1", "outputs": []},
                                      {"step": "s2", "outputs": []},
                                      {"step": "s3", "outputs": []}])
    assert G.main([str(root)]) == G.RC_OK


def test_a_BROKEN_chain_is_TAMPER(tmp_path):
    """And it must still fail when the property is genuinely violated."""
    root = _ledger(tmp_path / "run", [{"step": "s1", "outputs": []},
                                      {"step": "s2", "outputs": []},
                                      {"step": "s3", "outputs": []}])
    p = root / G.LEDGER_NAME
    lines = p.read_text().splitlines()
    rec = json.loads(lines[1]); rec["chain_prev"] = "0" * 64
    lines[1] = json.dumps(rec, sort_keys=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert G.main([str(root)]) == G.RC_TAMPER


def test_an_EMPTY_corpus_refuses(tmp_path, capsys):
    """Zero-denominator: no ledger anywhere is not a clean corpus."""
    (tmp_path / "empty").mkdir()
    assert G.check_corpus(tmp_path / "empty") == G.RC_UNRUNNABLE
    assert "VACUOUS" in capsys.readouterr().err


def test_a_corpus_where_NOTHING_is_verifiable_refuses(tmp_path, capsys):
    """Today's real shape: ledgers exist, none carries a chain.

    This is why the hygiene script calls it through
    `run_tolerating_uncheckable` — rc=2 with a denominator, not a green line
    over unverified ledgers.
    """
    for i in range(3):
        _ledger(tmp_path / f"run{i}", [{"step": "s1", "outputs": []}])
    assert G.check_corpus(tmp_path) == G.RC_UNRUNNABLE
    assert "never met a chain it could check" in capsys.readouterr().err


def test_a_corpus_with_ONE_verifiable_chain_passes(tmp_path):
    """The denominator is disclosed and a real chain still decides it."""
    _ledger(tmp_path / "unchained", [{"step": "s1", "outputs": []}])
    _ledger(tmp_path / "chained", [{"step": "s1", "outputs": []},
                                   {"step": "s2", "outputs": []}])
    assert G.check_corpus(tmp_path) == G.RC_OK


def test_a_corpus_containing_TAMPER_fails_even_beside_a_good_root(tmp_path):
    """One broken chain is not averaged away by a healthy neighbour."""
    _ledger(tmp_path / "good", [{"step": "s1", "outputs": []},
                                {"step": "s2", "outputs": []}])
    bad = _ledger(tmp_path / "bad", [{"step": "s1", "outputs": []},
                                     {"step": "s2", "outputs": []}])
    p = bad / G.LEDGER_NAME
    lines = p.read_text().splitlines()
    rec = json.loads(lines[1]); rec["chain_prev"] = "f" * 64
    lines[1] = json.dumps(rec, sort_keys=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert G.check_corpus(tmp_path) == G.RC_TAMPER


def test_the_three_outcomes_are_distinct():
    """Guards the guard: collapsed constants satisfy every assertion above."""
    assert len({G.RC_OK, G.RC_TAMPER, G.RC_UNRUNNABLE}) == 3
