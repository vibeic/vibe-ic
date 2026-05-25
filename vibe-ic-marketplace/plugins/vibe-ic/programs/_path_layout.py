#!/usr/bin/env python3
"""_path_layout.py — single source of truth for the project directory tree.

Phase-redesign branch — three Phase buckets defined by deliverable,
not by skill (see docs/architecture/RFC_v2.0_PHASE_REDESIGN.md):

  Phase 1 — structured spec (L1-L13 JSON) ← unified entry for both docs and dialogue
  Phase 2 — verified RTL + gate-level netlist + FPGA SOF
  Phase 3 — sign-off + tapeout + manufacturing (absorbs analog A5-A9, M1-M4, mfg)

  <project>/
  ├── input/                  raw vendor docs / OTP / PDK / prompt原文
  ├── reports/                human-readable summaries
  ├── waivers.json
  ├── provenance.jsonl
  ├── rig_topology.json
  │
  ├── phase1/                 結構化 spec (兩入口統一)
  │   ├── input_doc/          Path A：vendor docs verbatim extracts
  │   ├── input_prompt/       Path B：dialogue + fact-graph workspace
  │   ├── generated_docs/     L1.json … L13.json — UNIVERSAL HANDOFF
  │   ├── human_docs/         L*.md — human review
  │   ├── extraction_patterns.json
  │   ├── extraction_patterns.auto.json
  │   ├── completeness_check_config.json
  │   ├── ai_deep_review_patches.json
  │   └── analog/<block>/     A1 spec.json
  │
  ├── phase2/                 L1-L13 → verified netlist
  │   ├── stage1/             Steps 1-6: RTL gen + verification
  │   │   ├── rtl/
  │   │   ├── rtl.pre_gen_backup/
  │   │   ├── sim/
  │   │   ├── sim_full_stack/
  │   │   ├── formal/
  │   │   ├── tb/
  │   │   └── fpga/           Step 6 early prototype
  │   ├── stage2/             Steps 7-13: synth + DFT + LEC
  │   │   ├── constraints/
  │   │   ├── synth/
  │   │   └── dft/
  │   └── analog/<block>/     A2-A4 (topology / netlist / corner sweep)
  │
  └── phase3/                 sign-off → tapeout → manufacturing
      ├── stage3/             Steps 14-30: physical design + signoff
      │   ├── pnr/
      │   ├── cts/
      │   ├── extracted/      parasitics (SPEF)
      │   ├── eco/
      │   ├── spice/          post-layout SPICE correlation
      │   ├── sta/            post-route STA
      │   └── sim_postlayout/
      ├── stage4/             Steps 31-36: tapeout
      │   ├── gds/            final GDS
      │   ├── foundry_handoff/
      │   └── fpga/           Step 36 final on-board re-test
      ├── stage5_manufacturing/  Steps 37-40: fab / sort / packaging / final test
      ├── analog/             A5-A9 (layout / PV / resim / hardmacro / cosim)
      │   ├── <block>/        layout.mag / drc_clean.flag / lvs_match.flag / pre_vs_post.json
      │   └── hardmacro/<block>/  A8: lef + lib + gds + v
      └── mixed_signal/       M1-M4
          ├── <reports>       merge / power_domain / level_shifter / ...
          └── cosim/          AMS co-sim outputs

Helpers below take a `project: Path` and return the canonical path. Only
the canonical layout is supported — pre-release plugin, no installed
user base, no migration window. Programs MUST use these helpers (not
hardcoded strings) when reading or writing artefacts in subdirectories.
"""
from __future__ import annotations

from pathlib import Path


# ─── phase1 ──────────────────────────────────────────────────────────────

def phase1_dir(project: Path) -> Path:
    return project / "phase1"


def input_doc_dir(project: Path) -> Path:
    """Path A entry: verbatim extracts from vendor docs (was phase1/input_doc)."""
    return project / "phase1/input_doc"


def input_prompt_dir(project: Path) -> Path:
    """Path B entry: dialogue transcript + fact-graph workspace."""
    return project / "phase1/input_prompt"


def generated_docs_dir(project: Path) -> Path:
    """L1.json … L13.json — universal handoff to Phase 2."""
    return project / "phase1/generated_docs"


def human_docs_dir(project: Path) -> Path:
    """L*.md — human review counterpart to generated_docs/."""
    return project / "phase1/human_docs"


# ─── phase2 ──────────────────────────────────────────────────────────────

def phase2_dir(project: Path) -> Path:
    return project / "phase2"


def phase2_stage1_dir(project: Path) -> Path:
    return project / "phase2/stage1"


def phase2_stage2_dir(project: Path) -> Path:
    return project / "phase2/stage2"


def rtl_dir(project: Path) -> Path:
    return project / "phase2/stage1/rtl"


