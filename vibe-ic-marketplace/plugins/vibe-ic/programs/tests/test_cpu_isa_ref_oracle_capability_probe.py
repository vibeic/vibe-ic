"""A waiver may not assert a capability the environment HAS.

`cap:cpu_functional_oracle` claims a per-IC functional oracle cannot be
constructed. For a processor class with a DECLARED ISA that has a reference
simulator, that claim is decidable. These tests pin both halves:

  * the probe DECIDES it from measurement (and says NOT_APPLICABLE, never
    "constructible", when the design declares no ISA it knows)
  * the waiver gate REFUSES the waiver when the probe says CONSTRUCTIBLE, and
    is byte-identical to its previous behaviour in every other case
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
PROBE = PROGRAMS / "cpu_isa_ref_oracle_capability_probe.py"
WAIVER = PROGRAMS / "cpu_functional_oracle_waiver_check.py"

CONNECTIVITY_XML = """<results>
  <verdict>CONNECTIVITY_PASS</verdict>
  <verification_track>generic_full_stack</verification_track>
  <functional_verified>false</functional_verified>
  <capability_gap>cap:cpu_functional_oracle</capability_gap>
  <waiver_reason>generic_full_stack no-oracle class 'processor_cpu'</waiver_reason>
  <evidence>phase2/stage1/sim/full_stack.log</evidence>
</results>
"""


def _project(tmp_path: Path, declaration: str | None) -> Path:
    p = tmp_path / "proj"
    (p / "phase2" / "stage1" / "sim").mkdir(parents=True)
    (p / "reports" / "phase2" / "gates").mkdir(parents=True)
    (p / "plugin_output").mkdir(parents=True)
    (p / "phase2" / "stage1" / "sim" / "full_stack.log").write_text(
        "compiling generic full-stack TB\nFULL_STACK_TB_DONE\n")
    (p / "phase2" / "stage1" / "sim" / "results.xml").write_text(CONNECTIVITY_XML)
    (p / "reports" / "ic_class.json").write_text(
        json.dumps({"ic_class": "processor_cpu"}))
    if declaration is not None:
        (p / "plugin_output" / "declaration.json").write_text(declaration)
    return p


def _run(script: Path, *args: str):
    return subprocess.run([sys.executable, str(script), *args],
                          capture_output=True, text=True)


def _write_probe(project: Path, verdict: str) -> None:
    (project / "reports" / "phase2" / "gates"
     / "cpu_isa_ref_oracle_capability.json").write_text(json.dumps({
         "gate": "cpu_isa_ref_oracle_capability_probe",
         "verdict": verdict,
         "declared_isa_family": "riscv32",
         "declared_isa_source": "plugin_output/declaration.json",
         "reference_model": {"found": True, "path": "/foss/tools/bin/spike"},
         "toolchain": {"found": True,
                       "path": "/foss/tools/bin/riscv64-unknown-elf-gcc"},
         "oracle_shape": "differential vs the reference ISA simulator",
     }))


# ---------------------------------------------------------------- the probe

def test_probe_is_not_applicable_when_no_isa_is_declared(tmp_path):
    """No declared ISA must never become an assertion about constructibility."""
    proj = _project(tmp_path, json.dumps({"top_module": "widget"}))
    r = _run(PROBE, str(proj), "--container", "no_such_container_xyz")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NOT_APPLICABLE" in r.stdout


def test_probe_confirms_the_gap_when_the_tools_are_absent(tmp_path):
    """A container without the reference model licenses the waiver."""
    proj = _project(tmp_path, json.dumps({"cpu_isa": "rv32i_zifencei"}))
    r = _run(PROBE, str(proj), "--container", "no_such_container_xyz")
    assert r.returncode == 3, r.stdout + r.stderr
    assert "CAPABILITY_CONFIRMED" in r.stdout
    rep = json.loads((proj / "reports" / "phase2" / "gates"
                      / "cpu_isa_ref_oracle_capability.json").read_text())
    assert rep["declared_isa_family"] == "riscv32"
    assert rep["reference_model"]["found"] is False


def test_probe_reads_the_declaration_it_does_not_guess_from_names(tmp_path):
    """A module merely NAMED like a CPU is not a declared ISA."""
    proj = _project(tmp_path, json.dumps({"top_module": "riscv_looking_name"}))
    r = _run(PROBE, str(proj), "--container", "no_such_container_xyz")
    assert r.returncode == 2, r.stdout + r.stderr


# ---------------------------------------------------------- the waiver gate

def test_waiver_is_unchanged_when_the_probe_never_ran(tmp_path):
    """Reverse control: no probe artefact => the pre-existing verdict stands."""
    proj = _project(tmp_path, json.dumps({"cpu_isa": "rv32i"}))
    r = _run(WAIVER, str(proj))
    assert r.returncode == 3, r.stdout + r.stderr
    assert "PASS_WITH_WAIVERS" in r.stdout


def test_waiver_is_unchanged_when_the_capability_is_really_absent(tmp_path):
    """Reverse control: a CONFIRMED gap keeps the waiver licensed."""
    proj = _project(tmp_path, json.dumps({"cpu_isa": "rv32i"}))
    _write_probe(proj, "CAPABILITY_CONFIRMED")
    r = _run(WAIVER, str(proj))
    assert r.returncode == 3, r.stdout + r.stderr


def test_waiver_is_refused_when_the_capability_was_measured_present(tmp_path):
    """Forward control: the waiver's premise is false, so it must not be granted."""
    proj = _project(tmp_path, json.dumps({"cpu_isa": "rv32i"}))
    _write_probe(proj, "CONSTRUCTIBLE")
    r = _run(WAIVER, str(proj))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "GENERATOR gap" in r.stdout
    assert "cpu_isa_ref_oracle_capability.json" in r.stdout


def test_refusal_names_what_it_measured(tmp_path):
    """A FAIL has to be actionable: it must name the tools it found."""
    proj = _project(tmp_path, json.dumps({"cpu_isa": "rv32i"}))
    _write_probe(proj, "CONSTRUCTIBLE")
    r = _run(WAIVER, str(proj))
    assert "spike" in r.stdout
    assert "riscv64-unknown-elf-gcc" in r.stdout


def test_a_corrupt_probe_artefact_cannot_change_the_verdict(tmp_path):
    """Fail-open: unreadable probe output must not invent a FAIL."""
    proj = _project(tmp_path, json.dumps({"cpu_isa": "rv32i"}))
    (proj / "reports" / "phase2" / "gates"
     / "cpu_isa_ref_oracle_capability.json").write_text("{not json")
    r = _run(WAIVER, str(proj))
    assert r.returncode == 3, r.stdout + r.stderr
