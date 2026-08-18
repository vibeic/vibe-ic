#!/usr/bin/env python3
"""Tests for `hygiene_finding_delta.py` — the subset rule for the hygiene tier (#1498).

WHY THIS FILE EXISTS AT ALL, WHICH IS ITSELF THE FINDING
========================================================
The program shipped in PR #1650 with three properties verified by hand at the
console and NONE of them committed. `plugin_full_audit`'s D1 dimension caught it
on the landing gate — `untested non-synth programs: ['hygiene_finding_delta']` —
and it was right to: a verification that lives in a terminal scrollback is not a
verification the next reader inherits.

WHAT A TEST OF A SUBSET RULE HAS TO PROVE
=========================================
Both directions, always. A comparator that answers CLEAN unconditionally passes
every "does a clean tree pass?" test ever written, and is worthless. So for each
property there is a paired case:

    inherited finding      -> CLEAN, rc 0     (it must not block)
    introduced finding     -> INTRODUCED, rc 1 (it MUST block)

and separately, every way the question can be unanswerable must REFUSE with rc 2
rather than fall through to either verdict. `REFUSED` is not a third flavour of
failure; it is the program declining to answer, which is the only honest output
when the two records cannot be differenced.

The refusal cases are enumerated rather than sampled because each one is a
distinct way a real run has lied or could lie: a missing file read as an empty
one, a `--list` run read as an executed one, a wiring error read as a clean
sheet, two hosts differenced against each other, two different days, two
different shards, a normalisation that merges two findings into one.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
sys.path.insert(0, str(_PROGRAMS))

import hygiene_finding_delta as H  # noqa: E402

_PROG = _PROGRAMS / "hygiene_finding_delta.py"
_HOST = "host-a"


# ══════════════════════════════════════════════════════════════════════
# Fixtures — a minimal record with the shape the dispatcher really writes
# ══════════════════════════════════════════════════════════════════════

def _gate(label, state, corpus=None, expired=False):
    """One gate as `repo_hygiene_gates.sh --summary-json` writes it.

    `exemption_expired` is present on EVERY gate, never omitted: the program
    refuses a record that lacks the key, because such a record predates the
    expiry contract and would difference an expired promise away.
    """
    return {"label": label, "state": state, "seconds": 1,
            "exempt_until": None, "exempt_reason": None,
            "corpus": corpus, "exemption_expired": expired}


def _record(gates, **over):
    doc = {
        "listed_only": False,
        "declared": len(gates),
        "ran": len(gates),
        "passed": sum(1 for g in gates if g["state"] == "PASS"),
        "failed": sum(1 for g in gates if g["state"] == "FAIL"),
        "not_checked": 0,
        "not_checked_unexempted": [],
        "exemptions_expired": [],
        "wiring_errors": [],
        "corpora": [],
        "shard": None,
        "today": "2026-08-15",
        "gates": gates,
    }
    doc.update(over)
    return doc


def _base_gates():
    """A base that is RED, because main is red — that is the whole premise."""
    return [
        _gate("chip-AGNOSTIC source guard", "PASS"),
        _gate("63x8 census freshness", "FAIL"),
        _gate("citation routing is true", "FAIL"),
        _gate("declared reports are written atomically", "PASS"),
    ]


def _write(tmp_path, name, doc):
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _run(base, cand, base_host=_HOST, cand_host=_HOST, extra=()):
    """Invoke the CLI and return (rc, stdout). rc is the program's, not a shell's."""
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--base", str(base), "--candidate", str(cand),
         "--base-host", base_host, "--candidate-host", cand_host, *extra],
        capture_output=True, text=True, timeout=60)
    return cp.returncode, cp.stdout + cp.stderr


# ══════════════════════════════════════════════════════════════════════
# The two directions. Neither is meaningful without the other.
# ══════════════════════════════════════════════════════════════════════

def test_an_inherited_finding_does_not_block():
    """The base's own red is carried, not charged to the candidate.

    This is the property that makes landing possible at all: main fails 9 of its
    own 83 gates, so a rule demanding zero would mean nothing ever lands.
    """
    base = _record(_base_gates())
    cand = _record(_base_gates())
    d = H.delta(base, cand)
    assert d["status"] == H.CLEAN
    assert len(d["introduced"]) == 0
    assert len(d["carried"]) == 2, "both of the base's FAILs must be reported as carried"


def test_an_introduced_finding_blocks():
    """The paired guard. Without this, CLEAN above is indistinguishable from
    a comparator that has stopped looking."""
    base = _record(_base_gates())
    gates = _base_gates()
    gates[0]["state"] = "FAIL"          # a gate that PASSES on the base
    cand = _record(gates)
    d = H.delta(base, cand)
    assert d["status"] == H.INTRODUCED
    assert len(d["introduced"]) == 1
    kind, label, _corpus = d["introduced"][0]
    assert label == "chip-AGNOSTIC source guard"
    assert kind == "FAIL"


def test_the_two_directions_differ_only_in_the_one_flipped_gate():
    """Stated explicitly so a future edit cannot make both arms pass by
    weakening the comparator: the inputs are equal but for one field."""
    a = _record(_base_gates())
    b = copy.deepcopy(a)
    b["gates"][0]["state"] = "FAIL"
    diffs = [(x["label"], x["state"], y["state"])
             for x, y in zip(a["gates"], b["gates"]) if x != y]
    assert diffs == [("chip-AGNOSTIC source guard", "PASS", "FAIL")]
    assert H.delta(a, a)["status"] == H.CLEAN
    assert H.delta(a, b)["status"] == H.INTRODUCED


def test_a_finding_the_candidate_fixed_is_reported_and_does_not_block():
    base = _record(_base_gates())
    gates = _base_gates()
    gates[1]["state"] = "PASS"          # 63x8 census freshness, repaired
    cand = _record(gates)
    d = H.delta(base, cand)
    assert d["status"] == H.CLEAN
    assert any(f[1] == "63x8 census freshness" for f in d["cleared"])


def test_an_expired_exemption_is_a_finding_in_its_own_right():
    """A promise coming due is a finding when the CANDIDATE is the one that let
    it lapse — the day-equality refusal below covers the calendar's case.

    The record must agree with itself: the per-gate flag and the top-level
    `exemptions_expired` list name the same promises, or the program refuses it
    as an unreliable denominator (which is how this test first failed).
    """
    base = _record(_base_gates())
    gates = _base_gates()
    gates[3]["exemption_expired"] = True
    cand = _record(gates, exemptions_expired=[gates[3]["label"]])
    d = H.delta(base, cand)
    assert d["status"] == H.INTRODUCED
    assert any(f[0] == H.EXPIRED_KIND for f in d["introduced"])


def test_a_record_that_disagrees_with_itself_about_expiry_refuses():
    """The paired guard for the case above: the per-gate flag set WITHOUT the
    top-level entry is a record that cannot be used as a denominator."""
    gates = _base_gates()
    gates[3]["exemption_expired"] = True
    with pytest.raises(H.Refusal) as e:
        H.delta(_record(_base_gates()), _record(gates))   # no `exemptions_expired`
    assert "disagrees with itself" in str(e.value)


# ══════════════════════════════════════════════════════════════════════
# Every way the question is unanswerable REFUSES. None of them passes.
# ══════════════════════════════════════════════════════════════════════

def test_a_missing_record_refuses_rather_than_differencing_to_zero(tmp_path):
    """The defect this whole program exists to avoid: an absent measurement
    read as an empty one. `I could not look` and `nothing was there` must not
    render the same."""
    base = _write(tmp_path, "b.json", _record(_base_gates()))
    rc, out = _run(base, tmp_path / "does-not-exist.json")
    assert rc == H.RC_REFUSED
    assert "missing measurement is not" in out


def test_an_unreadable_record_refuses(tmp_path):
    base = _write(tmp_path, "b.json", _record(_base_gates()))
    bad = tmp_path / "c.json"
    bad.write_text("{not json", encoding="utf-8")
    rc, out = _run(base, bad)
    assert rc == H.RC_REFUSED
    assert "unreadable" in out


def test_a_document_without_a_gates_array_refuses(tmp_path):
    base = _write(tmp_path, "b.json", _record(_base_gates()))
    cand = _write(tmp_path, "c.json", {"declared": 3})
    rc, out = _run(base, cand)
    assert rc == H.RC_REFUSED
    assert "no `gates` array" in out


def test_a_list_only_run_refuses_because_nothing_executed(tmp_path):
    """`--list` states what WOULD run. Differencing it would report every gate
    as cleared."""
    base = _write(tmp_path, "b.json", _record(_base_gates()))
    cand = _write(tmp_path, "c.json", _record(_base_gates(), listed_only=True))
    rc, out = _run(base, cand)
    assert rc == H.RC_REFUSED
    assert "`--list` run" in out


def test_a_record_with_wiring_errors_certifies_nothing(tmp_path):
    """In the dispatcher's own words the set was not correctly declared."""
    base = _write(tmp_path, "b.json",
                  _record(_base_gates(),
                          wiring_errors=["'X' can report NOT_CHECKED with no "
                                         "`uncheckable_until` line preceding it"]))
    cand = _write(tmp_path, "c.json", _record(_base_gates()))
    rc, out = _run(base, cand)
    assert rc == H.RC_REFUSED
    assert "WIRING ERROR" in out


