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
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
sys.path.insert(0, str(_PROGRAMS))

import hygiene_finding_delta as H  # noqa: E402
import gate_process_attestation as A  # noqa: E402

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
            "corpus": corpus, "exemption_expired": expired, "scope": None}


def _attestation(row):
    """One real helper-shaped process record."""
    state = row["state"]
    rc = {"PASS": 0, "FAIL": 1, "NOT_CHECKED": 2,
          "WROTE_CORPUS": 0}[state]
    verdict = ("[PASS] checked" if state == "PASS" else
               "[NOT_CHECKED] unavailable" if state == "NOT_CHECKED" else
               "[FAIL] named finding")
    return A.process_attestation(
        row["label"], verdict + "\n", rc,
        ["python3", "checker.py", row["label"]])


def _record(gates, **over):
    counts = {state: sum(g["state"] == state for g in gates)
              for state in H.TERMINAL_STATES}
    doc = {
        "listed_only": False,
        "declared": len(gates),
        "ran": sum(counts[state] for state in H.PROCESS_STATES),
        "decided": counts["PASS"] + counts["FAIL"],
        "passed": counts["PASS"],
        "failed": counts["FAIL"],
        "not_checked": counts["NOT_CHECKED"],
        "wrote_corpus": counts["WROTE_CORPUS"],
        "deferred": counts["LISTED"],
        "other_shard": counts["OTHER_SHARD"],
        "out_of_scope": counts["OUT_OF_SCOPE"],
        "not_checked_unexempted": [
            g["label"] for g in gates if g["state"] == "NOT_CHECKED"
            and g.get("exempt_until") in (None, "")],
        "exemptions_expired": [
            g["label"] for g in gates if g.get("exemption_expired")],
        "wiring_errors": [],
        "corpora": [],
        "shard": None,
        "today": "2026-08-15",
        "gates": gates,
        "process_attestations": [
            _attestation(g) for g in gates
            if g["state"] in H.PROCESS_STATES
            and not H._legacy_structural_empty(g)],
    }
    doc.update(over)
    return doc


