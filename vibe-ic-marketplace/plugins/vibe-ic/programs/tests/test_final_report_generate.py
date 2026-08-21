#!/usr/bin/env python3
"""tests for final_report_generate.py — chip-agnostic final summary
generator.

Covers:
  - help / empty-project no-op
  - default output path = <project>/reports/final_summary.md
  - 8 stage tables (P0 + Stage 1-4 + Analog + Mixed + Stage 5) all rendered
  - cell-count parser pulls a count from a synth netlist + DEF
  - hardware-test schema: prefers reports/hw_test.json over legacy
  - tuning-loop convergence row populated when tuning_loop.json exists
  - waiver list rendered with review_required column
  - chip-agnostic guarantee: no IC name string from generator's own
    code (the generator only emits IC name from L1_DATASHEET.json[ic_name])
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
import pytest


PROG = Path(__file__).resolve().parent.parent / "final_report_generate.py"


def _run(args, **kw):
    return subprocess.run([sys.executable, str(PROG), *args],
                          capture_output=True, text=True, **kw)


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0
    assert "chip-AGNOSTIC" in r.stdout or "agnostic" in r.stdout.lower()


def test_empty_project_writes_minimal_report(tmp_path):
    r = _run([str(tmp_path), "--no-audit"])
    assert r.returncode == 0
    out = tmp_path / "reports" / "final_summary.md"
    assert out.is_file()
    text = out.read_text()
    assert "Phase 2+3 Final Summary" in text
    assert "## Verdict" in text
    assert "## Output #1 — Hardware verification" in text
    assert "## Output #2 — FPGA-verified GDS" in text
    assert "## Output #3 — Test patterns" in text
    assert "## Output #4 — Analog convergence" in text
    assert "## Cell count" in text
    assert "## Canonical step input/output" in text
    assert "## Waivers" in text
    assert "## Self-attestation" in text
    assert "## Chip-specific addendum" in text


def test_eight_stage_tables_rendered(tmp_path):
    """All 7 stage headers + P0 must appear regardless of project state."""
    r = _run([str(tmp_path), "--no-audit"])
    assert r.returncode == 0
    text = (tmp_path / "reports" / "final_summary.md").read_text()
    for header in (
        "P0 — Structural-RTL umbrella",
        "Stage 1 — RTL generation",
        "Stage 2 — Synthesis",
        "Stage 3 — Physical Design",
        "Analog Track A1-A9",
        "Mixed-Signal M1-M4",
        "Stage 4 — Sign-off",
        "Stage 5 — Manufacturing",
    ):
        assert header in text, f"missing stage header: {header}"


def test_cell_count_parsed_from_netlist_and_def(tmp_path):
    """Plant a tiny synth netlist + DEF; expect cell counts to surface."""
    (tmp_path / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (tmp_path / "phase2" / "stage2" / "synth" / "chip_top_asic_synth.v").write_text(textwrap.dedent("""
        module foo;
          DFFRQD1 ff1 ( .CK(c), .D(d), .Q(q) );
          DFFRQD1 ff2 ( .CK(c), .D(d), .Q(q) );
          NAND2D1 g1 ( .A(a), .B(b), .Z(z) );
          INVD1 i1 ( .A(a), .Z(z) );
        endmodule
    """).strip())
    (tmp_path / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    (tmp_path / "phase3" / "stage3" / "pnr" / "routed.def").write_text("DESIGN foo ;\nCOMPONENTS 4 ;\nEND\n")
    r = _run([str(tmp_path), "--no-audit"])
    assert r.returncode == 0
    text = (tmp_path / "reports" / "final_summary.md").read_text()
    assert "DFFRQD1" in text
    # synth count 4 OR DEF components 4 — both columns numeric
    assert "| 4 |" in text or "| 4 | `pnr/routed.def`" in text


def test_hw_test_schema_preferred_over_legacy(tmp_path):
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "hw_test.json").write_text(json.dumps({
        "tester": "Generic ATE",
        "board": "DUT-Board-X",
        "verdict": "PASS",
        "criterion": "all probes responding",
        "iterations": 3,
        "passed_iterations": 3,
        "evidence": ["reports/foo.json"],
    }))
    # legacy file should be IGNORED when hw_test.json exists
    (tmp_path / "reports" / "phase2").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "phase2" / "example_tester_test.json").write_text(json.dumps({
        "verdict": "FAIL", "byte_6": "0x02"
    }))
    r = _run([str(tmp_path), "--no-audit"])
    assert r.returncode == 0
    text = (tmp_path / "reports" / "final_summary.md").read_text()
    assert "Generic ATE" in text
    assert "DUT-Board-X" in text
    assert "all probes responding" in text
    # legacy chip-specific bytes must NOT leak through when canonical exists
    assert "0x02" not in text
    assert "byte_6" not in text


def test_legacy_example_tester_fallback(tmp_path):
    """When only legacy example_tester_test.json exists, generator coerces to generic
    schema. Chip-specific bytes will appear ONLY because they are in the
    legacy file's data — but the generator does not invent any."""
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "phase2").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "phase2" / "example_tester_test.json").write_text(json.dumps({
        "verdict": "PASS", "byte_6": "0xF2", "runs": 5,
    }))
    r = _run([str(tmp_path), "--no-audit"])
    assert r.returncode == 0
    text = (tmp_path / "reports" / "final_summary.md").read_text()
    assert "PASS" in text
    assert "(legacy example_tester_test.json)" in text or "example_tester_test.json" in text