def rtl_pre_gen_backup_dir(project: Path) -> Path:
    return project / "phase2/stage1/rtl.pre_gen_backup"


def sim_dir(project: Path) -> Path:
    return project / "phase2/stage1/sim"


def sim_full_stack_dir(project: Path) -> Path:
    return project / "phase2/stage1/sim_full_stack"


def formal_dir(project: Path) -> Path:
    return project / "phase2/stage1/formal"


def tb_dir(project: Path) -> Path:
    return project / "phase2/stage1/tb"


def fpga_early_dir(project: Path) -> Path:
    """Step 6: early FPGA prototype + on-board <half-duplex-tester> test (Phase 2)."""
    return project / "phase2/stage1/fpga"


def constraints_dir(project: Path) -> Path:
    return project / "phase2/stage2/constraints"


def synth_dir(project: Path) -> Path:
    return project / "phase2/stage2/synth"


def dft_dir(project: Path) -> Path:
    return project / "phase2/stage2/dft"


# ─── phase3 ──────────────────────────────────────────────────────────────

def phase3_dir(project: Path) -> Path:
    return project / "phase3"


def phase3_stage3_dir(project: Path) -> Path:
    return project / "phase3/stage3"


def phase3_stage4_dir(project: Path) -> Path:
    return project / "phase3/stage4"


def phase3_stage5_manufacturing_dir(project: Path) -> Path:
    """Steps 37-40: fab / wafer sort / packaging / final ATE."""
    return project / "phase3/stage5_manufacturing"


def phase3_mixed_signal_dir(project: Path) -> Path:
    return project / "phase3/mixed_signal"


def pnr_dir(project: Path) -> Path:
    return project / "phase3/stage3/pnr"


def cts_dir(project: Path) -> Path:
    return project / "phase3/stage3/cts"


def extracted_dir(project: Path) -> Path:
    """Parasitic extraction (SPEF)."""
    return project / "phase3/stage3/extracted"


def eco_dir(project: Path) -> Path:
    return project / "phase3/stage3/eco"


def spice_dir(project: Path) -> Path:
    return project / "phase3/stage3/spice"


def sta_dir(project: Path) -> Path:
    """Post-route STA. Pre-PnR STA is also written here."""
    return project / "phase3/stage3/sta"


def sim_postlayout_dir(project: Path) -> Path:
    return project / "phase3/stage3/sim_postlayout"


def mixed_signal_dir(project: Path) -> Path:
    return project / "phase3/mixed_signal"


def mixed_signal_cosim_dir(project: Path) -> Path:
    return project / "phase3/mixed_signal/cosim"


def gds_dir(project: Path) -> Path:
    return project / "phase3/stage4/gds"


def foundry_handoff_dir(project: Path) -> Path:
    return project / "phase3/stage4/foundry_handoff"


def fpga_final_dir(project: Path) -> Path:
    """Step 36: final FPGA recompile + on-board re-test (Phase 3 sign-off)."""
    return project / "phase3/stage4/fpga"


# ─── analog (distributed across phase1/2/3 per Layout P) ────────────────

def phase1_analog_block_dir(project: Path, block: str) -> Path:
    """A1 analog spec extraction outputs."""
    return project / "phase1/analog" / block


def phase2_analog_block_dir(project: Path, block: str) -> Path:
    """A2-A4 analog frontend (topology / netlist / corner sweep)."""
    return project / "phase2/analog" / block


def phase3_analog_block_dir(project: Path, block: str) -> Path:
    """A5-A9 analog backend (layout / PV / resim / hardmacro / cosim)."""
    return project / "phase3/analog" / block


def phase3_hardmacro_dir(project: Path) -> Path:
    """A8 packaged hardmacros (per-block lef/lib/gds/v)."""
    return project / "phase3/analog/hardmacro"


def phase3_hardmacro_block_dir(project: Path, block: str) -> Path:
    return project / "phase3/analog/hardmacro" / block


# Convenience aliases — most analog gates operate on backend artefacts
# (layout / DRC / LVS / hardmacro) which live under phase3/analog/.
# Callers that need A1 spec (phase1/analog/) or A2-A4 frontend
# (phase2/analog/) must use the phase-specific helpers above.
def analog_dir(project: Path) -> Path:
    """Default analog root — phase3 (where layout / PV / hardmacro live)."""
    return project / "phase3/analog"


def analog_block_dir(project: Path, block: str) -> Path:
    """Default per-block analog dir — phase3 (A5-A9 outputs).
    For A1 spec use phase1_analog_block_dir; for A2-A4 use phase2_analog_block_dir."""
    return project / "phase3/analog" / block


def hardmacro_dir(project: Path) -> Path:
    """A8 packaged hardmacros — phase3/analog/hardmacro/."""
    return project / "phase3/analog/hardmacro"


