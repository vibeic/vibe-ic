#!/usr/bin/env python3
"""Tests for GitHub issue #461 — final_summary.md is generated mid-flow
and never refreshed, producing four symptoms in
`programs/final_report_generate.py`:

  (1) attestation gate FAILs on runner-emitted netlists that appear
      AFTER the summary was generated (MISSING_ATTESTATION). Fix: the
      generator pre-writes the SHA-256 attestation table to the
      canonical report path BEFORE the internal compliance audit runs,
      so the gate reads current artefact hashes (regenerate-at-audit-
      time semantics).

  (2) three conflicting PASS counts in one report (headline vs prose vs
      a fresh --strict). Fix: all displayed counts come from a SINGLE
      verdict-rollup snapshot of ONE audit run, stamped with a snapshot
      marker.

  (3) ic_name placeholder printed even though L1_DATASHEET.json[ic_name]
      IS populated. Fix: read from the canonical
      `phase1/generated_docs/L1_DATASHEET.json` (the prior code probed
      only a flat `generated_docs/` that real projects never use).

  (4) the A1-A9 presence table shows all '—' although A4 artifacts exist
      and the compliance checker judges PASS. Fix: the presence table
      reuses the SAME path-glob logic the per-block compliance checkers
      (analog_a{1..9}_*_check.py) use — single source.

Each fixed-path test is paired with a regression guard for the prior
correct behavior (the corpus-sweep / empty-project conditions), so the
fix cannot silently break the existing contract.

Conventions follow programs/tests/test_final_report_generate.py
(sys.path.insert import pattern + subprocess CLI invocation).
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import final_report_generate as g  # noqa: E402
import agent_report_sha256_attestation_check as gate  # noqa: E402
import _path_layout as _pl  # noqa: E402

PROG = PROGRAMS / "final_report_generate.py"


def _run(args, **kw):
    return subprocess.run([sys.executable, str(PROG), *args],
                          capture_output=True, text=True, **kw)


def _summary_text(project: Path) -> str:
    return (project / "reports" / "final_summary.md").read_text()


# ────────────────────────────────────────────────────────────────────
# Symptom (1) — regenerate-at-audit-time / late-emitted netlist
# ────────────────────────────────────────────────────────────────────

def test_prewrite_attestation_refreshes_late_netlist(tmp_path):
    """FIXED PATH: a stale summary (attests only an old netlist) plus a
    late-emitted netlist FAILs the attestation gate; the generator's
    pre-write at audit time refreshes the table so the gate PASSes —
    this is the exact #461 symptom (1) sequence."""
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "old.v").write_text("module old;\nendmodule\n")
    out = _pl.report_path(tmp_path, "final_summary.md")

    # Mid-flow summary: attests old.v only.
    g._prewrite_attestation(tmp_path, out)

    # A late runner-emitted netlist appears AFTER the summary.
    (synth / "chip_top_synth.v").write_text("module late;\nendmodule\n")
    verdict_stale, findings_stale = gate.audit(tmp_path)
    assert verdict_stale == "FAIL"
    assert any(f.rule == "MISSING_ATTESTATION" for f in findings_stale)

    # Regenerate-at-audit-time: pre-write refreshes the table.
    g._prewrite_attestation(tmp_path, out)
    verdict_fresh, findings_fresh = gate.audit(tmp_path)
    assert verdict_fresh == "PASS", findings_fresh
    assert not findings_fresh


def test_prewrite_table_covers_all_runner_emitted_netlists(tmp_path):
    """The pre-written table must carry the sha256 of every late
    netlist named in the issue (synth, $_DLATCH techmap, PnR)."""
    import hashlib
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    files = {
        synth / "chip_top_synth.v": "module a;\nendmodule\n",
        synth / "_dlatch_map.v": "module b;\nendmodule\n",
        pnr / "chip_top_pnr.v": "module c;\nendmodule\n",
    }
    for p, txt in files.items():
        p.write_text(txt)
    out = _pl.report_path(tmp_path, "final_summary.md")
    g._prewrite_attestation(tmp_path, out)
    text = out.read_text()
    for p, txt in files.items():
        digest = hashlib.sha256(txt.encode()).hexdigest()
        assert f"sha256:{digest}" in text, f"missing attestation for {p.name}"


