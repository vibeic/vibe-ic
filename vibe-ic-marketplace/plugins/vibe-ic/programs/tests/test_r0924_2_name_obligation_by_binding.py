#!/usr/bin/env python3
"""R-0924-2 — a NAME obligation is discharged by BINDING, never by a trace.

`L8 resets.N.name = rst` states which port is the reset. No assertion can
discharge a name, so Step 5 sat on PROOF_CHAIN_PARTIAL forever (spm run23: 4 of
5 obligations proved unbounded, the fifth `resets.0.name`).
`formal_proof_evidence_check` now answers it structurally: the harness binds
the declared port as the reset AND a property guarded by it is asserted AND
this run PROVED it -> DISCHARGED_BY_BINDING with that evidence (port, property,
proof status). Anything less stays outstanding, with the reason.

Through the real programs (`formal_harness_gen.generate` ->
`formal_property_run.run` -> `formal_proof_evidence_check.audit`), in-image:

  bound + proven               -> DISCHARGED_BY_BINDING, gate PASS
  declared port not the reset  -> BINDING_OUTSTANDING, gate not PASS
  covering property refuted    -> BINDING_OUTSTANDING, gate not PASS

Needs yosys + sby on PATH (the vibeic-eda image, as CI and falsref run them).
Without them the engine arms are NOT_VERIFIED — declared through
`not_verified_tier`, named in the session's own summary, and a session with
VIBEIC_REQUIRE_EDA_VERIFICATION=1 (a landing host) fails on them. A bare
assertion made a host without the image read as a defect in this rule, and
a bare `pytest.skip` would read as a pass; neither is true. chip-AGNOSTIC.
"""
from __future__ import annotations

import json
import hashlib
import shutil
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import formal_harness_gen as fhg  # noqa: E402
import formal_property_run as fpr  # noqa: E402
import formal_proof_evidence_check as gate  # noqa: E402
from _tool_probes import skip_not_verified  # noqa: E402

NAME_ID = "L8.clock_and_reset_waveform.resets.0.name"
RTL = """module ctr(input clk, input rst, input en, output reg [3:0] q);
  always @(posedge clk) if (rst) q <= 4'd0; else if (en) q <= q + 4'd1;
endmodule
"""


def _project(tmp: Path, reset_name: str = "rst") -> Path:
    docs = tmp / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L3_PROTOCOL.json").write_text(json.dumps({"no_opcodes_in_input": True}))
    (docs / "L6_FSM.json").write_text(json.dumps({"no_fsm_in_input": True}))
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps(
        {"clock_and_reset_waveform": {"resets": [{"name": reset_name}]}}))
    rd = tmp / "phase2/stage1/rtl"
    rd.mkdir(parents=True)
    (rd / "ctr.v").write_text(RTL)
    return tmp


def _step5(project: Path, harness_edit=None):
    missing = [t for t in ("yosys", "sby") if shutil.which(t) is None]
    if missing:
        skip_not_verified(
            f"{missing} not on PATH, so no harness can be proved here",
            "tools/ci/run_suite_in_eda_image.sh -- programs/tests/test_r0924_2_name_obligation_by_binding.py")
    gen = fhg.generate(project=project, top="ctr")
    assert gen["verdict"] == "EMITTED", gen
    h = Path(gen["harness_path"])
    if harness_edit:
        edited = harness_edit(h.read_text())
        assert edited != h.read_text(), "the harness edit matched nothing"
        h.write_text(edited)
    res = fpr.run(project, harness=h, rtl=[Path(p) for p in gen["rtl_files"]],
                  top=gen["harness_module"], container=None, timeout=300)
    return res, gate.audit(project)


def _binding(rep: dict) -> dict:
    rows = [b for b in rep.get("binding_obligations") or [] if b["id"] == NAME_ID]
    assert len(rows) == 1, rep.get("findings")
    return rows[0]