# ─── phase1 metadata files (live INSIDE phase1/, not at project root) ────

def phase1_extraction_patterns_file(project: Path) -> Path:
    return project / "phase1/extraction_patterns.json"


def phase1_extraction_patterns_auto_file(project: Path) -> Path:
    return project / "phase1/extraction_patterns.auto.json"


def phase1_completeness_check_config_file(project: Path) -> Path:
    return project / "phase1/completeness_check_config.json"


def phase1_ai_deep_review_patches_file(project: Path) -> Path:
    return project / "phase1/ai_deep_review_patches.json"


# ─── reports ─────────────────────────────────────────────────────────────

def reports_dir(project: Path) -> Path:
    return project / "reports"


# `reports/` is partitioned into phase-aligned subfolders. Programs MUST
# write into the correct subfolder via `report_path()` (auto-routes by
# filename) or via a specific `reports_<phase>_dir()` helper. Top-level
# flat reports/ files are not allowed (except the two whitelisted root
# files); the `reports_subfolder_taxonomy_check` gate enforces this.

def reports_phase1_dir(project: Path) -> Path:
    return project / "reports/phase1"


def reports_phase2_dir(project: Path) -> Path:
    return project / "reports/phase2"


def reports_phase3_dir(project: Path) -> Path:
    return project / "reports/phase3"


def reports_audit_dir(project: Path) -> Path:
    return project / "reports/audit"


def reports_orchestrator_dir(project: Path) -> Path:
    return project / "reports/orchestrator"


def run_logs_dir(project: Path) -> Path:
    """Cross-phase orchestrator logs (full_flow.log, audit_final.log,
    phase{1,2,3,23}.log, etc.). Lives under reports/orchestrator/logs."""
    return project / "reports/orchestrator/logs"


# Category map: filename (or filename glob suffix) → reports subfolder.
# Used by `report_path()` to auto-route a flat report filename into the
# right phase subfolder. Keys are matched in order: exact match first,
# then suffix prefix match, then by-extension default.

_REPORT_CATEGORY: dict = {
    # Phase 1 (was phase1)
    "extraction_coverage_report.json": "phase1",
    "extraction_coverage_report.md": "phase1",
    "phase1_input_vs_generated_completeness.json": "phase1",
    "phase1_input_vs_generated_completeness.md": "phase1",
    # Phase 2 (was phase2)
    "synth_netlist.json": "phase2",
    "sdc_check.json": "phase2",
    "md905_test.json": "phase2",
    "test_cases.json": "phase2",
    "rtl_bugs.json": "phase2",
    "bringup_plan.md": "phase2",
    # Phase 3
    "antenna.rpt": "phase3",
    "antenna.json": "phase3",
    "drc_router.json": "phase3",
    "drc_signoff.json": "phase3",
    "drc_signoff.rpt": "phase3",
    "em.json": "phase3",
    "em.rpt": "phase3",
    "erc.rpt": "phase3",
    "foundry_handoff_audit.json": "phase3",
    "gds_size.json": "phase3",
    "ir_drop.json": "phase3",
    "ir_drop.rpt": "phase3",
    "lvs.json": "phase3",
    "lvs.rpt": "phase3",
    "power.json": "phase3",
    "power.rpt": "phase3",
    "si_crosstalk.json": "phase3",
    "si_crosstalk.rpt": "phase3",
    "spice_correlation.json": "phase3",
    "density.json": "phase3",
    "density.rpt": "phase3",
    # debug_first_pass.py outputs — phase varies per step
    "drc_fix_first_pass.json": "phase3",
    "hold_fix_first_pass.json": "phase3",
    "ir_drop_triage_first_pass.json": "phase3",
    "lvs_triage_first_pass.json": "phase3",
    "ppa_predict_first_pass.json": "phase2",
    "sta_review_first_pass.json": "phase3",
    "synth_doctor_first_pass.json": "phase2",
    # Analog (distributed — default lands in phase3 since most analog
    # artefacts are layout/PV/hardmacro which live in phase3)
    "analog_one_shot.json": "phase3",
    # Audit (cross-phase verdicts + summaries)
    "flow_compliance.json": "audit",
    "flow_compliance_check.log": "audit",
    "fpga_signoff.json": "audit",
    "phase23_completion_audit.json": "audit",
    "tapeout_checklist.json": "audit",
    "FINAL_REPORT.md": "audit",
    # NOTE: `final_summary.md` and `chip_specific_summary.md` are NOT
    # in this map; they are special-cased in `report_path()` below to
    # land at `reports/` root (doctrine rule #3 location + the only
    # files `reports_subfolder_taxonomy_check` whitelists at root).
    # Orchestrator (one-shot runner JSON)
    "phase1_one_shot.json": "orchestrator",
    "phase2_one_shot.json": "orchestrator",
    "phase3_one_shot.json": "orchestrator",
    "phase23_one_shot.json": "orchestrator",
    "vibe_ic_one_shot.json": "orchestrator",
    "analog_flow_compliance.json": "orchestrator",
}