def test_full_generator_with_audit_attestation_passes_on_late_netlist(tmp_path):
    """FIXED PATH end-to-end: running the generator WITH the internal
    audit on a project that ships a runner-emitted netlist leaves the
    attestation gate PASSing (the pre-write fires before the audit)."""
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "chip_top_synth.v").write_text(
        "module foo;\n DFFRQD1 ff1 (.CK(c),.D(d),.Q(q));\nendmodule\n")
    r = _run([str(tmp_path)])  # audit ENABLED (no --no-audit)
    assert r.returncode == 0, r.stderr
    verdict, findings = gate.audit(tmp_path)
    assert verdict == "PASS", findings


def test_prewrite_skipped_when_no_audit_regression(tmp_path):
    """REGRESSION GUARD: with --no-audit the internal audit never runs,
    so the (slower) pre-write is unnecessary; the report still
    generates and still carries the attestation table for whatever is
    on disk. Prior correct behavior must be preserved."""
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "chip_top_synth.v").write_text("module x;\nendmodule\n")
    r = _run([str(tmp_path), "--no-audit"])
    assert r.returncode == 0
    text = _summary_text(tmp_path)
    assert "## SHA-256 Attestation" in text
    assert "chip_top_synth.v" in text


# ────────────────────────────────────────────────────────────────────
# Symptom (2) — single counts snapshot, no conflicting numbers
# ────────────────────────────────────────────────────────────────────

def test_counts_snapshot_single_definition():
    """FIXED PATH: executed_pass == PASS + VACUOUS-PASS and
    executed_total == total − waived − skipped, matching the audit
    summary line. One snapshot, one definition."""
    rollup = {"PASS": 30, "VACUOUS-PASS": 4, "WAIVED-DEFERRED": 2,
              "SKIPPED-CONDITION": 5, "FAIL": 0, "MISSING": 1}
    total = 42
    snap = g._counts_snapshot(rollup, total)
    assert snap["executed_pass"] == 30 + 4
    assert snap["executed_total"] == 42 - 2 - 5
    assert snap["pass_only"] == 30
    assert snap["total_steps"] == 42


def test_report_has_one_executed_pass_value_everywhere(tmp_path):
    """FIXED PATH: the headline verdict block and the resource log must
    print the SAME executed-PASS fraction (no headline-vs-prose-vs-log
    divergence). We render with the audit so the rollup is real, then
    assert the two distinct count sites agree."""
    # Empty project → audit produces a deterministic rollup; both count
    # sites must quote the identical executed_pass/executed_total.
    r = _run([str(tmp_path)])
    assert r.returncode == 0
    text = _summary_text(tmp_path)
    import re
    # Verdict block:  "executed PASS = E/T,"
    m_head = re.search(r"executed PASS = (\d+)/(\d+),", text)
    # Resource log:   "executed PASS: **E/T**"
    m_log = re.search(r"executed PASS:\s+\*\*(\d+)/(\d+)\*\*", text)
    assert m_head is not None, "verdict-block executed-PASS fraction missing"
    assert m_log is not None, "resource-log executed-PASS fraction missing"
    assert m_head.groups() == m_log.groups(), (
        f"conflicting counts: verdict={m_head.groups()} "
        f"resource-log={m_log.groups()}")


def test_snapshot_marker_present(tmp_path):
    """FIXED PATH: a snapshot marker (timestamp + audit digest) is
    stamped beside the verdict so a reader knows the counts are a
    point-in-time snapshot."""
    r = _run([str(tmp_path)])
    assert r.returncode == 0
    text = _summary_text(tmp_path)
    assert "snapshot " in text and "audit-digest sha256:" in text


