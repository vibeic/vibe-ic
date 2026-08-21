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
import re
import sys
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _vacuous_exit as _vx  # noqa: E402


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


# ---------------------------------------------------------------------------
# THE HANDOFF ARTEFACT (step 14's own declared output)
#
# Step 14 is the synthesis HANDOFF gate and declares
# `phase2/stage2/synth/netlist.v` — the netlist PnR consumes. Both of its gate
# programs audited the RECIPE (the `*.ys` script, or the inline `yosys -p`
# command recovered from the synth log) and never opened the PRODUCT. So the
# gate could certify a perfectly-formed script while the artefact actually
# handed to PnR was a stub, or was the PREVIOUS run's netlist that the
# currently-audited script never produced.
#
# The recipe audit is unchanged. What is added is a read of the declared
# product, with the same staleness discipline `synth_netlist_check` already
# applies against the RTL (#426: "a close-loop re-gate must never be judged
# against the previous run's ghost netlist") — one artefact further down the
# chain, where it decides what PnR receives.
#
# STALENESS IS ONLY MEANINGFUL AGAINST A PRODUCER
# -----------------------------------------------
# The first cut compared the handoff netlist against EVERY script the project
# discovery globbed, and `ys_globs` reaches `phase3/**/*.ys` and `scripts/**/
# *.ys`. Phase 3 runs after phase 2 by construction, so a yosys script written
# under `phase3/` is NECESSARILY newer than the phase-2 handoff netlist:
# measured on a converged tree with a valid `phase2/stage2/synth/synth.ys` and
# a real netlist (both 08:00) plus a `phase3/lec/lec_post_top.ys` (12:00), the
# gate reported "the netlist handed to PnR is not the product of the audited
# recipe" on a project where it plainly was. A post-synthesis equivalence
# script does not produce the synthesis handoff and its clock says nothing
# about it.
#
# The comparison is therefore scoped to scripts that CLAIM TO PRODUCE the
# handoff netlist — those whose own `write_verilog` names it as the output
# path. That is the population the message is about, and it is read out of the
# script rather than assumed from where the file sits.
#
# WHAT THIS DELIBERATELY DOES NOT COVER, stated rather than hidden: a recipe
# that writes under another name which the runner later ALIASES to netlist.v
# (`design_one_shot_runner` writes `netlist_yosys.v` and copies it) is not a
# declared producer of this path, so the staleness arm has nothing to compare
# and says so in the report (`producer_scripts: []`). Unmeasured is recorded as
# unmeasured; it is never reported as agreement.
#
# ABSENCE IS DISCLOSED, NOT FAILED: step 9's `files_exist:
# phase2/stage2/synth/netlist.v` already blocks on a missing netlist and step 9
# blocks step 14, and a project audited through `--ys-file` or through
# `phase3/**/*.ys` legitimately has no phase-2 handoff netlist at all.
# ---------------------------------------------------------------------------
HANDOFF_NETLIST_REL = "phase2/stage2/synth/netlist.v"

_MODULE_DECL_RE = re.compile(r"^\s*module\s+[\\A-Za-z_]", re.MULTILINE)

# `write_verilog [-flags ...] <path>` — the yosys command that produces a
# gate-level netlist. The trailing path is the last non-flag token on the line.
_WRITE_VERILOG_RE = re.compile(r"^[ \t]*write_verilog\b([^\n;#]*)",
                               re.MULTILINE)


def _write_verilog_targets(text: str) -> List[str]:
    """Every output path a script's own ``write_verilog`` lines name."""
    out: List[str] = []
    for m in _WRITE_VERILOG_RE.finditer(text):
        toks = [t for t in m.group(1).split() if not t.startswith("-")]
        if toks:
            out.append(toks[-1])
    return out