def _refresh(doc, *, attest=True):
    """Re-derive the dispatcher's redundant counters after an adversarial edit."""
    gates = doc["gates"]
    fresh = _record(gates)
    for key in ("declared", "ran", "decided", "passed", "failed",
                "not_checked", "wrote_corpus", "deferred", "other_shard",
                "out_of_scope", "not_checked_unexempted",
                "exemptions_expired"):
        doc[key] = fresh[key]
    if attest:
        doc["process_attestations"] = fresh["process_attestations"]
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
    cp = _pr.run(
        [sys.executable, str(_PROG), "--base", str(base), "--candidate", str(cand),
         "--base-host", base_host, "--candidate-host", cand_host, *extra],
        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


_BENCHMARK_SHA = "a" * 40


def _transition_pair(*, replacement_state="PASS", benchmark_sha=_BENCHMARK_SHA):
    """The exact future EMPTY -> external routed-DEF declaration shape."""
    common = _gate("common hygiene finding", "FAIL")
    empty = _gate(H.ROUTED_DEF_EMPTY_LABEL, "NOT_CHECKED",
                  H.ROUTED_DEF_CORPUS)
    empty.update(corpus_item=0, corpus_items=0)
    base = _record(
        [copy.deepcopy(common), empty],
        corpora=[{"name": H.ROUTED_DEF_CORPUS, "items": 0, "gates": 1,
                  "expansion": "EXPANDED"}],
        corpus_inputs={"benchmark_data_sha": benchmark_sha})

    labels = [template.format(cell="demo/openpdkx")
              for template in H.ROUTED_DEF_GATE_LABELS]
    rows = [_gate(label, replacement_state if i == 0 else "PASS",
                  H.ROUTED_DEF_CORPUS)
            for i, label in enumerate(labels)]
    for row in rows:
        row.update(corpus_item=1, corpus_items=1)
    candidate = _record(
        [copy.deepcopy(common), *rows],
        corpora=[{"name": H.ROUTED_DEF_CORPUS, "items": 1,
                  "gates": len(rows), "expansion": "EXPANDED"}],
        corpus_inputs={"benchmark_data_sha": benchmark_sha})
    attested = {rec["label"]: rec for rec in candidate["process_attestations"]}
    manifest_gates = [
        {"label": row["label"],
         "argv_sha256": attested[row["label"]]["argv_sha256"]}
        for row in rows]
    receipts = []
    for row in rows:
        rec = attested[row["label"]]
        rc = rec["returncode"]
        receipts.append({
            "schema": 1, "complete": True, "label": row["label"],
            "argv_sha256": rec["argv_sha256"], "returncode": rc,
            "semantic": {key: rec[key] for key in (
                "returncode", "verdict_line", "finding_identities",
                "semantic_sha256")},
            "owned": {
                "protocol": 1, "rc": rc,
                "body": rec["verdict_line"] + "\n",
                "problem": None, "outcome": "natural", "launched": True,
                "census_ok": True, "final_descendants": [], "observed": [],
                "capability_error": "",
            },
        })
    evidence = {
        "schema": 1, "complete": True, "origin": H.BENCHMARK_DATA_ORIGIN,
        "benchmark_data_sha": benchmark_sha,
        "corpora": [{
            "name": H.ROUTED_DEF_CORPUS,
            "items": [{
                "ordinal": 1,
                "path": "ic/demo/v0.3.0_openpdkx/phase3/stage3/pnr/routed.def",
                "mode": "100644", "blob": "b" * 40,
                "gates": manifest_gates,
            }],
        }],
        "execution_receipts": receipts,
    }
    return base, candidate, evidence


def _empty_structural_record(*, attested):
    """Aggregate form of the measured 116b/cab8 structural protocols."""
    empty = _gate(H.ROUTED_DEF_EMPTY_LABEL, "NOT_CHECKED",
                  H.ROUTED_DEF_CORPUS)
    empty.update(corpus_item=0, corpus_items=0)
    doc = _record(
        [*_base_gates(), empty],
        corpora=[{"name": H.ROUTED_DEF_CORPUS, "items": 0, "gates": 1,
                  "expansion": "EXPANDED"}],
        corpus_inputs={"benchmark_data_sha": _BENCHMARK_SHA})
    if attested:
        doc["process_attestations"].append(_attestation(empty))
    return doc


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
    changed = _base_gates()
    changed[0]["state"] = "FAIL"
    b = _record(changed)
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
    gates[3].update(exempt_until="2026-08-14", exempt_reason="past promise",
                    exemption_expired=True)
    cand = _record(gates, exemptions_expired=[gates[3]["label"]])
    d = H.delta(base, cand)
    assert d["status"] == H.INTRODUCED
    assert any(f[0] == H.EXPIRED_KIND for f in d["introduced"])


def test_a_record_that_disagrees_with_itself_about_expiry_refuses():
    """The paired guard for the case above: the per-gate flag set WITHOUT the
    top-level entry is a record that cannot be used as a denominator."""
    gates = _base_gates()
    gates[3].update(exempt_until="2026-08-14", exempt_reason="past promise",
                    exemption_expired=True)
    with pytest.raises(H.Refusal) as e:
        H.delta(_record(_base_gates()),
                _record(gates, exemptions_expired=[]))
    assert "disagrees with its gates" in str(e.value)


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


@pytest.mark.parametrize(
    ("mutate", "diagnostic"),
    [
        (lambda payload: payload[:-1] + ', "gates": []}',
         "duplicate JSON key"),
        (lambda payload: payload.replace('"seconds": 1', '"seconds": NaN', 1),
         "non-finite JSON number"),
    ],
)
def test_summary_json_refuses_ambiguous_numbers_and_keys(
        tmp_path, mutate, diagnostic):
    base = _write(tmp_path, "base.json", _record(_base_gates()))
    candidate = tmp_path / "ambiguous.json"
    payload = json.dumps(_record(_base_gates()))
    candidate.write_text(mutate(payload), encoding="utf-8")
    rc, out = _run(base, candidate)
    assert rc == H.RC_REFUSED
    assert diagnostic in out


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
    assert "aggregate" in str(e.value)


def test_an_empty_gate_list_is_a_run_that_did_not_happen():
    """An empty result is not a zero."""
    with pytest.raises(H.Refusal) as e:
        H.delta(_record([]), _record(_base_gates()))
    assert "no complete gate array" in str(e.value)


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
                                 "items": 0, "gates": 0}]))
    rc, out = _run(base, cand)
    assert rc == H.RC_REFUSED