def test_the_name_obligation_is_classified_as_a_binding(tmp_path):
    proj = _project(tmp_path)
    rows = {o["id"]: o for o in fhg.declaration_obligations(proj)["obligations"]}
    assert rows[NAME_ID]["kind"] == "binding"
    assert rows[NAME_ID]["binding"] == {"role": "reset", "port": "rst"}
    # an untagged row (a results.json written before the tag) is read from
    # the L8 document at its own path, not from its description sentence
    bare = {"id": NAME_ID, "description": "unrelated words"}
    assert fhg.binding_obligation(bare, proj) == {"role": "reset", "port": "rst"}
    # behaviour is not a name; prose is not an identifier
    assert fhg.binding_obligation(dict(bare, id=NAME_ID.replace("name", "sync")), proj) is None
    prose = _project(tmp_path / "p", reset_name="the reset pin")
    assert fhg.binding_obligation(bare, prose) is None


def test_immediate_reset_assertion_from_slang_frontend_closes_binding():
    # formal_harness_gen emits this equivalent immediate form when the
    # read_slang frontend is needed; the gate must recognize the reset guard.
    harness = """\
    ctr dut (.q(q));
    always @(posedge clk) if (f_past_valid && rst_active)
        a_reset_safety_1: assert (q == 4'd0);
    """
    assert gate._reset_guarded_properties(harness) == ["a_reset_safety_1"]


def test_immediate_assertion_without_reset_guard_does_not_close_binding():
    harness = """\
    always @(posedge clk) if (f_past_valid)
        a_reset_safety_1: assert (q == 4'd0);
    """
    assert gate._reset_guarded_properties(harness) == []


def _immediate_binding_row(tmp_path, guard, predicate="q == 4'd0", harness_edit=None):
    project = _project(tmp_path)
    formal = project / "phase2/stage1/formal"
    formal.mkdir(parents=True)
    harness = formal / "formal_ctr.sv"
    body = f"""module formal_ctr(input rst, input clk);
    wire rst_active = rst;
    wire rst_active_q = rst;
    wire [3:0] q;
    ctr dut (.rst(rst), .q(q));
    reg f_past_valid = 1'b1;
    always @(posedge clk) if ({guard})
        a_reset_safety_1: assert ({predicate});
    endmodule
    """
    if harness_edit:
        body = harness_edit(body)
    harness.write_text(body)
    results = {
        "unresolved_obligations": [{"id": NAME_ID}],
        "all_proved": True,
        "properties": [{"task": "prove", "status": "PASS", "bound": "unbounded"}],
        "proof_inputs": {"files": {harness.name: hashlib.sha256(body.encode()).hexdigest()}},
    }
    # This is a software-only predicate fixture, not a native proof. Its
    # source record must still describe the public DUT actually on disk.
    import _chip_synth_read as csr
    results["chip_read"] = csr.current_chip_read(project, "ctr")
    row, = gate.binding_dispositions(project, formal, results)
    return row


def test_immediate_disjunction_cannot_discharge_reset_binding(tmp_path):
    row = _immediate_binding_row(tmp_path, "rst_active || f_past_valid")
    assert row["status"] == gate.BINDING_OUTSTANDING, row
    assert "no substantive reset assertion" in row["reason"]


def test_immediate_generated_sync_guard_discharges_binding(tmp_path):
    row = _immediate_binding_row(tmp_path, "f_past_valid && rst_active_q")
    assert row["status"] == gate.DISCHARGED_BY_BINDING, row
    assert row["property"] == "a_reset_safety_1"


def test_immediate_tautology_cannot_discharge_reset_binding(tmp_path):
    row = _immediate_binding_row(tmp_path, "f_past_valid && rst_active", "1'b1")
    assert row["status"] == gate.BINDING_OUTSTANDING, row
    assert "no substantive reset assertion" in row["reason"]


