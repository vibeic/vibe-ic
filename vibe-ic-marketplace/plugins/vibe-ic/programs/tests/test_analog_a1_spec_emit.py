"""Unit tests for `analog_a1_spec_emit` — the A1 spec PRODUCER.

WHAT EACH TEST IS HOLDING THE PRODUCER TO
=========================================
Every assertion is about an ARTEFACT (a file that exists or must not exist,
and what it says) or about the rc of the SHIPPED A1 gate. Nothing reaches into
the producer's internals, so no test here can pass or fail on a renamed
helper — only on a wrong artefact or a wrong absence.

The load-bearing one is `test_a_block_with_no_attributed_spec_gets_NO_spec_json`.
Measured on the gate of record: a spec.json carrying `"specs": []` plus an
`extraction_status` field returns rc=1 A1_SPEC_NO_FIELDS, which
`analog_one_shot_runner` reports as **FAIL**; and a spec.json filled with
per-type defaults would return rc=0 **PASS** on a block whose spec the
documents never stated. Between those two, the only honest artefact is none —
plus a sidecar a consumer can read unambiguously as "not extracted".
"""
from __future__ import annotations

import json

import pytest

from _analog_producer_fixture import (
    A1, GATE_A1, block, make_project, run_prog, bdir, read_json)


# ── the positive case ─────────────────────────────────────────────────────
def test_a_bound_spec_becomes_a_spec_json_the_gate_of_record_accepts(tmp_path):
    p = make_project(tmp_path, [
        block("vreg_alpha", "ldo",
              [{"name": "Vout", "target": 1.8, "unit": "V",
                "evidence_text": "regulated to 1.8 V"}]),
    ])
    cp = run_prog(A1, p)
    assert cp.returncode == 0, cp.stderr

    spec = bdir(p, "vreg_alpha") / "spec.json"
    assert spec.is_file(), "A1 bound a spec and wrote no artefact"
    body = read_json(spec)
    assert isinstance(body.get("specs"), list) and body["specs"], body
    entry = body["specs"][0]
    assert entry["name"] == "vout"
    assert entry["target"] == pytest.approx(1.8)
    assert entry["source"] == "L5"
    assert entry["evidence_text"] == "regulated to 1.8 V"

    gate = run_prog(GATE_A1, p, "--block", "vreg_alpha")
    assert gate.returncode == 0, (
        "the artefact this producer writes must satisfy the gate that judges "
        f"it: {gate.stdout}{gate.stderr}")


def test_the_emitted_spec_names_its_input_and_declares_no_defaults(tmp_path):
    p = make_project(tmp_path, [
        block("vreg_alpha", "ldo",
              [{"name": "Vout", "target": 1.8, "unit": "V"}]),
    ])
    assert run_prog(A1, p).returncode == 0
    prov = read_json(bdir(p, "vreg_alpha") / "spec.json")["_provenance"]
    assert prov["producer"] == "analog_a1_spec_emit"
    assert prov["input"]["path"].endswith("L5_ADI_SPEC.json")
    assert prov["input"]["sha256"], "the input digest must be recorded"
    assert prov["input"]["block_matched_by"] == "name"
    # Present AND empty by construction: a reader must never have to infer
    # "nothing was defaulted" from the absence of a key.
    assert prov["fields_defaulted"] == []
    assert prov["defaults_used"] is False
    assert prov["fields_bound"] == ["vout"]
    assert prov["ai_handoff"] is None


def test_a_partial_bind_records_the_handoff_in_the_artefact_it_emitted(
        tmp_path):
    """A spec.json carrying one field, next to 12 electrical rows nobody
    attributed to any block, is NOT this block's complete spec. The emitted
    artefact — not just the gap file — has to say that the rest is judgment
    and name who does it."""
    p = make_project(tmp_path, [
        block("vreg_alpha", "ldo", [{"name": "Vout", "target": 1.8,
                                     "unit": "V"}]),
    ], unattributed_rows=12)
    assert run_prog(A1, p).returncode == 0
    prov = read_json(bdir(p, "vreg_alpha") / "spec.json")["_provenance"]
    assert prov["unattributed_electrical_rows_not_bound"] == 12
    assert prov["ai_handoff"] is not None
    assert prov["ai_handoff"]["skill"] == "analog-spec-extract"
    assert "12" in prov["ai_handoff"]["reason"]