def test_whole_record_refuses_a_missing_gate_attestation():
    base = _record(_base_gates())
    candidate = _record(_base_gates())
    candidate["process_attestations"].pop()
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate)
    assert "exact bijection" in str(e.value)


def test_whole_record_refuses_an_extra_process_attestation():
    base = _record(_base_gates())
    candidate = _record(_base_gates())
    candidate["process_attestations"].append(
        copy.deepcopy(candidate["process_attestations"][0]))
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate)
    assert "exact bijection" in str(e.value)


def test_whole_record_refuses_a_forged_redundant_count():
    base = _record(_base_gates())
    candidate = _record(_base_gates(), ran=99)
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate)
    assert "ran count" in str(e.value)


def test_whole_record_refuses_pass_rc_zero_with_failure_semantics():
    """A self-consistent digest cannot turn measured red output into PASS."""
    base = _record(_base_gates())
    candidate = _record(_base_gates())
    row = candidate["gates"][0]
    candidate["process_attestations"][0] = A.process_attestation(
        row["label"], "[FAIL] checker found a real defect\n", 0,
        ["python3", "checker.py", row["label"]])
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate)
    assert "claims PASS" in str(e.value)
    assert "[FAIL] checker found a real defect" in str(e.value)


def test_whole_record_does_not_accept_bool_as_an_integer_count():
    base = _record(_base_gates())
    candidate = _record(_base_gates(), declared=True)
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate)
    assert "must be an integer" in str(e.value)


def test_whole_record_does_not_accept_integer_as_expiry_boolean():
    base = _record(_base_gates())
    candidate = _record(_base_gates())
    candidate["gates"][0]["exemption_expired"] = 0
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate)
    assert "boolean expiry verdict" in str(e.value)


def test_whole_record_refuses_a_non_terminal_state():
    gates = _base_gates()
    gates[0]["state"] = "QUEUED"
    candidate = _record(gates, process_attestations=[])
    with pytest.raises(H.Refusal) as e:
        H.delta(_record(_base_gates()), candidate)
    assert "non-terminal state" in str(e.value)


def test_out_of_scope_is_counted_and_disclosed_without_a_fake_process():
    gates = _base_gates()
    gates[0]["state"] = "OUT_OF_SCOPE"
    base = _record(copy.deepcopy(gates))
    candidate = _record(copy.deepcopy(gates))
    d = H.delta(base, candidate)
    assert d["status"] == H.CLEAN
    assert d["no_verdict_either_side"] == [gates[0]["label"]]
    assert all(rec["label"] != gates[0]["label"]
               for rec in candidate["process_attestations"])


@pytest.mark.parametrize("attested", [False, True])
def test_exact_structural_empty_protocols_self_compare_clean(attested):
    """116b synthesized no process; cab8 emits one real rc-2 process record."""
    base = _empty_structural_record(attested=attested)
    candidate = copy.deepcopy(base)
    d = H.delta(base, candidate)
    assert d["status"] == H.CLEAN
    assert d["no_verdict_either_side"] == [H.ROUTED_DEF_EMPTY_LABEL]