def test_immediate_non_dut_predicate_cannot_discharge_reset_binding(tmp_path):
    row = _immediate_binding_row(tmp_path, "f_past_valid && rst_active", "rst_active == 1'b1")
    assert row["status"] == gate.BINDING_OUTSTANDING, row
    assert "no substantive reset assertion" in row["reason"]


def test_immediate_self_equality_cannot_discharge_reset_binding(tmp_path):
    row = _immediate_binding_row(tmp_path, "f_past_valid && rst_active", "q == q")
    assert row["status"] == gate.BINDING_OUTSTANDING, row
    assert "no substantive reset assertion" in row["reason"]


def test_other_instance_output_connection_cannot_discharge_reset_binding(tmp_path):
    def disconnected_dut(body):
        return (body.replace("wire [3:0] q;", "wire [3:0] q = 4'd0;")
                .replace("ctr dut (.rst(rst), .q(q));",
                         "ctr dut (.rst(rst), .q());\n    dummy other (.q(q));")
                + "\nmodule dummy(input [3:0] q); endmodule\n")

    row = _immediate_binding_row(tmp_path, "f_past_valid && rst_active",
                                 harness_edit=disconnected_dut)
    assert row["status"] == gate.BINDING_OUTSTANDING, row
    assert "no substantive reset assertion" in row["reason"]


def test_bound_and_proven_is_discharged_by_binding(tmp_path):
    res, rep = _step5(_project(tmp_path))
    assert res["all_proved"] is True
    assert [o["id"] for o in res["unresolved_obligations"]] == [NAME_ID]
    b = _binding(rep)
    assert b["status"] == gate.DISCHARGED_BY_BINDING, b
    assert b["port"] == "rst" and b["property"] == "p_reset_safety_1"
    assert "PASS(unbounded)" in b["proof_status"]
    assert rep["discharged_by_binding"] == [NAME_ID]
    assert rep["verdict"] == "PASS", rep["findings"]
    assert "by binding" in rep["findings"][-1]
    # recorded as a binding, never as an authored (trace) property
    results = json.loads((tmp_path / "phase2/stage1/formal/results.json").read_text())
    assert results["authored_property_count"] == res["authored_property_count"]


def test_a_declared_port_that_is_not_the_reset_stays_outstanding(tmp_path):
    res, rep = _step5(_project(tmp_path, reset_name="arst"))
    b = _binding(rep)
    assert b["status"] == gate.BINDING_OUTSTANDING, b
    assert "'arst'" in b["reason"]
    assert rep["verdict"] != "PASS"
    assert NAME_ID in [o["id"] for o in rep.get("unresolved_obligations") or []]


def test_a_refuted_covering_property_stays_outstanding(tmp_path):
    res, rep = _step5(_project(tmp_path),
                      harness_edit=lambda t: t.replace("(q == '0)", "(q == 4'd5)"))
    assert res["all_proved"] is False
    b = _binding(rep)
    assert b["status"] == gate.BINDING_OUTSTANDING, b
    assert "not proven" in b["reason"]
    assert rep["verdict"] != "PASS"


def test_a_real_port_that_is_not_bound_as_the_reset_stays_outstanding(tmp_path):
    # `en` IS a connected DUT port — but the harness's reset is `rst`
    res, rep = _step5(_project(tmp_path, reset_name="en"))
    assert res["all_proved"] is True
    b = _binding(rep)
    assert b["status"] == gate.BINDING_OUTSTANDING, b
    assert "does not bind 'en' as the reset" in b["reason"]
    assert "does not connect" not in b["reason"]
    assert rep["verdict"] != "PASS"


# ── r2: the proof must name the harness it proved ───────────────────────────
SRST_RTL = RTL.replace("input rst", "input sys_rst").replace("if (rst)", "if (sys_rst)")