def test_a_gate_missing_the_expiry_key_refuses(tmp_path):
    """A record that cannot report an expired promise would difference one away."""
    gates = _base_gates()
    del gates[0]["exemption_expired"]
    base = _write(tmp_path, "b.json", _record(_base_gates()))
    cand = _write(tmp_path, "c.json", _record(gates))
    rc, out = _run(base, cand)
    assert rc == H.RC_REFUSED
    assert "expiry contract" in out


def test_differencing_across_hosts_refuses(tmp_path):
    """These findings are host-dependent — `gate_host_independence_check` is
    itself one of the gates — and a foreign baseline fails toward PASS whenever
    it is redder."""
    base = _write(tmp_path, "b.json", _record(_base_gates()))
    cand = _write(tmp_path, "c.json", _record(_base_gates()))
    rc, out = _run(base, cand, base_host="host-a", cand_host="host-b")
    assert rc == H.RC_REFUSED
    assert "host" in out.lower()


def test_different_days_refuse_because_expiry_is_computed_against_the_day():
    base = _record(_base_gates(), today="2026-08-14")
    cand = _record(_base_gates(), today="2026-08-15")
    with pytest.raises(H.Refusal) as e:
        H.delta(base, cand)
    assert "different days" in str(e.value)


def test_different_shards_refuse_because_each_covers_a_different_set():
    base = _record(_base_gates(), shard="1/2")
    cand = _record(_base_gates(), shard="2/2")
    with pytest.raises(H.Refusal) as e:
        H.delta(base, cand)
    assert "shard" in str(e.value)