def test_structural_empty_refuses_a_forged_rc_zero_attestation():
    base = _empty_structural_record(attested=True)
    candidate = copy.deepcopy(base)
    row = candidate["gates"][-1]
    candidate["process_attestations"][-1] = A.process_attestation(
        row["label"], "[PASS] forged\n", 0,
        ["python3", "structural-empty.py"])
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate)
    assert "claims NOT_CHECKED over process rc 0" in str(e.value)


def test_structural_empty_refuses_a_mismatched_attestation_identity():
    base = _empty_structural_record(attested=True)
    candidate = copy.deepcopy(base)
    candidate["process_attestations"][-1]["label"] = "some other empty row"
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate)
    assert "exact bijection" in str(e.value)


# ══════════════════════════════════════════════════════════════════════
# The one bootstrap declaration transition: exact or refused
# ══════════════════════════════════════════════════════════════════════

def test_a_delta_with_no_transition_still_states_the_population_as_empty():
    """THE DIRECTION THAT MAKES THE ONE ABOVE MEAN SOMETHING.

    `corpus_transitions` used to be written only when there WAS a transition,
    so a record produced by a run that examined the corpora and found none was
    byte-identical to a record produced by a run in which the producer never
    executed. MEASURED: the end-to-end post-bootstrap test read the key with
    `.get(..., [])`, matched a record that did not have it, and reported the
    equal-corpus path as proved while never reaching it. Empty is a population;
    absent is a silence.

    AND THE SECOND ARM IS THE POST-BOOTSTRAP PROPERTY ITSELF: two runs whose
    corpus is ALREADY EXPANDED and equal must produce an ordinary CLEAN delta
    and demand no second one-use transition. That is the claim
    `test_end_to_end_post_bootstrap_equal_corpus_uses_ordinary_delta` is named
    for and cannot reach — its stub knob does not cross the hermetic arm's
    `env -i` profile (`hermetic_candidate_runner.py:793`,
    `gatekeeper-verify-merge.sh:512-535` passes an exact `--env` list), so on
    any docker-capable host BOTH its arms run the ordinary one-gate dispatch
    and the corpora are equal because neither expanded. It is pinned here,
    where `delta` is handed the expanded records directly and the assertion can
    actually fail.
    """
    base, candidate, _evidence = _transition_pair()
    for arm, pair in (("EMPTY on both arms", base), ("EXPANDED on both", candidate)):
        d = H.delta(pair, pair)
        assert "corpus_transitions" in d, (arm, sorted(d))
        assert d["corpus_transitions"] == [], (arm, d["corpus_transitions"])
        assert d["status"] == H.CLEAN, (arm, d)


def test_exact_attested_routed_def_empty_to_expanded_transition_is_clean():
    """Common red is carried; the exact manifest population is introduced."""
    base, candidate, evidence = _transition_pair()
    d = H.delta(base, candidate, evidence)
    assert d["status"] == H.CLEAN
    assert d["carried"] == [["FAIL", "common hygiene finding", ""]]
    transition = d["corpus_transitions"][0]
    assert {key: transition[key] for key in (
        "corpus", "base_items", "candidate_items", "replacement_gates",
        "benchmark_data_sha", "bounded_not_checked")} == {
            "corpus": H.ROUTED_DEF_CORPUS,
            "base_items": 0,
            "candidate_items": 1,
            "replacement_gates": 4,
            "benchmark_data_sha": _BENCHMARK_SHA,
            "bounded_not_checked": [],
        }
    assert len(transition["parent_evidence_sha256"]) == 64