def test_a_type_matched_bind_is_not_reported_as_a_name_attribution(tmp_path):
    """`l5_block_specs` falls back from name to TYPE. A type match is weaker
    evidence than a name match and the artefact has to say which it was."""
    p = make_project(tmp_path, [
        block("regulator_one", "ldo",
              [{"name": "Vout", "target": 1.8, "unit": "V"}]),
    ])
    # Rename the block in the list only, so the L5 entry matches by TYPE.
    lst = p / "phase3/analog/analog_block_list.json"
    data = json.loads(lst.read_text())
    data["blocks"][0]["name"] = "regulator_two"
    lst.write_text(json.dumps(data))

    assert run_prog(A1, p).returncode == 0
    prov = read_json(bdir(p, "regulator_two") / "spec.json")["_provenance"]
    assert prov["input"]["block_matched_by"] == "type"


# ── THE HONEST ABSENCE ────────────────────────────────────────────────────
def test_a_block_with_no_attributed_spec_gets_NO_spec_json(tmp_path):
    p = make_project(tmp_path, [
        block("keeper_x", "pull", specs=None, low_confidence=True),
    ])
    cp = run_prog(A1, p)
    assert cp.returncode == 2, (
        "nothing bound, so the producer must defer — rc 2, not a success "
        f"and not an error: {cp.stdout}{cp.stderr}")

    assert not (bdir(p, "keeper_x") / "spec.json").exists(), (
        "a block whose spec the documents never stated must not receive a "
        "spec.json — that artefact is read by every downstream consumer as "
        "an extraction that happened")

    gap = bdir(p, "keeper_x") / "spec_gap.json"
    assert gap.is_file(), "the absence must be RECORDED, not merely silent"
    body = read_json(gap)
    assert body["status"] == "NO_SPEC_IN_DOCS"
    assert body["spec_json_written"] is False
    assert body["ai_handoff"]["skill"] == "analog-spec-extract"
    assert body["ai_handoff"]["track"] == "skill"
    assert body["evidence_paragraph"], (
        "the gap must carry the evidence Phase 1 did find, or a reader "
        "cannot tell an extraction gap from a missing input")
    assert body["_provenance"]["defaults_used"] is False


def test_the_absent_spec_keeps_the_gate_at_WAIVED_not_FAIL(tmp_path):
    """The runner maps gate rc 2 -> WAIVED and rc 1 -> FAIL. Writing ANY
    spec.json for a spec-less block converts an honest deferral into a
    fabricated failure; this pins the resulting gate rc, which is the thing
    the runner actually reports."""
    p = make_project(tmp_path, [block("keeper_x", "pull", specs=None)])
    cp = run_prog(A1, p)
    # PRECONDITION, or this test passes vacuously wherever the producer does
    # not exist: gate rc 2 is also what an untouched tree returns.
    assert cp.returncode == 2 and (bdir(p, "keeper_x")
                                   / "spec_gap.json").is_file(), (
        f"the producer did not run, so the gate rc below would prove "
        f"nothing: rc={cp.returncode} {cp.stdout}{cp.stderr}")
    gate = run_prog(GATE_A1, p, "--block", "keeper_x")
    assert gate.returncode == 2, (
        f"expected WAIVED (rc 2), got rc {gate.returncode}: "
        f"{gate.stdout}{gate.stderr}")


