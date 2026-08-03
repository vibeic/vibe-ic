#!/usr/bin/env python3
"""
rtl_scan_scope.py — shared authoritative-RTL scan-scope policy (ORGANIC #545).

THE PROBLEM
-----------
Structural gates that `project.rglob("*.sv")` from the project root swept up
files that are NOT flow products and must never be linted as authoritative
RTL:

  * `input/**` — STAGED VENDOR RTL (reused-IP closure). Linting it produced
    false positives whose only workaround was renaming unused vendor files.
  * runner-generated intermediates — `sim_full_stack/`, `oracle_run/`,
    `.fpga_stash/` (sv2v-flattened copies). These are regenerated every run,
    so moving them is not durable, and they tripped CDC / undriven false
    positives.

The old per-gate exclusion sets matched a path component by EXACT equality
(`'sim_full_stack' != 'sim'`) and did not exclude dot-dirs, so the
intermediates leaked back in.

THE POLICY (canonical, chip-AGNOSTIC)
-------------------------------------
Authoritative RTL = the flow's own emitted RTL (phase2/stage1/rtl/ + declared
glue), NOT staged vendor input or any build/sim/oracle intermediate. A path is
EXCLUDED when any of its directory components:

  * equals a build/output dir          (build, synth, pnr, gds, db, dft,
                                         reports, output_files, incremental_db,
                                         __pycache__, node_modules, formal)
  * starts with "."                    (dot-dirs: .git, .fpga_stash, ...)
  * starts with "sim"                  (sim, sim_full_stack, sim_work, ...)
  * equals "input" or "oracle_run"     (vendor staging / oracle scratch)

Component matching is PREFIX/equality on each component, never a single exact
whole-string compare — that is the #545 fix.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

# Directory components excluded by exact name (build / output / scratch dirs).
#
# `steps` is the flow's own PUBLICATION VIEW: `<project>/steps/<phase>/<stage>/
# <id>_<name>/` republishes each canonical step output under its flow-step id.
# Every file there is already in scope at its canonical location if it belongs
# in scope at all, so including the tree can only (a) duplicate a file that is
# already scanned or (b) admit a build OUTPUT whose canonical directory this
# very list excludes. Both happened, and the second one was expensive:
#
#     steps/phase2/stage2/9_synthesis_yosys_mapped_netlist/netlist.v
#     steps/phase2/stage2/14_synthesis_handoff_gate_pre_pnr_yosys_script_netl/netlist.v
#
# are the SAME emitted gate-level netlist published twice. The component
# `synth` in this set never matched them, because the publication view names
# the directory after the flow step (`9_synthesis_...`), not after the build
# dir. MEASURED on a 3.1M-cell design: this collector returned 9 files /
# 715,640,356 bytes where the design's RTL is 3 files / 12,499 bytes — a
# factor of 57,255. `cdc_async_input_check` then took 160.7 s / 3.5 GB RSS and
# `clock_domain_reg_crossing_check` 67.0 s / 3.5 GB, both TIMED OUT under the
# P0 umbrella's per-gate budget, and the P0 FAIL halted the flow at phase 2.
#
# It is also semantically wrong for these two consumers: CDC is a property of
# RTL clock-domain structure, and a flattened NAND/NOR/DFF netlist carries
# none of it. The gates were paying 57,000x to read a file that cannot answer
# the question they ask.
EXCLUDED_DIR_NAMES = frozenset({
    "build", "synth", "pnr", "gds", "db", "dft", "reports",
    "output_files", "incremental_db", "__pycache__", "node_modules",
    "formal", "oracle_run", "input", "steps",
})

def is_excluded_component(part: str) -> bool:
    """True when a single path component marks its subtree as non-authoritative
    (build/output dir, dot-dir, or a sim/sim_*/input/oracle scratch dir).

    The `sim` family is matched as exactly `sim` OR a `sim_<...>` prefix
    (sim_full_stack, sim_work) — NOT a bare `sim*` prefix, so an unrelated
    dir like `simba`/`similar` is not falsely excluded (the #545 exact-match
    fix must not over-correct into over-broad matching)."""
    if not part:
        return False
    if part.startswith("."):          # dot-dirs: .git, .fpga_stash, ...
        return True
    if part in EXCLUDED_DIR_NAMES:
        return True
    if part == "sim" or part.startswith("sim_"):
        return True
    return False


def is_excluded_rel(rel: Path) -> bool:
    """True when a project-relative path lies under an excluded directory."""
    # only the DIRECTORY components decide scope (the leaf filename does not).
    return any(is_excluded_component(p) for p in rel.parts[:-1])


def authoritative_rtl_files(project_dir: Path,
                            exts=("*.v", "*.sv")) -> List[Path]:
    """Return the authoritative-RTL file list under `project_dir`, applying the
    canonical scan-scope exclusions (#545). chip-AGNOSTIC."""
    out: List[Path] = []
    for ext in exts:
        for f in project_dir.rglob(ext):
            if not f.is_file():
                continue
            if is_excluded_rel(f.relative_to(project_dir)):
                continue
            out.append(f)
    return out
