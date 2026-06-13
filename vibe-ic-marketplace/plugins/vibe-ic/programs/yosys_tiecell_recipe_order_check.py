#!/usr/bin/env python3
"""
yosys_tiecell_recipe_order_check.py — Enforce the two v0.1.98 LOAD-BEARING
ordering rules of the constant-net tie-cell pass in a Yosys .ys synth script.

Context (synth-doctor skill, "Constant nets need a tie-cell pass before PnR"):
The v0.1.95 recipe `hilomap; splitnets; clean` was found INSUFFICIENT on the
HDLC pilot — it shipped a gate netlist that still tripped TritonRoute DRT-0305
("zero_ net") during detailed route. Two extra ordering rules turned out to be
load-bearing, not optional:

  RULE 1 — `setundef -zero` MUST appear BEFORE `hilomap`.
      A function with don't-care output bits leaves yosys emitting `1'hx` for
      dead/unreachable bits (common in framing/CRC logic). Those survive
      `hilomap` as bare `zero_`/`x` nets that TritonRoute rejects with DRT-0305.
      `setundef -zero` resolves the x bits to 0 FIRST so `hilomap` can tie them.

  RULE 2 — `opt_clean` (and `clean -purge`) MUST NOT appear AFTER `hilomap`.
      `opt_clean` / `clean -purge` treat the just-inserted tie cells as
      removable constant drivers and DELETE them, re-introducing the bare
      constant nets. On HDLC, `hilomap; opt_clean` left 0 surviving tie cells
      and DRT-0305 fired; `setundef -zero; hilomap; splitnets; clean` kept all
      1780 conb_1 cells and PnR ran clean. (Plain `clean` is fine; only the
      aggressive `opt_clean` / `clean -purge` strip the tie cells.)

This program is the structural complement to yosys_hilomap_required_check.py
(which asserts techmap → hilomap → write_verilog ordering). This one asserts
the two additional v0.1.98 refinement rules. A FAIL here catches a real silicon
DOA: a script that synthesizes fine but ships an UNROUTABLE netlist.

Usage:
    python3 yosys_tiecell_recipe_order_check.py --ys-file scripts/synth.ys
    python3 yosys_tiecell_recipe_order_check.py --ys-file scripts/synth.ys --json report.json

Exit codes:
    0 — both rules satisfied (or script is not a real-PDK synth script → SKIP).
    1 — one or more rules violated; stderr lists which.
    2 — argument or I/O error (missing/unreadable file).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Tuple


def _strip_comments(lines: List[str]) -> List[str]:
    """Drop everything from '#' to end-of-line (Yosys line-comment rule)."""
    out: List[str] = []
    for raw in lines:
        line = raw.rstrip("\n")
        if "#" in line:
            line = line.split("#", 1)[0]
        out.append(line)
    return out


def _first_token(line: str) -> str:
    toks = line.strip().split()
    return toks[0] if toks else ""


def _indices_where(lines: List[str], pred) -> List[int]:
    """0-based line indices where pred(stripped_line, tokens) is True."""
    out: List[int] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        toks = stripped.split()
        if pred(stripped, toks):
            out.append(i)
    return out


def diagnose(ys_text: str) -> dict:
    """Pure analysis of a .ys script body. Returns a structured report dict.

    verdict:
      SKIP      — not a real-PDK synth script (no dfflibmap/abc/synth command),
                  so the tie-cell recipe does not apply.
      CLEAN     — synth script, hilomap present, both rules satisfied.
      VIOLATION — synth script, hilomap present, ≥1 rule broken.
      NO_HILOMAP— synth script but no hilomap at all (this program does not
                  flag that — that is yosys_hilomap_required_check.py's job —
                  so it reports SKIP_NO_HILOMAP and exits 0 here).
    """
    lines = _strip_comments(ys_text.splitlines())

    # Only audit genuine PDK synth scripts. A synth script issues at least one
    # of {dfflibmap, abc, synth} as a COMMAND (first token on a line).
    synth_cmds = {"dfflibmap", "abc", "synth"}
    is_synth = any(_first_token(ln) in synth_cmds for ln in lines)
    if not is_synth:
        return {
            "verdict": "SKIP",
            "reason": "not a real-PDK synth script (no dfflibmap/abc/synth command)",
            "violations": [],
        }

    hilomap_idx = _indices_where(lines, lambda s, t: t[0] == "hilomap")
    if not hilomap_idx:
        # Presence of hilomap is enforced elsewhere; here there is nothing to
        # order, so the two refinement rules are vacuously inapplicable.
        return {
            "verdict": "SKIP_NO_HILOMAP",
            "reason": "synth script with no hilomap; presence enforced by "
                      "yosys_hilomap_required_check.py",
            "violations": [],
        }

    first_hilomap = hilomap_idx[0]
    last_hilomap = hilomap_idx[-1]

    # `setundef` command lines (any args, e.g. `setundef -zero`).
    setundef_idx = _indices_where(lines, lambda s, t: t[0] == "setundef")
    # `setundef -zero` specifically (the load-bearing form).
    setundef_zero_idx = _indices_where(
        lines, lambda s, t: t[0] == "setundef" and "-zero" in t)

    # Aggressive cleaners that strip tie cells:
    #   `opt_clean` (any args), `clean -purge`.
    def _is_aggressive_clean(s: str, t: List[str]) -> bool:
        if t[0] == "opt_clean":
            return True
        if t[0] == "clean" and "-purge" in t:
            return True
        return False

    aggressive_clean_idx = _indices_where(lines, _is_aggressive_clean)

    violations: List[dict] = []

    # RULE 1: setundef -zero BEFORE the first hilomap.
    if not setundef_zero_idx:
        if setundef_idx:
            violations.append({
                "rule": "RULE1_setundef_zero_before_hilomap",
                "detail": (
                    f"`setundef` is present (line "
                    f"{setundef_idx[0] + 1}) but NOT with `-zero`. v0.1.98 "
                    f"requires `setundef -zero` so don't-care `1'hx` bits "
                    f"resolve to 0 before hilomap ties them; otherwise they "
                    f"survive as bare `zero_`/`x` nets and TritonRoute hits "
                    f"DRT-0305."),
            })
        else:
            violations.append({
                "rule": "RULE1_setundef_zero_before_hilomap",
                "detail": (
                    f"MISSING `setundef -zero` before `hilomap` (first "
                    f"hilomap at line {first_hilomap + 1}). Without it, "
                    f"don't-care `1'hx` output bits survive hilomap as bare "
                    f"`zero_`/`x` nets and OpenROAD detailed_route hits "
                    f"DRT-0305."),
            })
    else:
        first_setundef_zero = setundef_zero_idx[0]
        if first_setundef_zero > first_hilomap:
            violations.append({
                "rule": "RULE1_setundef_zero_before_hilomap",
                "detail": (
                    f"ORDER: `setundef -zero` at line "
                    f"{first_setundef_zero + 1} occurs AFTER the first "
                    f"`hilomap` at line {first_hilomap + 1}. It must run "
                    f"BEFORE hilomap so x-bits are resolved to 0 first."),
            })

    # RULE 2: no opt_clean / clean -purge AFTER the last hilomap.
    offending = [a for a in aggressive_clean_idx if a > last_hilomap]
    if offending:
        violations.append({
            "rule": "RULE2_no_opt_clean_after_hilomap",
            "detail": (
                f"`opt_clean`/`clean -purge` at line(s) "
                f"{[o + 1 for o in offending]} run AFTER the last `hilomap` "
                f"(line {last_hilomap + 1}). They delete the just-inserted "
                f"tie cells, re-introducing the bare constant nets that "
                f"trip DRT-0305. Use plain `clean` (or nothing) after "
                f"hilomap."),
        })

    return {
        "verdict": "VIOLATION" if violations else "CLEAN",
        "reason": "ok: setundef -zero precedes hilomap and no aggressive "
                  "clean follows it" if not violations else
                  f"{len(violations)} tie-cell recipe ordering rule(s) broken",
        "violations": violations,
        "first_hilomap_line": first_hilomap + 1,
        "last_hilomap_line": last_hilomap + 1,
    }


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Enforce v0.1.98 tie-cell recipe ordering rules in a "
                    "Yosys .ys synth script.")
    ap.add_argument("--ys-file", required=True,
                    help="path to the Yosys .ys synth script")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="optional path to write the JSON report")
    args = ap.parse_args(argv)

    if not os.path.exists(args.ys_file):
        msg = f"yosys_tiecell_recipe_order_check: MISSING — file not found: {args.ys_file}"
        print(msg, file=sys.stderr)
        if args.json_out:
            try:
                with open(args.json_out, "w") as f:
                    json.dump({"verdict": "MISSING", "reason": msg,
                               "violations": []}, f, indent=2)
            except OSError:
                pass
        return 2
    try:
        with open(args.ys_file, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        print(f"yosys_tiecell_recipe_order_check: error reading "
              f"{args.ys_file}: {e}", file=sys.stderr)
        return 2

    report = diagnose(text)
    report["ys_file"] = args.ys_file

    if args.json_out:
        try:
            with open(args.json_out, "w") as f:
                json.dump(report, f, indent=2)
        except OSError as e:
            print(f"warning: could not write JSON to {args.json_out}: {e}",
                  file=sys.stderr)

    verdict = report["verdict"]
    if verdict in ("SKIP", "SKIP_NO_HILOMAP"):
        print(f"yosys_tiecell_recipe_order_check: {verdict} — {report['reason']}")
        return 0
    if verdict == "CLEAN":
        print(f"yosys_tiecell_recipe_order_check: CLEAN — {report['reason']} "
              f"({args.ys_file})")
        return 0
    # VIOLATION
    print(f"yosys_tiecell_recipe_order_check: VIOLATION — {report['reason']}",
          file=sys.stderr)
    for v in report["violations"]:
        print(f"  [{v['rule']}] {v['detail']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
