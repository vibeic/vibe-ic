"""Real ngspice receiver-noise component proof; physical readiness is separate."""
import json
import shutil
from pathlib import Path

import mixed_signal_m3_run as m3
import mixed_signal_interface_si_check as si_gate

FIXTURE = Path(__file__).parent / "fixtures/m3_receiver_noise"


def test_ordinary_receiver_noise_observation_is_measured(tmp_path):
    project = tmp_path / "component"
    shutil.copytree(FIXTURE, project)
    assert m3.main([str(project), "--top", "bridge_top", "--container", "host"]) == 2
    report = json.loads((project / m3.SI).read_text())
    assert report["coverage"]["noise"] == "MEASURED", report
    measurement = report["receiver_noise"]
    assert measurement["verdict"] == "PASS"
    assert 1e-5 <= measurement["criteria"][0]["measured"] <= 2.5e-5
    assert measurement["criteria"][0]["units"] == "V_RMS"
    audit = m3.audit(project, "si")
    assert audit["coverage"]["noise"] == "MEASURED"
    assert audit["receiver_noise"] == measurement
    assert audit["passed"] is False
    assert audit["findings"][0]["rule"] == "SI_COVERAGE_NOT_MEASURED"
    assert si_gate.main([str(project), "--require-current-production"]) == 1


import hashlib
import os
import pytest
import _mixed_signal_native as native
import mixed_signal_signoff_run as m4


def read(path):
    return json.loads(path.read_text())


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


@pytest.fixture
def project(tmp_path):
    dst = tmp_path / "component"
    shutil.copytree(FIXTURE, dst)
    return dst


@pytest.fixture
def measured(project):
    assert m3.main([str(project), "--top", "bridge_top", "--container", "host"]) == 2
    assert m3.audit(project, "si")["coverage"]["noise"] == "MEASURED"
    return project


def modify_contract(project, change):
    path = project / "input/mixed_signal/native.json"
    data = read(path)
    change(data["si"]["receiver_noise"])
    write(path, data)


@pytest.mark.parametrize("damage", ['unknown_analysis', 'wrong_design', 'missing_model', 'stale_model', 'unbounded_criteria', 'unknown_metric', 'wrong_units', 'empty_criteria', 'nonfinite_band', 'unbounded_grid', 'outside_project', 'foreign_symlink', 'missing_field', 'hidden_include'])
def test_invalid_noise_declaration_refuses_before_any_execution(project, tmp_path, monkeypatch, damage):
    path = project / "input/mixed_signal/native.json"
    data = read(path); spec = data["si"]["receiver_noise"]
    if damage == "unknown_analysis": spec["analysis"] = "syntax_only"
    elif damage == "wrong_design": spec["top"] = "other_top"
    elif damage == "missing_model": spec["model"] = "input/mixed_signal/absent.sp"
    elif damage == "stale_model": (project / spec["model"]).write_text("changed current bytes\n")
    elif damage == "unbounded_criteria": spec["criteria"][0].pop("max")
    elif damage == "unknown_metric": spec["criteria"][0]["metric"] = "expected_noise"
    elif damage == "wrong_units": spec["criteria"][0]["units"] = "V_squared_per_Hz"
    elif damage == "empty_criteria": spec["criteria"] = []
    elif damage == "nonfinite_band": spec["frequency_stop_hz"] = float("inf")
    elif damage == "unbounded_grid": spec["points_per_decade"] = 200000
    elif damage == "outside_project": spec["model"] = str(tmp_path / "foreign.sp")
    elif damage == "foreign_symlink":
        foreign = tmp_path / "foreign.sp"; shutil.copyfile(project / spec["model"], foreign)
        link = project / "input/mixed_signal/link.sp"; link.symlink_to(foreign)
        spec["model"] = str(link.relative_to(project))
    elif damage == "missing_field": spec.pop("temperature_c")
    elif damage == "hidden_include":
        model = project / spec["model"]
        model.write_text(model.read_text() + '.include "unbound.sp"\n')
    write(path, data)
    calls = []
    monkeypatch.setattr(native.Engine, "run", lambda *a, **k: calls.append(a))
    assert m3.main([str(project), "--top", "bridge_top", "--container", "host"]) == 1
    assert calls == []
    assert not (project / m3.RECEIPT).exists()
    assert not (project / m3.SI).exists()


