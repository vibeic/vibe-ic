from __future__ import annotations


import json


import sys


from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import gate_process_attestation as A  # noqa: E402


_PROGRAMS = Path(__file__).resolve().parents[1]


_REPO_ROOT = _PROGRAMS.parents[3]


_VERIFY = _REPO_ROOT / "tools" / "gatekeeper-verify-merge.sh"


def _gate(label, state, corpus=None, expired=False):
    """One gate as `repo_hygiene_gates.sh --summary-json` writes it."""
    return {"label": label, "state": state, "seconds": 1,
            "exempt_until": None, "exempt_reason": None,
            "corpus": corpus, "exemption_expired": expired, "scope": None}


def _attestation(gate):
    rc = {"PASS": 0, "FAIL": 1, "NOT_CHECKED": 2,
          "WROTE_CORPUS": 0}[gate["state"]]
    return A.process_attestation(
        gate["label"], "[PASS] checked\n" if rc == 0 else "[FAIL] named\n",
        rc, ["python3", "checker.py", gate["label"]])


def _record(gates):
    count = lambda state: sum(g["state"] == state for g in gates)
    return {
        "listed_only": False, "declared": len(gates),
        "ran": sum(count(s) for s in
                   ("PASS", "FAIL", "NOT_CHECKED", "WROTE_CORPUS")),
        "decided": count("PASS") + count("FAIL"),
        "passed": count("PASS"), "failed": count("FAIL"),
        "not_checked": count("NOT_CHECKED"),
        "wrote_corpus": count("WROTE_CORPUS"),
        "deferred": count("LISTED"), "other_shard": count("OTHER_SHARD"),
        "out_of_scope": count("OUT_OF_SCOPE"),
        "not_checked_unexempted": [
            g["label"] for g in gates if g["state"] == "NOT_CHECKED"
            and not g.get("exempt_until")],
        "exemptions_expired": [], "wiring_errors": [], "corpora": [],
        "shard": None, "today": "2026-08-15", "gates": gates,
        "process_attestations": [
            _attestation(g) for g in gates if g["state"] in
            ("PASS", "FAIL", "NOT_CHECKED", "WROTE_CORPUS")],
    }


def _write(tmp_path, name, doc):
    p = tmp_path / name
    p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return p


def test_both_arms_are_asked_for_a_hygiene_record():
    """The defect exactly: arm A2 set the variable and arm B did not, so the
    baseline had nothing to be differenced against."""
    src = _VERIFY.read_text(encoding="utf-8")
    assert "--env GATEKEEPER_HYGIENE_REPORT=/evidence/hygiene.json" in src, \
        "no land arm is asked for a hygiene record at all"
    assert ('publish_validated_arm_artifact "$A2_VALIDATION" "$A2_OUTPUT" '
            'hygiene.json "$BASE_HYG"') in src, \
        "arm A2 must write the BASE record"
    assert ('publish_validated_arm_artifact "$B2_VALIDATION" "$B2_OUTPUT" '
            'hygiene.json "$CAND_HYG"') in src, \
        ("arm B must write the CANDIDATE record — without it `CAND_HYG` is a "
         "path nothing ever writes and the subset rule has no candidate side")


def test_the_candidate_record_variable_is_read_and_not_only_assigned():
    """`CAND_HYG` was assigned once and never read. A variable that is only
    written is the signature of wiring that was planned and not finished."""
    src = _VERIFY.read_text(encoding="utf-8")
    reads = [l for l in src.splitlines()
             if "$CAND_HYG" in l or "${CAND_HYG" in l]
    assert len(reads) >= 2, (
        "CAND_HYG is assigned and never read — that was the whole defect:\n"
        + "\n".join(reads))


def test_the_base_record_is_cached_beside_the_base_log():
    """A `--base-gate-cache` hit SKIPS arm A2, so a cache that stores the log
    and not the record degrades every queued landing to the coarse comparison —
    in exactly the mode the merge queue runs in."""
    src = _VERIFY.read_text(encoding="utf-8")
    # THE HAZARD WAS REMOVED RATHER THAN FIXED, and that is why this test now
    # reads the other way round. 7c376e348 (v1.10.69) made the base-gate cache
    # unconditionally inert: the flag is still accepted, then cleared before it
    # can be consulted, because "reading or writing a mutable baseline cache
    # concurrently with that candidate would let it turn introduced failures
    # into 'pre-existing' ones". With no cache HIT possible, arm A2 always runs
    # and always writes BASE_HYG, so there is no cached record to store.
    #
    # Asserting the disable is not a retreat: it is the tripwire. Re-enabling
    # the cache re-opens exactly the defect this file exists for — a hit SKIPS
    # A2 and the differential silently degrades to the coarse comparison — so
    # whoever re-enables it fails HERE and has to restore the record and the
    # host alongside it.
    assert 'BASE_GATE_CACHE=""' in src, \
        ("the base-gate cache is live again; a hit SKIPS arm A2, so the cached "
         "entry must carry the base RECORD and the HOST that measured it, and "
         "this test has to go back to asserting that")
    disable = src.split('if [ -n "$BASE_GATE_CACHE" ]; then', 1)[1].split(
        "\nfi\n", 1)[0]
    assert 'BASE_GATE_CACHE=""' in disable, \
        "the cache is no longer cleared unconditionally when it is supplied"
