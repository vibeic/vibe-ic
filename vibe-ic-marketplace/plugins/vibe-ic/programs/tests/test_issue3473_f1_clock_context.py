"""#3473 F1: contextual clock observations are not physical targets."""
from __future__ import annotations

import json
import hashlib
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import clock_target_provenance as provenance  # noqa: E402
import l19_constraint_token_emit as l19_emit  # noqa: E402
import l8_doc_clock_freq_synth as producer  # noqa: E402
import spi_protocol_synth as spi_consumer  # noqa: E402
from _reset_input_semantics import clock_edge_semantics  # noqa: E402


EXACT_SIMULATION_ONLY = """# Constraints

The functional retained-checkpoint fixture declares a single rising-edge clock
named `clk`. The clock period is 10 ns for lint and simulation context.
No generated clock, false path, multicycle path, I/O delay, die area, floorplan, placement,
PDN, routing, package, or physical signoff constraint is claimed. Physical
implementation is outside the bounded Step 1 through Step 4 replay.
"""


def _write_project(tmp_path: Path, text: str) -> Path:
    project = tmp_path / "project"
    docs = project / "input" / "docs"
    generated = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    generated.mkdir(parents=True)
    (docs / "L9_constraints_floorplan.md").write_text(text)
    l8 = {
        "clock_mhz": None,
        "clock_domains": [{
            "name": "clk", "source_pin": "clk", "domain_kind": "primary",
            "role": "master", "freq_hz": None, "freq_mhz": None,
            "period_ns": None,
        }],
        "clocks": [{
            "name": "clk", "source_pin": "clk", "freq_hz": None,
            "freq_mhz": None, "period_ns": None,
        }],
    }
    for name in ("L8_RTL_CONSTANTS.json", "L8_TIMING_WAVEFORM.json"):
        (generated / name).write_text(json.dumps(l8))
    (generated / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "dut",
        "top_module_pins": [
            {"name": "clk", "mode": "input"},
            {"name": "data_i", "mode": "input"},
            {"name": "data_o", "mode": "output"},
        ],
    }))
    (generated / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps({
        "doc_id": "L19", "fields": {"constraints_present": False},
    }))
    return project


def _l8(project: Path) -> dict:
    return json.loads((project / "phase1/generated_docs/L8_RTL_CONSTANTS.json").read_text())


def _clock(project: Path) -> dict:
    return _l8(project)["clock_domains"][0]


def _sdc(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PROGRAMS / "sdc_gen.py"), str(project),
         "--top-name", "dut", "--force"],
        capture_output=True, text=True,
    )