def _cli_rerun(project: Path, extra: list) -> None:
    """The documented Step-5 CLI sequence's second half: regenerate the
    harness, then `formal_property_run.py` — whose proof does NOT run."""
    gen = fhg.generate(project=project, top="ctr")
    assert gen["verdict"] == "EMITTED", gen
    try:
        fpr.main([str(project), "--harness", gen["harness_path"],
                  "--rtl", *gen["rtl_files"], "--top", gen["harness_module"],
                  *extra])
    except SystemExit:
        pass


def _stale_pairing(tmp_path: Path, extra: list) -> dict:
    proj = _project(tmp_path)                      # L8 declares `rst`
    (proj / "phase2/stage1/rtl/ctr.v").write_text(SRST_RTL)
    res, rep = _step5(proj)                        # a real proof of the sys_rst harness
    assert res["all_proved"] is True
    assert _binding(rep)["status"] == gate.BINDING_OUTSTANDING   # binds sys_rst
    results = (proj / "phase2/stage1/formal/results.json").read_text()
    (proj / "phase2/stage1/rtl/ctr.v").write_text(RTL)          # port renamed to rst
    _cli_rerun(proj, extra)
    # the old proof survives untouched; the harness on disk is a new one
    assert (proj / "phase2/stage1/formal/results.json").read_text() == results
    assert "rst_active = rst;" in (proj / "phase2/stage1/formal/formal_ctr.sv").read_text()
    return gate.audit(proj)


def test_a_harness_rewritten_by_an_emit_only_run_is_not_the_one_proven(tmp_path):
    rep = _stale_pairing(tmp_path, ["--emit-only"])
    b = _binding(rep)
    assert b["status"] == gate.BINDING_OUTSTANDING, b
    assert "harness not the one proven" in b["reason"]
    assert rep["verdict"] != "PASS"


def test_a_harness_rewritten_by_an_env_unavailable_run_is_not_the_one_proven(tmp_path):
    rep = _stale_pairing(tmp_path, ["--container", "vibeic-no-such-container-r0924"])
    assert (tmp_path / "phase2/stage1/formal/formal_env_unavailable.json").is_file()
    b = _binding(rep)
    assert b["status"] == gate.BINDING_OUTSTANDING, b
    assert "harness not the one proven" in b["reason"]
    assert rep["verdict"] != "PASS"


def test_the_discharge_names_the_proved_harness(tmp_path):
    res, rep = _step5(_project(tmp_path))
    b = _binding(rep)
    assert b["status"] == gate.DISCHARGED_BY_BINDING, b
    h = tmp_path / "phase2/stage1/formal/formal_ctr.sv"
    import hashlib
    assert b["proved_harness_sha256"]["formal_ctr.sv"] == hashlib.sha256(h.read_bytes()).hexdigest()
    assert res["proof_inputs"]["source"].startswith("sby src")


# Issue #3145: keep the real partial proof immutable while changing only the
# current public DUT. The normal CLI, not a binding helper alone, decides it.
import os
import re
import subprocess
import pytest
from unittest.mock import patch
import _chip_synth_read as csr
import design_one_shot_runner as runner