def test_cli_accepts_only_an_explicit_parent_owned_transition_record(tmp_path):
    base, candidate, evidence = _transition_pair()
    base_path = _write(tmp_path, "base-transition.json", base)
    candidate_path = _write(tmp_path, "candidate-transition.json", candidate)
    evidence_path = _write(tmp_path, "parent-transition.json", evidence)
    rc, out = _run(
        base_path, candidate_path,
        extra=("--trusted-transition-evidence", str(evidence_path)))
    assert rc == H.RC_OK, out
    assert "exact corpus transition" in out
    assert "process-attested replacement gate(s)" in out


@pytest.mark.parametrize(
    ("mutate", "diagnostic"),
    [
        (lambda payload: payload[:-1] + ', "schema": 1}',
         "duplicate JSON key"),
        (lambda payload: payload.replace('"ordinal": 1', '"ordinal": NaN', 1),
         "non-finite JSON number"),
    ],
)
def test_parent_evidence_json_refuses_ambiguous_numbers_and_keys(
        tmp_path, mutate, diagnostic):
    base, candidate, evidence = _transition_pair()
    base_path = _write(tmp_path, "base-transition.json", base)
    candidate_path = _write(tmp_path, "candidate-transition.json", candidate)
    evidence_path = tmp_path / "ambiguous-parent-transition.json"
    evidence_path.write_text(mutate(json.dumps(evidence)), encoding="utf-8")
    rc, out = _run(
        base_path, candidate_path,
        extra=("--trusted-transition-evidence", str(evidence_path)))
    assert rc == H.RC_REFUSED
    assert diagnostic in out


def test_transition_refuses_without_parent_owned_evidence():
    base, candidate, _evidence = _transition_pair()
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate)
    assert "parent-owned canonical manifest" in str(e.value)


def test_parent_evidence_requires_activation_not_a_copied_phase1_empty_record():
    """An explicit bootstrap request cannot degrade into an ordinary no-op."""
    phase1_base, _expanded, evidence = _transition_pair()
    candidate = copy.deepcopy(phase1_base)
    with pytest.raises(H.Refusal) as e:
        H.delta(phase1_base, candidate, evidence)
    assert "retained the base declaration set" in str(e.value)


def test_cli_parent_evidence_requires_activation_not_a_copied_empty_record(
        tmp_path):
    phase1_base, _expanded, evidence = _transition_pair()
    base_path = _write(tmp_path, "phase1-base.json", phase1_base)
    candidate_path = _write(
        tmp_path, "candidate-copy.json", copy.deepcopy(phase1_base))
    evidence_path = _write(tmp_path, "parent-transition.json", evidence)
    rc, out = _run(
        base_path, candidate_path,
        extra=("--trusted-transition-evidence", str(evidence_path)))
    assert rc == H.RC_REFUSED
    assert "retained the base declaration set" in out


def test_transition_refuses_a_forged_positive_item_count():
    base, candidate, evidence = _transition_pair()
    candidate["corpora"][0]["items"] = 2
    for row in candidate["gates"][1:]:
        row["corpus_items"] = 2
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "every item ordinal" in str(e.value)


def test_transition_refuses_a_forged_gate_count():
    base, candidate, evidence = _transition_pair()
    candidate["corpora"][0]["gates"] += 1
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "says" in str(e.value) and "gate(s)" in str(e.value)


def test_transition_refuses_a_missing_process_attestation():
    base, candidate, evidence = _transition_pair()
    candidate["process_attestations"].pop()
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "exact bijection" in str(e.value)


def test_transition_refuses_a_forged_process_attestation():
    base, candidate, evidence = _transition_pair()
    candidate["process_attestations"][0]["returncode"] = 7
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "digest mismatch" in str(e.value)


def test_transition_refuses_a_self_consistent_candidate_lie_against_parent_rc():
    """Candidate JSON can agree with itself and still did not own the OS run."""
    base, candidate, evidence = _transition_pair()
    candidate["gates"][1]["state"] = "FAIL"
    _refresh(candidate)  # makes a fully self-consistent rc-1 FAIL attestation
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "complete process-semantic receipt" in str(e.value)


