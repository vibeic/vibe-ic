#!/usr/bin/env python3
"""
yosys_script_template_check.py — Audit a Yosys .ys script for the three
flags CLAUDE.md rule 4 requires on real-PDK synthesis:

    - ``-sv``       : SystemVerilog enabled on at least one read_verilog (or
                      the equivalent read_slang / read_sv invocation).
    - ``-flatten``  : hierarchy collapsed (either via ``synth -flatten`` or a
                      standalone ``flatten`` command after ``proc``/``opt``).
    - ``hilomap``   : constant 1'b0 / 1'b1 nets replaced by real PDK tie
                      cells. Missing this leads OpenROAD detailed_route into
                      DRT-0305 "zero_ GROUND" on a fresh-agent Phase-3 run.

This program is a static auditor — it does not invoke Yosys itself; it just
checks that the script an LLM emitted contains the three tokens. A companion
program (``yosys_hilomap_required_check.py``) enforces the ordering
constraint separately.

Usage:
    python3 yosys_script_template_check.py --ys-file scripts/synth.ys

Exit codes:
    0 — all three tokens present (or --simulation-only mode waives them)
    1 — one or more tokens missing; stderr lists which
    2 — argument or I/O error

Rationale: v068 fresh-agent agent wrote a synth.ys that omitted hilomap on
the first pass and only added it after detailed_route tripped DRT-0305. A
pre-synth gate would have caught this in seconds.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Tuple


def _strip_comments(lines: List[str]) -> List[str]:
    """Remove Yosys-style line comments (#) while keeping original line index.

    Yosys treats '#' as a line-comment marker starting the rest of the line.
    We drop the post-'#' segment but preserve the line slot so error messages
    can cite accurate line numbers.
    """
    out: List[str] = []
    for raw in lines:
        # Strip trailing newline but keep the line in the list
        line = raw.rstrip("\n")
        # Locate '#' that is NOT inside a quoted string. Yosys .ys files almost
        # never use quoted strings, so a flat search is fine.
        if "#" in line:
            line = line.split("#", 1)[0]
        out.append(line)
    return out


def _find_token(lines: List[str], token: str) -> List[int]:
    """Return 0-based line indices where *token* appears as a standalone
    command or argument (word-boundary, not substring-of-name)."""
    hits: List[int] = []
    for i, line in enumerate(lines):
        # Split into whitespace tokens; match exact equality
        words = line.strip().split()
        if token in words:
            hits.append(i)
            continue
        # Also allow token to appear mid-command as a flag, e.g. "synth -flatten"
        # The word-equality check above already covers that since split()
        # returns ["synth", "-flatten"].
    return hits


def audit(ys_path: str, simulation_only: bool = False,
          allow_no_sv: bool = False) -> Tuple[int, List[str]]:
    """Run the audit. Returns (exit_code, messages)."""
    if not os.path.exists(ys_path):
        return 2, [f"error: file not found: {ys_path}"]
    try:
        with open(ys_path, "r", encoding="utf-8", errors="replace") as f:
            raw_lines = f.readlines()
    except OSError as e:
        return 2, [f"error: cannot read {ys_path}: {e}"]

    lines = _strip_comments(raw_lines)

    missing: List[str] = []

    # v1.6.228 — skip non-synth .ys scripts. Genuine PDK synth scripts
    # issue at least one of {dfflibmap, abc, synth} as a Yosys COMMAND
    # (first non-whitespace token on a line). Flatten/post-process
    # scripts (e.g. FPGA-reverify pipeline emitted by
    # pdk_yosys_flatten_for_quartus) only do flatten/clean/rename and
    # shouldn't be audited for -sv / -flatten / hilomap. chip-AGNOSTIC.
    _synth_cmds = {"dfflibmap", "abc", "synth"}
    _is_synth = False
    for _ln in lines:
        _tok = _ln.split()
        if _tok and _tok[0] in _synth_cmds:
            _is_synth = True
            break
    if not _is_synth:
        return 0, [f"ok: {ys_path} is a non-synth post-process script — skipped"]

    # --- -sv flag -----------------------------------------------------------
    sv_hits = _find_token(lines, "-sv")
    # Also treat read_slang / read_systemverilog as satisfying -sv because
    # those command forms imply SV parsing without a flag.
    slang_hits = [i for i, line in enumerate(lines)
                  if "read_slang" in line or "read_systemverilog" in line]
    if not sv_hits and not slang_hits and not allow_no_sv:
        missing.append(
            "-sv: no '-sv' flag on any read_verilog (nor a read_slang / "
            "read_systemverilog command). CLAUDE.md rule 4 requires -sv for "
            "SystemVerilog RTL; rule 7 says run sv_compat_check first to "
            "confirm whether it is needed. Pass --allow-no-sv if the RTL is "
            "plain Verilog-2001 (sv_compat_check should have verified this)."
        )

    # --- -flatten / flatten -------------------------------------------------
    flatten_flag_hits = _find_token(lines, "-flatten")
    flatten_cmd_hits = _find_token(lines, "flatten")
    if not flatten_flag_hits and not flatten_cmd_hits:
        missing.append(
            "-flatten: neither 'synth -flatten' nor a standalone 'flatten' "
            "command found. Without flattening, hierarchical names bleed "
            "through and downstream OpenROAD / ATPG flows break on "
            "backslash-escaped paths."
        )

    # --- hilomap ------------------------------------------------------------
    hilomap_hits = _find_token(lines, "hilomap")
    if not hilomap_hits:
        missing.append(
            "hilomap: no 'hilomap' command found. CLAUDE.md rule 4 requires "
            "hilomap to map 1'b0/1'b1 to PDK tie cells; missing it causes "
            "OpenROAD detailed_route to trip DRT-0305 'zero_ GROUND'."
        )

    if simulation_only:
        # Simulation-only scripts don't need hilomap. We still require
        # -flatten for sim speed and -sv for SV support.
        missing = [m for m in missing if not m.startswith("hilomap:")]

    if missing:
        return 1, missing
    return 0, [f"ok: {ys_path} contains -sv, -flatten, hilomap"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Audit a Yosys .ys script for -sv, -flatten, and hilomap. "
            "CLAUDE.md rule 4 requires all three for real-PDK synthesis; "
            "missing hilomap trips OpenROAD detailed_route DRT-0305."
        )
    )
    # Wave 92 / v1.6.16 — accept `<project_dir> --json <out>` invocation
    # alongside legacy `--ys-file`.
    ap.add_argument("project_dir", nargs="?", default=None,
                    help="Project directory; auto-discovers *.ys scripts "
                         "under synth/, phase3/, scripts/. SKIP rc=2 if none.")
    ap.add_argument("--ys-file", default=None,
                    help="Path to a single Yosys .ys synthesis script.")
    ap.add_argument("--json", default=None,
                    help="Aggregate findings into a JSON report at this path.")
    ap.add_argument("--simulation-only", action="store_true",
                    help="Waive the hilomap requirement (sim-only scripts).")
    ap.add_argument("--allow-no-sv", action="store_true",
                    help=("Waive the -sv requirement (plain Verilog-2001 RTL "
                          "that sv_compat_check has verified needs no -sv)."))
    args = ap.parse_args(argv)

    if not args.project_dir and not args.ys_file:
        ap.error("either <project_dir> positional OR --ys-file is required")

    if args.ys_file:
        code, msgs = audit(args.ys_file,
                           simulation_only=args.simulation_only,
                           allow_no_sv=args.allow_no_sv)
        for m in msgs:
            print(m, file=sys.stderr if code else sys.stdout)
        if args.json:
            import json as _json
            from pathlib import Path as _Path
            out = _Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(_json.dumps(
                {"verdict": "PASS" if code == 0 else "FAIL",
                 "ys_file": args.ys_file, "messages": msgs},
                indent=2) + "\n")
        return code

    # Project-dir auto-discovery mode
    from pathlib import Path as _Path
    import json as _json
    project = _Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"error: project dir not found: {project}", file=sys.stderr)
        return 2
    ys_globs = ["phase2/stage2/synth/*.ys", "phase2/stage2/synth/**/*.ys",
                "phase3/synth/*.ys", "phase3/**/*.ys",
                "scripts/*.ys", "scripts/**/*.ys"]
    ys_files: list[str] = []
    for g in ys_globs:
        ys_files.extend(str(p) for p in project.glob(g))
    ys_files = sorted(set(ys_files))
    if not ys_files:
        # v1.6.180 (#72 P2-8) — confirm-or-flag the inline-mode case.
        # v1.7.64 — run the #649 CONTENT audit on the inline `yosys -p`
        # command first; only a NO_INLINE_COMMAND result falls through to
        # the weaker file-existence confirmer. NOTE: --simulation-only is
        # deliberately NOT consulted here. The inline audit classifies each
        # extracted command by whether it binds a Liberty library, which is
        # an objective property of the command yosys actually ran; letting a
        # caller-supplied flag waive a real-PDK command would reintroduce
        # exactly the bypass #649 closed.
        from _yosys_inline_mode_detect import resolve_no_ys_script
        rc, fields = resolve_no_ys_script(project)
        verdict = fields["verdict"]
        reason_text = fields["reason"]
        report = {
            "verdict": verdict,
            "reason_class": fields["reason_class"],
            "reason": reason_text,
            "inline_evidence": fields["inline_evidence"],
            "project": str(project), "findings": [],
            "messages": fields["messages"],
        }
        if args.json:
            out = _Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(_json.dumps(report, indent=2) + "\n")
        stream = sys.stderr if rc else sys.stdout
        print(f"{verdict}: {reason_text}", file=stream)
        for m in report["messages"]:
            print(f"  {m}", file=stream)
        return rc

    overall = 0
    findings: list[dict] = []
    for f in ys_files:
        code, msgs = audit(f,
                           simulation_only=args.simulation_only,
                           allow_no_sv=args.allow_no_sv)
        findings.append({"ys_file": f,
                         "verdict": "PASS" if code == 0 else "FAIL",
                         "messages": msgs})
        if code != 0:
            overall = code
    report = {
        "verdict": "PASS" if overall == 0 else "FAIL",
        "project": str(project),
        "ys_files_audited": len(ys_files),
        "findings": findings,
    }
    if args.json:
        out = _Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_json.dumps(report, indent=2) + "\n")
    for f in findings:
        prefix = "ok" if f["verdict"] == "PASS" else "FAIL"
        for m in f["messages"]:
            print(f"[{prefix}] {f['ys_file']}: {m}",
                  file=sys.stderr if overall else sys.stdout)
    return overall


if __name__ == "__main__":
    sys.exit(main())
