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

# The sidecar `rtl_transitive_cone.prune_to_cone` MOVES out-of-cone sources
# into: `<rtl_dir>_out_of_cone/` beside the staged tree (currently
# `phase2/stage1/rtl_out_of_cone/`). It is matched as a SUFFIX rather than by
# exact name because the sidecar is derived from whatever the staged RTL
# directory is called, and a second exact literal here would drift the moment
# that name changes.
#
# WHY IT MUST BE EXCLUDED (vibe-ic#781 L8): a file in there has been declared
# NOT PART OF THE BUILD SET. Leaving it in scope had project-root RTL gates
# still linting it as authoritative RTL — reporting findings against sources the
# flow does not compile, which is the exact contradiction "moved out of the
# build set" is supposed to remove. It is a MOVE, not a delete, so the files
# stay auditable and `--restore` puts them back in scope.
#
# THE RULE IS A PLAIN SUFFIX: a component ending in `_out_of_cone`. There is no
# "…but not when the component IS the suffix" carve-out any more — that made
# `analysis_out_of_cone/` excluded while a directory named exactly
# `_out_of_cone` was not, which is not a rule anyone can state (vibe-ic#781
# L-suffix). Breadth is acknowledged: any directory a user names `*_out_of_cone`
# is excluded too. That is a LINT-SCOPE policy only — the build set is the
# staged tree, decided by the filelist, never by this module — so the cost of
# breadth here is at worst an unlinted directory that says in its own name that
# it is not part of the cone.
EXCLUDED_DIR_SUFFIXES = ("_out_of_cone",)


def is_excluded_component(part: str) -> bool:
    """True when a single path component marks its subtree as non-authoritative
    (build/output dir, dot-dir, a sim/sim_*/input/oracle scratch dir, or the
    out-of-cone sidecar).

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
    if any(part.endswith(s) for s in EXCLUDED_DIR_SUFFIXES):
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