def test_transition_refuses_a_self_consistent_wrong_command_digest():
    base, candidate, evidence = _transition_pair()
    row = candidate["gates"][1]
    forged = A.process_attestation(
        row["label"], "[PASS] checked\n", 0,
        ["python3", "different-checker.py", row["label"]])
    candidate["process_attestations"][1] = forged
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "ordinal, command and complete process-semantic" in str(e.value)


def test_transition_refuses_candidate_semantics_that_disagree_with_parent():
    base, candidate, evidence = _transition_pair()
    row = candidate["gates"][1]
    candidate["process_attestations"][1] = A.process_attestation(
        row["label"], "[PASS] candidate-authored substitute\n", 0,
        ["python3", "checker.py", row["label"]])
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "complete process-semantic receipt" in str(e.value)


def test_transition_refuses_malformed_parent_semantic_digest():
    base, candidate, evidence = _transition_pair()
    evidence["execution_receipts"][0]["semantic"]["semantic_sha256"] = "0" * 64
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "digest mismatch" in str(e.value)


def test_transition_refuses_missing_parent_execution_receipt():
    base, candidate, evidence = _transition_pair()
    evidence["execution_receipts"].pop()
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "do not exact-cover" in str(e.value)


def test_transition_refuses_nonterminal_parent_execution_receipt():
    base, candidate, evidence = _transition_pair()
    evidence["execution_receipts"][0]["owned"]["census_ok"] = False
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "natural owned terminal result" in str(e.value)


def test_transition_refuses_bool_as_parent_protocol_integer():
    base, candidate, evidence = _transition_pair()
    evidence["execution_receipts"][0]["owned"]["protocol"] = True
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "natural owned terminal result" in str(e.value)


def test_transition_refuses_bool_as_evidence_schema_integer():
    base, candidate, evidence = _transition_pair()
    evidence["schema"] = True
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "no exact complete parent-owned" in str(e.value)


def test_transition_refuses_manifest_identity_not_in_candidate():
    base, candidate, evidence = _transition_pair()
    evidence["corpora"][0]["items"][0]["gates"][0]["label"] = \
        "unrelated label"
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "manifest gate" in str(e.value)


def test_transition_refuses_an_unrelated_base_gate_removal():
    base, candidate, evidence = _transition_pair()
    candidate["gates"] = candidate["gates"][1:]
    _refresh(candidate)
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "unrelated removals never transition" in str(e.value)


def test_transition_refuses_an_unrelated_candidate_gate_addition():
    base, candidate, evidence = _transition_pair()
    candidate["gates"].append(_gate("unrelated new gate", "PASS"))
    _refresh(candidate)
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "unrelated additions" in str(e.value)


def test_transition_refuses_an_unexempted_candidate_not_checked():
    base, candidate, evidence = _transition_pair(
        replacement_state="NOT_CHECKED")
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "unexempted NOT_CHECKED" in str(e.value)


def test_transition_discloses_a_bounded_candidate_not_checked():
    base, candidate, evidence = _transition_pair(
        replacement_state="NOT_CHECKED")
    row = candidate["gates"][1]
    row.update(exempt_until="2026-08-16", exempt_reason="known prerequisite",
               exemption_expired=False)
    _refresh(candidate)
    # The independent receipt remains rc 2, as does the refreshed candidate
    # process attestation; only the bounded exemption metadata changed.
    d = H.delta(base, candidate, evidence)
    assert d["status"] == H.CLEAN
    assert d["corpus_transitions"][0]["bounded_not_checked"] == [row["label"]]


@pytest.mark.parametrize("state", ["FAIL", "WROTE_CORPUS"])
def test_transition_candidate_findings_block(state):
    base, candidate, evidence = _transition_pair(replacement_state=state)
    d = H.delta(base, candidate, evidence)
    assert d["status"] == H.INTRODUCED
    assert any(finding[0] == state for finding in d["introduced"])