_REPORT_SUBDIR_CATEGORY: dict = {
    # Top-level reports/ subdirs that bucket many files, mapped to a
    # single phase parent.
    "cdc": "phase2",
    "coverage": "phase2",
    "dft": "phase2",
    "fpga": "phase2",
    "gates": "phase2",
    "lint": "phase2",
    "plugin_quality": "phase2",
    "doc_extract": "phase1",
    "pdf": "phase1",
    "phase1_presence.json": "phase1",
    "sta": "phase3",
    "pnr": "phase3",
    "mixed_signal": "phase3",
    "analog": "phase3",
    "signoff": "audit",
    "hardware": "audit",
}


def report_path(project: Path, filename: str) -> Path:
    """Auto-route a report filename into its phase-aligned subfolder.

    Examples:
        report_path(p, "synth_netlist.json")  → reports/phase2/synth_netlist.json
        report_path(p, "drc_signoff.rpt")     → reports/phase3/drc_signoff.rpt
        report_path(p, "final_summary.md")    → reports/final_summary.md       (root)
        report_path(p, "chip_specific_summary.md") → reports/chip_specific_summary.md
        report_path(p, "fpga/on_board_pass.json")
                                              → reports/phase2/fpga/on_board_pass.json

    Unknown filenames default to reports/audit/ (cross-phase fallback)
    so writers don't crash, but the `reports_subfolder_taxonomy_check`
    gate will surface unknowns at audit time.

    `final_summary.md` and `chip_specific_summary.md` are the two
    whitelisted root-level files per doctrine rule #3 +
    `reports_subfolder_taxonomy_check`. They land at `reports/`, not
    `reports/audit/`, which closes the producer-consumer mismatch where
    the auto-router was placing them where the gate could not find them.
    """
    if filename in REPORTS_VALID_ROOT_FILES:
        return reports_dir(project) / filename
    head, _, tail = filename.partition("/")
    if head in _REPORT_SUBDIR_CATEGORY:
        sub = _REPORT_SUBDIR_CATEGORY[head]
        return reports_dir(project) / sub / filename
    if filename in _REPORT_CATEGORY:
        return reports_dir(project) / _REPORT_CATEGORY[filename] / filename
    # Unknown → audit/ as safe default
    return reports_dir(project) / "audit" / filename


# Ordered list of valid reports/ children (for the taxonomy whitelist
# gate). Anything else under reports/ is a violation.
REPORTS_VALID_SUBDIRS: tuple = (
    "phase1", "phase2", "phase3", "audit", "orchestrator",
)

# The only two markdown files allowed at `reports/` root by
# `reports_subfolder_taxonomy_check`. Doctrine rule #3 ("reports/ root
# holds only final_summary.md + chip_specific_summary.md") + the
# attestation gate read them from this canonical location. Used by
# `report_path()` to bypass the bucket router for these two filenames.
REPORTS_VALID_ROOT_FILES: tuple = (
    "final_summary.md",
    "chip_specific_summary.md",
)


# Top-level whitelist (for the canonical-top-level enforcement gate).
TOP_LEVEL_VALID_DIRS: tuple = (
    "input", "phase1", "phase2", "phase3", "reports",
)
TOP_LEVEL_VALID_FILES: tuple = (
    "provenance.jsonl", "rig_topology.json", "waivers.json",
)


# Single shared helper that every one-shot runner calls right before
# its DONE banner. Generates the canonical `reports/final_summary.md`
# (chip-AGNOSTIC) by invoking `final_report_generate.py` as a
# subprocess. Best-effort: failure is logged but does NOT change the
# runner's verdict (the runner's own step audit is the source of truth;
# the summary is a derived view).
def emit_final_summary(project, programs_dir=None, timeout: int = 240) -> bool:
    """Run `final_report_generate.py` against `project` and return True
    on success, False on any failure (exception, missing tool, non-zero
    exit, timeout). Caller logs the True/False; do NOT use the return
    to gate the verdict — final report is a downstream artefact."""
    import subprocess  # local import: helper is rarely called
    import sys
    from pathlib import Path
    if programs_dir is None:
        programs_dir = Path(__file__).resolve().parent
    final_gen = Path(programs_dir) / "final_report_generate.py"
    if not final_gen.is_file():
        return False
    try:
        r = subprocess.run(
            [sys.executable, str(final_gen), str(project)],
            timeout=timeout, check=False,
            capture_output=True, text=True,
        )
        return r.returncode == 0
    except Exception:
        return False