def test_snapshot_marker_deterministic_for_same_audit():
    """The marker's audit-digest is a pure function of the audit text +
    verdict (timestamp aside), so equal audits yield equal digests."""
    a = g._snapshot_marker("Overall: PASS\nSteps: 1/1", "PASS")
    b = g._snapshot_marker("Overall: PASS\nSteps: 1/1", "PASS")
    da = a.split("audit-digest sha256:")[1].split(" ")[0]
    db = b.split("audit-digest sha256:")[1].split(" ")[0]
    assert da == db
    c = g._snapshot_marker("Overall: FAIL\nSteps: 0/1", "FAIL")
    dc = c.split("audit-digest sha256:")[1].split(" ")[0]
    assert dc != da


# ────────────────────────────────────────────────────────────────────
# Symptom (3) — ic_name read from the canonical phase1 location
# ────────────────────────────────────────────────────────────────────

def test_ic_name_read_from_canonical_phase1_path(tmp_path):
    """FIXED PATH: ic_name lands in the report when L1_DATASHEET.json
    is at the canonical phase1/generated_docs/ location."""
    gd = _pl.generated_docs_dir(tmp_path)
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps(
        {"ic_name": "SYNTH_PART_42"}))
    r = _run([str(tmp_path), "--no-audit"])
    assert r.returncode == 0
    text = _summary_text(tmp_path)
    assert "SYNTH_PART_42" in text
    assert "(unknown — fill in via L1_DATASHEET.json[ic_name])" not in text


def test_ic_name_legacy_flat_path_still_supported(tmp_path):
    """REGRESSION GUARD: the prior flat `generated_docs/` location must
    still be honored as a fallback so legacy trees keep working."""
    flat = tmp_path / "generated_docs"
    flat.mkdir(parents=True)
    (flat / "L1_DATASHEET.json").write_text(json.dumps(
        {"part_number": "LEGACY_PART_7"}))
    r = _run([str(tmp_path), "--no-audit"])
    assert r.returncode == 0
    assert "LEGACY_PART_7" in _summary_text(tmp_path)


def test_ic_name_placeholder_when_genuinely_absent(tmp_path):
    """REGRESSION GUARD: the placeholder still appears when NO L doc
    supplies an ic_name (the empty-project / corpus-sweep condition)."""
    r = _run([str(tmp_path), "--no-audit"])
    assert r.returncode == 0
    assert "(unknown — fill in via L1_DATASHEET.json[ic_name])" in _summary_text(tmp_path)


# ────────────────────────────────────────────────────────────────────
# Symptom (4) — A1-A9 presence table mirrors the compliance checkers
# ────────────────────────────────────────────────────────────────────

def test_a4_presence_matches_compliance_checker_path(tmp_path):
    """FIXED PATH: the A4 corner-sweep artefact lives where the
    compliance checker (analog_a4_corner_sweep_check.py) looks for it —
    phase3/analog/<block>/corner_results.json. The presence grid must
    register it (prior code looked under phase2/analog/, so the cell
    read '—' while the gate PASSed)."""
    analog = tmp_path / "phase3" / "analog"
    (analog / "blk0").mkdir(parents=True)
    (analog / "analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": "blk0"}]}))
    # A4 artefact at the CHECKER's canonical path.
    (analog / "blk0" / "corner_results.json").write_text(json.dumps(
        {"corners": [{"name": "tt", "simulator_run": True}]}))
    grid = g._gather_analog_block_grid(tmp_path, ["blk0"])
    assert grid["blk0"]["A4"] is True

    # And the rendered report shows a ✅ in the blk0 row (not all '—').
    r = _run([str(tmp_path), "--no-audit"])
    assert r.returncode == 0
    text = _summary_text(tmp_path)
    blk_rows = [ln for ln in text.splitlines() if "`blk0`" in ln and "|" in ln]
    grid_row = [ln for ln in blk_rows if "✅" in ln]
    assert grid_row, f"blk0 A1-A9 row has no ✅; rows: {blk_rows}"