def test_transition_candidate_expired_exemption_blocks():
    base, candidate, evidence = _transition_pair()
    row = candidate["gates"][1]
    row.update(exempt_until="2026-08-14", exempt_reason="past promise",
               exemption_expired=True)
    _refresh(candidate)
    d = H.delta(base, candidate, evidence)
    assert d["status"] == H.INTRODUCED
    assert [H.EXPIRED_KIND, row["label"], H.ROUTED_DEF_CORPUS] \
        in d["introduced"]


@pytest.mark.parametrize("arm", ["base", "candidate"])
def test_transition_refuses_a_missing_benchmark_sha(arm):
    base, candidate, evidence = _transition_pair()
    {"base": base, "candidate": candidate}[arm]["corpus_inputs"] = {}
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "full Git object id" in str(e.value)


def test_transition_refuses_mismatched_benchmark_shas():
    base, candidate, evidence = _transition_pair()
    candidate["corpus_inputs"]["benchmark_data_sha"] = "b" * 40
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "do not bind the same immutable" in str(e.value)


def test_transition_refuses_a_failed_candidate_corpus_producer():
    base, candidate, evidence = _transition_pair()
    candidate["corpora"][0]["expansion"] = "PRODUCER_FAILED"
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "producer FAILED" in str(e.value)


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


# ══════════════════════════════════════════════════════════════════════
# vibe-ic#1764 — the delta may not re-collapse what the dispatcher split
# ══════════════════════════════════════════════════════════════════════

def _corpus_row(name, expansion):
    """One `corpora` row as `gate_dispatch_over` writes it.

    `items` is 0 in BOTH states on purpose: that integer is exactly what made
    the two indistinguishable, and a consumer that keys off it alone will read
    "somebody measured a population of zero" over a corpus nothing opened.
    """
    return {"name": name, "items": 0, "gates": 1, "expansion": expansion}


def test_a_corpus_nothing_opened_is_not_reported_as_one_that_was_read():
    """Both states, in one call, because the defect is about the PAIR."""
    # BOTH corpora on BOTH arms: the two runs must declare the same gate set
    # for either to be a denominator for the other, and the property under
    # test is the PARTITION between them, not a difference between the arms.
    def population(corpus):
        row = _gate(f'corpus "{corpus}" population', "NOT_CHECKED",
                    corpus=corpus)
        row["corpus_item"] = 0
        row["corpus_items"] = 0
        return row

    def arm():
        return _record(
            _base_gates() + [population("read but empty"),
                             population("never opened")],
            corpora=[_corpus_row("read but empty", "EXPANDED"),
                     _corpus_row("never opened", H.NO_CORPUS_EXPANSION)])

    d = H.delta(arm(), arm())

    assert d["empty_corpora"] == ["read but empty"], d["empty_corpora"]
    assert d["absent_corpora"] == ["never opened"], d.get("absent_corpora")
    assert "never opened" not in d["empty_corpora"], (
        "a corpus whose producer resolved nothing is reported under the "
        "sentence for a corpus that WAS read and holds none — the dispatcher "
        "stopped collapsing these and the delta put it back (vibe-ic#1764)")
    assert "read but empty" not in d["absent_corpora"]


def test_a_refusal_still_carries_both_corpus_lists():
    """A caller reads these with `.get`, and an absent key must not be a state
    the reader has to guess about — the same reason `exempt_until` is always
    present on a gate."""
    refused = H.compare(Path("/nonexistent-base.json"),
                        Path("/nonexistent-cand.json"), _HOST, _HOST)
    assert refused["status"] == H.REFUSED
    assert refused["empty_corpora"] == [] and refused["absent_corpora"] == []
    # THE THIRD LIST, ADDED FOR THE SAME REASON AND AFTER THE SAME DEFECT:
    # `corpus_transitions` was written only when there WAS a transition, so
    # both the refusal record and every no-transition record left the reader
    # guessing between "none" and "never looked".
    assert refused["corpus_transitions"] == [], refused


