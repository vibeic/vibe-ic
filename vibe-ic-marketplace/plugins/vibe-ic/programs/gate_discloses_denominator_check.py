#!/usr/bin/env python3
"""gate_discloses_denominator_check.py — a PASS must say how much it looked at.

THE CLASS (vibe-ic#447), measured four times before this existed
=================================================================
A gate answers PASS after examining NOTHING, and its output is
indistinguishable from a real clean run:

    nda_tracked_tree_scan        PASSed on 21 of 20143 blobs (cwd prefix shift)
    l4_systemrdl_export          audit-corpus found 0 of 201 documents -> PASS
                                 (skip-set matched the ABSOLUTE path)
    cross_layer_reference_check  46 cells in a checkout vs 23 in a worktree,
                                 making a COUNT-based baseline host-dependent
    source_chip_agnostic_check   a scan of 1239 files and a scan of 0 printed
                                 the same sentence, byte for byte

Four different walking bugs — cwd, absolute-vs-relative, tracked-vs-on-disk —
and one thing in common: NONE OF THEM COULD BE SEEN FROM THE OUTPUT. Each
survived until something unrelated exposed it.

WHAT THIS CHECKS, AND WHAT IT DELIBERATELY DOES NOT
====================================================
TWO POPULATIONS, ONE DISCRIMINATOR.

``--population ci`` (the default, and what CI wires) runs every gate in
``tools/ci/repo_hygiene_gates.sh`` against a scratch EMPTY repository and
requires that a PASS there DISCLOSE that it examined nothing.

``--population project`` (#511) runs EVERY ``programs/*_check.py`` — the whole
registry, not a sample — against a fresh, structurally empty PROJECT
(``input/docs/`` and ``reports/`` created, nothing in them), one throwaway
directory per gate because gates write into the project they audit. Same
requirement, same predicate.

#511 arrived as a deterministic SAMPLE of 41 of the 481 gates, which found two
that answered a bare ``[PASS] <gate>`` and nothing else. A sample establishes
that the class exists; it cannot say how big it is, and a fix sized to the
sample would leave the rest of the population unmeasured and unratcheted. The
census run by this population is the answer to both: it measures the whole
registry and it FREEZES the result, so the set can shrink but cannot grow
without a source edit somebody has to write.

THE INVENTORY IS THIS CHECK'S OWN DENOMINATOR
==============================================
``_EMPTY_PROJECT_SILENT_PASS`` names every gate measured to answer rc 0 over
an empty project without disclosing it, with a DATE and a reason. It is not an
excuse list: it is the count of what is still wrong, printed on every run,
whether the check passes or fails.

The comparison is EXACT-SET EQUALITY, in both directions, and that is the
whole mechanism:

  * a gate that goes silent and is NOT in the inventory FAILs the check — the
    list cannot absorb a new instance unnoticed, which is the defect a check
    like this exists to catch;
  * a gate IN the inventory that now discloses ALSO FAILs it, with "delete the
    entry" — so the list cannot keep claiming a defect that is fixed, and it
    can only ever be made shorter by a visible edit.

It does NOT require a gate to FAIL on an empty tree. PASS-on-empty is often
CORRECT — ``tracked_symlink_portability_check`` on a tree with no symlinks is
genuinely clean — and a check that demanded otherwise would fire on legitimate
state, which is how the orphan-capability detector (#439) earned deletion
rather than a landing.

    THE DISCRIMINATOR IS DISCLOSURE, NOT VERDICT.

A gate may say PASS over zero items as long as a reader can SEE that it was
zero: a count, or an explicit "no corpus" / "nothing to check" / SKIP.

MEASURED WHILE BUILDING IT, and the reason the discriminator is what it is: a
first version looked only at the LAST line for a digit and flagged 5 of 25.
Four were false — ``tracked_symlink_portability_check`` prints
``dangling ...: 0`` on the line ABOVE its verdict, and
``artefact_defect_close_check`` says ``[SKIPPED] no issue corpus``, which IS
the disclosure. Scanning the WHOLE output for a count or an explicit
nothing-statement gives **0 of 25**. The class is currently closed; this exists
to keep the fifth instance from landing.

The gate list is PARSED from the CI script rather than duplicated here, so a
gate added to CI is covered without anyone remembering to add it twice.

chip-AGNOSTIC: it reasons about process exit codes and output text only.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_PLUGIN = _HERE.parent

# This repo's disclosed-skip vocabulary is written with UNDERSCORES —
# `VACUOUS_PASS`, `PASS_SKIP`, `NOT_APPLICABLE`, `NOT_CHECKED`. `\b` does not
# match between a letter and `_` (both are word characters), so `\bVACUOUS\b`
# recognises NONE of them. Measured over all 481 `*_check.py` driven against an
# empty project: 26 gates that plainly disclose — `VACUOUS_PASS: no
# analog_block_list.json`, `PASS_SKIP — no CRC module found`,
# `"verdict": "NOT_APPLICABLE"` — were counted as silent, and only escaped
# being reported as such because the `\d` alternative happened to match a digit
# elsewhere in their output. `_` is the boundary here, so the tokens are
# matched as the tokens they are.
_TOKEN_RE = (r"(?<![A-Za-z])(?:SKIP|SKIPPED|VACUOUS|NOTHING_SCANNED"
             r"|NOT_APPLICABLE|NOT_CHECKED|NOT_RUN)(?![A-Za-z])")

# A gate discloses its scope with a NUMBER, or by saying plainly that there was
# nothing to examine. Both are honest; only silence is not.
#
# The nothing-statement is deliberately NOT a bare `\bno\b`: `benchmark_clean_
# room_check` prints "clean-room run dir (no inherited samples / scores)" over
# an empty directory, and that sentence describes the RESULT, not the
# population — it is exactly as true of a scan that read nothing as of one that
# read a thousand files. Requiring the negation to land on an
# examined/found/present verb keeps a statement ABOUT THE SCOPE ("no manifest
# files found") in and a statement about the finding out.
_DISCLOSURE_RE = re.compile(
    r"\d"
    r"|\bno\s+(?:issue\s+)?corpus\b"
    r"|\bnone\b|\bnothing\b|\bnot\s+present\b|\bnot\s+a\s+directory\b"
    r"|\bnot\s+applicable\b|\binapplicable\b"
    r"|\bno\s+[\w./*-]+(?:\s+[\w./*-]+){0,4}\s+"
    r"(?:found|present|detected|declared|exists?|emitted|available)\b"
    r"|" + _TOKEN_RE,
    re.IGNORECASE)


#: The non-numeric half of `_DISCLOSURE_RE`: a STATED REASON or a verdict
#: token, as opposed to a bare count. Split out so the census can report how
#: many rc-0 gates disclose with a number ONLY — see `_NUMBER_ONLY_DECISION`.
_REASON_RE = re.compile(
    r"\bno\s+(?:issue\s+)?corpus\b"
    r"|\bnone\b|\bnothing\b|\bnot\s+present\b|\bnot\s+a\s+directory\b"
    r"|\bnot\s+applicable\b|\binapplicable\b"
    r"|\bno\s+[\w./*-]+(?:\s+[\w./*-]+){0,4}\s+"
    r"(?:found|present|detected|declared|exists?|emitted|available)\b"
    r"|" + _TOKEN_RE,
    re.IGNORECASE)

# ---------------------------------------------------------------------------
# DOES A BARE COUNT SUFFICE? — decided here rather than by omission (#511).
#
# YES, it passes this check, and the residual is PUBLISHED rather than
# silently accepted. Three reasons, in order of weight:
#
#  1. The bar #511 states is disjunctive: "a VACUOUS_PASS token, a stated
#     reason, OR a denominator". `PASS — {'files_scanned': 0, 'violations': 0}`
#     IS a denominator — a reader can see the population was empty. It is
#     exactly what `_gate_denominator` asks for minus the written reason.
#  2. The CI population above has drawn this line since #447 ("a count, or an
#     explicit no-corpus / nothing-to-check / SKIP"), and that predicate was
#     measured: whole-output scanning gives 0 false flags of 25. Applying a
#     STRICTER bar to the second population would put two discriminators in
#     one program, disagreeing about the same output.
#  3. MEASURED 2026-07-28 over all 481: 202 gates exit 0, of which 151
#     disclose a reason or a token, 34 disclose with a number only, and 17
#     disclose nothing at all. Demanding prose of the 34 would put a set twice
#     the size of the real defect on an exemption list on day one — the shape
#     the issue warned against.
#
# WHAT THE COUNT DOES NOT BUY, and the reason `dead_plugin_path_check` was
# fixed in this same change despite already printing a number: the integer
# that matters is the SCAN SIZE, not the HIT COUNT. `files_scanned: 0` beside
# `violations: 0` is honest arithmetic; `0 retired-plugin reference(s)` with no
# scan size is the #447 class wearing a digit. From TEXT ALONE those two are
# not separable — you cannot tell which integer is the denominator without
# knowing what the gate's unit IS, which is precisely why `_gate_denominator`
# makes a gate NAME its unit instead of emitting a bare integer.
#
# So: the machine enforces the floor it can enforce, and REPORTS
# `rc_zero_number_only` on every run so the residual is a number somebody can
# act on rather than a silence. Narrowing it is per-gate work with a per-gate
# unit, not a predicate this program can tighten.
_NUMBER_ONLY_DECISION = (
    "a bare count passes this check (it IS a denominator); the count of gates "
    "disclosing with a number ONLY is published as rc_zero_number_only so the "
    "residual is visible, because a HIT count is not a SCAN SIZE and text "
    "alone cannot separate them")

# ---------------------------------------------------------------------------
# OUTSIDE THE 0/1/2 CONVENTION — recorded, not folded in (#511 side note).
#
# MEASURED 2026-07-28: three gates exit 3 over an empty project. rc 3 is the
# `PASS_WITH_WAIVERS` code `flow_compliance_check._check_program_exit_zero`
# honours ONLY when the `PASS_WITH_WAIVERS` stdout sentinel is also present —
# a bare rc 3 stays a FAIL there. These three are NOT a disclosure defect and
# are deliberately not judged by the disclosure rule (which asks only about
# rc 0); they are named here and counted in the census so "three gates sit
# outside the convention" is a visible fact rather than a gap in the histogram.
_RC_OUTSIDE_CONVENTION_NOTE = (
    "exit code outside this repo's 0=PASS / 1=FAIL / 2=NOT-CHECKED "
    "convention over an empty project; not a disclosure finding, recorded so "
    "the census has no unexplained residue")


def discloses(text: str) -> bool:
    """Does this gate's output say what it examined?

    ONE predicate for both populations. A second copy tuned per population is
    how the two would come to disagree about the same output.
    """
    return bool(_DISCLOSURE_RE.search(text or ""))


def discloses_a_reason(text: str) -> bool:
    """Stricter: does it say WHY, not merely how many?

    Reported, never enforced — see `_NUMBER_ONLY_DECISION`.
    """
    return bool(_REASON_RE.search(text or ""))


# ---------------------------------------------------------------------------
# THE INVENTORY (#511) — every `programs/*_check.py` MEASURED to answer rc 0
# over an empty project without saying what it examined.
#
# Read this as a defect register, not a permission list. Each entry is dated,
# names the exact output that made it silent, and is compared for EXACT SET
# EQUALITY on every run: a new instance cannot be absorbed here without a
# source edit, and a fixed one cannot stay here.
#
# WHY THESE FIFTEEN ARE RECORDED RATHER THAN REWRITTEN. Thirteen are one shape
# in one family — an analog/SPICE gate whose entire output is `[PASS] <gate>`
# when its subject (a block list, a corner sweep, a hardmacro, a SPICE
# correlation report) is absent. #511 fixed the two it MEASURED, and named the
# reason not to sweep the rest here: a batch rewrite of thirteen gates in the
# change that introduces the check is thirteen unmeasured edits riding on one
# measurement. They are stated, dated and frozen instead, so the next change
# that touches any of them has a red test telling it what to do.
#
# "FIX THE CONVENTION, NOT THE FOURTEEN GATES" — MEASURED, AND THERE IS NO
# SHARED SITE TO FIX. Every one of the fifteen carries its OWN inline
# `print(f"[{status}] <name>")` in its own `main()`; the convention is COPIED,
# not shared. `_analog_a_check_common` does have the family's emitters
# (`emit_pass`, `vacuous_pass`) and every gate that USES them already
# discloses — which is why the A1-A9 gates are absent from this list. None of
# the fifteen calls them (`analog_digital_interface_check` imports the module,
# for the ORGANIC #676 class predicate, not for rendering).
#
# So the convention fix is not one edit: a shared emitter can refuse to render
# a verdict without a denominator, but it cannot INVENT fifteen denominators —
# each gate has a different unit (blocks, corners, hardmacro views, netlist
# devices, Liberty arcs, correlation points) and a different vacuity
# condition, and computing them is per-gate work. What IS one edit, and is
# what this file delivers, is the machine that stops the SIXTEENTH being
# written the same way — and it is general over all 481 gates rather than
# scoped to this family.
#
# The two non-analog entries are different from each other and from the family:
#   * benchmark_clean_room_check answers "clean-room run dir (no inherited
#     samples / scores)" over a directory with no run in it at all. The
#     sentence is about the FINDING and is equally true of a scan that read
#     nothing, which is the #447 class in prose form rather than in a count.
#   * corner_yield_vs_spec_check prints the bare family one-liner but is not
#     part of the analog A1-A9 family, so it does not share their fix.
# ---------------------------------------------------------------------------
_MEASURED_ON = "2026-07-28"

# #521 CLOSED FOURTEEN OF THE FIFTEEN, AND THE MECHANISM ABOVE IS WHAT
# REQUIRED THE DELETION. Every analog / SPICE entry that was frozen here on
# 2026-07-28 has been removed, because each of those gates now routes its own
# `summary["skipped"]` through `_vacuous_exit.exit_code` and answers rc 2 —
# not rc 0 — over a project with nothing in it. `audit_project_gates` only
# collects `silent` from rc-0 results, so leaving the entries in place would
# have raised fourteen STALE_INVENTORY_ENTRY findings. That is the ratchet
# working exactly as its docstring promises: the list got SHORTER, by a
# visible edit, and it could not have stayed the same.
#
# The prediction in the note above — "a batch rewrite of thirteen gates is
# thirteen unmeasured edits riding on one measurement" — was the right caution
# and is answered by measurement rather than waived: the seventeen gates of
# #521 were swept over 200 tracked project roots before and after, and the
# only tier movement is PASS -> VACUOUS.
#
# `benchmark_clean_room_check` is untouched and REMAINS. Its defect is a
# different one (a sentence that states the finding rather than the
# population, while the gate genuinely exits 0), so #521's fix does not reach
# it and it must keep being counted.
_EMPTY_PROJECT_SILENT_PASS: Dict[str, Dict[str, str]] = {
    name: {"measured": _MEASURED_ON, "reason": reason}
    for name, reason in (
        ("benchmark_clean_room_check",
         "`PASS: clean-room run dir (no inherited samples / scores)` states "
         "the finding, not the population — equally true over a directory "
         "with no run in it"),
    )
}

#: Gates that cannot be driven against an empty project at all, with the
#: reason. Measured 2026-07-28 over all 481: this list is EMPTY — every gate
#: ran and returned an exit code inside the timeout. It exists so that a gate
#: which later stops being driveable has somewhere to be RECORDED rather than
#: quietly dropped from the population.
_UNDRIVEABLE: Dict[str, Dict[str, str]] = {}

_RUN_RE = re.compile(
    # Accepts BOTH `run` and its `run_*` variants. A wrapper added for one
    # gate (`run_tolerating_uncheckable`) silently escaped this parser, so any
    # gate wired through it would not be covered — a coverage hole in the very
    # check that exists to close coverage holes.
    r'^\s*run(?:_\w+)?\s+"([^"]+)"\s+"?(\$ROOT|\$PLUGIN)"?\s+(.+)$', re.M)


def parse_gates(script: Path) -> List[Tuple[str, str, str]]:
    """(label, cwd-token, command) for every `run` line in the CI script."""
    try:
        text = script.read_text(errors="replace")
    except OSError:
        return []
    return [(m.group(1), m.group(2), m.group(3).strip())
            for m in _RUN_RE.finditer(text)]


def _scratch_repo(base: Path) -> Path:
    """An empty but VALID git repository — several gates ask git for a
    tracked-file list, and a non-repo would make them fail for the wrong
    reason."""
    d = base / "empty"
    d.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(d), "config", k, v], check=True)
    (d / "seed.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(d), "add", "seed.txt"], check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-qm", "base"], check=True)
    return d


def _expand(cmd: str, repo_root: Path, scratch: Path) -> List[str]:
    c = cmd.replace('"$PG/', str(_HERE) + "/")
    c = c.replace('"$ROOT/', str(repo_root) + "/")
    c = c.replace('"', "")
    c = c.replace("$PLUGIN", str(_PLUGIN))
    c = c.replace("$ROOT", str(scratch))
    return c.split()


def audit(repo_root: Path, timeout: int = 120) -> Tuple[str, List[Dict]]:
    script = repo_root / "tools" / "ci" / "repo_hygiene_gates.sh"
    gates = parse_gates(script)
    if not gates:
        # Never a silent PASS — this program's own denominator.
        return "NOTHING_SCANNED", []

    findings: List[Dict] = []
    with tempfile.TemporaryDirectory() as td:
        scratch = _scratch_repo(Path(td))
        for label, _wd, cmd in gates:
            argv = _expand(cmd, repo_root, scratch)
            try:
                r = subprocess.run(argv, cwd=str(scratch), capture_output=True,
                                   text=True, timeout=timeout)
            except (OSError, subprocess.SubprocessError) as exc:
                findings.append({
                    "gate": label, "kind": "GATE_UNRUNNABLE",
                    "detail": f"could not be driven against a scratch tree: {exc}",
                })
                continue
            out = (r.stdout or "") + (r.stderr or "")
            if r.returncode == 0 and not discloses(out):
                findings.append({
                    "gate": label, "kind": "PASS_WITHOUT_DENOMINATOR",
                    "detail": ("answered PASS over an EMPTY tree without "
                               "disclosing that it examined nothing — this "
                               "output is indistinguishable from a real clean "
                               "run"),
                    "output_tail": out.strip().splitlines()[-1][:200]
                    if out.strip() else "(no output at all)",
                })
    return ("FAIL" if findings else "PASS"), findings


# ── population 2 (#511): every `programs/*_check.py`, over an empty PROJECT ──

def project_check_programs(programs_dir: Path) -> List[Path]:
    """Every registered gate program, in a stable order."""
    return sorted(programs_dir.glob("*_check.py"))


def _drive_on_empty_project(prog: Path, timeout: int) -> Dict:
    """Run ONE gate against its OWN fresh empty project.

    A fresh directory per gate, never a shared one: gates write into the
    project they audit, so a shared scratch would let gate N's report become
    gate N+1's input and the population would stop being empty part-way
    through.

    The exit code is captured DIRECTLY from the child. Nothing is piped.
    """
    with tempfile.TemporaryDirectory(prefix="empty_project_") as td:
        proj = Path(td)
        (proj / "input" / "docs").mkdir(parents=True)
        (proj / "reports").mkdir(parents=True)
        try:
            r = subprocess.run([sys.executable, str(prog), "."],
                               cwd=str(proj), capture_output=True, text=True,
                               timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"gate": prog.stem, "rc": None, "disclosed": None,
                    "unrunnable": f"exceeded the {timeout}s probe budget"}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"gate": prog.stem, "rc": None, "disclosed": None,
                    "unrunnable": f"could not be driven: {exc}"}
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    return {"gate": prog.stem, "rc": r.returncode,
            "disclosed": discloses(out),
            "reasoned": discloses_a_reason(out),
            "output_tail": (out.splitlines()[-1][:200] if out
                            else "(no output at all)")}


def audit_project_gates(programs_dir: Path, timeout: int = 120,
                        workers: int = 0) -> Tuple[str, List[Dict], Dict]:
    """Drive EVERY `*_check.py` against an empty project; ratchet the result.

    Returns ``(verdict, findings, stats)``. ``stats`` carries the census —
    how many gates, how many answered rc 0, how many of those disclosed —
    because a check that reports only its findings publishes no denominator of
    its own, which is the thing it is here to require of others.
    """
    progs = project_check_programs(programs_dir)
    if not progs:
        # Never a silent PASS — this program's own denominator.
        return "NOTHING_SCANNED", [], {"gates_probed": 0}

    workers = workers or min(8, (os.cpu_count() or 2))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(
            lambda p: _drive_on_empty_project(p, timeout), progs))

    findings: List[Dict] = []
    silent: List[str] = []
    number_only: List[str] = []
    outside_convention: List[Dict] = []
    unrunnable: List[str] = []
    rc0 = 0
    for res in results:
        gate = res["gate"]
        if res["rc"] not in (None, 0, 1, 2):
            # Recorded, not judged — see `_RC_OUTSIDE_CONVENTION_NOTE`.
            outside_convention.append({"gate": gate, "rc": res["rc"],
                                       "note": _RC_OUTSIDE_CONVENTION_NOTE})
        if res.get("unrunnable"):
            unrunnable.append(gate)
            if gate not in _UNDRIVEABLE:
                findings.append({
                    "gate": gate, "kind": "GATE_UNRUNNABLE",
                    "detail": res["unrunnable"] + " — record it in "
                              "_UNDRIVEABLE with a reason, or fix it; a gate "
                              "that silently leaves the population is a hole "
                              "in the census",
                })
            continue
        if res["rc"] != 0:
            continue
        rc0 += 1
        if res["disclosed"]:
            if not res.get("reasoned"):
                # Discloses with a NUMBER only. Passes (see
                # `_NUMBER_ONLY_DECISION`) and is counted, never hidden.
                number_only.append(gate)
            continue
        silent.append(gate)
        if gate not in _EMPTY_PROJECT_SILENT_PASS:
            findings.append({
                "gate": gate, "kind": "PASS_WITHOUT_DENOMINATOR",
                "detail": ("answered rc 0 over a structurally EMPTY project "
                           "without disclosing that it examined nothing — "
                           "this output is indistinguishable from a real "
                           "clean run. Give it a `_gate_denominator` "
                           "denominator, or record it in "
                           "_EMPTY_PROJECT_SILENT_PASS with a date and a "
                           "reason; the inventory is visible and cannot grow "
                           "without this edit"),
                "output_tail": res["output_tail"],
            })

    # The other direction: an inventory entry that no longer describes reality.
    for gate in sorted(_EMPTY_PROJECT_SILENT_PASS):
        if gate not in silent:
            findings.append({
                "gate": gate, "kind": "STALE_INVENTORY_ENTRY",
                "detail": ("recorded in _EMPTY_PROJECT_SILENT_PASS as "
                           "answering a bare PASS over an empty project, but "
                           "it no longer does (it discloses, no longer exits "
                           "0, or no longer exists). DELETE the entry — an "
                           "inventory that keeps fixed defects on it stops "
                           "being a count of what is wrong"),
            })
    for gate in sorted(_UNDRIVEABLE):
        if gate not in unrunnable:
            findings.append({
                "gate": gate, "kind": "STALE_UNDRIVEABLE_ENTRY",
                "detail": ("recorded in _UNDRIVEABLE, but it CAN now be "
                           "driven against an empty project. DELETE the "
                           "entry"),
            })

    stats = {
        "gates_probed": len(progs),
        "rc_zero": rc0,
        "rc_zero_disclosing": rc0 - len(silent),
        # Of the disclosing ones, how many say WHY vs merely HOW MANY.
        "rc_zero_reasoned": rc0 - len(silent) - len(number_only),
        "rc_zero_number_only": len(number_only),
        "rc_zero_number_only_decision": _NUMBER_ONLY_DECISION,
        "rc_zero_silent": len(silent),
        "inventory_size": len(_EMPTY_PROJECT_SILENT_PASS),
        "inventory_measured_on": _MEASURED_ON,
        "undriveable_size": len(_UNDRIVEABLE),
        "silent_gates": sorted(silent),
        "number_only_gates": sorted(number_only),
        "rc_outside_convention": sorted(outside_convention,
                                        key=lambda d: d["gate"]),
    }
    return ("FAIL" if findings else "PASS"), findings, stats


def _print_inventory(stats: Dict) -> None:
    """The inventory IS this check's denominator, so it is printed on every
    run — passing or failing. A count nobody sees until something breaks is
    the shape that lets a list grow."""
    print(f"  KNOWN-SILENT INVENTORY (this check's own denominator): "
          f"{stats.get('inventory_size', 0)} gate(s), measured "
          f"{stats.get('inventory_measured_on')}", file=sys.stderr)
    for gate in sorted(_EMPTY_PROJECT_SILENT_PASS):
        meta = _EMPTY_PROJECT_SILENT_PASS[gate]
        print(f"    {meta['measured']}  {gate}: {meta['reason']}",
              file=sys.stderr)
    print(f"  UNDRIVEABLE: {stats.get('undriveable_size', 0)} gate(s)",
          file=sys.stderr)
    for gate in sorted(_UNDRIVEABLE):
        print(f"    {_UNDRIVEABLE[gate]['measured']}  {gate}: "
              f"{_UNDRIVEABLE[gate]['reason']}", file=sys.stderr)


def _main_project_population(a) -> int:
    programs_dir = Path(a.programs_dir).resolve() if a.programs_dir else _HERE
    verdict, findings, stats = audit_project_gates(
        programs_dir, timeout=a.timeout)

    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            {"verdict": verdict, "population": "project",
             "programs_dir": str(programs_dir),
             "inventory": _EMPTY_PROJECT_SILENT_PASS,
             "undriveable": _UNDRIVEABLE,
             "findings": findings, **stats}, indent=2) + "\n")

    if verdict == "NOTHING_SCANNED":
        print(f"NOTHING_SCANNED: no `*_check.py` found under {programs_dir} — "
              f"this check would otherwise report a clean result over an empty "
              f"gate list, which is the very defect it exists to catch.",
              file=sys.stderr)
        return 2

    for f in findings:
        print(f"  [{f['kind']}] {f['gate']}", file=sys.stderr)
        print(f"      {f['detail']}", file=sys.stderr)
        if f.get("output_tail"):
            print(f"      last line: {f['output_tail']}", file=sys.stderr)

    print(f"  probed {stats['gates_probed']} programs/*_check.py against a "
          f"structurally EMPTY project (input/docs/ + reports/, nothing in "
          f"them), one fresh directory each", file=sys.stderr)
    print(f"  rc 0: {stats['rc_zero']} | disclosing: "
          f"{stats['rc_zero_disclosing']} (reason "
          f"{stats['rc_zero_reasoned']} / number-only "
          f"{stats['rc_zero_number_only']}) | silent: "
          f"{stats['rc_zero_silent']}", file=sys.stderr)
    print(f"  NUMBER-ONLY (passes; published, not hidden): "
          f"{_NUMBER_ONLY_DECISION}", file=sys.stderr)
    if stats["rc_outside_convention"]:
        print(f"  OUTSIDE THE 0/1/2 CONVENTION: "
              f"{len(stats['rc_outside_convention'])} gate(s), recorded not "
              f"judged", file=sys.stderr)
        for e in stats["rc_outside_convention"]:
            print(f"    rc {e['rc']}  {e['gate']}", file=sys.stderr)
    _print_inventory(stats)

    if findings:
        print(f"[FAIL] {len(findings)} disclosure finding(s) over "
              f"{stats['gates_probed']} gate(s).", file=sys.stderr)
        return 1
    print(f"[PASS] every rc-0 gate of {stats['gates_probed']} either discloses "
          f"what it examined or is on the dated inventory above.",
          file=sys.stderr)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("repo_root", nargs="?", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument(
        "--population", choices=("ci", "project"), default="ci",
        help=("`ci` (default) probes the gates wired into "
              "tools/ci/repo_hygiene_gates.sh against an empty REPO; "
              "`project` probes every programs/*_check.py against an empty "
              "PROJECT (#511)"))
    ap.add_argument("--programs-dir", dest="programs_dir", default=None,
                    help="`project` population only: the directory holding "
                         "*_check.py (default: this program's own directory)")
    ap.add_argument("--timeout", type=int, default=120,
                    help="per-gate probe budget in seconds (default 120)")
    a = ap.parse_args(argv)

    if a.population == "project":
        return _main_project_population(a)

    root = Path(a.repo_root).resolve() if a.repo_root else _PLUGIN.parents[2]
    verdict, findings = audit(root, timeout=a.timeout)
    gates = parse_gates(root / "tools" / "ci" / "repo_hygiene_gates.sh")

    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            {"verdict": verdict, "population": "ci",
             "gates_probed": len(gates),
             "findings": findings}, indent=2) + "\n")

    if verdict == "NOTHING_SCANNED":
        print(f"NOTHING_SCANNED: no `run` lines parsed from "
              f"{root}/tools/ci/repo_hygiene_gates.sh — this check would "
              f"otherwise report a clean result over an empty gate list, "
              f"which is the very defect it exists to catch.", file=sys.stderr)
        return 2

    for f in findings:
        print(f"  [{f['kind']}] {f['gate']}", file=sys.stderr)
        print(f"      {f['detail']}", file=sys.stderr)
        if f.get("output_tail"):
            print(f"      last line: {f['output_tail']}", file=sys.stderr)

    if findings:
        print(f"[FAIL] {len(findings)} gate(s) of {len(gates)} answer PASS "
              f"over an empty tree without disclosing it.", file=sys.stderr)
        return 1
    print(f"[PASS] all {len(gates)} CI gate(s) disclose what they examined "
          f"(probed against an empty tree).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
