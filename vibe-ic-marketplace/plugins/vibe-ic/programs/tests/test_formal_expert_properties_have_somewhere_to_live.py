"""The flow asks the `formal-verify` role for properties. They must have
somewhere to live, something to read them back, and a count that sees them.

MEASURED 2026-09-15 (lane icsub2) on `subservient` x gf180mcuD. The request the
flow files, verbatim from `phase2/stage1/formal/formal_authoring_request.json`::

    fallback_skill      formal-verify
    invocation_status   REQUIRED_NOT_INVOKED
    reason              "applicable formal obligations remain without a sound
                         property; invoke formal-verify on these exact IDs and
                         record each authored property in
                         property_contract.json before rerunning Step 5"
    unresolved          L8.clock_and_reset_waveform.resets.0.name
                        L8.clock_and_reset_waveform.resets.0.polarity
                        L8.clock_and_reset_waveform.resets.0.port_description

and what step 5 reported, on a design where those properties were authored,
PROVED UNBOUNDED by SymbiYosys, and falsified against four RTL mutants::

    formal_proof_evidence_check -> rc 1  FAIL
      EXPERT_FALLBACK_NOT_INVOKED (#1974)

THREE DEFECTS, and the request could not be answered until all three were
closed:

  1. NO CHANNEL. The only file carrying properties is the generated harness,
     and `formal_harness_gen` ends in an unconditional
     `out_path.write_text(harness)` -- so a property the expert authored was
     destroyed by the next run of the producer that had asked for it.

  2. NO READ-BACK. `formal_property_run` measures completion against
     `property_contract.json`, which `formal_harness_gen` writes, and nothing
     moved an obligation out of it. A correct receipt left the contract
     reading three UNAUTHORED.

  3. A MISCOUNT. `_assertion_count(harness)` returned 0 whenever `run()`
     reused an existing .sby (`harness is None`), and never looked inside the
     included fragment -- publishing "contract claims 4 covered obligation(s)
     but harness contains 0 assert statement(s)" about a proof that had just
     discharged four outputs.

THE READ-BACK IS NOT A RUBBER STAMP, and that is what most of this file pins.
A receipt closes an obligation only when it says INVOKED, carries a
disposition for that EXACT id at status AUTHORED naming a property, and THAT
PROPERTY IS DECLARED in the harness or the fragment it includes. Each of those
is a separate case below, because each is a different way a receipt can be
wrong.

chip-AGNOSTIC: generic `fixture_core` RTL, generic obligation ids, no design,
PDK or vendor token.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import formal_harness_gen as G  # noqa: E402
import formal_property_run as R  # noqa: E402

import pytest  # noqa: E402


OBLIGATIONS = [
    {"id": "L8.clock_and_reset_waveform.resets.0.polarity", "layer": "L8",
     "description": "declared temporal behavior polarity=active_high",
     "author": "formal-verify", "status": "UNAUTHORED"},
    {"id": "L8.clock_and_reset_waveform.resets.0.name", "layer": "L8",
     "description": "declared temporal behavior name=i_rst",
     "author": "formal-verify", "status": "UNAUTHORED"},
]

FRAGMENT = """\
    property p_expert_one;
        @(posedge i_clk) (f_past_valid && $past(i_rst)) |-> (o_q == 1'b0);
    endproperty
    a_expert_one: assert property (p_expert_one);

    property p_expert_two;
        @(posedge i_clk) (f_past_valid && i_rst) |-> (o_q == 1'b0);
    endproperty
    a_expert_two: assert property (p_expert_two);
"""

HARNESS = """\
`default_nettype none
module formal_fixture_core (input wire i_clk);
    (* anyseq *) wire i_rst;
    wire o_q;
    fixture_core dut (.i_clk(i_clk), .i_rst(i_rst), .o_q(o_q));
    reg f_past_valid = 1'b0;
    always @(posedge i_clk) f_past_valid <= 1'b1;
    property p_reset_safety_1;
        @(posedge i_clk) (f_past_valid && $past(i_rst)) |-> (o_q == '0);
    endproperty
    a_reset_safety_1: assert property (p_reset_safety_1);
endmodule
`default_nettype wire
"""


def _receipt(tmp: Path, status="AUTHORED", invoked="INVOKED",
             props=("p_expert_one", "p_expert_two"), ids=None):
    ids = ids if ids is not None else [o["id"] for o in OBLIGATIONS]
    G._write_property_contract(tmp.parent.parent.parent, {
        "property_denominator": len(OBLIGATIONS), "authored_property_count": 0,
        "unresolved_obligations": OBLIGATIONS})
    import hashlib
    (tmp / "formal_expert_review.json").write_text(json.dumps({
        "invocation_status": invoked,
        "request_sha256": hashlib.sha256((tmp / G.AUTHORING_REQUEST).read_bytes()).hexdigest(),
        "dispositions": [
            {"id": i, "status": status, "property": p, "reason": "authored"}
            for i, p in zip(ids, props)],
    }))


def _formal_dir(tmp_path: Path, fragment: str = FRAGMENT) -> Path:
    d = tmp_path / "phase2/stage1/formal"
    d.mkdir(parents=True, exist_ok=True)
    if fragment is not None:
        (d / G.EXPERT_PROPERTIES_SVH).write_text(fragment)
    return d


# ── 1. the channel ────────────────────────────────────────────────────────

def test_the_harness_includes_the_fragment_when_it_is_there(tmp_path):
    body = G.emit_harness.__doc__  # the function exists on both trees
    assert body
    text = G.emit_harness(
        _iface(), "i_clk", "i_rst", False, [],
        expert_properties=G.EXPERT_PROPERTIES_SVH)
    assert f'`include "{G.EXPERT_PROPERTIES_SVH}"' in text
    assert text.index("`include") < text.index("endmodule"), (
        "the fragment is a FRAGMENT: it must be inside the harness module so "
        "it sees the DUT ports and f_past_valid")


def test_a_design_with_no_fragment_gets_the_harness_it_always_got(tmp_path):
    text = G.emit_harness(_iface(), "i_clk", "i_rst", False, [])
    assert "`include" not in text


def _iface():
    from formal_harness_gen import ModuleIface, Port
    try:
        return ModuleIface(name="fixture_core", ports=[
            Port(name="i_clk", direction="input", width=1),
            Port(name="i_rst", direction="input", width=1),
            Port(name="o_q", direction="output", width=1)], params=[])
    except TypeError:  # pragma: no cover — shape drift is reported, not hidden
        pytest.skip("ModuleIface/Port signature changed; re-derive the fixture")


# ── 2. the read-back, and every way a receipt can be wrong ────────────────

def test_a_correct_receipt_closes_its_obligations(tmp_path):
    d = _formal_dir(tmp_path)
    _receipt(d)
    closed = G._expert_closed_obligations(d, OBLIGATIONS, HARNESS)
    assert {c["id"] for c in closed} == {o["id"] for o in OBLIGATIONS}
    assert all(c["author"] == "formal-verify" for c in closed)
    assert all(c["status"] == "AUTHORED" for c in closed)


def test_no_receipt_closes_nothing(tmp_path):
    d = _formal_dir(tmp_path)
    assert G._expert_closed_obligations(d, OBLIGATIONS, HARNESS) == []


def test_a_receipt_that_records_no_invocation_closes_nothing(tmp_path):
    d = _formal_dir(tmp_path)
    _receipt(d, invoked="REQUIRED_NOT_INVOKED")
    assert G._expert_closed_obligations(d, OBLIGATIONS, HARNESS) == []


def test_a_disposition_that_is_not_AUTHORED_closes_nothing(tmp_path):
    d = _formal_dir(tmp_path)
    _receipt(d, status="REVIEWED")
    assert G._expert_closed_obligations(d, OBLIGATIONS, HARNESS) == []


def test_a_disposition_naming_no_property_closes_nothing(tmp_path):
    d = _formal_dir(tmp_path)
    _receipt(d, props=("", ""))
    assert G._expert_closed_obligations(d, OBLIGATIONS, HARNESS) == []


def test_a_property_NOBODY_WROTE_closes_nothing(tmp_path):
    """THE ANTI-RUBBER-STAMP CLAUSE. A receipt may name any string; only a
    property that is actually DECLARED discharges an obligation."""
    d = _formal_dir(tmp_path)
    _receipt(d, props=("p_expert_one", "p_never_written"))
    closed = G._expert_closed_obligations(d, OBLIGATIONS, HARNESS)
    assert [c["property"] for c in closed] == ["p_expert_one"]


def test_closure_by_omission_is_impossible(tmp_path):
    """An obligation with no disposition at all stays open, however complete
    the rest of the receipt is."""
    d = _formal_dir(tmp_path)
    _receipt(d, ids=[OBLIGATIONS[0]["id"]], props=("p_expert_one",))
    closed = G._expert_closed_obligations(d, OBLIGATIONS, HARNESS)
    assert {c["id"] for c in closed} == {OBLIGATIONS[0]["id"]}


def test_a_property_in_the_HARNESS_also_counts(tmp_path):
    """The fragment is where an EXPERT property lives; a receipt may also
    point at one the generator itself wrote."""
    d = _formal_dir(tmp_path, fragment=None)
    _receipt(d, ids=[OBLIGATIONS[0]["id"]], props=("p_reset_safety_1",))
    closed = G._expert_closed_obligations(d, OBLIGATIONS, HARNESS)
    assert [c["property"] for c in closed] == ["p_reset_safety_1"]


def test_an_unreadable_receipt_closes_nothing(tmp_path):
    d = _formal_dir(tmp_path)
    (d / "formal_expert_review.json").write_text("{ not json")
    assert G._expert_closed_obligations(d, OBLIGATIONS, HARNESS) == []


# ── 3. the count, and the stale task file ─────────────────────────────────

def test_the_assert_count_sees_the_included_fragment(tmp_path):
    d = _formal_dir(tmp_path)
    h = d / "formal_fixture_core.sv"
    h.write_text(HARNESS)
    assert R._assertion_count(h) == 1, "the harness alone"
    assert R._assertion_count(h, [d / G.EXPERT_PROPERTIES_SVH]) == 3, (
        "an assert lives where it is WRITTEN; the fragment's two are real")


def test_the_assert_count_ignores_commented_out_asserts(tmp_path):
    d = _formal_dir(tmp_path, fragment="// a_dead: assert property (p_x);\n")
    h = d / "formal_fixture_core.sv"
    h.write_text(HARNESS)
    assert R._assertion_count(h, [d / G.EXPERT_PROPERTIES_SVH]) == 1


def test_a_reused_sby_gains_the_fragment_in_its_files_block(tmp_path):
    """MEASURED: a task file written BEFORE the fragment existed does not list
    it, sby stages only what `[files]` names, and yosys then dies with
    "Can't open include file". A task file that names a source must stage it.
    """
    d = _formal_dir(tmp_path)
    sby = d / "formal_fixture_core.sby"
    sby.write_text("[tasks]\nsafety prove\n\n[files]\nfixture_core.v\n"
                   "formal_fixture_core.sv\n")
    assert R._ensure_expert_fragment_staged(sby, d) is True
    block = sby.read_text().split("[files]")[1]
    assert G.EXPERT_PROPERTIES_SVH in block
    # and it is idempotent: a second pass adds nothing
    assert R._ensure_expert_fragment_staged(sby, d) is False
    assert sby.read_text().count(G.EXPERT_PROPERTIES_SVH) == 1


def test_a_reused_sby_binds_observers_added_by_the_expert_fragment(tmp_path):
    """A stale task must bind an expert observer, not merely stage its text."""
    d = _formal_dir(tmp_path, fragment="""\\
    // @observe observed_state = dut.state
    (* keep *) wire observed_state;
    """)
    sby = d / "formal_fixture_core.sby"
    sby.write_text("[script]\n"
                   "read_verilog -formal -sv formal_fixture_core.sv\n"
                   "hierarchy -top formal_fixture_core\nproc\nflatten\n"
                   "prep -top formal_fixture_core\n\n[files]\n"
                   "formal_fixture_core.sv\n")
    result = R.run(tmp_path, top="fixture_core", emit_only=True)
    assert result["verdict"] == "EMIT_ONLY"
    text = sby.read_text()
    assert "select -assert-any formal_fixture_core/w:dut.state" in text
    assert "connect -nomap -set observed_state dut.state" in text
    assert text.count("connect -nomap -set observed_state dut.state") == 1
    assert text.index("connect -nomap -set observed_state dut.state") < text.index("prep -top")
    assert R._ensure_expert_observers_bound(sby, d) is False


def test_a_project_with_no_fragment_leaves_its_sby_byte_identical(tmp_path):
    d = _formal_dir(tmp_path, fragment=None)
    sby = d / "formal_fixture_core.sby"
    original = "[tasks]\nsafety prove\n\n[files]\nfixture_core.v\n"
    sby.write_text(original)
    assert R._ensure_expert_fragment_staged(sby, d) is False
    assert sby.read_text() == original


def test_the_fragment_is_never_read_as_a_source(tmp_path):
    """It is a FRAGMENT. `[files]` stages it; `read_verilog` must never be
    handed a macro body -- the same rule the header staging follows."""
    d = _formal_dir(tmp_path)
    sby = d / "formal_fixture_core.sby"
    sby.write_text("[tasks]\nsafety prove\n\n[script]\n"
                   "safety: read_verilog -formal -sv formal_fixture_core.sv\n"
                   "prep -top formal_fixture_core\n\n[files]\n"
                   "formal_fixture_core.sv\n")
    R._ensure_expert_fragment_staged(sby, d)
    script = sby.read_text().split("[script]")[1].split("[files]")[0]
    assert G.EXPERT_PROPERTIES_SVH not in script


# #3063: PROGRAM_FIXTURE provider, self-authored neutral INPUT, real producers.
def _neutral_invocation_flow(project, provider="complete", proof_mutation=None,
                             reused=False, deterministic=False, program=False):
    import hashlib
    import shutil
    from not_verified_tier import skip_not_verified
    import formal_proof_evidence_check as consumer
    if any(shutil.which(tool) is None for tool in ("yosys", "sby")):
        skip_not_verified("native invocation control needs yosys/sby",
                          "Run this module in the pinned EDA image")
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True)
    l3 = {"no_opcodes_in_input": True, "reject_rules": [] if deterministic or program else [
        "A data bit sampled with reset inactive must appear at q after a rising edge."]}
    if provider == "partial":
        l3["reject_rules"].append("A second declared capture obligation remains for the provider.")
    l8 = ({"clock_and_reset_waveform": {"resets": [
        {"name": "rst", "sync": "synchronous", "polarity": "active_high"}]}}
          if program else {"formal_applicability": {"status": "NOT_APPLICABLE",
              "reason": "This neutral INPUT specifies capture in L3 and no extra waveform obligations."}})
    for name, data in (("L3_PROTOCOL.json", l3), ("L6_FSM.json", {"no_fsm_in_input": True}),
                       ("L8_TIMING_WAVEFORM.json", l8)):
        (docs / name).write_text(json.dumps(data))
    rd = project / "phase2/stage1/rtl"
    rd.mkdir(parents=True)
    rtl = rd / "sample_cell.v"
    rtl.write_text("module sample_cell(input clk, input rst, input d, output reg q);\n"
                   "always @(posedge clk) if(rst) q <= 0; else q <= d;\nendmodule\n")
    form = "concurrent" if program else "immediate"
    first = G.generate(project=project, top="sample_cell", assertion_form=form)
    f = project / "phase2/stage1/formal"
    active = f / G.AUTHORING_REQUEST
    original = active.read_bytes() if active.exists() else None
    if original is not None:
        (project / "request-before.json").write_bytes(original)
    if provider is not None and not deterministic and not program:
        request = json.loads(original)
        # The fixture provider actually runs this authoring action. It is not
        # a human, AI review, or proof; the subsequent native runner is separate.
        fragment = ("always @(posedge clk) if(f_past_valid && !$past(rst))\n"
                    " p_requested_capture: assert(q == $past(d));\n")
        if provider == "non_property":
            fragment = "p_requested_capture: cover(q);\n"
        (f / G.EXPERT_PROPERTIES_SVH).write_text(fragment)
        receipt = {"fallback_skill": "formal-verify", "invocation_status": "INVOKED",
                   "invoked_by": "PROGRAM_FIXTURE neutral provider", "provider_kind": "PROGRAM_FIXTURE",
                   "request_sha256": hashlib.sha256(original).hexdigest(),
                   "dispositions": [{"id": r["id"], "status": "AUTHORED",
                                     "property": "p_requested_capture"}
                                    for r in request["unresolved_obligations"]]}
        if provider == "forged_hash":
            receipt["request_sha256"] = "0" * 64
        elif provider == "missing_disposition":
            receipt["dispositions"] = []
        elif provider == "partial":
            receipt["dispositions"] = receipt["dispositions"][:1]
        elif provider == "wrong_role":
            receipt["fallback_skill"] = "unrelated-role"
        (f / "formal_expert_review.json").write_text(json.dumps(receipt))
    second = G.generate(project=project, top="sample_cell", assertion_form=form)
    if proof_mutation == "FAIL":
        rtl.write_text(rtl.read_text().replace("else q <= d", "else q <= ~d"))
    elif proof_mutation == "ERROR":
        rtl.write_text(rtl.read_text().replace("else q <= d", "else q <= ;"))
    kwargs = dict(top=second["harness_module"], container=None, timeout=60,
                  mem_limit_kb=4 * 1024 * 1024, prove_engines="direct")
    if reused:
        emitted = R.run(project, harness=Path(second["harness_path"]), rtl=[rtl], emit_only=True, **kwargs)
        result = R.run(project, sby=project / emitted["sby"], **kwargs)
    else:
        result = R.run(project, harness=Path(second["harness_path"]), rtl=[rtl], **kwargs)
    checked = consumer.audit(project)
    (project / "invocation-receipt.json").write_text(json.dumps({
        "provider_kind": "PROGRAM_FIXTURE" if provider is not None and not program and not deterministic else None,
        "first_floor": first, "second_floor": second, "producer": result,
        "consumer": checked}, indent=2))
    return original, f, result, checked


@pytest.mark.parametrize("reused", [False, True])
def test_completed_floor_preserves_requested_role_and_actual_fixture_invocation(tmp_path, reused):
    import hashlib
    original, f, result, checked = _neutral_invocation_flow(tmp_path, reused=reused)
    assert result["verdict"] == checked["verdict"] == "PASS"
    assert result["expert_fallback_required"] is False
    assert result["expert_fallback_invoked"] is True
    assert result.get("expert_fallback_requested") is True
    assert result["expert_fallback_invocation_status"] == "INVOKED"
    assert result["expert_fallback_skill"] == "formal-verify"
    assert result["expert_fallback_invoked_by"] == "PROGRAM_FIXTURE neutral provider"
    assert result["expert_fallback_receipt"] == "phase2/stage1/formal/formal_expert_review.json"
    assert result["expert_fallback_request_sha256"] == hashlib.sha256(original).hexdigest()
    assert not (f / G.AUTHORING_REQUEST).exists()
    assert result["property_denominator"] == json.loads(original)["property_denominator"] == 2
    assert result["authored_property_count"] == 2 and not result["unresolved_obligations"]
    snapshot = json.loads((f / G.PROPERTY_CONTRACT).read_text())["authoring_request"]
    assert snapshot["text"].encode() == original
    # A further floor/proof cycle keeps the same completed handoff identity.
    G.generate(project=tmp_path, top="sample_cell", assertion_form="immediate")
    assert G._authoring_request_snapshot(f) == snapshot


@pytest.mark.parametrize("proof_status", ["FAIL", "ERROR"])
def test_actual_fixture_invocation_survives_failed_or_error_native_proof(tmp_path, proof_status):
    _, _, result, checked = _neutral_invocation_flow(tmp_path, proof_mutation=proof_status)
    assert result["expert_fallback_invoked"] is True
    assert result["expert_fallback_invocation_status"] == "INVOKED"
    assert result["expert_fallback_invoked_by"] == "PROGRAM_FIXTURE neutral provider"
    assert result["all_proved"] is False and checked["verdict"] == "FAIL"
    assert {r["status"] for r in result["properties"]} == {proof_status}
    assert result["property_denominator"] == 2


def test_partial_floor_keeps_original_invocation_and_remaining_exact_request_id(tmp_path):
    import hashlib
    original, f, result, checked = _neutral_invocation_flow(tmp_path, provider="partial")
    request = json.loads(original)
    assert result["all_proved"] is True
    assert result["expert_fallback_invoked"] is True
    assert result["expert_fallback_invocation_status"] == "INVOKED"
    assert result["expert_fallback_invoked_by"] == "PROGRAM_FIXTURE neutral provider"
    assert result["expert_fallback_required"] is True
    assert result["expert_fallback_request_sha256"] == hashlib.sha256(original).hexdigest()
    assert (f / G.AUTHORING_REQUEST).read_bytes() == original
    assert result["property_denominator"] == request["property_denominator"] == 3
    assert [r["id"] for r in result["unresolved_obligations"]] == [
        request["unresolved_obligations"][1]["id"]]
    assert result["verdict"] == checked["verdict"] == "INCOMPLETE"


@pytest.mark.parametrize("active", ["{", "[]"])
def test_unreadable_active_request_cannot_disappear_into_a_completed_floor(tmp_path, active):
    f = _formal_dir(tmp_path, fragment=None)
    harness = f / "formal_fixture_core.sv"
    harness.write_text("module formal_fixture_core; always @* assert(1); endmodule\n")
    (f / G.AUTHORING_REQUEST).write_text(active)
    (f / G.PROPERTY_CONTRACT).write_text(json.dumps({
        "property_denominator": 1, "unresolved_obligations": []}))
    result = {"verdict": "PASS", "all_proved": True}
    R._attach_property_contract(result, f, harness)
    assert result["verdict"] == "INCOMPLETE"
    assert result["expert_fallback_invoked"] is False
    assert [r["id"] for r in result["unresolved_obligations"]] == [
        "formal.authoring_request_invalid"]


@pytest.mark.parametrize("provider", ["forged_hash", "missing_disposition", "non_property", "wrong_role", None])
def test_invalid_or_absent_provider_cannot_close_requested_obligations(tmp_path, provider):
    original, f, result, checked = _neutral_invocation_flow(tmp_path, provider=provider)
    assert (f / G.AUTHORING_REQUEST).exists()
    assert result["property_denominator"] == json.loads(original)["property_denominator"] == 2
    assert result["unresolved_obligations"]
    assert result["verdict"] != "PASS" and checked["verdict"] != "PASS"
    if provider in (None, "forged_hash", "wrong_role"):
        assert result["expert_fallback_invoked"] is False


@pytest.mark.parametrize("mutation", ["request_hash", "missing_disposition", "non_property",
                                      "wrong_role", "snapshot_hash", "erase_history", "shrink_denominator"])
def test_consumer_rechecks_retired_request_and_receipt(tmp_path, mutation):
    import formal_proof_evidence_check as consumer
    _, f, result, checked = _neutral_invocation_flow(tmp_path)
    assert checked["verdict"] == "PASS"
    path = f / "formal_expert_review.json"
    receipt = json.loads(path.read_text())
    if mutation == "request_hash":
        receipt["request_sha256"] = "0" * 64
    elif mutation == "missing_disposition":
        receipt["dispositions"] = []
    elif mutation == "non_property":
        receipt["dispositions"][0]["property"] = "not_an_assertion"
    elif mutation == "wrong_role":
        receipt["fallback_skill"] = "unrelated-role"
    elif mutation == "snapshot_hash":
        contract = json.loads((f / G.PROPERTY_CONTRACT).read_text())
        contract["authoring_request"]["sha256"] = "0" * 64
        (f / G.PROPERTY_CONTRACT).write_text(json.dumps(contract))
    elif mutation == "erase_history":
        result.update(expert_fallback_requested=False, expert_fallback_invoked=False,
                      expert_fallback_invocation_status="", expert_fallback_receipt=None)
        (f / "results.json").write_text(json.dumps(result))
    elif mutation == "shrink_denominator":
        result["property_denominator"] = 1
        (f / "results.json").write_text(json.dumps(result))
    path.write_text(json.dumps(receipt))
    rejected = consumer.audit(tmp_path)
    assert rejected["verdict"] == "FAIL", rejected
    assert "EXPERT_AUTHORING_IDENTITY_INVALID" in " ".join(rejected["findings"])


def test_deterministic_floor_does_not_invent_an_expert_event(tmp_path):
    original, _, result, checked = _neutral_invocation_flow(tmp_path, deterministic=True)
    assert original is None and result["verdict"] == checked["verdict"] == "PASS"
    assert result["expert_fallback_invoked"] is False
    assert result.get("expert_fallback_requested") is False
    assert result["expert_fallback_invocation_status"] == ""


def test_native_program_answer_keeps_its_distinct_provider_status(tmp_path):
    _, _, result, checked = _neutral_invocation_flow(tmp_path, provider=None, program=True)
    assert result["expert_fallback_invoked"] is True, result
    assert result["expert_fallback_invocation_status"] == "INVOKED_BY_PROGRAM"
    assert result.get("expert_fallback_invoked_by") == "formal_property_run"
    assert result["program_discharged_obligations"]
    assert checked["verdict"] == "PASS", checked
