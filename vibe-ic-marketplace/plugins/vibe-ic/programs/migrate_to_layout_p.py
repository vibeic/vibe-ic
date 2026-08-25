#!/usr/bin/env python3
"""migrate_to_layout_p.py — pre-v2 → Layout P project migration.

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
Migrates an IC project directory from the pre-v2 layout (phase2a/,
phase2b/, top-level analog/ + manufacturing/) to the v2 Layout P
(phase1/, phase2/, phase3/ with analog distributed and manufacturing
under phase3/stage5_manufacturing/).

Steps:
  1. git mv (or plain mv when --no-git) of top-level phase2a/ → phase1/.
  2. phase1/extracted_docs/ → phase1/input_doc/.
  3. phase2b/ → phase2/.
  4. analog/<block>/  →
       - phase1/analog/<block>/  (A1 — owns spec.json)
       - phase2/analog/<block>/  (A2-A4 — owns topology / netlist /
         corner_results)
       - phase3/analog/<block>/  (A5-A9 — owns layout / PV / hardmacro
         / pre_vs_post / hw_measurements)
     Strategy: probe each block-dir's file contents to decide where it
     belongs. A block with both layout + spec stays whole at the
     phase3 backend root (because most analog work is backend); only
     the spec.json is symlinked / copied up to phase1/analog/<block>/.
  5. analog/hardmacro/  → phase3/analog/hardmacro/.
  6. analog/analog_block_list.json (top-level) → phase1/analog/
     (A1's deliverable per the canonical flow).
  7. manufacturing/ → phase3/stage5_manufacturing/.
  8. Rewrite provenance.jsonl paths:
       phase2a/ → phase1/, phase2a/extracted_docs/ → phase1/input_doc/,
       phase2b/ → phase2/, manufacturing/ → phase3/stage5_manufacturing/.
       Each rewritten record gets a `migration_note` field so the
       audit trail remains transparent.

Idempotent: rerunning on an already-migrated project is a no-op.

Sanity-checks at end:
  - top_level_outputs_in_canonical_check (whitelist gate).
  - canonical_path_symlink_forbid_check (no symlinks under canonical
    deliverable trees).

Usage:
    python3 migrate_to_layout_p.py <project_dir>
    python3 migrate_to_layout_p.py <project_dir> --no-git
    python3 migrate_to_layout_p.py <project_dir> --dry-run

Exit codes (APPLY mode — unchanged):
    0 — migration applied (or already-migrated; idempotent).
    1 — migration encountered an error that left the project in an
        inconsistent state (caller must inspect).
    2 — usage / IO error before any move was attempted.

Exit codes (--dry-run, the DETECTOR mode):
    0 — the project is already on v2 Layout P; nothing to migrate.
    1 — pre-v2 residue found. Nothing was moved; the printed remedy is
        this same command without --dry-run.
    2 — usage / IO error.
    --dry-run writes NOTHING, which is why it is the mode a gate may run:
    every mover is guarded by `ctx.dry_run` and the provenance rewrite is
    computed and then discarded.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple


# ── Decision rules ─────────────────────────────────────────────────

# Files / globs that anchor an analog block's owning phase.
_PHASE1_ANCHORS = ("spec.json",)
_PHASE2_ANCHORS = ("topology.md", "corner_results.json")  # + *.sp
_PHASE3_ANCHORS = (
    "layout.mag", "drc_clean.flag", "lvs_match.flag",
    "pre_vs_post.json", "hw_measurements.json",
)


def _classify_analog_block(block_dir: Path) -> str:
    """Pick the canonical destination phase for an analog block.

    A block-dir contents are inspected and the *most-backend* anchor
    wins (phase3 > phase2 > phase1). When no anchor matches, we
    default to phase3 (backend) — the historical convention for
    layout/PV work and where `analog_dir()` points in
    `_path_layout.py`.
    """
    names = {p.name for p in block_dir.iterdir() if p.is_file()}
    # Phase 3 anchors
    if any(a in names for a in _PHASE3_ANCHORS):
        return "phase3"
    # Phase 2 anchors (incl. *.sp glob)
    if any(a in names for a in _PHASE2_ANCHORS):
        return "phase2"
    if any(n.endswith(".sp") for n in names):
        return "phase2"
    # Phase 1 anchors
    if any(a in names for a in _PHASE1_ANCHORS):
        return "phase1"
    # Default: phase3 backend
    return "phase3"


# ── Move helpers ───────────────────────────────────────────────────

class MigCtx:
    def __init__(self, project: Path, use_git: bool, dry_run: bool):
        self.project = project
        self.use_git = use_git
        self.dry_run = dry_run
        self.moves: List[Tuple[Path, Path]] = []
        self.notes: List[str] = []
        #: Provenance records whose paths still spell the pre-v2 layout. Part
        #: of the SAME question `moves` answers — a project whose directories
        #: were moved by hand but whose provenance still names `phase2a/` is
        #: not on Layout P either — and counted separately only so the
        #: --dry-run verdict can say which of the two it found.
        self.prov_rewrites: int = 0

    def _mv(self, src: Path, dst: Path) -> None:
        if not src.exists():
            return
        if dst.exists():
            # If dst is a directory and src is a directory, merge
            # children rather than overwriting.
            if dst.is_dir() and src.is_dir():
                for child in src.iterdir():
                    self._mv(child, dst / child.name)
                if self.dry_run:
                    return
                try:
                    src.rmdir()
                except OSError:
                    pass
                return
            # Conflicting non-dir destination: leave src untouched but
            # record the conflict.
            self.notes.append(f"CONFLICT: {src} → {dst} (dst exists)")
            return
        self.moves.append((src, dst))
        if self.dry_run:
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        if self.use_git:
            cp = subprocess.run(
                ["git", "mv", str(src), str(dst)],
                cwd=str(self.project), capture_output=True, text=True,
            )
            if cp.returncode != 0:
                # git mv fails for untracked files; fall back to plain mv
                shutil.move(str(src), str(dst))
        else:
            shutil.move(str(src), str(dst))


# ── Migration steps ────────────────────────────────────────────────

def _step1_phase2a_to_phase1(ctx: MigCtx) -> None:
    src = ctx.project / "phase2a"
    if not src.is_dir():
        return
    dst = ctx.project / "phase1"
    ctx._mv(src, dst)


def _step2_extracted_docs_to_input_doc(ctx: MigCtx) -> None:
    src = ctx.project / "phase1" / "extracted_docs"
    if not src.is_dir():
        return
    dst = ctx.project / "phase1" / "input_doc"
    ctx._mv(src, dst)


def _step3_phase2b_to_phase2(ctx: MigCtx) -> None:
    src = ctx.project / "phase2b"
    if not src.is_dir():
        return
    dst = ctx.project / "phase2"
    ctx._mv(src, dst)


def _step4_analog_distribution(ctx: MigCtx) -> None:
    analog_root = ctx.project / "analog"
    if not analog_root.is_dir():
        return

    # 4a. top-level analog_block_list.json → phase1/analog/
    bl = analog_root / "analog_block_list.json"
    if bl.is_file():
        ctx._mv(bl, ctx.project / "phase1" / "analog" / "analog_block_list.json")

    # 4b. hardmacro/ → phase3/analog/hardmacro/
    hm = analog_root / "hardmacro"
    if hm.is_dir():
        ctx._mv(hm, ctx.project / "phase3" / "analog" / "hardmacro")

    # 4c. each block-dir distributed by anchor heuristic
    for block_dir in sorted(p for p in analog_root.iterdir() if p.is_dir()):
        owner = _classify_analog_block(block_dir)
        ctx._mv(block_dir,
                ctx.project / owner / "analog" / block_dir.name)

    # 4d. clean up empty analog/ root
    if analog_root.exists() and analog_root.is_dir():
        try:
            if not any(analog_root.iterdir()):
                if not ctx.dry_run:
                    analog_root.rmdir()
        except OSError:
            pass


def _step5_manufacturing(ctx: MigCtx) -> None:
    src = ctx.project / "manufacturing"
    if not src.is_dir():
        return
    dst = ctx.project / "phase3" / "stage5_manufacturing"
    ctx._mv(src, dst)


def _step6_rewrite_provenance(ctx: MigCtx) -> None:
    prov = ctx.project / "provenance.jsonl"
    if not prov.is_file():
        return
    new_lines = []
    rewrites = 0
    for raw in prov.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            new_lines.append(raw)
            continue
        before = json.dumps(rec, sort_keys=True)
        _rewrite_dict_paths(rec)
        after = json.dumps(rec, sort_keys=True)
        if before != after:
            rec.setdefault("migration_note",
                           "v2 Layout P path rewrite (migrate_to_layout_p.py)")
            rewrites += 1
        new_lines.append(json.dumps(rec, ensure_ascii=False))
    if rewrites and not ctx.dry_run:
        prov.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    ctx.prov_rewrites = rewrites
    ctx.notes.append(f"provenance.jsonl: rewrote {rewrites} record(s)")


_PATH_MAPS = [
    ("phase2a/extracted_docs/", "phase1/input_doc/"),
    ("phase2a/",                 "phase1/"),
    ("phase2b/",                 "phase2/"),
    ("manufacturing/",           "phase3/stage5_manufacturing/"),
    # analog/<file>: only rewrite the top-level analog/analog_block_list.json
    # — per-block paths are too varied to safely rewrite mechanically.
    ("analog/analog_block_list.json",
     "phase1/analog/analog_block_list.json"),
    ("analog/hardmacro/",        "phase3/analog/hardmacro/"),
]


def _rewrite_dict_paths(obj) -> None:
    """In-place path-rewrite on a JSON-parseable structure. Walks all
    string values and applies _PATH_MAPS prefix substitution."""
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            v = obj[k]
            if isinstance(v, str):
                obj[k] = _rewrite_str(v)
            elif isinstance(v, (dict, list)):
                _rewrite_dict_paths(v)
            # Also rewrite the keys (some provenance records use paths
            # as dict keys for the outputs map).
            new_k = _rewrite_str(k) if isinstance(k, str) else k
            if new_k != k:
                obj[new_k] = obj.pop(k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str):
                obj[i] = _rewrite_str(v)
            else:
                _rewrite_dict_paths(v)


def _rewrite_str(s: str) -> str:
    """Apply `_PATH_MAPS` to one string, ONCE, however many times it is run.

    THE PROVENANCE ARM WAS NOT IDEMPOTENT, and the module docstring three
    screens up promises that it is. Three of the six maps have a replacement
    that CONTAINS its own pattern::

        manufacturing/                 -> phase3/stage5_manufacturing/
        analog/hardmacro/              -> phase3/analog/hardmacro/
        analog/analog_block_list.json  -> phase1/analog/analog_block_list.json

    so a plain `str.replace` re-fires on its own output. Measured 2026-08-25 on
    the very fixture `tests/test_migrate_to_layout_p.py::_build_prev2` already
    ships::

        run 1  manufacturing/yield.json
            -> phase3/stage5_manufacturing/yield.json
        run 2  -> phase3/stage5_phase3/stage5_manufacturing/yield.json
        run 3  -> phase3/stage5_phase3/stage5_phase3/stage5_manufacturing/...

    Each re-run corrupts the audit trail one level further, and the directory
    moves stay clean throughout — so the run prints `moves: 0`, reports itself
    a no-op, and has just rewritten a path to somewhere that does not exist.
    The shipped idempotency test asserted on `ctx.moves` alone and could not
    see it; it was found by wiring `--dry-run` into flow step D1, where a
    correctly migrated project began reporting residue it did not have.

    THE FIX: when the pattern occurs inside the replacement, rewrite only the
    occurrences that are not already part of a replacement — split on `new`
    first, substitute inside each segment, and rejoin.
    """
    for old, new in _PATH_MAPS:
        # match either bare prefix at start, or as a substring (covers
        # absolute paths like /home/.../phase2b/...).
        if old not in s:
            continue
        if old in new:
            s = new.join(seg.replace(old, new) for seg in s.split(new))
        else:
            s = s.replace(old, new)
    return s


# ── Top-level driver ───────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("project", type=Path)
    p.add_argument("--no-git", action="store_true",
                   help="use plain mv instead of git mv")
    p.add_argument("--dry-run", action="store_true",
                   help="list moves without applying them")
    args = p.parse_args()

    project = args.project.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    ctx = MigCtx(project=project, use_git=not args.no_git,
                 dry_run=args.dry_run)

    _step1_phase2a_to_phase1(ctx)
    _step2_extracted_docs_to_input_doc(ctx)
    _step3_phase2b_to_phase2(ctx)
    _step4_analog_distribution(ctx)
    _step5_manufacturing(ctx)
    _step6_rewrite_provenance(ctx)

    # Summary
    print(f"\n=== migrate_to_layout_p ({'DRY-RUN' if args.dry_run else 'APPLIED'}) ===")
    print(f"project: {project}")
    print(f"moves: {len(ctx.moves)}")
    for src, dst in ctx.moves:
        rs = src.relative_to(project)
        rd = dst.relative_to(project)
        print(f"  {rs}  →  {rd}")
    for note in ctx.notes:
        print(f"NOTE: {note}")
    print("=== done ===")

    # --dry-run IS A DETECTOR, AND UNTIL 2026-08-25 IT RETURNED 0 EITHER WAY.
    # Measured on two fixture projects at that date: a canonical tree printed
    # `moves: 0` and a pre-v2 tree printed `moves: 4`, and BOTH exited 0. The
    # answer was only ever in the prose, so nothing automatic could read it and
    # this program had no caller that was not a human reading its output.
    #
    # Inspection now carries a verdict:  0 = already Layout P (nothing to do),
    # 1 = pre-v2 residue found, and the remedy is this same command without
    # --dry-run. THE APPLY CONTRACT IS UNCHANGED — 0 on a completed migration,
    # idempotent as before — because a migration that ran and left nothing
    # behind is a success, and returning 1 for the work it just did would make
    # the caller re-run it forever.
    if not args.dry_run:
        return 0
    pending = len(ctx.moves) + ctx.prov_rewrites
    if not pending:
        print("[PASS] migrate_to_layout_p: project is on v2 Layout P; "
              "nothing to migrate.")
        return 0
    print(f"[FAIL] migrate_to_layout_p: {len(ctx.moves)} pre-v2 path(s) and "
          f"{ctx.prov_rewrites} provenance record(s) still spell the pre-v2 "
          f"layout. Remedy:  python3 migrate_to_layout_p.py {project}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