def test_analog_a_step_paths_match_checker_roots(tmp_path):
    """FIXED PATH: every A-step candidate path must root under
    phase3/analog/<block>/ (or phase3/analog/hardmacro/<block>/ for A8),
    mirroring the per-block checkers. This is the single-source guard
    that catches future drift back to the phase1/phase2 split."""
    paths = g._analog_a_step_paths(tmp_path, "blkX")
    p3 = str(tmp_path / "phase3" / "analog" / "blkX")
    p3_hm = str(tmp_path / "phase3" / "analog" / "hardmacro" / "blkX")
    for step in ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A9"):
        canonical = [p for p in paths[step] if str(p).startswith(p3)]
        assert canonical, f"{step} has no phase3/analog/blkX candidate"
    # A8 hardmacro lives under phase3/analog/hardmacro/<block>/; its
    # candidates are produced by globbing that dir.
    (tmp_path / "phase3" / "analog" / "hardmacro" / "blkX").mkdir(parents=True)
    (tmp_path / "phase3" / "analog" / "hardmacro" / "blkX" / "x.lef").write_text("LEF\n")
    paths2 = g._analog_a_step_paths(tmp_path, "blkX")
    assert any(str(p).startswith(p3_hm) for p in paths2["A8"])
    # NONE of the candidates may use the abandoned phase1/phase2 split.
    for step, ps in paths.items():
        for p in ps:
            assert "phase1/analog" not in str(p), f"{step} still probes phase1/analog"
            assert "phase2/analog" not in str(p), f"{step} still probes phase2/analog"


def test_legacy_root_analog_dir_still_supported(tmp_path):
    """REGRESSION GUARD: the legacy v1 root-level analog/<block>/ layout
    (the A6 checker's _block_dir fallback) must still be recognized."""
    (tmp_path / "phase3" / "analog").mkdir(parents=True)
    (tmp_path / "phase3" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": ["blkL"]}))
    legacy = tmp_path / "analog" / "blkL"
    legacy.mkdir(parents=True)
    (legacy / "spec.json").write_text(json.dumps({"spec": "x"}))
    grid = g._gather_analog_block_grid(tmp_path, ["blkL"])
    assert grid["blkL"]["A1"] is True


def test_no_analog_means_empty_grid_regression(tmp_path):
    """REGRESSION GUARD: a pure-digital project (no analog_block_list)
    must still produce the digital-only message, never crash."""
    r = _run([str(tmp_path), "--no-audit"])
    assert r.returncode == 0
    text = _summary_text(tmp_path)
    assert "pure-digital project" in text or "analog track not run" in text


# ────────────────────────────────────────────────────────────────────
# Cross-cutting regression: chip-agnostic + canonical sections intact
# ────────────────────────────────────────────────────────────────────

def test_generator_output_still_chip_agnostic(tmp_path):
    """REGRESSION GUARD (corpus-sweep condition): the generator's OWN
    output on an empty project must name no IC / vendor / SKU."""
    r = _run([str(tmp_path), "--no-audit"])
    assert r.returncode == 0
    text = _summary_text(tmp_path)
    forbidden = ["EXAMPLE_CHIP", "Apple", "Lightning", "byte[6]", "0xF2",
                 "bandgap", "VBG", "tsmc", "sky130"]
    leaked = [w for w in forbidden if w in text]
    assert not leaked, f"chip-specific terms leaked: {leaked}"


def test_canonical_sections_intact(tmp_path):
    """REGRESSION GUARD: all canonical sections still render."""
    r = _run([str(tmp_path), "--no-audit"])
    assert r.returncode == 0
    text = _summary_text(tmp_path)
    for sec in ("## Verdict", "## Stage breakdown",
                "## SHA-256 Attestation", "## Self-attestation",
                "## Chip-specific addendum"):
        assert sec in text, f"missing section {sec}"