def test_an_empty_gate_list_is_a_run_that_did_not_happen():
    """An empty result is not a zero."""
    with pytest.raises(H.Refusal) as e:
        H.delta(_record([]), _record(_base_gates()))
    assert "not a zero" in str(e.value)


def test_a_normalisation_collapse_refuses_rather_than_merging_two_findings():
    """Two different gate labels that normalise to one key would be compared as
    a single finding. Asserted on the data rather than argued for."""
    with pytest.raises(H.Refusal) as e:
        H.check_injective(["a  b", "a b"], "base")
    assert "NORMALISATION COLLAPSE" in str(e.value)


def test_a_failed_corpus_producer_refuses(tmp_path):
    """A loop whose corpus never expanded ran zero iterations and found nothing
    — which is not the same as finding nothing wrong."""
    base = _write(tmp_path, "b.json", _record(_base_gates()))
    cand = _write(tmp_path, "c.json", _record(
        _base_gates(), corpora=[{"name": "ic-roots", "expansion": "PRODUCER_FAILED",
                                 "items": 0}]))
    rc, out = _run(base, cand)
    assert rc == H.RC_REFUSED


# ══════════════════════════════════════════════════════════════════════
# The CLI contract: exit codes and the JSON the verdict is rendered from
# ══════════════════════════════════════════════════════════════════════

def test_cli_exit_codes_are_derived_from_one_verdict_object(tmp_path):
    """Exit code and printed report must come from the same structure. A gate
    that prints FAIL while exiting 0 is itself a finding (see §2.1 of the gate
    v2 plan — it nearly landed 135 PRs on a false pass)."""
    base = _write(tmp_path, "b.json", _record(_base_gates()))
    same = _write(tmp_path, "same.json", _record(_base_gates()))
    gates = _base_gates()
    gates[0]["state"] = "FAIL"
    worse = _write(tmp_path, "worse.json", _record(gates))

    j_ok = tmp_path / "ok.json"
    rc, out = _run(base, same, extra=("--json", str(j_ok)))
    assert rc == H.RC_OK
    assert "[PASS]" in out and "no finding introduced" in out
    assert json.loads(j_ok.read_text())["status"] == H.CLEAN

    j_bad = tmp_path / "bad.json"
    rc, out = _run(base, worse, extra=("--json", str(j_bad)))
    assert rc == H.RC_INTRODUCED
    assert "[FAIL]" in out and "INTRODUCED" in out
    doc = json.loads(j_bad.read_text())
    assert doc["status"] == H.INTRODUCED
    assert len(doc["introduced"]) == 1


def test_the_three_exit_codes_are_distinct():
    """0 / 1 / 2 must not collapse: a caller branching on them needs `refused`
    to be different from `introduced`, or a run that could not look becomes a
    run that found a problem — and both become `not clean`."""
    assert len({H.RC_OK, H.RC_INTRODUCED, H.RC_REFUSED}) == 3
    assert (H.RC_OK, H.RC_INTRODUCED, H.RC_REFUSED) == (0, 1, 2)
