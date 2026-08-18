#!/usr/bin/env python3
"""
yosys_hilomap_required_check.py — Assert a Yosys .ys script's commands occur
in the order required by CLAUDE.md rule 4.

Rule: Any Yosys synth script targeting a real PDK (not simulation-only) MUST
contain `hilomap` AFTER `techmap` AND BEFORE the final `write_verilog`.

Why it matters: v068 fresh-agent Phase-3 run shipped a synth.ys where hilomap
was positioned correctly, but a prior iteration of the same agent skipped
hilomap entirely and OpenROAD detailed_route tripped DRT-0305 on the
unmapped tie net. A hard gate on the ordering constraint catches the bug
before Yosys even runs.

Ordering checked:
    1. `techmap` appears at least once.
    2. `hilomap` appears at least once, on a line AFTER every `techmap`.
    3. `write_verilog` appears at least once, on a line AFTER every
       `hilomap`.

Two input shapes, both audited (the second landed in v1.7.64, PR #474; this
docstring described only the first until then, so the file promised a
narrower gate than it ships):
    * a `.ys` script — `--ys-file <path>`, or every `*.ys` auto-discovered
      under a project dir. The ordering checks above run on the script text.
    * NO `.ys` script, because the runner synthesised with an inline
      `yosys -p '<commands>'`. The command is recovered from the runner's own
      synth log (the `-- Running command \\`...'` echo line) and the same
      hilomap + flatten requirement is checked on its TEXT, by
      `_yosys_inline_mode_detect.resolve_no_ys_script`.

What the project-dir branch reports when there is no `.ys` script — note that
`verdict` stays VACUOUS_PASS on every rc=0 tier, so `reason_class` is the
field that says how much was actually verified:
    rc=1  verdict FAIL,          reason_class inline_yosys_p_mode_nonconformant
          — a real-PDK inline command (one that binds a Liberty library) is
          missing hilomap and/or flatten. Blocking, by design.
    rc=0  verdict VACUOUS_PASS,  reason_class inline_yosys_p_mode_conformant
          — an inline command WAS extracted and checked, and it conforms (or
          only simulation-only commands, which bind no Liberty, were found).
          The verdict word is "vacuous" because no `.ys` script existed to
          audit; the reason_class is what records that the command itself was
          read and verified. `inline_evidence` names the log(s).
    rc=0  verdict VACUOUS_PASS,  reason_class inline_yosys_p_mode_confirmed
    rc=0  verdict VACUOUS_PASS_UNCONFIRMED,
                                 reason_class inline_yosys_p_mode_unconfirmed
          — no inline command was echoed anywhere, so nothing could be read.
          These are the pre-v1.7.64 marker-FILE-existence tiers, kept: a
          non-Yosys flow is legitimate, and `_unconfirmed` flags for a
          reviewer that no synthesis evidence was found at all.

Usage:
    python3 yosys_hilomap_required_check.py --ys-file scripts/synth.ys
    python3 yosys_hilomap_required_check.py <project_dir> [--json <out>]

Exit codes:
    0 — every audited input satisfied the ordering; or a `.ys` script issues
        none of {dfflibmap, abc, synth} and so is not a synth script at all;
        or the no-`.ys`-script branch reached one of its three rc=0 tiers
        above.
    1 — one or more conditions violated; stderr lists which. Reachable from
        BOTH branches — a non-conformant inline command fails here too.
    2 — argument error, unreadable `--ys-file`, or a project dir that does
        not exist. NOT used for "nothing to audit"; that is a rc=0
        VACUOUS_PASS tier.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Tuple


def _strip_comments(lines: List[str]) -> List[str]:
    """Drop everything from '#' to end-of-line. Yosys line-comment rule."""
    out: List[str] = []
    for raw in lines:
        line = raw.rstrip("\n")
        if "#" in line:
            line = line.split("#", 1)[0]
        out.append(line)
    return out


def _last_index_of_command(lines: List[str], cmd: str) -> int:
    """Return the 0-based index of the LAST line whose first non-space
    whitespace-split token equals *cmd*. Returns -1 if not found.

    We care about command position — a line like `hilomap -hicell ...` counts
    as a `hilomap` invocation; a mid-line mention does not. Mid-line mentions
    would be unusual in a .ys script but we filter them out to be safe.
    """
    last = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        tokens = stripped.split()
        if tokens and tokens[0] == cmd:
            last = i
    return last


def _first_index_of_command(lines: List[str], cmd: str) -> int:
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        tokens = stripped.split()
        if tokens and tokens[0] == cmd:
            return i
    return -1


def _all_indices_of_command(lines: List[str], cmd: str) -> List[int]:
    out: List[int] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        tokens = stripped.split()
        if tokens and tokens[0] == cmd:
            out.append(i)
    return out


def audit(ys_path: str) -> Tuple[int, List[str]]:
    if not os.path.exists(ys_path):
        return 2, [f"error: file not found: {ys_path}"]
    try:
        with open(ys_path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.readlines()
    except OSError as e:
        return 2, [f"error: cannot read {ys_path}: {e}"]
    lines = _strip_comments(raw)

    techmap_idx = _all_indices_of_command(lines, "techmap")
    hilomap_idx = _all_indices_of_command(lines, "hilomap")
    write_v_idx = _all_indices_of_command(lines, "write_verilog")

    errs: List[str] = []

    # v1.6.228 — skip non-synth .ys scripts. A genuine PDK synth
    # script issues at least one of {dfflibmap, abc, synth} as a
    # Yosys COMMAND (i.e. the FIRST non-whitespace token on a line).
    # Substring matching is unsafe because filenames passed to
    # `read_verilog` often contain "synth" (e.g. "synth_shim.v").
    # Flatten/post-process scripts (e.g. pdk_yosys_flatten_for_quartus
    # FPGA-reverify pipeline) are not synth and shouldn't be audited.
    # chip-AGNOSTIC.
    synth_cmds = {"dfflibmap", "abc", "synth"}
    is_synth = False
    for ln in lines:
        tokens = ln.split()
        if tokens and tokens[0] in synth_cmds:
            is_synth = True
            break
    if not is_synth:
        return 0, []  # gate vacuously PASS — not a synth script

    # Condition 1: hilomap must appear at least once.
    if not hilomap_idx:
        errs.append(
            "MISSING hilomap: CLAUDE.md rule 4 requires a `hilomap` command "
            "in every real-PDK synth script. Without it OpenROAD "
            "detailed_route hits DRT-0305 'zero_ GROUND'."
        )
        return 1, errs

    # Condition 2: techmap must appear and every techmap must be before the
    # FIRST hilomap. Yosys semantics: techmap lowers to gate-level; hilomap
    # then substitutes tie-cells for the constant nets in that gate-level
    # netlist. Running hilomap first would have nothing to substitute.
    first_hilomap = hilomap_idx[0]
    if not techmap_idx:
        errs.append(
            "MISSING techmap: `hilomap` is present but there is no "
            "`techmap` before it. hilomap can only substitute tie cells on a "
            "post-techmap gate-level netlist."
        )
    else:
        last_techmap = techmap_idx[-1]
        if last_techmap > first_hilomap:
            errs.append(
                f"ORDER hilomap_before_techmap: last `techmap` at line "
                f"{last_techmap + 1} occurs AFTER first `hilomap` at line "
                f"{first_hilomap + 1}. hilomap must follow techmap."
            )

    # Condition 3 (new in v0.99 — surfaced by <benchmark> run 4): if `abc` is
    # invoked between the last `techmap` and the (last) `hilomap`, that
    # ordering is broken. ABC re-introduces gate-level constants that need
    # another `techmap` lowering before `hilomap` can substitute the tie
    # cells. Catches the run-4 silent class where pre-PnR gates pass but
    # detailed_route still hits DRT-0305 because hilomap operated on a
    # netlist with un-mapped post-ABC zeros.
    abc_idx = _all_indices_of_command(lines, "abc")
    if abc_idx and techmap_idx and hilomap_idx:
        last_techmap = techmap_idx[-1]
        first_hilomap = hilomap_idx[0]
        # Find any abc that sits strictly between last_techmap and first_hilomap.
        offending = [
            a for a in abc_idx
            if last_techmap < a < first_hilomap
        ]
        if offending:
            errs.append(
                f"ORDER abc_between_techmap_and_hilomap: `abc` at line(s) "
                f"{[o + 1 for o in offending]} runs AFTER the last `techmap` "
                f"(line {last_techmap + 1}) but BEFORE `hilomap` (line "
                f"{first_hilomap + 1}). Add a second `techmap` after abc so "
                f"hilomap can substitute tie cells on the lowered netlist; "
                f"otherwise OpenROAD detailed_route will hit DRT-0305."
            )

    # Condition 4: every write_verilog must come AFTER the last hilomap.
    if not write_v_idx:
        errs.append(
            "MISSING write_verilog: no `write_verilog` command found. "
            "Without it Yosys produces no netlist output for OpenROAD."
        )
    else:
        last_hilomap = hilomap_idx[-1]
        first_write = write_v_idx[0]
        if first_write < last_hilomap:
            errs.append(
                f"ORDER write_verilog_before_hilomap: first `write_verilog` "
                f"at line {first_write + 1} occurs BEFORE last `hilomap` at "
                f"line {last_hilomap + 1}. The netlist would be written "
                f"before tie cells are substituted."
            )

    if errs:
        return 1, errs
    return 0, [f"ok: {ys_path} has techmap → hilomap → write_verilog in order"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Assert Yosys .ys ordering: techmap -> hilomap -> write_verilog. "
            "Pre-PnR gate that catches the DRT-0305 'zero_ GROUND' trigger "
            "before OpenROAD ever runs."
        )
    )
    # Wave 92 / v1.6.16 — flow_compliance_check invokes step gates with
    # `<project_dir> --json <out>`. Accept that signature while
    # preserving the legacy `--ys-file <path>` form for direct CLI use.
    ap.add_argument("project_dir", nargs="?", default=None,
                    help="Project directory; auto-discovers *.ys scripts "
                         "under synth/, phase3/, scripts/. If none are found "
                         "it audits the inline `yosys -p` command echoed in "
                         "the runner's synth log instead — rc=1 when that "
                         "command is a non-conformant real-PDK one, else a "
                         "rc=0 VACUOUS_PASS tier. (This help used to say "
                         "'reports SKIP (rc=2) if none found'; that branch "
                         "has never returned 2.)")
    ap.add_argument("--ys-file", default=None,
                    help="Path to a single Yosys .ys synthesis script.")
    ap.add_argument("--json", default=None,
                    help="Aggregate findings into a JSON report at this path.")
    args = ap.parse_args(argv)

    if not args.project_dir and not args.ys_file:
        ap.error("either <project_dir> positional OR --ys-file is required")

    if args.ys_file:
        code, msgs = audit(args.ys_file)
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

    import json as _json
    if not ys_files:
        # v1.6.180 (#72 P2-8) — positively confirm the inline-mode case.
        # v1.7.64 — before falling back to that file-existence confirmer,
        # run the #649 CONTENT audit on the inline `yosys -p` command the
        # runner echoed into its synth log. Until now the content audit
        # existed only inside flow_compliance_check._run_yosys_gates, and
        # that in-process copy governs Step 14 only when it FAILs; the gate
        # the flow YAML actually declares (this CLI) emitted VACUOUS_PASS
        # for a real-PDK inline synth that skipped hilomap.
        from _yosys_inline_mode_detect import resolve_no_ys_script
        rc, fields = resolve_no_ys_script(project)
        verdict = fields["verdict"]
        reason_text = fields["reason"]
        report = {
            "verdict": verdict,
            "reason_class": fields["reason_class"],
            "reason": reason_text,
            "inline_evidence": fields["inline_evidence"],
            "project": str(project), "messages": fields["messages"],
        }
        if args.json:
            out = _Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(_json.dumps(report, indent=2) + "\n")
        stream = sys.stderr if rc else sys.stdout
        print(f"{verdict}: {reason_text}", file=stream)
        # vibe-ic#599. The verdict word stays VACUOUS_PASS on purpose — no `.ys`
        # script existed to audit, and `reason_class` is what records how much
        # was verified. That distinction was invisible to the roll-up, which
        # reads the printed token and never the report, so a step whose inline
        # `yosys -p` command HAD been extracted and checked was tallied as one
        # where nothing was examined. This line is the disclosure the roll-up
        # consumes; it is emitted only on the tiers whose reason_class says a
        # command was actually read, never on `_unconfirmed`.
        if rc == 0 and fields["reason_class"] in (
                "inline_yosys_p_mode_conformant",
                "inline_yosys_p_mode_confirmed"):
            print(f"SUBSTANTIVE_PASS: no `.ys` script existed, and the "
                  f"equivalent was verified by another route "
                  f"({fields['reason_class']})", file=stream)
        for m in report["messages"]:
            print(f"  {m}", file=stream)
        return rc

    overall = 0
    findings: list[dict] = []
    for f in ys_files:
        code, msgs = audit(f)
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