def test_the_producer_never_writes_an_empty_specs_list(tmp_path):
    """Regression on the one shape that looks honest and is not: `specs: []`
    is rc=1 A1_SPEC_NO_FIELDS at the gate, i.e. a FAIL manufactured out of an
    honest gap."""
    p = make_project(tmp_path, [
        block("keeper_x", "pull", specs=None),
        block("widget_q", "charge_pump", specs=None),
        block("vreg_alpha", "ldo",
              [{"name": "Vout", "target": 1.8, "unit": "V"}]),
    ])
    assert run_prog(A1, p).returncode == 0
    found = list(p.rglob("spec.json"))
    # PRECONDITION: an empty sweep would pass this test on any tree that has
    # no spec.json at all, including one where nothing ran.
    assert len(found) == 1, (
        f"expected exactly the one bindable block to have produced a "
        f"spec.json, found {[str(f) for f in found]}")
    for spec in found:
        body = read_json(spec)
        assert body.get("specs"), (
            f"{spec} carries an empty specs[] — the one artefact shape that "
            f"reads as an extraction and gates as a defect")


def test_a_spec_less_block_does_not_borrow_its_sibling_type_default(tmp_path):
    """Two blocks of the SAME class, one with a bound number and one without.
    The one without must stay empty-handed: inheriting the sibling's value —
    or a per-type static default — is exactly the failure mode that grades a
    real simulation against an invented target."""
    p = make_project(tmp_path, [
        block("vreg_alpha", "ldo", [{"name": "Vout", "target": 1.8,
                                     "unit": "V"}]),
        block("vreg_beta", "ldo", specs=None),
    ])
    run_prog(A1, p)
    assert (bdir(p, "vreg_alpha") / "spec.json").is_file()
    assert not (bdir(p, "vreg_beta") / "spec.json").exists()
    assert (bdir(p, "vreg_beta") / "spec_gap.json").is_file()


# ── deferral to the AI track, and to a human ──────────────────────────────
def test_an_artefact_this_producer_did_not_write_is_never_overwritten(tmp_path):
    """The AI track (`analog-spec-extract`) exists precisely to make the
    judgment the deterministic track refuses. A producer that clobbered its
    output would destroy the thing it defers to."""
    p = make_project(tmp_path, [
        block("vreg_alpha", "ldo", [{"name": "Vout", "target": 1.8,
                                     "unit": "V"}]),
    ])
    d = bdir(p, "vreg_alpha")
    d.mkdir(parents=True, exist_ok=True)
    authored = {"block": "vreg_alpha",
                "specs": [{"name": "psrr", "min": 45.0, "unit": "dB"}],
                "_provenance": {"producer": "analog-spec-extract"}}
    (d / "spec.json").write_text(json.dumps(authored))

    assert run_prog(A1, p).returncode == 0
    assert read_json(d / "spec.json") == authored


def test_a_stale_spec_this_producer_wrote_does_not_outlive_its_evidence(tmp_path):
    p = make_project(tmp_path, [
        block("vreg_alpha", "ldo", [{"name": "Vout", "target": 1.8,
                                     "unit": "V"}]),
    ])
    assert run_prog(A1, p).returncode == 0
    assert (bdir(p, "vreg_alpha") / "spec.json").is_file()

    # The evidence disappears (a re-extraction that found nothing).
    p2 = make_project(tmp_path, [block("vreg_alpha", "ldo", specs=None)])
    assert p2 == p
    cp = run_prog(A1, p)
    assert cp.returncode == 2
    assert not (bdir(p, "vreg_alpha") / "spec.json").exists(), (
        "a spec.json whose evidence no longer exists must not survive the "
        "re-run — a stale artefact outliving its input is indistinguishable "
        "from a fresh extraction")
    assert (bdir(p, "vreg_alpha") / "spec_gap.json").is_file()


def test_no_analog_input_at_all_is_an_input_error_not_a_deferral(tmp_path):
    (tmp_path / "phase3/analog").mkdir(parents=True)
    cp = run_prog(A1, tmp_path)
    assert cp.returncode == 1, (
        "an unusable input is rc 1; rc 2 means 'measured, nothing bound' and "
        "must not be reused for 'there was nothing to measure'")
