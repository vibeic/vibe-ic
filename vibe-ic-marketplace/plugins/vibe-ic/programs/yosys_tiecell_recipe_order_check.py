#!/usr/bin/env python3
"""yosys_tiecell_recipe_order_check.py — Enforce the two v0.1.98 LOAD-BEARING
ordering rules of the constant-net tie-cell pass in a Yosys synthesis recipe.

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
(which asserts techmap → hilomap → write_verilog ordering) and to
yosys_script_template_check.py (which asserts -sv / -flatten / hilomap token
presence). Neither of those checks `setundef`-before-`hilomap` or
aggressive-clean-after-`hilomap`; this one does, and nothing else does.

──────────────────────────────────────────────────────────────────────────
HOW SEVERE A VIOLATION IS — CORRECTED AGAINST A REAL PUBLISHED RUN
──────────────────────────────────────────────────────────────────────────
This file used to claim a RULE 1 violation "catches a real silicon DOA: a
script that synthesizes fine but ships an UNROUTABLE netlist". Measured on the
one published run this gate can judge today
(`benchmark-data/ic/caravel_user_project`), that is FALSE as stated:

    phase3/stage3/pnr/openroad.log:278  PG_CLEANUP_SIG: zero_ (GROUND)
    phase3/stage3/pnr/openroad.log:279  PG_CLEANUP_DONE: deleted=0 reclassified=1
    phase3/stage3/pnr/openroad.log:595  [INFO DRT-0199]   Number of violations = 0.
    phase3/stage3/pnr/openroad.log:619  [INFO DRT-0198] Complete detail routing.

The run ROUTED, with zero detailed-route violations, because the v0.2.14 PG-net
cleanup shipped in the generated `pnr.tcl` reclassifies exactly this net before
`global_route`. `phase3_one_shot_runner.py` calls the same phenomenon "cosmetic
[DRT-0305] warnings" in its own comment. So:

  * the VERDICT is true — the don't-care bits really are unresolved, and the
    netlist really does carry `x` constants into PnR;
  * the CONSEQUENCE is NOT "unroutable": the flow already mitigates the routing
    symptom downstream. What survives is that the tie value is decided by a
    downstream cleanup pass instead of by the synthesis recipe, which is a
    determinism/intent problem, not a DOA.

*** THAT ASSESSMENT EXPIRED WITH vibe-ic#687. ***

The downstream mitigation it rests on — `PG_CLEANUP_SIG: zero_ (GROUND)`,
the retype to SIGNAL — was REMOVED by #687, correctly: the same retype was
also hiding genuinely unrouted supplies. With it gone, an unresolved `x`
reaches `PG_CLEANUP_UNROUTED_SUPPLY` and HARD-FAILS PnR. Re-measured on the
same IC one plugin generation later (caravel_user_project x sky130A, v1.9.65,
die 2920x3520):

    phase2/stage2/synth/user_project_wrapper_synth.v:1793
        assign io_out = { \\mprj.counter.count [15:8], 22'hxxxxxx,
                          \\mprj.counter.count [7:0] };
    phase3/stage3/pnr/openroad.log
        PG_CLEANUP_UNROUTED_SUPPLY: zero_ (GROUND) iterms=0 bterms=44
    reports/orchestrator/phase3_one_shot.json
        "name": "pnr", "status": "FAIL",
        "detail": "PG_UNROUTED_SUPPLY: 1 POWER/GROUND net(s) carry real
                   terminals and no special-net geometry ..."

44 driverless chip-top output bits, reported as a power/ground rail. So the
current consequence of a RULE 1 violation is: PnR FAILs, and the finding names
the wrong defect class. Not a determinism nit, and not a DOA either — a hard
stop with a misleading name.

──────────────────────────────────────────────────────────────────────────
WHERE IT IS WIRED, AND WHY REPORT-ONLY
──────────────────────────────────────────────────────────────────────────
Wired at flow Step 14 (`flow/phase1_phase2_phase3.yaml`) in the
`advisory_program_exit_zero` slot — the slot that RUNS a gate, RECORDS its
verdict, and never fails the step. Two measurements say report-only is the
honest tier today:

  1. EVERY runner-produced real-PDK synthesis violates RULE 1.
     `phase3_one_shot_runner.py` builds its inline yosys command with a
     `hilomap` clause and never emits `setundef -zero` (grep: the only two
     `setundef` occurrences in that file are comments). Blocking on day one
     would redden every future real-PDK run produced by the canonical runner.
     Fixing the producer is a change to how don't-care CHIP-TOP OUTPUT and
     OUTPUT-ENABLE bits resolve, so it needs a functional/LEC re-verification
     — it is not a recipe-string edit, and it is not done here.

     >>> REASON 1 IS DISCHARGED. The producer now emits `setundef -zero`
     inside the hilomap clause itself (order true by construction, all four
     interpolation sites), pinned by
     `tests/test_setundef_zero_before_hilomap_producer.py` including the
     bidirectional negative control. The functional re-verification asked for
     above was run: post-fix RTL-vs-mapped-netlist LEC on
     caravel_user_project x sky130A. Blocking no longer reddens the canonical
     runner — it is REASON 2 (coverage) that still governs the tier, so the
     tier is deliberately left ADVISORY here rather than flipped by the same
     change that removed reason 1. Flipping it is a flow-tier decision on
     evidence wider than the one design measured here.
  2. COVERAGE IS 1 OF 16, NOT "15 CLEAN".
     Over `benchmark-data/` (123 directories with a `phase2/` or `phase3/`
     child), 16 publish a mapped netlist. Exactly 1 of those 16 also publishes
     a synth log that echoes the command yosys ran, so 1 is judgeable and 15
     are NOT. Reporting those 15 as PASS would manufacture 15 fresh false
     clean bills. They get the explicit NOT-CHECKED tier (rc 2) instead.

What would make it blocking: a producer that emits `setundef -zero` (with the
functional re-verification), plus a synth-log publication convention that
raises coverage above 1/16.

Usage:
    yosys_tiecell_recipe_order_check.py <project_dir> [--json report.json]
    yosys_tiecell_recipe_order_check.py --ys-file scripts/synth.ys
    yosys_tiecell_recipe_order_check.py --ys-file scripts/synth.ys --json out.json

Exit codes (the flow_compliance_check three-way convention, routed through
`_vacuous_exit` so the printed verdict and the exit code cannot disagree):
    0 — a real synthesis recipe was READ and both rules hold.
    1 — a real synthesis recipe was READ and >= 1 rule is violated.
    2 — NOT CHECKED: nothing judgeable was found (no synth recipe, or only a
        simulation-only one, or the file/dir is unreadable). This is NOT a
        pass over the design; `summary.reason` says which case it was.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _vacuous_exit as _vx           # noqa: E402

GATE = "yosys_tiecell_recipe_order_check"


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


def _diagnose_units(lines: List[str], unit: str = "line") -> dict:
    """The shared analysis core, over an ordered list of yosys COMMANDS.

    `lines` is one command per element, already comment-stripped. `unit` names
    what an index means in the human message: a `.ys` script has "line"s, an
    inline `yosys -p 'a; b; c'` body has "command"s. Splitting this out of
    `diagnose` is what lets the inline path reuse the rules verbatim instead
    of re-implementing them — the two synthesis front-ends this plugin ships
    disagree on exactly RULE 1, and only one shared implementation can be
    trusted to say so.
    """
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
                    f"`setundef` is present ({unit} "
                    f"{setundef_idx[0] + 1}) but NOT with `-zero`. v0.1.98 "
                    f"requires `setundef -zero` so don't-care `1'hx` bits "
                    f"resolve to 0 before hilomap ties them; otherwise they "
                    f"survive as bare `zero_`/`x` nets that a downstream "
                    f"pass — not the synthesis recipe — has to resolve."),
            })
        else:
            violations.append({
                "rule": "RULE1_setundef_zero_before_hilomap",
                "detail": (
                    f"MISSING `setundef -zero` before `hilomap` (first "
                    f"hilomap at {unit} {first_hilomap + 1}). Without it, "
                    f"don't-care `1'hx` output bits survive hilomap as bare "
                    f"`zero_`/`x` nets; OpenROAD detailed_route reports "
                    f"DRT-0305 on them and the generated pnr.tcl's PG-net "
                    f"cleanup is what decides their value."),
            })
    else:
        first_setundef_zero = setundef_zero_idx[0]
        if first_setundef_zero > first_hilomap:
            violations.append({
                "rule": "RULE1_setundef_zero_before_hilomap",
                "detail": (
                    f"ORDER: `setundef -zero` at {unit} "
                    f"{first_setundef_zero + 1} occurs AFTER the first "
                    f"`hilomap` at {unit} {first_hilomap + 1}. It must run "
                    f"BEFORE hilomap so x-bits are resolved to 0 first."),
            })

    # RULE 2: no opt_clean / clean -purge AFTER the last hilomap.
    offending = [a for a in aggressive_clean_idx if a > last_hilomap]
    if offending:
        violations.append({
            "rule": "RULE2_no_opt_clean_after_hilomap",
            "detail": (
                f"`opt_clean`/`clean -purge` at {unit}(s) "
                f"{[o + 1 for o in offending]} run AFTER the last `hilomap` "
                f"({unit} {last_hilomap + 1}). They delete the just-inserted "
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


def diagnose(ys_text: str) -> dict:
    """Pure analysis of a .ys script body. Returns a structured report dict.

    verdict:
      SKIP      — not a real-PDK synth script (no dfflibmap/abc/synth command),
                  so the tie-cell recipe does not apply.
      CLEAN     — synth script, hilomap present, both rules satisfied.
      VIOLATION — synth script, hilomap present, >= 1 rule broken.
      SKIP_NO_HILOMAP — synth script but no hilomap at all (this program does
                  not flag that — that is yosys_hilomap_required_check.py's
                  job).
    """
    return _diagnose_units(_strip_comments(ys_text.splitlines()), unit="line")


def diagnose_inline_command(cmd: str) -> dict:
    """Analyse ONE inline `yosys -p '<a; b; c>'` command body.

    The body is a `;`-separated command sequence on a single line, so it is
    split on `;` rather than on newlines. Comment stripping is deliberately
    NOT applied: a `-p` body carries no yosys line comments, but it does carry
    file paths and `-D<MACRO>` defines in which a `#` would be data.
    """
    return _diagnose_units([c.strip() for c in cmd.split(";")],
                           unit="command")


# ---------------------------------------------------------------------------
# Project mode
# ---------------------------------------------------------------------------

#: Where a synthesis `.ys` script lives, project-relative and DEEP. Copied from
#: `yosys_hilomap_required_check.main` on purpose, and deliberately NOT from
#: `flow_compliance_check._YS_SEARCH_ORDER`: that order globs `*.ys` at the
#: project ROOT and then "prefers a name containing synth", so a LEC script
#: named e.g. `lec_post_<top>_synth.ys` dropped at the project root would be
#: selected as THE synthesis script, come back SKIP (it is not a synth
#: recipe), and the inline path — the only branch that judges anything on the
#: published corpus — would never run. Here every discovered `.ys` is audited
#: and an all-SKIP result falls THROUGH to the inline path, so no single file
#: can shadow the real recipe.
_YS_GLOBS: Tuple[str, ...] = (
    "phase2/stage2/synth/*.ys", "phase2/stage2/synth/**/*.ys",
    "phase3/synth/*.ys", "phase3/**/*.ys",
    "scripts/*.ys", "scripts/**/*.ys",
)

#: Directories a mapped (post-synthesis) netlist is published under.
_NETLIST_DIRS: Tuple[str, ...] = (
    "phase2/stage2/synth", "phase3/stage2/synth", "phase3/synth",
)
#: A STRUCTURAL netlist instantiates cells and has no `always` block. Both
#: patterns are PDK-agnostic: no cell prefix, vendor or library name appears.
_INSTANTIATION_RE = re.compile(
    r"^\s*[A-Za-z_][\w$]*\s+[A-Za-z_\\][\w$\\.\[\]]*\s*\(", re.MULTILINE)
_BEHAVIOURAL_RE = re.compile(r"^\s*always\b", re.MULTILINE)


def find_ys_scripts(project: Path) -> List[Path]:
    """Every `.ys` under the canonical synthesis-script locations, sorted."""
    found: List[Path] = []
    for g in _YS_GLOBS:
        found.extend(project.glob(g))
    return sorted(set(found))


def has_mapped_netlist(project: Path) -> List[str]:
    """Project-relative paths of published STRUCTURAL netlists.

    Used only to tell the two NOT-CHECKED sub-cases apart: "this project never
    synthesised" is a different disclosure from "this project shipped a mapped
    netlist and no recipe anybody can read". It never changes the exit code.
    """
    out: List[str] = []
    for sub in _NETLIST_DIRS:
        d = project / sub
        if not d.is_dir():
            continue
        for v in sorted(d.glob("*.v")):
            try:
                text = v.read_text(errors="replace")
            except OSError:
                continue
            if _BEHAVIOURAL_RE.search(text):
                continue
            if _INSTANTIATION_RE.search(text):
                out.append(str(v.relative_to(project)))
    return out


def audit_project(project: Path) -> dict:
    """Audit a project directory. Returns the structured report.

    Resolution order, strongest evidence first:

      1. every `.ys` under the canonical synthesis locations;
      2. if none of those is a synthesis recipe, the inline
         `yosys -p '<cmds>'` command the runner echoed into its own synth log
         (`_yosys_inline_mode_detect.extract_inline_yosys_commands`);
      3. NOT CHECKED.

    A command that binds no Liberty library is a SIMULATION-ONLY synth: it maps
    to generic gates, needs no tie cells, and is waived — the same waiver
    `_yosys_inline_mode_detect._LIBERTY_RE` implements for the two sibling
    Step-14 gates. Without it a sim-only synth carrying `hilomap` would
    false-fire.
    """
    report: dict = {
        "gate": GATE,
        "project": str(project),
        "mode": None,
        "findings": [],
        "violations": [],
        "netlists_published": has_mapped_netlist(project),
    }

    # --- (1) .ys scripts --------------------------------------------------
    ys_files = find_ys_scripts(project)
    judged_any = False
    for f in ys_files:
        try:
            text = f.read_text(errors="replace")
        except OSError as e:
            report["findings"].append(
                {"source": str(f.relative_to(project)), "verdict": "UNREADABLE",
                 "reason": str(e), "violations": []})
            continue
        d = diagnose(text)
        d["source"] = str(f.relative_to(project))
        report["findings"].append(d)
        if d["verdict"] in ("CLEAN", "VIOLATION"):
            judged_any = True
            report["violations"].extend(d["violations"])
    if judged_any:
        report["mode"] = "ys_script"
        report["ys_files_audited"] = len(ys_files)
        report["verdict"] = "VIOLATION" if report["violations"] else "CLEAN"
        report["summary"] = {
            "skipped": False,
            "reason": "ys_script_audited",
            "judged": sum(1 for d in report["findings"]
                          if d.get("verdict") in ("CLEAN", "VIOLATION")),
            "denominator": len(ys_files),
        }
        return report

    # --- (2) inline `yosys -p` command from the runner's own synth log ----
    try:
        from _yosys_inline_mode_detect import (extract_inline_yosys_commands,
                                               _LIBERTY_RE)
    except Exception as exc:                       # incomplete install
        report["mode"] = "unavailable"
        report["verdict"] = "NOT_CHECKED"
        report["summary"] = {
            "skipped": True,
            "reason": f"inline_detector_unavailable ({type(exc).__name__})",
            "judged": 0, "denominator": 0,
        }
        return report

    cmds = extract_inline_yosys_commands(project)
    for rel, cmd in cmds:
        if not _LIBERTY_RE.search(cmd):
            report["findings"].append(
                {"source": rel, "verdict": "SKIP_SIMULATION_ONLY",
                 "reason": "inline command binds no Liberty library — a "
                           "simulation-only synth needs no tie cells",
                 "violations": []})
            continue
        d = diagnose_inline_command(cmd)
        d["source"] = rel
        report["findings"].append(d)
        if d["verdict"] in ("CLEAN", "VIOLATION"):
            judged_any = True
            report["violations"].extend(d["violations"])
    if judged_any:
        report["mode"] = "inline_yosys_p"
        report["verdict"] = "VIOLATION" if report["violations"] else "CLEAN"
        report["summary"] = {
            "skipped": False,
            "reason": "inline_command_audited",
            "judged": sum(1 for d in report["findings"]
                          if d.get("verdict") in ("CLEAN", "VIOLATION")),
            "denominator": len(cmds),
        }
        return report

    # --- (3) NOT CHECKED --------------------------------------------------
    # The distinction that matters: a project that published a mapped netlist
    # and no readable recipe was NOT audited, and saying PASS here is exactly
    # the empty-result-reads-as-clean-result substitution this repo keeps
    # paying for. Both sub-cases exit 2 (VACUOUS), never 0.
    report["mode"] = "none"
    report["verdict"] = "NOT_CHECKED"
    sim_only = [f for f in report["findings"]
                if f.get("verdict") == "SKIP_SIMULATION_ONLY"]
    if sim_only and not report["netlists_published"]:
        reason = "only_simulation_only_synth"
        detail = (f"{len(sim_only)} inline synthesis command(s) were found and "
                  f"every one binds no Liberty library, i.e. is a "
                  f"simulation-only synth that legitimately needs no tie "
                  f"cells. No real-PDK recipe was available to judge.")
    elif report["netlists_published"]:
        reason = "netlist_published_but_no_readable_recipe"
        detail = (
            f"{len(report['netlists_published'])} mapped netlist(s) are "
            f"published under this project but neither a synthesis `.ys` "
            f"script nor a synth log echoing the inline `yosys -p` command "
            f"was found, so the tie-cell recipe could not be read. This is "
            f"NOT a clean bill: the recipe was never examined.")
    else:
        reason = "no_synthesis_recipe_and_no_mapped_netlist"
        detail = ("no synthesis `.ys` script, no echoed inline `yosys -p` "
                  "command, and no mapped netlist — nothing was synthesised "
                  "here for the tie-cell recipe to apply to.")
    report["summary"] = {"skipped": True, "reason": reason,
                         "judged": 0,
                         "denominator": len(report["netlists_published"])}
    report["reason"] = detail
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _write_json(path: Optional[str], report: dict) -> None:
    if not path:
        return
    try:
        out = Path(path)
        if out.parent and str(out.parent) not in ("", "."):
            out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")
    except OSError as e:
        print(f"warning: could not write JSON to {path}: {e}",
              file=sys.stderr)


def audit_ys_file(ys_file: str) -> dict:
    """Audit ONE `.ys` script. Returns the structured report; the caller routes
    the exit code from `summary`."""
    if not os.path.exists(ys_file):
        return {"gate": GATE, "verdict": "NOT_CHECKED", "ys_file": ys_file,
                "reason": f"file not found: {ys_file}", "violations": [],
                "summary": {"skipped": True, "reason": "ys_file_not_found",
                            "judged": 0, "denominator": 0}}
    try:
        with open(ys_file, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        return {"gate": GATE, "verdict": "NOT_CHECKED", "ys_file": ys_file,
                "reason": f"error reading {ys_file}: {e}", "violations": [],
                "summary": {"skipped": True, "reason": "ys_file_unreadable",
                            "judged": 0, "denominator": 0}}

    report = diagnose(text)
    report["gate"] = GATE
    report["ys_file"] = ys_file
    verdict = report["verdict"]
    skipped = verdict in ("SKIP", "SKIP_NO_HILOMAP")
    report["summary"] = {
        "skipped": skipped,
        "reason": ("ys_script_audited" if not skipped
                   else ("not_a_synthesis_script" if verdict == "SKIP"
                         else "synthesis_script_without_hilomap")),
        "judged": 0 if skipped else 1,
        "denominator": 1,
    }
    return report


def _print_ys_report(report: dict, passed: bool, skipped: bool) -> None:
    stream = sys.stdout if passed else sys.stderr
    print(_vx.verdict_line(GATE, passed, skipped,
                           _vx.skip_reason(report["summary"])), file=stream)
    print(f"{GATE}: {report['verdict']} — {report['reason']} "
          f"({report.get('ys_file')})", file=stream)
    for v in report["violations"]:
        print(f"  [{v['rule']}] {v['detail']}", file=sys.stderr)


def audit_project_dir(project_dir: str) -> dict:
    """Audit a project by path. Returns the structured report; the caller
    routes the exit code from `summary`."""
    project = Path(project_dir).resolve()
    if not project.is_dir():
        return {"gate": GATE, "verdict": "NOT_CHECKED", "project": str(project),
                "mode": "none", "findings": [], "violations": [],
                "netlists_published": [],
                "reason": f"project dir not found: {project}",
                "summary": {"skipped": True, "reason": "project_dir_not_found",
                            "judged": 0, "denominator": 0}}
    return audit_project(project)


def _print_project_report(report: dict, passed: bool, skipped: bool) -> None:
    stream = sys.stdout if passed else sys.stderr
    print(_vx.verdict_line(GATE, passed, skipped,
                           _vx.skip_reason(report["summary"])), file=stream)
    # The denominator, on every run, pass or fail: which recipe was read and
    # how many were available to read.
    print(f"  mode={report['mode']} judged={report['summary']['judged']} "
          f"of denominator={report['summary']['denominator']} "
          f"netlists_published={len(report['netlists_published'])}",
          file=stream)
    for f in report["findings"]:
        print(f"  [{f.get('verdict')}] {f.get('source')}: "
              f"{f.get('reason', '')}", file=stream)
    for v in report["violations"]:
        print(f"  [{v['rule']}] {v['detail']}", file=sys.stderr)
    if skipped:
        print(f"  {report.get('reason', '')}", file=stream)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Enforce the v0.1.98 tie-cell recipe ordering rules "
                    "(setundef -zero before hilomap; no opt_clean after it) "
                    "in a Yosys synthesis recipe — either a .ys script or the "
                    "inline `yosys -p` command the runner echoed into its "
                    "synth log.")
    ap.add_argument("project_dir", nargs="?", default=None,
                    help="Project directory. Audits every .ys under the "
                         "canonical synthesis locations; if none of them is a "
                         "synthesis recipe, audits the inline `yosys -p` "
                         "command echoed in the runner's synth log instead. "
                         "rc 2 (NOT CHECKED) when neither exists.")
    ap.add_argument("--ys-file", dest="ys_file", default=None,
                    help="path to a single Yosys .ys synth script")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="optional path to write the JSON report")
    args = ap.parse_args(argv)

    if not args.project_dir and not args.ys_file:
        ap.error("either <project_dir> positional OR --ys-file is required")

    # ONE exit-routing site, in the entry function, reading the gate's OWN
    # structured conclusion. `gate_skip_routing_check` accuses (rule
    # `structured-skip-not-read-back`) any gate that writes a truthy `skipped`
    # into its result and then chooses an exit code without reading it back —
    # measured on an earlier draft of this file, where the routing lived in the
    # two mode helpers and `main` only forwarded their integer.
    if args.ys_file:
        report = audit_ys_file(args.ys_file)
    else:
        report = audit_project_dir(args.project_dir)

    _write_json(args.json_out, report)
    skipped = _vx.summary_is_skipped(report["summary"])
    passed = report["verdict"] != "VIOLATION"

    if args.ys_file:
        _print_ys_report(report, passed, skipped)
    else:
        _print_project_report(report, passed, skipped)
    if skipped:
        _vx.announce_vacuous(GATE, _vx.skip_reason(report["summary"]))
    return _vx.exit_code(passed, skipped)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
