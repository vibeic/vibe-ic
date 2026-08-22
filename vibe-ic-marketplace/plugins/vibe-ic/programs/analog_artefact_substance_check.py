#!/usr/bin/env python3
"""
analog_artefact_substance_check.py — catch substance-less analog
deliverables that pass `analog_per_block_pv_completeness_check` and
`analog_hardmacro_check` on file-presence alone.

Real-world inspiration: phase2+3_v10627 shipped 8 analog blocks each
with the full per-block deliverable set (spec/topology/.sp/corners/
layout.mag/.gds/drc_clean.flag/lvs_match.flag/pre_vs_post.json) AND
the 4-file hardmacro (.gds/.lef/.lib/.v) — both presence-only gates
went green. But every `<block>.gds` was a 64-byte HEADER+ENDLIB stub
with zero cells inside, and the agent itself marked the .v files
`attestation_kind: ai_authored_methodology_stub`. The presence gates
gave a false positive; the v1.6.27 audit reported PASS=49 with
4.1 MB of nominal "8 hardmacros" that contained almost no real bits.

Two failure modes (chip-AGNOSTIC, conservative thresholds):

1. **STUB_FILE_TOO_SMALL** — analog deliverables below per-type
   minimum size. Defaults are intentionally low so that a real
   single-transistor block still passes:
     `<block>.gds`           ≥ 200 bytes  (a 64-byte HEADER+ENDLIB
                                           stub trips; a 1-cell GDS
                                           with even a single
                                           BOUNDARY record clears
                                           ~250 bytes)
     `<block>.lef`           ≥ 250 bytes
     `<block>.lib`           ≥ 200 bytes
     `<block>.v`             ≥ 150 bytes
     `<block>.sp`            ≥ 200 bytes  (a placeholder
                                           `* netlist stub\n.end\n`
                                           is < 50 bytes)

2. **AI_STUB_SELF_DECLARED** — file content contains the
   `ai_authored_methodology_stub` self-marker the v10627 agent
   wrote into every stub it produced. Honesty preserved (the agent
   labelled its own stubs); this gate just bubbles the signal up
   from the artefact into the project verdict so an audit can't
   accidentally treat it as a real deliverable.

VACUOUS_PASS: no `analog/analog_block_list.json` or empty blocks
list → digital-only project, gate inapplicable.

Usage:
    python3 analog_artefact_substance_check.py <project_dir>
                                                [--json <out>]
                                                [--min-gds-bytes N]
                                                [--allow-stub-marker]

Exit codes:
    0  PASS / VACUOUS_PASS
    1  one or more analog deliverables are stubs
    2  argument or I/O error

chip-AGNOSTIC. Per-type byte thresholds + stub-marker substring are
the only gating criteria; no chip / vendor / specific block-name
hardcoded.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


# Per-extension minimum file size in bytes. Conservative — a real
# single-transistor analog block trivially clears these thresholds.
_MIN_BYTES_BY_EXT: Dict[str, int] = {
    ".gds": 200,
    ".lef": 250,
    ".lib": 200,
    ".v":   150,
    ".sp":  200,
}

# Self-declared stub markers. v10627 used a single stable identifier;
# v1.6.30 generalises to a panel because a future agent could pick a
# different label (`placeholder`, `TODO implement`, etc.). Substring
# match is case-INsensitive on the lowercased file text. Markers are
# listed lower-cased here. Override / extend at the CLI via
# --stub-markers / --extra-stub-markers.
_STUB_MARKER = "ai_authored_methodology_stub"  # legacy name; first entry
_STUB_MARKERS_DEFAULT: tuple = (
    "ai_authored_methodology_stub",     # v10627 honest self-marker
    "ai_authored_stub",                 # likely shorthand variant
    "methodology_stub",
    "methodology placeholder",
    "behavioral stub",                  # hand-typed analog stand-in
    "behavioural stub",                 # en_GB spelling
    "placeholder netlist",
    "placeholder layout",
    "placeholder hardmacro",
    "stub: do not tape out",
    "do not tape out",                  # generic foundry-block flag
    "todo implement",                   # half-implemented file
    "todo: implement",
    "__stub__",
    "@stub",                            # python/javadoc-style marker
)


@dataclass
class StubFinding:
    block: str
    rel_path: str
    size_bytes: int
    rule: str       # STUB_FILE_TOO_SMALL / AI_STUB_SELF_DECLARED
    detail: str = ""


def _load_block_list(project: Path) -> Optional[List[str]]:
    path = project / "phase3" / "analog" / "analog_block_list.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    blocks = data.get("blocks") or []
    out: List[str] = []
    for entry in blocks:
        if isinstance(entry, str) and entry:
            out.append(entry)
        elif isinstance(entry, dict):
            name = entry.get("name") or entry.get("block")
            if isinstance(name, str) and name:
                out.append(name)
    return out


def _candidate_paths(project: Path, block: str) -> List[Path]:
    """Per-block files this gate inspects across A1-A8 deliverable
    locations: per-block dir + hardmacro dir."""
    bdir = project / "phase3" / "analog" / block
    hdir = project / "phase3" / "analog" / "hardmacro" / block
    out: List[Path] = []
    for stem_dir, exts in (
        (bdir, (".gds", ".sp")),
        (hdir, (".gds", ".lef", ".lib", ".v")),
    ):
        for ext in exts:
            p = stem_dir / f"{block}{ext}"
            if p.exists():
                out.append(p)
    return out


def _check_file(project: Path, block: str, path: Path,
                min_size_overrides: Optional[Dict[str, int]] = None,
                allow_stub_marker: bool = False,
                stub_markers: Optional[Tuple[str, ...]] = None
                ) -> List[StubFinding]:
    """Return findings for a single file (size + stub-marker checks).

    Resolves symlinks: a symlink to a valid file is treated as the
    file. A broken symlink is treated as size-0 (will fail size check)."""
    findings: List[StubFinding] = []
    real = path.resolve() if path.is_symlink() else path
    rel = path.relative_to(project)
    try:
        size = real.stat().st_size if real.exists() else 0
    except OSError:
        size = 0
    ext = path.suffix
    min_bytes = (min_size_overrides or {}).get(ext, _MIN_BYTES_BY_EXT.get(ext, 0))
    if size < min_bytes:
        findings.append(StubFinding(
            block=block, rel_path=str(rel), size_bytes=size,
            rule="STUB_FILE_TOO_SMALL",
            detail=f"{size} bytes < min {min_bytes} for {ext}"))
    if not allow_stub_marker:
        # Read the file's text content for any marker. Binary files
        # (.gds) read as `errors='replace'` so substring search is
        # well-defined; markers typically appear in comment-bearing
        # text files (.v / .sp / .lef / .lib) but the search is
        # uniform across all extensions.
        markers = stub_markers if stub_markers is not None else _STUB_MARKERS_DEFAULT
        try:
            text = real.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            text = ""
        hits = [m for m in markers if m in text]
        if hits:
            findings.append(StubFinding(
                block=block, rel_path=str(rel), size_bytes=size,
                rule="AI_STUB_SELF_DECLARED",
                detail=f"file matches stub marker(s): {', '.join(hits)}"))
    return findings


def audit(project: Path,
          min_size_overrides: Optional[Dict[str, int]] = None,
          allow_stub_marker: bool = False,
          stub_markers: Optional[Tuple[str, ...]] = None
          ) -> Tuple[str, List[StubFinding]]:
    blocks = _load_block_list(project)
    if blocks is None or not blocks:
        return "VACUOUS_PASS", []
    findings: List[StubFinding] = []
    for block in blocks:
        for path in _candidate_paths(project, block):
            findings.extend(_check_file(
                project, block, path,
                min_size_overrides=min_size_overrides,
                allow_stub_marker=allow_stub_marker,
                stub_markers=stub_markers))
    return ("FAIL" if findings else "PASS"), findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Catch substance-less analog deliverables (stub files).")
    ap.add_argument("project_dir")
    ap.add_argument("--json", help="write JSON report to this path")
    ap.add_argument("--min-gds-bytes", type=int,
                    help="override the .gds size threshold (default "
                         f"{_MIN_BYTES_BY_EXT['.gds']})")
    ap.add_argument("--allow-stub-marker", action="store_true",
                    help="skip ALL stub-marker substring checks "
                         "(size-only mode)")
    ap.add_argument("--stub-markers",
                    help="comma-separated REPLACEMENT list of stub "
                         "markers (overrides the built-in panel). "
                         "Lower-cased substring match.")
    ap.add_argument("--extra-stub-markers",
                    help="comma-separated ADDITIONS to the built-in "
                         "stub-marker panel (lower-cased substring).")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"error: project dir not found: {project}", file=sys.stderr)
        return 2

    overrides: Dict[str, int] = {}
    if args.min_gds_bytes is not None:
        overrides[".gds"] = args.min_gds_bytes

    if args.stub_markers:
        markers: Tuple[str, ...] = tuple(
            m.strip().lower() for m in args.stub_markers.split(",")
            if m.strip())
    else:
        markers = _STUB_MARKERS_DEFAULT
    if args.extra_stub_markers:
        markers = markers + tuple(
            m.strip().lower() for m in args.extra_stub_markers.split(",")
            if m.strip())

    verdict, findings = audit(
        project, min_size_overrides=overrides,
        allow_stub_marker=args.allow_stub_marker,
        stub_markers=markers)

    report = {
        "gate": "analog_artefact_substance_check",
        "verdict": verdict,
        "project": str(project),
        "min_size_thresholds": {**_MIN_BYTES_BY_EXT, **overrides},
        "stub_markers": list(markers) if not args.allow_stub_marker else None,
        "findings_count": len(findings),
        "findings": [asdict(f) for f in findings],
    }
    if verdict == "VACUOUS_PASS":
        report["reason"] = ("phase3/analog/analog_block_list.json missing or "
                            "empty; gate inapplicable.")

    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out_path, json.dumps(report, indent=2) + "\n")

    if verdict == "VACUOUS_PASS":
        print(f"VACUOUS_PASS: {report['reason']}")
        return 0
    if verdict == "PASS":
        print(f"PASS: every analog deliverable clears the per-extension "
              f"substance threshold; no stub-marker hits.")
        return 0
    print(f"FAIL: {len(findings)} substance-less analog deliverable(s):",
          file=sys.stderr)
    for f in findings[:12]:
        print(f"  [{f.block}] {f.rel_path} ({f.size_bytes}B): "
              f"{f.rule} — {f.detail}", file=sys.stderr)
    if len(findings) > 12:
        print(f"  … and {len(findings) - 12} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