def declares_handoff_netlist(ys_path, project) -> bool:
    """Does this script name the step-14 handoff netlist as its own output?

    Resolution is relative to the SCRIPT's directory, which is how yosys
    resolves a relative `write_verilog` target (it runs with the script's
    directory as cwd in this flow). A target that resolves elsewhere, or a
    script with no `write_verilog` at all, is not a producer of this artefact
    and its timestamp is not evidence about it.
    """
    from pathlib import Path as _Path
    script = _Path(ys_path)
    handoff = (_Path(project) / HANDOFF_NETLIST_REL)
    try:
        text = script.read_text(errors="replace")
    except OSError:
        return False
    try:
        handoff_res = handoff.resolve()
    except OSError:  # pragma: no cover - defensive
        return False
    for target in _write_verilog_targets(text):
        cand = _Path(target)
        if not cand.is_absolute():
            cand = script.parent / cand
        try:
            if cand.resolve() == handoff_res:
                return True
        except OSError:  # pragma: no cover - defensive
            continue
    return False


def audit_handoff_netlist(project, ys_files: List[str]):
    """``(rc, report dict, messages)`` for step 14's declared handoff netlist.

    rc is 1 when the netlist PnR would consume is a stub, or is older than a
    script that DECLARES ITSELF ITS PRODUCER; 0 otherwise (including when
    absent, and when no audited script claims to write it).
    """
    from pathlib import Path as _Path
    netlist = _Path(project) / HANDOFF_NETLIST_REL
    report = {"handoff_netlist": HANDOFF_NETLIST_REL, "present": False,
              "bytes": None, "has_module": None, "stale_vs_scripts": [],
              "producer_scripts": [], "scripts_considered": len(ys_files)}
    msgs: List[str] = []
    if not netlist.is_file():
        msgs.append(
            f"{HANDOFF_NETLIST_REL} absent — step 14 declares it as the "
            f"artefact handed to PnR; step 9's files_exist clause is what "
            f"blocks on that, so this gate records it rather than re-failing it")
        return 0, report, msgs

    report["present"] = True
    try:
        text = netlist.read_text(errors="replace")
        nl_mtime = netlist.stat().st_mtime
    except OSError as exc:
        report["bytes"] = 0
        msgs.append(f"{HANDOFF_NETLIST_REL} unreadable: {exc}")
        return 1, report, msgs

    report["bytes"] = len(text.encode("utf-8", "replace"))
    body = [ln for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("//")]
    report["has_module"] = bool(_MODULE_DECL_RE.search(text))

    rc = 0
    if not body:
        rc = 1
        msgs.append(
            f"{HANDOFF_NETLIST_REL} is empty or comment-only — the synthesis "
            f"recipe this gate certified produced no netlist, and PnR would "
            f"consume nothing")
    elif not report["has_module"]:
        rc = 1
        msgs.append(
            f"{HANDOFF_NETLIST_REL} declares no `module` — the handoff "
            f"artefact is not a Verilog netlist")

    producers = [f for f in ys_files if declares_handoff_netlist(f, project)]
    report["producer_scripts"] = producers
    stale = []
    for f in producers:
        try:
            if _Path(f).stat().st_mtime > nl_mtime:
                stale.append(f)
        except OSError:
            continue
    report["stale_vs_scripts"] = stale
    if stale:
        rc = 1
        msgs.append(
            f"{HANDOFF_NETLIST_REL} is OLDER than the script(s) that declare "
            f"themselves its producer ({stale}) — the netlist handed to PnR is "
            f"not the product of the audited recipe; re-run synthesis before "
            f"handing off")
    elif ys_files and not producers:
        # Say that the comparison did not happen. A silent 0 here would be
        # indistinguishable from "checked and agreed".
        msgs.append(
            f"staleness not compared: none of the {len(ys_files)} audited "
            f"script(s) names {HANDOFF_NETLIST_REL} as its own write_verilog "
            f"target, so none of them is a declared producer of it and their "
            f"timestamps carry no information about it")
    return rc, report, msgs


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
        # The PRODUCT, not just the recipe: inline-mode synthesis hands the
        # same `phase2/stage2/synth/netlist.v` to PnR.
        hrc, hreport, hmsgs = audit_handoff_netlist(project, [])
        verdict = fields["verdict"]
        reason_text = fields["reason"]
        if hrc:
            verdict = "FAIL"
            rc = hrc
        report = {
            "verdict": verdict,
            "reason_class": fields["reason_class"],
            "reason": reason_text,
            "inline_evidence": fields["inline_evidence"],
            "project": str(project), "findings": [],
            "handoff_netlist_audit": hreport,
            "messages": list(fields["messages"]) + hmsgs,
        }
        if args.json:
            out = _Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(_json.dumps(report, indent=2) + "\n")
        stream = sys.stderr if rc else sys.stdout
        print(f"{verdict}: {reason_text}", file=stream)
        for m in report["messages"]:
            print(f"  {m}", file=stream)
        # ORGANIC #887, THE THIRD CASE — and it is the same defect as the two
        # step-3 gates arriving from the other direction.
        #
        # This branch has ALWAYS printed a recognised line-start disclosure
        # (`VACUOUS_PASS…:`). The consumer never saw it. `output_snippet` keeps
        # only the LAST `_OUTPUT_SNIPPET_CHARS` (300) characters of each stream,
        # the verdict line above is ~249 characters and goes FIRST, and the
        # ~194-character handoff-netlist note printed after it evicts the token
        # from the window. MEASURED on this tree against an empty project:
        #
        #     len(stdout) = 444
        #     _stdout_signals_vacuous(FULL stdout)      -> True
        #     _stdout_signals_vacuous(consumer snippet) -> False
        #
        # Path-length INDEPENDENT — lost at every checkout depth, on a short
        # `tmp_path` as surely as on a deep one. Its sibling on the same step,
        # `yosys_hilomap_required_check`, prints a comparable sentence with
        # nothing after it and is read correctly. Two gates, one disclosure,
        # opposite outcomes, decided by how much text followed.
        #
        # The repair is NOT to reorder these lines — that only buys headroom
        # until the next message is added, which is how this arrived. It is to
        # put the token on the stream whose CONTENT IS BOUNDED: stderr is empty
        # on this rc-0 path, and `_vacuous_exit.announce_vacuous` writes one
        # line built from the gate name and the gate's OWN `reason_class`
        # token. Nothing caller-supplied reaches it, so the tail cut is a no-op
        # on that stream at any depth and behind any amount of stdout.
        #
        # The exit code is deliberately NOT moved here (unlike the two step-3
        # gates): `resolve_no_ys_script` owns this branch's rc and uses it to
        # separate a NON-CONFORMANT inline `yosys -p` command (#649, rc 1) from
        # a conformant one, and re-routing that is a different question from
        # the one #887 asks. `verdict` is checked rather than `rc` for the same
        # reason — when the handoff-netlist arm fails it rewrites `verdict` to
        # FAIL, and a failing gate has not passed vacuously.
        if str(verdict).startswith("VACUOUS"):
            _vx.announce_vacuous("yosys_script_template_check",
                                 fields["reason_class"], stream=sys.stderr)
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
    # The PRODUCT the audited recipe is supposed to have written.
    hrc, hreport, hmsgs = audit_handoff_netlist(project, ys_files)
    if hrc:
        overall = hrc
    report = {
        "verdict": "PASS" if overall == 0 else "FAIL",
        "project": str(project),
        "ys_files_audited": len(ys_files),
        "findings": findings,
        "handoff_netlist_audit": hreport,
        "handoff_netlist_messages": hmsgs,
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
    for m in hmsgs:
        print(f"[{'FAIL' if hrc else 'ok'}] {HANDOFF_NETLIST_REL}: {m}",
              file=sys.stderr if hrc else sys.stdout)
    return overall


if __name__ == "__main__":
    sys.exit(main())