def _formal_bytes(project):
    formal = project / "phase2/stage1/formal"
    return {str(p.relative_to(formal)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(formal.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def issue3145_native_seeds(tmp_path_factory):
    supplied = os.environ.get("ISSUE3145_FORMAL_SEEDS")
    if supplied:
        root = Path(supplied)
        positive, failed = root / "native-seed", root / "native-failed-seed"
    else:
        missing = [t for t in ("yosys", "sby") if shutil.which(t) is None]
        if missing:
            skip_not_verified(f"{missing}: no real partial-proof seed",
                              "run this owning module in the cached EDA image")
        root = tmp_path_factory.mktemp("issue3145-seeds")
        positive = _project(root / "native-seed")
        l8 = positive / "phase1/generated_docs/L8_TIMING_WAVEFORM.json"
        doc = json.loads(l8.read_text())
        doc["clock_and_reset_waveform"]["resets"][0]["min_assert_cycles"] = 2
        l8.write_text(json.dumps(doc, sort_keys=True))
        runner.step_emit_phase2_manifests(positive, [], top_name="ctr", container="")
        failed = root / "native-failed-seed"
        shutil.copytree(positive, failed)
        _step5(failed, harness_edit=lambda t: t.replace("(q == '0)", "(q == 4'd5)"))
    for path, proved in ((positive, True), (failed, False)):
        results = json.loads((path / "phase2/stage1/formal/results.json").read_text())
        assert results["all_proved"] is proved
        assert results["chip_read"] == csr.current_chip_read(path, "ctr")
        assert results["proof_inputs"]["source"].startswith("sby src")
        assert any(t["bound"] == ("unbounded" if proved else "cex")
                   for t in results["properties"])
    return positive, failed


def _issue3145_copy(tmp_path, seeds, failed=False):
    project = tmp_path / "public-component"
    shutil.copytree(seeds[int(failed)], project)
    return project


def _issue3145_cli(project):
    output = project / "consumer.json"
    argv = [sys.executable, "-B", str(PROGRAMS / "formal_proof_evidence_check.py"),
            str(project), "--json", str(output)]
    proc = subprocess.run(argv, capture_output=True, text=True,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    (project / "consumer-process.json").write_text(json.dumps({
        "argv": argv, "exit_code": proc.returncode, "stdout": proc.stdout,
        "stderr": proc.stderr, "terminal": True}, indent=2))
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    rep = json.loads(output.read_text())
    assert rep["property_denominator"] == 3, rep
    assert rep["verdict"] == "INCOMPLETE", rep
    assert any(o["id"].endswith("min_assert_cycles")
               for o in rep["unresolved_obligations"]), rep
    return rep


def test_issue3145_matching_native_partial_binding_remains_reusable(tmp_path, issue3145_native_seeds):
    project = _issue3145_copy(tmp_path, issue3145_native_seeds)
    before = _formal_bytes(project)
    rep = _issue3145_cli(project)
    assert _binding(rep)["status"] == gate.DISCHARGED_BY_BINDING, rep
    assert NAME_ID in rep["discharged_by_binding"]
    assert _formal_bytes(project) == before


@pytest.mark.parametrize("change", ["missing_reset", "changed_dut", "changed_readset", "changed_built"])
def test_issue3145_current_dut_freshness_before_binding(tmp_path, issue3145_native_seeds, change):
    project = _issue3145_copy(tmp_path, issue3145_native_seeds)
    before = _formal_bytes(project)
    rtl = project / "phase2/stage1/rtl/ctr.v"
    outputs = [(p.name, p.direction, p.width) for p in fhg.parse_module(rtl.read_text(), "ctr").ports
               if p.direction == "output"]
    if change == "missing_reset":
        rtl.write_text(re.sub(r"\brst\b", "fixture_reset_input_neutral", rtl.read_text()))
        assert "rst" not in {p.name for p in fhg.parse_module(rtl.read_text(), "ctr").ports
                             if p.direction == "input"}
    elif change == "changed_dut":
        rtl.write_text(rtl.read_text().replace("q + 4'd1", "q + 4'd2"))
        assert "rst" in {p.name for p in fhg.parse_module(rtl.read_text(), "ctr").ports
                         if p.direction == "input"}
    elif change == "changed_readset":
        (rtl.parent / "public_extra.v").write_text("module public_extra(input a, output z); assign z=a; endmodule\n")
    else:
        # A public synthetic *built-read* mismatch, not fabricated proof data.
        built = csr.built_record_path(project)
        built.parent.mkdir(parents=True, exist_ok=True)
        record = csr.current_chip_read(project, "ctr")
        record["top"] = "public_different_built_top"
        built.write_text(json.dumps(record))
    assert [(p.name, p.direction, p.width) for p in fhg.parse_module(rtl.read_text(), "ctr").ports
            if p.direction == "output"] == outputs
    rep = _issue3145_cli(project)
    row = _binding(rep)
    assert row["status"] == gate.BINDING_OUTSTANDING, row
    assert NAME_ID not in rep.get("discharged_by_binding", []), rep
    assert NAME_ID in {o["id"] for o in rep["unresolved_obligations"]}
    if change == "missing_reset":
        assert "current DUT input" in row["reason"], row
    elif change == "changed_built":
        assert "phase-3 synthesis" in row["reason"], row
    else:
        assert "now" in row["reason"], row
    assert _formal_bytes(project) == before


@pytest.mark.parametrize("failed", [False, True], ids=["partial", "counterexample"])
def test_issue3145_normal_producer_reuses_matching_proof_without_rewriting(tmp_path, issue3145_native_seeds, failed):
    project = _issue3145_copy(tmp_path, issue3145_native_seeds, failed)
    before = _formal_bytes(project)
    with patch.object(fpr, "run", wraps=fpr.run) as invoked:
        runner.step_emit_phase2_manifests(project, [], top_name="ctr", container="")
    assert invoked.call_count == 0
    assert _formal_bytes(project) == before
    if failed:
        rep = gate.audit(project)
        assert rep["verdict"] == "FAIL", rep
        assert _binding(rep)["status"] == gate.BINDING_OUTSTANDING


@pytest.mark.parametrize("failed", [False, True], ids=["partial", "counterexample"])
def test_issue3145_normal_producer_refreshes_stale_source_and_retains_entire_proof(tmp_path, issue3145_native_seeds, failed):
    project = _issue3145_copy(tmp_path, issue3145_native_seeds, failed)
    before = _formal_bytes(project)
    rtl = project / "phase2/stage1/rtl/ctr.v"
    rtl.write_text(rtl.read_text().replace("q + 4'd1", "q + 4'd2"))
    with patch.object(fpr, "run", wraps=fpr.run) as invoked:
        runner.step_emit_phase2_manifests(project, [], top_name="ctr", container="")
    assert invoked.call_count == 1, "stale current source must invoke the real formal producer"
    histories = list((project / "phase2/stage1/formal_history").glob("*"))
    assert len(histories) == 1, histories
    retained = {str(p.relative_to(histories[0])): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in histories[0].rglob("*") if p.is_file()}
    assert retained == before, "retain every old transcript, proof input, failure and counterexample byte"
    if failed:
        assert any(name.endswith("trace.aiw") for name in retained), retained
        old = json.loads((histories[0] / "results.json").read_text())
        assert old["all_proved"] is False and old["verdict"] == "FAIL"
    current = json.loads((project / "phase2/stage1/formal/results.json").read_text())
    assert current["chip_read"] == csr.current_chip_read(project, "ctr")
    assert current["all_proved"] is True
    assert _binding(_issue3145_cli(project))["status"] == gate.DISCHARGED_BY_BINDING


# Issue #3304: a retained, genuinely unfinished program check must be eligible
# for the current owners once, without invalidating completed/AI-only proofs.
_ISSUE3304_OWNERS = ("formal_harness_gen.py", "formal_property_run.py",
                     "formal_structural_check.py")


def _issue3304_owner_hashes():
    return {name: hashlib.sha256((PROGRAMS / name).read_bytes()).hexdigest()
            for name in _ISSUE3304_OWNERS}


@pytest.fixture(scope="module")
def issue3304_native_seed(tmp_path_factory):
    root = tmp_path_factory.mktemp("issue3304-seed")
    project = _project(root / "native-structural-partial")
    l8 = project / "phase1/generated_docs/L8_TIMING_WAVEFORM.json"
    doc = json.loads(l8.read_text())
    doc["clock_and_reset_waveform"]["resets"][0]["polarity"] = "active_high"
    l8.write_text(json.dumps(doc))
    # The visible counter's reset assertion really proves, while a second
    # state bit has a defined, non-forcing reset dependency. The structural
    # check honestly cannot close reset polarity for the complete state.
    (project / "phase2/stage1/rtl/ctr.v").write_text("""module ctr(
      input clk, input rst, input en, input d, input clear,
      output reg [3:0] q, output wire y);
      reg x;
      always @(posedge clk) begin
        if (rst) q <= 0; else if (en) q <= q + 1;
        x <= rst ? d ^ clear : d;
      end
      assign y = x;
    endmodule
    """)
    runner.step_emit_phase2_manifests(project, [], top_name="ctr", container="")
    formal = project / "phase2/stage1/formal"
    results = json.loads((formal / "results.json").read_text())
    assert results["verdict"] == "INCOMPLETE" and results["all_proved"] is True
    assert gate.proof_source_staleness(project, formal, results) == []
    _, refuted, opened = fpr._verified_program_closures(formal)
    polarity = "L8.clock_and_reset_waveform.resets.0.polarity"
    assert not refuted and polarity in opened, opened
    assert any(isinstance(c.get("claim"), dict)
               and c["verdict"] == "NOT_DISCHARGED"
               for c in opened[polarity]["claims"])
    return project


@pytest.mark.parametrize("owner", [None, *_ISSUE3304_OWNERS],
                         ids=["legacy-identity-absent", "harness-changed",
                              "producer-changed", "checker-changed"])
def test_issue3304_normal_producer_refreshes_only_unfinished_program_owners(
        tmp_path, issue3304_native_seed, owner):
    project = tmp_path / "public-component"
    shutil.copytree(issue3304_native_seed, project)
    formal = project / "phase2/stage1/formal"
    record = formal / "results.json"
    result = json.loads(record.read_text())
    if owner is None:
        result.pop("program_owner_sha256", None)
    else:
        # A controlled retained-owner record, never a fabricated proof: every
        # native proof input, status, disposition and transcript is unchanged.
        result["program_owner_sha256"] = _issue3304_owner_hashes()
        result["program_owner_sha256"][owner] = "0" * 64
    record.write_text(json.dumps(result, indent=2) + "\n")
    before = _formal_bytes(project)
    assert gate.proof_source_staleness(project, formal, result) == []
    with patch.object(fpr, "run", wraps=fpr.run) as invoked:
        runner.step_emit_phase2_manifests(project, [], top_name="ctr", container="")
    assert invoked.call_count == 1, "unfinished current inputs need the owning formal producer"
    histories = list((formal.parent / "formal_history").glob("*"))
    assert len(histories) == 1
    retained = {str(p.relative_to(histories[0])): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in histories[0].rglob("*") if p.is_file()}
    assert retained == before
    current = json.loads(record.read_text())
    assert current["program_owner_sha256"] == _issue3304_owner_hashes()
    expected = ("program-owner-identity-absent" if owner is None
                else "program-owner-changed:" + owner)
    assert current["continuation_refresh_reason"] == expected
    assert current["verdict"] == "INCOMPLETE", "an owner retry is not a PASS waiver"
    after = _formal_bytes(project)
    with patch.object(fpr, "run", wraps=fpr.run) as invoked:
        runner.step_emit_phase2_manifests(project, [], top_name="ctr", container="")
    assert invoked.call_count == 0, "same owning code must reuse even unresolved output"
    assert _formal_bytes(project) == after
    assert len(list((formal.parent / "formal_history").glob("*"))) == 1


@pytest.mark.parametrize("kind", ["same-owner", "unrelated-source", "ai-only", "counterexample"])
def test_issue3304_normal_producer_preserves_current_and_nonprogram_evidence(
        tmp_path, issue3304_native_seed, issue3145_native_seeds, kind):
    seed = (issue3304_native_seed if kind in ("same-owner", "unrelated-source")
            else issue3145_native_seeds[int(kind == "counterexample")])
    project = tmp_path / "public-component"
    shutil.copytree(seed, project)
    formal = project / "phase2/stage1/formal"
    record = formal / "results.json"
    result = json.loads(record.read_text())
    if kind in ("same-owner", "unrelated-source"):
        result["program_owner_sha256"] = _issue3304_owner_hashes()
    else:
        # Legacy AI-only and true CEX records must remain reusable too.
        result.pop("program_owner_sha256", None)
    record.write_text(json.dumps(result, indent=2) + "\n")
    if kind == "unrelated-source":
        (project / "phase3").mkdir(exist_ok=True)
        (project / "phase3/other-step.yaml").write_text("unrelated: changed\n")
    before = _formal_bytes(project)
    with patch.object(fpr, "run", wraps=fpr.run) as invoked:
        runner.step_emit_phase2_manifests(project, [], top_name="ctr", container="")
    assert invoked.call_count == 0
    assert _formal_bytes(project) == before
    assert not list((formal.parent / "formal_history").glob("*"))



def test_issue3304_complete_native_proof_is_not_invalidated_by_legacy_identity(tmp_path):
    project = _project(tmp_path / "complete-native")
    runner.step_emit_phase2_manifests(project, [], top_name="ctr", container="")
    formal = project / "phase2/stage1/formal"
    record = formal / "results.json"
    result = json.loads(record.read_text())
    result.pop("program_owner_sha256", None)
    record.write_text(json.dumps(result, indent=2) + "\n")
    assert gate.audit(project)["verdict"] == "PASS"
    before = _formal_bytes(project)
    with patch.object(fpr, "run", wraps=fpr.run) as invoked:
        runner.step_emit_phase2_manifests(project, [], top_name="ctr", container="")
    assert invoked.call_count == 0
    assert _formal_bytes(project) == before


def test_issue3304_environment_recovery_is_not_latched_by_failed_refresh(
        tmp_path, issue3304_native_seed):
    project = tmp_path / "public-component"
    shutil.copytree(issue3304_native_seed, project)
    formal = project / "phase2/stage1/formal"
    record = formal / "results.json"
    legacy = json.loads(record.read_text())
    legacy.pop("program_owner_sha256", None)
    record.write_text(json.dumps(legacy, indent=2) + "\n")
    before = _formal_bytes(project)
    # Force only the executor's real missing-tool branch. No successful proof
    # or new owner identity may be manufactured when the engine is unavailable.
    with patch.object(fpr, "_run_sby", return_value="sby: command not found\n"), \
            patch.object(fpr, "run", wraps=fpr.run) as invoked:
        runner.step_emit_phase2_manifests(project, [], top_name="ctr", container="")
    assert invoked.call_count == 1, "the incomplete legacy obligation must reach its producer"
    assert json.loads(record.read_text()) == legacy
    assert json.loads((formal / "formal_env_unavailable.json").read_text())["verdict"] == "ENV_UNAVAILABLE"
    histories = list((formal.parent / "formal_history").glob("*"))
    assert len(histories) == 1
    retained = {str(p.relative_to(histories[0])): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in histories[0].rglob("*") if p.is_file()}
    assert retained == before
    # Receipt clearing during the unsuccessful attempt is not a permanent
    # blocker: the retained program-routed obligation still needs its owner.
    assert not (formal / fpr.PROGRAM_RECEIPT).exists()
    with patch.object(fpr, "run", wraps=fpr.run) as invoked:
        runner.step_emit_phase2_manifests(project, [], top_name="ctr", container="")
    assert invoked.call_count == 1
    current = json.loads(record.read_text())
    assert current["program_owner_sha256"] == _issue3304_owner_hashes()
    assert current["continuation_refresh_reason"] == "program-owner-identity-absent"
    assert current["verdict"] == "INCOMPLETE"
    assert (formal / fpr.PROGRAM_RECEIPT).is_file()