def test_exact_simulation_only_period_stays_contextual_and_physical_consumers_refuse(
        tmp_path):
    project = _write_project(tmp_path, EXACT_SIMULATION_ONLY)
    assert producer.main([str(project), "--apply"]) == 0

    clock = _clock(project)
    assert clock["period_ns"] == 10.0
    assert clock["freq_evidence"]["physical_target_status"] == "CONTEXT_ONLY"
    assert _l8(project)["clock_mhz"] is None

    resolved = provenance.resolve(project)
    assert resolved["tier"] == provenance.NOT_DETERMINED_TIER, resolved
    assert resolved["period_ns"] is None

    report = l19_emit.run(project)
    assert report["status"] == "OK", report
    fields = json.loads((project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").read_text())["fields"]
    assert fields["clock_target"]["status"] == "NOT_STATED"
    assert fields["clock_target"]["period_ns"] is None
    assert fields["constraints_present"] is False
    spi_consumer.apply_spi_synth(
        project / "phase1/generated_docs", is_spi=False, spi_ic_name=None)
    fields = json.loads((project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").read_text())["fields"]
    assert fields["clock_target"]["status"] == "NOT_STATED"
    assert fields["constraints_present"] is False

    consumer = _sdc(project)
    assert consumer.returncode == 1, consumer.stdout + consumer.stderr
    assert "L8_CLOCK_TARGET_NOT_PHYSICAL" in consumer.stderr
    assert not list(project.rglob("*.sdc"))


def test_design_owned_physical_target_reaches_the_same_consumers(tmp_path):
    project = _write_project(
        tmp_path,
        "# Constraints\n\nclk: The clock period is 12 ns for physical implementation.\n",
    )
    assert producer.main([str(project), "--apply"]) == 0
    clock = _clock(project)
    assert clock["period_ns"] == 12.0
    assert clock["freq_evidence"]["physical_target_status"] == "DECLARED"
    resolved = provenance.resolve(project)
    assert resolved["tier"] == "l8_declared", resolved
    assert resolved["period_ns"] == 12.0

    report = l19_emit.run(project)
    assert report["status"] == "OK", report
    fields = json.loads((project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").read_text())["fields"]
    assert fields["clock_target"]["status"] == "DECLARED"
    assert fields["clock_target"]["period_ns"] == 12.0
    spi_consumer.apply_spi_synth(
        project / "phase1/generated_docs", is_spi=False, spi_ic_name=None)
    fields = json.loads((project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").read_text())["fields"]
    assert fields["clock_target"]["status"] == "DECLARED"
    assert fields["constraints_present"] is True

    consumer = _sdc(project)
    assert consumer.returncode == 0, consumer.stdout + consumer.stderr
    deck = (project / "phase2/stage1/fpga/dut.sdc").read_text()
    assert "create_clock -name clk -period 12 [get_ports {clk}]" in deck


def test_mixed_context_and_physical_claim_is_ambiguous_and_refused(tmp_path):
    project = _write_project(
        tmp_path,
        "# Constraints\n\nclk: The clock period is 9 ns for lint and simulation "
        "context and as a physical signoff constraint.\n",
    )
    assert producer.main([str(project), "--apply"]) == 0
    clock = _clock(project)
    assert clock["period_ns"] == 9.0
    assert clock["freq_evidence"]["physical_target_status"] == "AMBIGUOUS"
    assert provenance.resolve(project)["tier"] == provenance.NOT_DETERMINED_TIER
    consumer = _sdc(project)
    assert consumer.returncode == 1
    assert "clk:AMBIGUOUS" in consumer.stderr


def test_ordinary_unqualified_design_clock_keeps_legacy_authority(tmp_path):
    project = _write_project(
        tmp_path, "# Constraints\n\nclk: The clock period is 7.5 ns.\n")
    assert producer.main([str(project), "--apply"]) == 0
    assert _clock(project)["freq_evidence"]["physical_target_status"] == "DECLARED"
    assert provenance.resolve(project)["period_ns"] == 7.5


def test_source_bound_rising_named_clock_edge_has_explicit_basis():
    sentence = (
        "- On a rising `clk_i` edge, drive `count_o` to zero when `rst_ni` "
        "is low; otherwise retain its value."
    )
    text = "\n" * 9 + sentence + "\n"
    result = clock_edge_semantics(
        "clk_i", {"input/docs/phase1_prompt.md": text})
    assert result["edge"] == "posedge"
    edge = result["semantic_provenance"]["edge"]
    assert edge["kind"] == "explicit"
    assert edge["basis"] == [{
        "file": "input/docs/phase1_prompt.md",
        "line": 10,
        "quote": sentence,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }]


def test_named_edge_never_borrows_a_foreign_clock():
    result = clock_edge_semantics(
        "clk_i", {"input/docs/phase1_prompt.md":
                  "On a falling `other_clk` edge, update the output.\n"})
    assert result == {
        "edge": "posedge",
        "semantic_provenance": {"edge": {
            "kind": "convention", "rule": "default_positive_clock_edge"}},
    }


def test_conflicting_named_edge_sentences_remain_ambiguous():
    text = ("On a rising `clk_i` edge, sample the input.\n"
            "On a falling `clk_i` edge, update the output.\n")
    result = clock_edge_semantics(
        "clk_i", {"input/docs/phase1_prompt.md": text})
    assert result["edge"] == "unknown"
    edge = result["semantic_provenance"]["edge"]
    assert edge["kind"] == "conflict"
    assert {row["line"] for row in edge["basis"]} == {1, 2}
