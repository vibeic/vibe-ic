"""Issue #3444: Step 11 consumes and reconciles the exact current L20."""
from __future__ import annotations

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


def test_declared_shift_frequency_is_refused_until_an_actuator_exists(tmp_path):
    project = _project(tmp_path, [_chain(frequency_mhz=4)])
    binding, problems = S.load_l20_scan_contract(project, "clk", 2)
    assert binding is None
    assert "no shift-frequency actuator" in "; ".join(problems)


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
