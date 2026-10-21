"""Issue #3444: Step 11 consumes and reconciles the exact current L20."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as D  # noqa: E402
import fault_scan_chain_insert as S  # noqa: E402


def _project(tmp_path: Path, chains: list[dict]) -> Path:
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L20_DFT_SCAN_TOPOLOGY.json").write_text(json.dumps({
        "doc_id": "L20", "applicability": "APPLICABLE",
        "extraction_status": "EXTRACTED",
        "fields": {"dft_present": True, "scan_chains": chains,
                   "test_compression": None, "bist_mbist": [],
                   "jtag_tap": None},
    }, indent=2) + "\n")
    return tmp_path


def _chain(**overrides):
    row = {"name": "core_scan", "length": 2, "scan_in": "sin",
           "scan_out": "sout", "clock": "clk"}
    row.update(overrides)
    return row


def _report(binding: dict) -> dict:
    report = {
        "clock": "clk", "input_flop_count": 2,
        "internal_chain_length": 2,
        "dft_ports": ["sin", "shift", "test", "tck", "sout"],
        "l20_contract": binding,
    }
    constraint = S.scan_shift_constraint(binding)
    if constraint is not None:
        report["scan_shift_constraint"] = constraint[1]
    report["l20_reconciliation"] = S.reconcile_l20_scan_contract(binding, report)
    return report


def test_positive_current_one_chain_contract_reconciles(tmp_path):
    project = _project(tmp_path, [_chain()])
    binding, problems = S.load_l20_scan_contract(
        project, expected_clock="clk", expected_length=2)
    assert problems == [] and binding is not None
    assert binding["path"].endswith("L20_DFT_SCAN_TOPOLOGY.json")
    assert len(binding["sha256"]) == 64
    report = _report(binding)
    assert report["l20_reconciliation"]["ok"] is True
    assert S.l20_binding_is_current(project, report)[0] is True
    assert D.dft_scan_insertion_contract(project)[0] is True


def test_stale_l20_bytes_invalidate_the_receipt(tmp_path):
    project = _project(tmp_path, [_chain()])
    binding, _ = S.load_l20_scan_contract(project, "clk", 2)
    report = _report(binding)
    path = project / binding["path"]
    path.write_text(path.read_text().replace('"core_scan"', '"renamed"'))
    ok, reason = S.l20_binding_is_current(project, report)
    assert ok is False
    assert "differs" in reason


def test_saved_pass_cannot_hide_changed_measurements(tmp_path):
    project = _project(tmp_path, [_chain()])
    binding, _ = S.load_l20_scan_contract(project, "clk", 2)
    report = _report(binding)
    report["internal_chain_length"] = 1
    # The saved reconciliation still says PASS; the consumer must re-derive it.
    ok, reason = S.l20_binding_is_current(project, report)
    assert ok is False
    assert "reconciliation" in reason


def test_multi_chain_is_refused_before_native_execution(tmp_path, monkeypatch):
    project = _project(tmp_path, [_chain(), _chain(name="second")])
    netlist = project / "phase2" / "stage2" / "synth" / "mapped.v"
    netlist.parent.mkdir(parents=True)
    netlist.write_text(
        "module top(input clk, input d, output q);\n"
        "sky130_fd_sc_hd__dfxtp_1 u0 (.CLK(clk), .D(d), .Q(q));\n"
        "endmodule\n")
    monkeypatch.setattr(S._fatpg, "_run_docker", lambda *a, **k: (
        (_ for _ in ()).throw(AssertionError("native tool must not run"))))
    rc, report = S.run_chain(
        project, "phase2/stage2/synth/mapped.v", "clk", "sky130",
        require_l20_contract=True)
    assert rc == 1
    assert report["stage"] == "l20_contract"
    assert "exactly one" in "; ".join(report["problems"])


def test_declared_length_must_equal_the_mapped_flop_count(tmp_path):
    project = _project(tmp_path, [_chain(length=3)])
    binding, problems = S.load_l20_scan_contract(project, "clk", 2)
    assert binding is None
    assert any("flop count 2" in problem for problem in problems)


def test_fixed_scan_ports_are_enforced(tmp_path):
    for key, value, expected in (("scan_in", "custom_si", "fixed port 'sin'"),
                                 ("scan_out", "custom_so", "fixed port 'sout'")):
        project = _project(tmp_path / key, [_chain(**{key: value})])
        binding, problems = S.load_l20_scan_contract(project, "clk", 2)
        assert binding is None
        assert expected in "; ".join(problems)


def test_declared_clock_must_equal_step11_clock(tmp_path):
    project = _project(tmp_path, [_chain(clock="other_clk")])
    binding, problems = S.load_l20_scan_contract(project, "clk", 2)
    assert binding is None
    assert "does not match Step 11 clock" in "; ".join(problems)


def test_declared_shift_frequency_emits_a_separate_bound_scan_mode_sdc(tmp_path):
    project = _project(tmp_path, [_chain(frequency_mhz=4)])
    binding, problems = S.load_l20_scan_contract(project, "clk", 2)
    assert problems == [] and binding is not None
    built = S.scan_shift_constraint(binding)
    assert built is not None
    text, metadata = built
    assert "-period 250" in text
    assert "[get_ports {clk}]" in text
    assert metadata["frequency_mhz"] == 4.0
    assert metadata["period_ns"] == 250.0
    assert metadata["l20_sha256"] == binding["sha256"]


def test_frequency_actuator_rejects_nonfinite_ambiguous_or_unsafe_values(tmp_path):
    cases = [
        _chain(frequency_mhz=float("inf")),
        _chain(frequency_mhz=10, shift_freq_mhz=5),
        _chain(frequency_mhz=10, clock="clk}] ; source bad.tcl; #"),
    ]
    for index, chain in enumerate(cases):
        project = _project(tmp_path / str(index), [chain])
        binding, problems = S.load_l20_scan_contract(project, chain["clock"], 2)
        assert binding is None
        assert problems


def test_published_frequency_receipt_requires_its_exact_constraint_bytes(tmp_path):
    project = _project(tmp_path, [_chain(frequency_mhz=10)])
    binding, problems = S.load_l20_scan_contract(project, "clk", 2)
    assert problems == [] and binding is not None
    text, metadata = S.scan_shift_constraint(binding)
    report = _report(binding)
    report["published"] = True
    path = project / metadata["path"]
    path.parent.mkdir(parents=True)
    path.write_text(text)
    assert S.l20_binding_is_current(project, report)[0] is True

    path.write_text(text.replace("-period 100", "-period 99"))
    ok, reason = S.l20_binding_is_current(project, report)
    assert ok is False
    assert "constraint artifact differs" in reason


def test_published_frequency_receipt_refuses_a_missing_constraint(tmp_path):
    project = _project(tmp_path, [_chain(frequency_mhz=10)])
    binding, problems = S.load_l20_scan_contract(project, "clk", 2)
    assert problems == [] and binding is not None
    report = _report(binding)
    report["published"] = True
    report["chain_length_matches_flop_count"] = True
    report["authorized_by_l20_contract"] = True
    scan_netlist = project / "phase2/stage2/dft/scan_netlist.v"
    scan_netlist.parent.mkdir(parents=True)
    scan_netlist.write_text("module top; endmodule\n")
    receipt = project / "reports/phase2/dft/scan_chain.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps(report))
    ok, reason = S.l20_binding_is_current(project, report)
    assert ok is False
    assert "constraint artifact is missing" in reason
    assert D.scan_netlist_is_real_chain(project) is False


def test_successful_chain_publishes_the_frequency_actuator(tmp_path, monkeypatch):
    project = _project(tmp_path, [_chain(frequency_mhz=10)])
    netlist = project / "phase2/stage2/synth/netlist.v"
    netlist.parent.mkdir(parents=True)
    netlist.write_text(
        "module top(input clk, input [1:0] d, output [1:0] q);\n"
        "sky130_fd_sc_hd__dfxtp_1 u0 (.CLK(clk), .D(d[0]), .Q(q[0]));\n"
        "sky130_fd_sc_hd__dfxtp_1 u1 (.CLK(clk), .D(d[1]), .Q(q[1]));\n"
        "endmodule\n")

    def fake_run_docker(project, cmd, **kwargs):
        output = cmd[cmd.index("-o") + 1].removeprefix("/work/")
        path = project / output
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = {"internalCount": 2, "boundaryCount": 0,
                    "order": [{"kind": "dff"}, {"kind": "dff"}]}
        path.write_text(
            "/* FAULT METADATA: '" + json.dumps(metadata)
            + "' END FAULT METADATA */\n"
            "module top(input clk, input sin, input shift, input test, "
            "input tck, output sout); endmodule\n")
        return 0, ("Internal scan chain successfully constructed. Length: 2\n"
                   "Boundary scan cells successfully chained. Length: 0\n"
                   "Total scan-chain length: 2\n"), ""

    monkeypatch.setattr(S._fatpg, "_run_docker", fake_run_docker)
    rc, report = S.run_chain(
        project, "phase2/stage2/synth/netlist.v", "clk", "sky130",
        skip_boundary="off", require_l20_contract=True)

    assert rc == 0 and report["published"] is True
    constraint = project / S.SCAN_SHIFT_SDC_REL
    assert constraint.read_text().splitlines()[2] == (
        "create_clock -name {scan_shift} -period 100 [get_ports {clk}]")
    assert report["scan_shift_constraint"]["sha256"] == hashlib.sha256(
        constraint.read_bytes()).hexdigest()
    assert S.l20_binding_is_current(project, report)[0] is True


def test_reconciliation_rejects_measured_length_port_and_clock_mutations(tmp_path):
    project = _project(tmp_path, [_chain()])
    binding, _ = S.load_l20_scan_contract(project, "clk", 2)
    base = _report(binding)
    mutations = [
        {"internal_chain_length": 1},
        {"dft_ports": ["shift", "test", "tck", "sout"]},
        {"dft_ports": ["sin", "shift", "test", "tck"]},
        {"clock": "other_clk"},
    ]
    for mutation in mutations:
        report = {**base, **mutation}
        assert S.reconcile_l20_scan_contract(binding, report)["ok"] is False
