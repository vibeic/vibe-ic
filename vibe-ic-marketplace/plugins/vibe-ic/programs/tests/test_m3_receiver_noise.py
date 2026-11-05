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


@pytest.mark.parametrize("damage", ["unknown_analysis", "wrong_design", "missing_model", "stale_model",
                                    "unbounded_criteria", "unknown_metric", "wrong_units", "empty_criteria",
                                    "nonfinite_band", "unbounded_grid", "outside_project", "foreign_symlink",
                                    "unknown_field", "missing_field", "hidden_include", "model_dependency_collision"])
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
    elif damage == "unknown_field": spec["trust_expected_noise"] = True
    elif damage == "missing_field": spec.pop("temperature_c")
    elif damage == "model_dependency_collision":
        spec["dependencies"] = {spec["model"]: spec["model_sha256"]}
        spec["model_sha256"] = "0" * 64
    elif damage == "hidden_include":
        model = project / spec["model"]
        model.write_text(model.read_text() + '.include "unbound.sp"\n')
        spec["model_sha256"] = hashlib.sha256(model.read_bytes()).hexdigest()
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
        modify_contract(project, lambda s: s.update(model_sha256=hashlib.sha256(model.read_bytes()).hexdigest()))
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


@pytest.mark.parametrize("damage,rule", [
    ("missing_execution", "MISSING_NOISE_OBSERVATION"),
    ("syntax_only", "MISSING_NOISE_OBSERVATION"),
    ("replayed_spectrum", "STALE_NATIVE_OUTPUT"),
    ("replayed_log", "STALE_NATIVE_OUTPUT"),
    ("wrong_token", "MISSING_NOISE_OBSERVATION"),
    ("wrong_model_identity", "MISSING_NOISE_OBSERVATION"),
    ("wrong_design", "WRONG_DESIGN"),
    ("foreign_output", "FOREIGN_INPUT"),
    ("stale_model", "STALE_NOISE_MODEL"),
    ("stale_criteria", "STALE_INPUT"),
    ("fabricated_measured", "CONTRADICTS_NATIVE_OUTPUT"),
    ("corrupt_scalar", "CONTRADICTS_NATIVE_OUTPUT"),
    ("short_spectrum", "MISSING_NOISE_OBSERVATION"),
    ("wrong_units", "CONTRADICTS_NATIVE_OUTPUT"),
    ("missing_scalar", "STALE_NATIVE_OUTPUT"),
])
def test_current_noise_consumer_rejects_corrupt_native_evidence(measured, tmp_path, damage, rule):
    record = read(measured / m3.RECEIPT)
    work = measured / record["native_root"] / "si/receiver_noise"
    if damage == "missing_execution":
        record["execution"] = [e for e in record["execution"] if "receiver_noise/noise.sp" not in " ".join(e["command"])]
    elif damage == "syntax_only": record["execution"][-1]["stage"] = "compile"
    elif damage in ("replayed_spectrum", "replayed_log"):
        path = work / ("spectrum.txt" if damage == "replayed_spectrum" else "noise.log")
        os.utime(path, ns=(1, 1))
    elif damage in ("wrong_token", "wrong_model_identity"):
        path = work / "noise.log"; stamp = path.stat().st_mtime_ns
        target = record["run_id"] if damage == "wrong_token" else read(measured / "input/mixed_signal/native.json")["si"]["receiver_noise"]["model_sha256"]
        path.write_text(path.read_text().replace(target, "f" * len(target)))
        os.utime(path, ns=(stamp, stamp))
    elif damage == "wrong_design":
        si = read(measured / m3.SI); si["top"] = "other_design"; write(measured / m3.SI, si)
    elif damage == "foreign_output":
        foreign = tmp_path / "foreign_spectrum.txt"; shutil.copyfile(work / "spectrum.txt", foreign)
        (work / "spectrum.txt").unlink(); (work / "spectrum.txt").symlink_to(foreign)
    elif damage == "stale_model":
        model = measured / "input/mixed_signal/receiver_noise.sp"
        model.write_text(model.read_text().replace("1000", "2000"))
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
    # Hostile rehashes cannot turn corrupt native output into measured evidence.
    record["outputs"] = {rel: m3.digest(measured / rel) for rel in record["outputs"] if (measured / rel).is_file()}
    write(measured / m3.RECEIPT, record)
    audit = m3.audit(measured, "si")
    assert audit["passed"] is False
    assert audit["findings"][0]["rule"] == rule, audit
    assert "receiver_noise" not in audit  # no positive diagnostic after refusal
    assert si_gate.main([str(measured), "--require-current-production"]) == 1


def test_foreign_noise_receipt_cannot_be_reused(measured, tmp_path):
    foreign = tmp_path / "other_project"
    shutil.copytree(measured, foreign)
    assert m3.audit(foreign, "si")["findings"][0]["rule"] == "WRONG_PROJECT"


def test_noise_audit_cannot_overwrite_native_measurements(measured):
    record = read(measured / m3.RECEIPT)
    scalar = measured / record["native_root"] / "si/receiver_noise/integrated.txt"
    before = scalar.read_bytes()
    assert si_gate.main([str(measured), "--require-current-production", "--json", str(scalar)]) == 1
    assert scalar.read_bytes() == before
