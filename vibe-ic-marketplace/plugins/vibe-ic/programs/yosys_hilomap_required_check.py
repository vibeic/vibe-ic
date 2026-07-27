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

Two input shapes, both audited:
    * a `.ys` script (`--ys-file`, or auto-discovered under a project dir) —
      the ordering checks below run on the script text.
    * NO `.ys` script, because the runner synthesised with an inline
      `yosys -p '<commands>'` — the command is recovered from the runner's
      own synth log (the "-- Running command" echo line) and the same
      hilomap/flatten requirement is checked on it. Only when no inline
      command was echoed anywhere does the gate fall back to reporting
      VACUOUS_PASS.

Usage:
    python3 yosys_hilomap_required_check.py --ys-file scripts/synth.ys
    python3 yosys_hilomap_required_check.py <project_dir> [--json <out>]

Exit codes:
    0 — all three conditions satisfied, or the inline command verified, or
        no auditable input exists at all (VACUOUS_PASS).
    1 — one or more conditions violated; stderr lists which.
    2 — argument or I/O error.
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
                         "under synth/, phase3/, scripts/, and reports SKIP "
                         "(rc=2) if none found.")
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
        # ORGANIC / step-14 d7 — VERIFY the inline command before falling back
        # to a vacuous verdict.
        #
        # This branch used to call `detect_inline_mode` ONLY, which answers
        # "did SOME inline yosys run happen" from marker-FILE existence. That
        # is adjacent to, not the same as, what this gate claims to decide:
        # whether hilomap actually ran after techmap and before write_verilog.
        # MEASURED on the real spm x ihp-sg13g2 run: this program wrote
        # reports/phase2/gates/yosys_hilomap.json with verdict VACUOUS_PASS /
        # reason_class inline_yosys_p_mode_confirmed — "gate is legitimately
        # not applicable" — while phase2/stage2/synth/synth.log line 16 held
        # the complete inline command, `... abc -liberty <lib>; hilomap
        # -hicell <TIEHI> L_HI -locell <TIELO> L_LO; clean; ... write_verilog
        # ...`. The ordering the gate exists to check was on disk, correct,
        # and unread; the step self-reported "not applicable" instead of
        # "verified".
        #
        # `audit_inline_yosys` (already in _yosys_inline_mode_detect, already
        # used by flow_compliance_check's in-process Step-14 gate) parses the
        # "-- Running command" echo line out of the runner's synth log and
        # checks hilomap/-flatten on real-PDK (Liberty-bound) commands.
        # Calling it here makes the DECLARED gate — the one whose JSON is the
        # step's artefact — read the same evidence. Consequences:
        #   * conformant real-PDK inline command -> verdict PASS (rc 0), with
        #     the log named. Not vacuous: something was measured.
        #   * non-conformant real-PDK inline command -> verdict FAIL, rc 1.
        #     This gate can now fail where it previously could not; step 14's
        #     `optional_program_exit_zero` makes that BLOCKING, and the rc=1
        #     path was executed against a fixture before wiring it.
        #   * ONLY simulation-only inline commands (no Liberty bound) ->
        #     VACUOUS_PASS, but with the reason DERIVED from the command
        #     rather than assumed: hilomap genuinely does not apply. The
        #     verdict must not read as "verified", because no real-PDK
        #     command was checked.
        #   * no inline command echoed anywhere -> unchanged, fall through to
        #     the pre-existing marker-file confirmation below.
        from _yosys_inline_mode_detect import (
            audit_inline_yosys, check_inline_command_conformance,
            detect_inline_mode, extract_inline_yosys_commands)
        inline_verdict, inline_logs, inline_reasons = \
            audit_inline_yosys(project)
        if inline_verdict in ("PASS", "FAIL"):
            failed = inline_verdict == "FAIL"
            # `audit_inline_yosys` returns PASS both when real-PDK commands
            # conformed and when only sim-only commands ran. Re-derive which,
            # so the reason text states what was actually examined.
            n_real_pdk = sum(
                1 for _rel, _cmd in extract_inline_yosys_commands(project)
                if check_inline_command_conformance(_cmd)[1] == "real_pdk")
            if failed:
                verdict, reason_class = "FAIL", \
                    "inline_yosys_command_nonconformant"
                reason_text = (
                    "no .ys scripts found; the inline `yosys -p` command "
                    "extracted from the runner's synth log is NON-CONFORMANT "
                    "— see messages (CLAUDE.md rule 4; OpenROAD "
                    "detailed_route trips DRT-0305 'zero_ GROUND' on the "
                    "unmapped tie net).")
            elif n_real_pdk:
                verdict, reason_class = "PASS", \
                    "inline_yosys_command_verified"
                reason_text = (
                    f"no .ys scripts found, but {n_real_pdk} real-PDK "
                    f"(Liberty-bound) inline `yosys -p` synthesis command(s) "
                    f"were extracted from the runner's synth log and "
                    f"VERIFIED: each issues hilomap and a flatten directive.")
            else:
                verdict, reason_class = "VACUOUS_PASS", \
                    "inline_yosys_command_simulation_only"
                reason_text = (
                    "no .ys scripts found; the inline `yosys -p` command(s) "
                    "extracted from the runner's synth log bind NO Liberty "
                    "library, so this is a simulation-only synthesis and the "
                    "tie-cell (hilomap) requirement does not apply. Nothing "
                    "was verified against a real PDK.")
            report = {
                "verdict": verdict,
                "reason_class": reason_class,
                "reason": reason_text,
                "inline_evidence": inline_logs,
                "real_pdk_commands_audited": n_real_pdk,
                "project": str(project), "messages": inline_reasons,
            }
            if args.json:
                out = _Path(args.json)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(_json.dumps(report, indent=2) + "\n")
            print(f"{verdict}: {reason_text}",
                  file=sys.stderr if failed else sys.stdout)
            for m in inline_reasons:
                print(f"  {m}", file=sys.stderr)
            return 1 if failed else 0

        # v1.6.180 (#72 P2-8) — no inline command was echoed at all. Positively
        # confirm the inline-mode case from marker files; report a distinct
        # verdict tier when no supporting evidence is found so audit reviewers
        # can spot an unconfirmed VACUOUS_PASS.
        inline_status, inline_evidence = detect_inline_mode(project)
        if inline_status == "confirmed":
            verdict = "VACUOUS_PASS"
            reason_class = "inline_yosys_p_mode_confirmed"
            reason_text = (
                "no .ys scripts found, BUT inline `yosys -p` runner "
                "mode is positively confirmed by project markers "
                f"({len(inline_evidence)} evidence path(s)); gate is "
                "legitimately not applicable."
            )
        else:
            verdict = "VACUOUS_PASS_UNCONFIRMED"
            reason_class = "inline_yosys_p_mode_unconfirmed"
            reason_text = (
                "no .ys scripts found AND no inline `yosys -p` "
                "runner-mode markers detected. Gate stays rc=0 "
                "(vacuous) but reviewers should confirm a synthesis "
                "step actually ran — otherwise a missing synth "
                "artefact is being silently masked."
            )
        report = {
            "verdict": verdict,
            "reason_class": reason_class,
            "reason": reason_text,
            "inline_evidence": inline_evidence,
            "project": str(project), "messages": [],
        }
        if args.json:
            out = _Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(_json.dumps(report, indent=2) + "\n")
        print(f"{verdict}: {reason_text}")
        return 0

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