# ══════════════════════════════════════════════════════════════════════
# SAME TOOLCHAIN — the axis the host check does not cover (vibe-ic#1327)
#
# `toolchain_profile` decides comparability and had no caller. These cases
# drive it through this program's refusal path in all three directions, with
# the SAME two records and the SAME denominator on every arm: what moves is
# only the profile written beside them.
# ══════════════════════════════════════════════════════════════════════

import toolchain_profile as _TC  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


def _profile(*, iverilog: bool):
    """A profile in the shipped shape, differing in ONE keyed tool."""
    keyed = {t: True for t in _TC.KEYED_TOOLS}
    versions = {t: "1.0" for t in _TC.KEYED_TOOLS}
    keyed["iverilog"] = iverilog
    if not iverilog:
        versions["iverilog"] = _TC.UNKNOWN_VERSION
    return {"keyed": keyed,
            "recorded": {t: True for t in _TC.RECORDED_TOOLS},
            "versions": versions,
            "fingerprint": _TC.fingerprint(keyed, versions)}


def _pair(tmp_path):
    """One clean/clean pair: without a sidecar this comparison is CLEAN."""
    base = _write(tmp_path, "base.json", _record(_base_gates()))
    cand = _write(tmp_path, "cand.json", _record(_base_gates()))
    return base, cand


def test_no_sidecar_is_disclosed_not_refused(tmp_path):
    """A record from before this axis existed must not ban a landing."""
    base, cand = _pair(tmp_path)
    rc, out = _run(base, cand)
    assert rc == 0, out


def test_matching_toolchains_do_not_refuse(tmp_path):
    base, cand = _pair(tmp_path)
    for p in (base, cand):
        H.toolchain_sidecar(p).write_text(json.dumps(_profile(iverilog=True)))
    rc, out = _run(base, cand)
    assert rc == 0, out


def test_a_differing_toolchain_refuses(tmp_path):
    """THE MUTATION IS ONE TOOL. Same gates, same host, same day — the arms
    were simply not measured under the same tool set, and 25 failures of this
    repo's own red set turned on exactly that difference."""
    base, cand = _pair(tmp_path)
    H.toolchain_sidecar(base).write_text(json.dumps(_profile(iverilog=True)))
    H.toolchain_sidecar(cand).write_text(json.dumps(_profile(iverilog=False)))
    rc, out = _run(base, cand)
    assert rc == 2, out
    assert "same toolchain" in out
    assert "iverilog" in out


def test_an_unreadable_profile_refuses_and_says_so(tmp_path):
    """UNREADABLE never collapses into DIFFERENT: both refuse, and only one of
    them is somebody's fault."""
    base, cand = _pair(tmp_path)
    H.toolchain_sidecar(base).write_text("{not json")
    H.toolchain_sidecar(cand).write_text(json.dumps(_profile(iverilog=True)))
    rc, out = _run(base, cand)
    assert rc == 2, out
    assert "UNREADABLE" in out


def test_the_writer_and_the_reader_spell_the_sidecar_the_same(tmp_path):
    """Two spellings of one path is a write nothing ever reads."""
    import gatekeeper_review as GR
    p = tmp_path / "hygiene.json"
    assert GR.toolchain_sidecar(p) == H.toolchain_sidecar(p)


def test_gatekeeper_review_stamps_a_profile_it_can_adjudicate(tmp_path):
    """The producer's output must be an input `toolchain_profile.compare`
    calls SAME against this host — a stamp nothing can read is not a record."""
    import gatekeeper_review as GR
    p = tmp_path / "hygiene.json"
    p.write_text("{}")
    GR._stamp_toolchain(p)
    doc = json.loads(GR.toolchain_sidecar(p).read_text())
    verdict, _ = _TC.compare(doc, _TC.profile())
    assert verdict == _TC.SAME, verdict