@pytest.mark.parametrize("damage", ["violated_limit", "bad_model"])
def test_real_noise_failure_reaches_current_gate_and_m4(project, damage):
    if damage == "violated_limit":
        modify_contract(project, lambda s: s["criteria"][0].update(min=0, max=1e-6))
    else:
        data = read(project / "input/mixed_signal/native.json")
        spec = data["si"]["receiver_noise"]
        model = project / spec["model"]
        model.write_text(model.read_text().replace("1000", "undeclared_device_value"))
    assert m3.main([str(project), "--top", "bridge_top", "--container", "host"]) == 1
    si = read(project / m3.SI)
    assert si["verdict"] == "FAIL"
    assert si["receiver_noise"]["verdict"] == "FAIL"
    audit = m3.audit(project, "si")
    assert audit["verdict"] == "FAIL"
    if damage == "violated_limit":
        assert si["coverage"]["noise"] == "MEASURED"
        assert audit["receiver_noise"]["criteria"][0]["measured"] > 1e-6
        assert audit["receiver_noise"]["criteria"][0]["verdict"] == "FAIL"
    assert si_gate.main([str(project), "--require-current-production"]) == 1
    assert m4.main([str(project), "--top", "bridge_top"]) == 1
    signoff = read(project / m4.OUTPUT)
    assert signoff["verdict"] == "FAIL" and signoff["ready_for_tapeout"] is False
    assert next(c for c in signoff["checks"] if c["step"] == "M3_si")["verdict"] == "FAIL"


def test_missing_noise_declaration_stays_unmeasured(project):
    path = project / "input/mixed_signal/native.json"
    data = read(path); data["si"].pop("receiver_noise"); write(path, data)
    assert m3.main([str(project), "--top", "bridge_top", "--container", "host"]) == 2
    result = read(project / m3.SI)
    assert result["coverage"]["noise"] == "NOT_MEASURED"
    receipt = read(project / m3.RECEIPT)
    assert not any("receiver_noise/noise.sp" in " ".join(e["command"]) for e in receipt["execution"])
    assert m3.audit(project, "si")["passed"] is False


@pytest.mark.parametrize("damage,rule", [('wrong_token', 'MISSING_NOISE_OBSERVATION'), ('stale_criteria', 'CONTRADICTS_NATIVE_OUTPUT'), ('fabricated_measured', 'CONTRADICTS_NATIVE_OUTPUT'), ('corrupt_scalar', 'CONTRADICTS_NATIVE_OUTPUT'), ('short_spectrum', 'MISSING_NOISE_OBSERVATION'), ('wrong_units', 'CONTRADICTS_NATIVE_OUTPUT'), ('missing_scalar', 'MISSING_NOISE_OBSERVATION')])
def test_current_noise_consumer_rejects_corrupt_native_evidence(measured, tmp_path, damage, rule):
    record = read(measured / m3.RECEIPT)
    work = measured / record["native_root"] / "si/receiver_noise"
    if damage == "wrong_token":
        path = work / "noise.log"; stamp = path.stat().st_mtime_ns
        target = record["run_id"]
        path.write_text(path.read_text().replace(target, "f" * len(target)))
        os.utime(path, ns=(stamp, stamp))
    elif damage == "stale_criteria": modify_contract(measured, lambda s: s["criteria"][0].update(max=3e-5))
    elif damage == "fabricated_measured":
        si = read(measured / m3.SI)
        si["receiver_noise"]["criteria"][0]["measured"] = 0
        write(measured / m3.SI, si)
    elif damage == "corrupt_scalar":
        path = work / "integrated.txt"; stamp = path.stat().st_mtime_ns
        path.write_text("onoise_total onoise_total\n1e-6 1e-6\n")
        os.utime(path, ns=(stamp, stamp))
    elif damage == "short_spectrum":
        path = work / "spectrum.txt"; stamp = path.stat().st_mtime_ns
        path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n")
        os.utime(path, ns=(stamp, stamp))
    elif damage == "wrong_units":
        si = read(measured / m3.SI); si["receiver_noise"]["criteria"][0]["units"] = "V_squared_per_Hz"
        write(measured / m3.SI, si)
    elif damage == "missing_scalar": (work / "integrated.txt").unlink()
    write(measured / m3.RECEIPT, record)
    audit = m3.audit(measured, "si")
    assert audit["passed"] is False
    assert audit["findings"][0]["rule"] == rule, audit
    assert "receiver_noise" not in audit  # no positive diagnostic after refusal
    assert si_gate.main([str(measured), "--require-current-production"]) == 1




def test_noise_audit_cannot_overwrite_native_measurements(measured):
    record = read(measured / m3.RECEIPT)
    scalar = measured / record["native_root"] / "si/receiver_noise/integrated.txt"
    before = scalar.read_bytes()
    assert si_gate.main([str(measured), "--require-current-production", "--json", str(scalar)]) == 1
    assert scalar.read_bytes() == before