def test_tuning_loop_convergence_row(tmp_path):
    (tmp_path / "phase3" / "analog").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase3" / "analog" / "analog_block_list.json").write_text(json.dumps({
        "blocks": [{"name": "block_a"}, {"name": "block_b"}]
    }))
    (tmp_path / "phase3" / "analog" / "block_a").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase3" / "analog" / "block_a" / "tuning_loop.json").write_text(json.dumps({
        "block": "block_a",
        "iterations": [
            {"iteration": 1, "all_corners_pass": False},
            {"iteration": 2, "all_corners_pass": False},
            {"iteration": 3, "all_corners_pass": True},
        ],
    }))
    r = _run([str(tmp_path), "--no-audit"])
    assert r.returncode == 0
    text = (tmp_path / "reports" / "final_summary.md").read_text()
    assert "block_a" in text
    assert "block_b" in text
    # block_a converged in 3 iters
    assert "| `block_a` | 3 | ✅ |" in text


def test_waivers_rendered_with_review_required(tmp_path):
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [
            {"id": "20",
             "reason": "test reason xyz",
             "ticket": "TKT-001",
             "approver": "alice",
             "review_required": True},
        ]
    }))
    r = _run([str(tmp_path), "--no-audit"])
    assert r.returncode == 0
    text = (tmp_path / "reports" / "final_summary.md").read_text()
    assert "TKT-001" in text
    assert "alice" in text
    assert "test reason xyz" in text


def test_no_chip_specific_strings_in_generator(tmp_path):
    """The generator's OWN output (with empty inputs) must not name any IC,
    protocol, opcode, tester model, or analog block. (Project-supplied data
    can; generator code must not.)"""
    r = _run([str(tmp_path), "--no-audit"])
    assert r.returncode == 0
    text = (tmp_path / "reports" / "final_summary.md").read_text()
    # words frequently used in chip-specific contexts
    forbidden = ["EXAMPLE_CHIP", "Apple", "Lightning", "EXAMPLE_TESTER", "byte[6]", "0xF2",
                 "EngineerMode", "TestMode", "bandgap", "VBG"]
    leaked = [w for w in forbidden if w in text]
    assert not leaked, f"chip-specific terms leaked in generator output: {leaked}"


def test_chip_specific_addendum_link_when_present(tmp_path):
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    # v1.6.34: chip_specific_summary.md lives at reports/ root (per
    # doctrine rule #3 + reports_subfolder_taxonomy_check whitelist).
    (tmp_path / "reports" / "chip_specific_summary.md").write_text("# Chip\n")
    r = _run([str(tmp_path), "--no-audit"])
    text = (tmp_path / "reports" / "final_summary.md").read_text()
    assert "chip_specific_summary.md" in text
    assert "See" in text and "for IC-specific" in text


def test_chip_specific_addendum_message_when_absent(tmp_path):
    r = _run([str(tmp_path), "--no-audit"])
    assert r.returncode == 0
    text = (tmp_path / "reports" / "final_summary.md").read_text()
    # #1168: the guidance is unchanged, but the path of a file this run does NOT
    # ship is no longer spelled as a backticked citation (see
    # test_issue1168_generators_cite_only_shipped_artefacts.py).
    assert "No chip-specific addendum present" in text
    assert "reports/chip_specific_summary.md" in text
    assert "Author it by hand" in text
    assert "`reports/chip_specific_summary.md`" not in text


def test_explicit_out_path(tmp_path):
    custom = tmp_path / "custom_out.md"
    r = _run([str(tmp_path), "--no-audit", "--out", str(custom)])
    assert r.returncode == 0
    assert custom.is_file()
    # default path should NOT exist when --out is used
    assert not (tmp_path / "reports" / "final_summary.md").is_file()
