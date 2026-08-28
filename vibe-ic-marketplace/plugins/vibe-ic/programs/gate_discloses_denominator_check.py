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
import time
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_PLUGIN = _HERE.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import _watchdog as _wd  # noqa: E402  progress-stall process supervision

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

# ── the ONE parser of the hygiene script ────────────────────────────────────
# `gate_host_independence_check` imports `parse_declarations` from here rather
# than carrying a second copy of it. It used to carry a verbatim copy of a
# regex, and the copy is what let the gap below stay invisible in BOTH readers
# at once: a defect fixed in one would have had to be noticed twice.
#
# MEASURED at v1.9.77, which is why this is a scanner and no longer a regex:
#
#     the dispatcher's own record (`--list --summary-json`)   68 invocations
#     what the regex found                                    59
#
# The nine it could not see are 3 gates x 3 published cells, declared inside
#
#     for _cell in "$ROOT"/benchmark-data/ic/*/*/; do
#       run_tolerating_uncheckable "DRC PASS is not vacuous ($(basename ...))" \
#         "$ROOT" python3 "$PG/drc_vacuous_pass_check.py" "$_cell"
#
# and the regex missed them TWICE over:
#
#   * its label group was `"([^"]+)"`, which stops at the FIRST inner quote —
#     the one inside `$(basename "$(dirname "$_cell")")` — so the line matched
#     nothing at all and the gate was absent from the denominator; and
#   * it never folded `\` continuations, so the four gates written across two
#     lines were captured TRUNCATED. One of them, `severity=ERROR is consumed`,
#     was thereby "probed" with a bare `\` as its last argument: what the
#     host-independence probe compared was argparse rejecting a stray
#     backslash (rc 2) in both trees, not the gate.
#
# A DECLARATION IS NOT AN INVOCATION, and conflating them is what made the
# gap look like a parser bug alone. A `run` line inside a loop is declared
# ONCE and invoked once per iteration, so the two counts differ BY DESIGN
# (59 declarations, 68 invocations). Everything downstream reconciles them
# instead of asserting they are equal.
_RUN_HEAD_RE = re.compile(r'^(\s*)run(?:_\w+)?\s+(.*)$')

# Shared with ``gate_host_independence_check``.  The declaration belongs to
# the run line, so every meta-runner must preserve it; otherwise an excluded
# remote gate simply comes back through a nested sweep.
HOST_INDEPENDENCE_EXCLUDE_RE = re.compile(
    r'^\s*#\s*host-independence:\s*EXCLUDE\b[\s—:-]*(.*?)\s*$')

#: Shell parameters this repo's readers can resolve to a real path. Anything
#: else in a declaration — a loop variable, a command substitution — is
#: RUNTIME-EXPANDED: only bash, at the moment it iterates, knows what it is.
_RESOLVABLE_VARS = frozenset({"ROOT", "PLUGIN", "PG", "PJSON"})
_VAR_RE = re.compile(r'\$\{?([A-Za-z_]\w*)\}?')


class GateDecl(NamedTuple):
    """One `run` line as the hygiene script DECLARES it.

    `lineno` is 1-based and points at the line the `run` keyword is on, which
    is what the host-independence EXCLUDE directive is anchored against.

    `runtime_expansion` is None for a declaration a reader can drive as
    written, and otherwise NAMES the piece only bash can resolve. It is a
    disclosure, not a filter: such a gate stays in every denominator, and a
    reader that cannot drive it must SAY so rather than drop it.
    """
    label: str
    cwd_token: str
    cmd: str
    lineno: int
    runtime_expansion: Optional[str]
    host_independence_exclusion: Optional[str] = None


def _logical_lines(text: str) -> List[Tuple[int, str]]:
    """(1-based line number of the FIRST physical line, joined text).

    Backslash continuations are folded, so a gate written across two lines is
    read as the one command bash runs.
    """
    out: List[Tuple[int, str]] = []
    buf: List[str] = []
    start = 1
    for i, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.rstrip()
        if not buf:
            start = i
        if stripped.endswith("\\"):
            buf.append(stripped[:-1].rstrip())
            continue
        buf.append(stripped)
        out.append((start, " ".join(x for x in buf if x != "")))
        buf = []
    if buf:
        out.append((start, " ".join(x for x in buf if x != "")))
    return out


def _read_quoted(s: str) -> Optional[Tuple[str, str]]:
    """Read one double-quoted shell word off the front of `s`.

    Returns (contents, rest) or None. A `"` inside a `$( … )` substitution does
    NOT close the word — that is exactly the quote the old regex stopped at.
    """
    if not s.startswith('"'):
        return None
    depth = 0
    i = 1
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            i += 2
            continue
        if c == "$" and s[i + 1:i + 2] == "(":
            depth += 1
            i += 2
            continue
        if c == ")" and depth:
            depth -= 1
        elif c == '"' and depth == 0:
            return s[1:i], s[i + 1:]
        i += 1
    return None


def _runtime_expansion(label: str, cmd: str) -> Optional[str]:
    """The piece of this declaration only bash can resolve, or None."""
    for where, text in (("label", label), ("command", cmd)):
        if "$(" in text:
            frag = text[text.index("$("):][:60]
            return f"a command substitution in the {where}: {frag}"
        for m in _VAR_RE.finditer(text):
            if m.group(1) not in _RESOLVABLE_VARS:
                return (f"the shell variable ${m.group(1)} in the {where} — "
                        f"it is bound by the enclosing loop, not by this "
                        f"reader")
    return None


def parse_declarations(script: Path) -> List[GateDecl]:
    """Every gate the hygiene script declares, continuations folded."""
    try:
        text = script.read_text(errors="replace")
    except OSError:
        return []
    physical = text.splitlines()
    out: List[GateDecl] = []
    for lineno, line in _logical_lines(text):
        m = _RUN_HEAD_RE.match(line)
        if not m:
            continue
        got = _read_quoted(m.group(2).strip())
        if got is None:
            continue
        label, rest = got
        rest = rest.lstrip()
        cwd_quoted = _read_quoted(rest)
        if cwd_quoted is not None:
            cwd_token, rest = cwd_quoted
        else:
            parts = rest.split(None, 1)
            if not parts:
                continue
            cwd_token, rest = parts[0], (parts[1] if len(parts) > 1 else "")
        if cwd_token not in ("$ROOT", "$PLUGIN"):
            continue
        cmd = rest.strip()
        if not cmd:
            continue
        above = physical[lineno - 2] if lineno >= 2 else ""
        excluded = HOST_INDEPENDENCE_EXCLUDE_RE.match(above)
        reason = None
        if excluded:
            reason = (excluded.group(1).strip()
                      or "declared at the gate, no reason given")
        out.append(GateDecl(label, cwd_token, cmd, lineno,
                            _runtime_expansion(label, cmd), reason))
    return out


def parse_gates(script: Path) -> List[Tuple[str, str, str]]:
    """(label, cwd-token, command) for every `run` line in the CI script."""
    return [(g.label, g.cwd_token, g.cmd) for g in parse_declarations(script)]


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
    # A LOOP VARIABLE IS BOUND TO THE SCRATCH TREE, and that is the faithful
    # binding rather than a convenience: this probe's entire fixture is "drive
    # the gate against an empty tree and see whether it says so", and the loop
    # gates take exactly one argument — the directory to examine. Leaving the
    # token unsubstituted handed the gate the literal string `$_cell`, which is
    # a path that cannot exist, so the probe would have measured "the gate
    # refused a nonexistent directory" and counted that as coverage.
    c = _VAR_RE.sub(
        lambda m: (m.group(0) if m.group(1) in _RESOLVABLE_VARS
                   else str(scratch)), c)
    return c.split()


class CiAudit(NamedTuple):
    """The CI-population result, carrying its own denominator.

    `declared` vs `probed` is the disclosure this program spent a version
    demanding of everybody else and did not make itself: the verdict line said
    "all N CI gate(s) disclose what they examined" using the DECLARED count
    while N of them had never been launched at all.
    """
    verdict: str
    findings: List[Dict]
    declared: int
    probed: int
    not_driven: List[Tuple[str, str]]   # (label, why)
    #: vibe-ic#1181 — the loop ran out of its AGGREGATE budget and stopped
    #: early. Carried as its own field, not folded into `not_driven`, because
    #: the two are different sentences: a gate that is `not_driven` was
    #: examined and found undriveable, and a gate dropped by the budget was
    #: never looked at. Only the second one makes the verdict unsafe to read
    #: as clean.
    truncated: bool = False


def _driveable(argv: List[str]) -> Optional[str]:
    """Why this argv cannot be launched, or None.

    Checked BEFORE the run rather than inferred from the child's stderr: a
    python interpreter that cannot open its script exits 2 with a message, and
    rc 2 is indistinguishable here from a gate that honestly refused. MEASURED
    on the real script at v1.9.77: 21 of 59 gates are `$PLUGIN`-relative
    (`python3 programs/x.py`) and this probe runs every gate from the scratch
    tree, so the interpreter never found the file — and all 21 were counted in
    the "all 59 disclose" sentence.
    """
    if len(argv) < 2:
        return "no program to launch"
    prog = Path(argv[1])
    if not prog.is_absolute():
        return (f"the gate names a path relative to its own cwd ({argv[1]}) "
                f"and this probe runs every gate from the scratch tree, so "
                f"the interpreter cannot open it")
    if not prog.is_file():
        return f"{prog} does not exist"
    return None


def audit_ci(repo_root: Path, timeout: int = 120,
             budget: Optional[float] = None,
             skip_host_excluded: bool = False) -> CiAudit:
    """Drive every declared CI gate over an empty scratch tree.

    `timeout` bounds ONE gate. `budget` bounds the WHOLE loop, and vibe-ic#1181
    is why it exists: without it this function's runtime is the SUM of up to 74
    per-gate timeouts and nothing caps it. MEASURED on an idle host at
    a38902d1 — 74 declared, 50 driven, **192.9s**, slowest single gate 35.1s.
    That is already past the suite's own `--timeout=180`, and the worst case is
    50 x 120s.

    Why the per-test timeout could not save it: the wait is inside
    `subprocess.run`, and `pytest-timeout --timeout-method=thread` cannot
    interrupt a blocking syscall. The timeout fired, printed its stack, and the
    invocation still never finished — so the WHOLE pytest run produced no
    summary line and every other file in that selection went unmeasured. That
    is the same ambiguity as `no tests ran`: it greps as neither pass nor fail.

    TRUNCATION IS NOT A PASS. When the budget runs out the remaining gates are
    recorded in `not_driven` and `truncated` is set, and the verdict becomes
    `NOT_CHECKED` rather than `PASS` — "I could not look" must never arrive as
    "I looked and it was clean". A FINDING still outranks it: a violation found
    over a partial view is still a violation, which is the same rule
    `flow_step_execution_coverage_check` applies to its own partial sweeps.
    """

    script = repo_root / "tools" / "ci" / "repo_hygiene_gates.sh"
    gates = parse_declarations(script)
    if not gates:
        # Never a silent PASS — this program's own denominator.
        return CiAudit("NOTHING_SCANNED", [], 0, 0, [])

    findings: List[Dict] = []
    not_driven: List[Tuple[str, str]] = []
    truncated = False
    deadline = None if budget is None else time.monotonic() + float(budget)

    # PARALLEL, AND A FRESH SCRATCH PER GATE — the two are one decision.
    #
    # vibe-ic#1181: serially this loop measured 192.9s on an idle host (74
    # declared, 50 driven), already past the suite's `--timeout=180`, and the
    # per-test timeout could not end it because the wait is inside
    # `subprocess.run`. Fanning the gates out brings the wall clock under the
    # harness bound, which is what actually closes the issue; the aggregate
    # `budget` below stays as the backstop for the pathological case.
    #
    # The shared scratch could not survive the fan-out, and should not have
    # survived serially either: THESE GATES WRITE INTO THE TREE THEY AUDIT.
    # `_drive_on_empty_project` already says so for the other population — "a
    # fresh directory per gate, never a shared one: gates write into the
    # project they audit, so a shared scratch would let gate N's report become
    # gate N+1's input and the population would stop being empty part-way
    # through". The CI population had exactly that defect and it was invisible
    # because the order was fixed. One scratch per gate removes it and is what
    # makes concurrency safe.
    def _probe(decl):
        """Drive one gate in its own empty repo. Returns (kind, label, payload)."""
        label, cmd = decl.label, decl.cmd
        if skip_host_excluded and decl.host_independence_exclusion is not None:
            return ("not_driven", label,
                    "EXCLUDED from host-independence by its adjacent "
                    f"declaration: {decl.host_independence_exclusion}")
        if deadline is not None and time.monotonic() >= deadline:
            return ("budget", label,
                    f"aggregate budget of {budget:g}s exhausted before this "
                    f"gate was launched (vibe-ic#1181)")
        # Driveability is a property of the ARGV SHAPE, so it is
        # decided before a scratch tree is made — making one for a
        # gate that will not be driven is 74 wasted `git init`s.
        # The placeholder never reaches a subprocess: the argv that
        # runs is re-expanded against the real scratch below.
        argv = _expand(cmd, repo_root, Path('/nonexistent-probe'))
        why = _driveable(argv)
        if why is not None:
            return ("not_driven", label, why)
        # TWO BOUNDS, BECAUSE THEY MEAN DIFFERENT THINGS — and they used to be
        # ONE number, which is why a healthy gate could be filed as a defect.
        #
        # `timeout` was a per-gate WALL, and its expiry outside the aggregate
        # budget filed GATE_UNRUNNABLE → verdict FAIL. That is a finding
        # against a gate for being SLOW. This repo's own hygiene suite takes
        # ~57 min end to end with one gate two thirds of it, and eight of these
        # probes run concurrently on whatever else the host is doing, so the
        # number decided the verdict far more often than the gate did. It is
        # now the STALL GRACE: a gate whose CPU, I/O and output have ALL sat
        # flat for that long is hung, and calling THAT unrunnable is true.
        #
        # `budget` (#1181) is the aggregate probe budget, and it is NOT a
        # verdict — its expiry marks the sweep truncated → NOT_CHECKED, an
        # honest "how far it got". So it stays a wall clock, moved onto the
        # supervisor's `abort_probe`, which stops the child with its own
        # distinct outcome instead of being folded into the stall.
        def _budget_spent():
            if deadline is not None and time.monotonic() > deadline:
                return (f"aggregate budget of {budget:g}s ran out while "
                        f"this gate was running (vibe-ic#1181)")
            return None

        with tempfile.TemporaryDirectory() as gd:
            scratch = _scratch_repo(Path(gd))
            argv = _expand(cmd, repo_root, scratch)
            # The abort predicate is only READ once per poll, so the poll
            # cadence has to be able to notice the budget. Left at the cadence
            # derived from the (large) stall grace, a 3 s aggregate budget was
            # acted on 30 s late — measured. This is an observation cadence,
            # never a runtime bound: sampling more often can only make the
            # supervisor NOTICE sooner, never kill a working job.
            kw = {}
            if deadline is not None:
                kw["poll_s"] = max(0.25, min(float(timeout) / 4.0,
                                             float(budget) / 4.0))
            try:
                r = _wd.run_host_supervised(
                    argv, cwd=str(scratch), stall_grace_s=float(timeout),
                    abort_probe=(_budget_spent if deadline is not None
                                 else None), **kw)
            except (OSError, subprocess.SubprocessError) as exc:
                return ("unrunnable", label, str(exc))
            if r.outcome == "launch_error":
                return ("unrunnable", label, r.err)
            if r.aborted:
                return ("budget", label, r.abort_reason)
            if r.stalled:
                return ("unrunnable", label,
                        f"made no forward progress — no CPU, no I/O and no "
                        f"output — for {timeout}s, and was stopped as hung")
            out = (r.out or "") + (r.err or "")
            if r.rc == 0 and not discloses(out):
                return ("silent", label, out)
            return ("ok", label, "")

    workers = min(8, (os.cpu_count() or 2))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for kind, label, payload in ex.map(_probe, gates):
            if kind == "budget":
                truncated = True
                not_driven.append((label, payload))
            elif kind == "not_driven":
                not_driven.append((label, payload))
            elif kind == "unrunnable":
                findings.append({
                    "gate": label, "kind": "GATE_UNRUNNABLE",
                    "detail": f"could not be driven against a scratch tree: "
                              f"{payload}",
                })
            elif kind == "silent":
                findings.append({
                    "gate": label, "kind": "PASS_WITHOUT_DENOMINATOR",
                    "detail": ("answered PASS over an EMPTY tree without "
                               "disclosing that it examined nothing — this "
                               "output is indistinguishable from a real clean "
                               "run"),
                    "output_tail": payload.strip().splitlines()[-1][:200]
                    if payload.strip() else "(no output at all)",
                })

    # ORDER IS THE CLAIM. A finding survives truncation — a violation seen
    # over a partial view is still a violation. Absence does not: with the
    # loop cut short, "no findings" is a statement about how far it got.
    verdict = "FAIL" if findings else ("NOT_CHECKED" if truncated else "PASS")
    return CiAudit(verdict, findings, len(gates),
                   len(gates) - len(not_driven), not_driven, truncated)


def audit(repo_root: Path, timeout: int = 120,
          budget: Optional[float] = None) -> Tuple[str, List[Dict]]:
    """Back-compatible view of `audit_ci` — the verdict and the findings."""
    res = audit_ci(repo_root, timeout=timeout, budget=budget)
    return res.verdict, res.findings


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
        # `timeout` is the STALL GRACE, not a probe wall. As a wall its
        # expiry filed GATE_UNRUNNABLE → FAIL, i.e. a census hole reported
        # against a gate that was merely slower than the constant on a host
        # running eight of these at once.
        try:
            r = _wd.run_host_supervised(
                [sys.executable, str(prog), "."], cwd=str(proj),
                stall_grace_s=float(timeout))
        except (OSError, subprocess.SubprocessError) as exc:
            return {"gate": prog.stem, "rc": None, "disclosed": None,
                    "unrunnable": f"could not be driven: {exc}"}
        if r.outcome == "launch_error":
            return {"gate": prog.stem, "rc": None, "disclosed": None,
                    "unrunnable": f"could not be driven: {r.err}"}
        if r.stalled:
            return {"gate": prog.stem, "rc": None, "disclosed": None,
                    "unrunnable": f"made no forward progress for {timeout}s "
                                  f"and was stopped as hung"}
    out = ((r.out or "") + (r.err or "")).strip()
    return {"gate": prog.stem, "rc": r.rc,
            "disclosed": discloses(out),
            "reasoned": discloses_a_reason(out),
            "output_tail": (out.splitlines()[-1][:200] if out
                            else "(no output at all)")}


#: A path that does not exist, and cannot be made to exist by a gate that
#: mkdir -p's its own outputs.
_ABSENT = "/nonexistent/vibeic-absent-project-fixture/no-such-project"

#: Two phrasings the shared `_REASON_RE` does not reach, both measured in this
#: population: "gate not YET applicable", and "no <noun> directory" with no
#: trailing found/present verb. Widened HERE rather than in `_REASON_RE`,
#: because loosening the shared predicate would also loosen the empty-project
#: fixture, which is not the thing being changed.
_ABSENT_REASON_RE = re.compile(
    r"not\s+(?:yet\s+)?applicable"
    r"|\bno\s+[\w./*-]+(?:\s+[\w./*-]+){0,4}\s+"
    r"(?:director(?:y|ies)|tree|file|dir)\b", re.IGNORECASE)


def _honest_about_an_absent_project(out: str) -> bool:
    """A reason, OR every count it published is zero.

    THE DISCRIMINATOR IS A NONZERO COUNT, and getting here took two wrong
    standards, each caught by replaying the real strings.

    `discloses` (the empty-project standard) accepts a bare count, and passed
    the very program this fixture was built for: "checked 1 project(s) --
    ALL_PASS" contains a digit. Over a path that is not there, a count of ONE
    is not a denominator; it asserts that one project was opened when none was.

    `discloses_a_reason` (stricter) then flagged 7, and all 7 were honest:
    `Files: 0  Errors: 0  Warnings: 0  Result: PASS`, `PASS -- 0 waveform
    artifact(s)`. A count of ZERO is a true statement about an absent project
    and a reader can act on it. Rejecting those would have made the fixture
    fire on correct behaviour, which is how a gate earns being switched off.

    So the line is between a count that is zero and a count that is not:

        "checked 1 project(s) -- ALL_PASS"                -> not honest
        "Files: 0  Errors: 0  Warnings: 0  Result: PASS"  -> honest
        "PASS -- 0 waveform artifact(s)"                  -> honest
        "no hw-debug-loop evidence directory; not yet applicable" -> honest
        "[NOT CHECKED] no such project ... nothing was examined"  -> honest
    """
    if discloses_a_reason(out) or _ABSENT_REASON_RE.search(out):
        return True
    ints = [int(m) for m in re.findall(r"\b\d+\b", out)]
    return bool(ints) and all(i == 0 for i in ints)


def _drive_on_absent_project(prog: Path, timeout: int = 120) -> Dict:
    """The SECOND fixture: a project path that is not there at all.

    The empty-project fixture above creates the directory (``input/docs/`` and
    ``reports/``), so it asks "what does a gate say when the ARTEFACTS are
    missing". It never asks what a gate says when the PROJECT is missing, and
    the two answers are not the same code path — one walks a real tree and
    finds nothing, the other never gets a tree at all.

    That gap held two real defects, both found in v1.8.29/30 by running gates
    against a typo'd path rather than by anything failing:

        opcode_field_width_consistency_check  "checked 1 project(s) -- ALL_PASS"
        analog_lef_gds_outline_check          "no analog_block_list.json --
                                               digital-only project"

    The first exited 0 having opened nothing; the second exited 0 and stated a
    conclusion about a design nobody looked at. Both are now fixed, so this
    fixture finds NOTHING today — it is a ratchet that holds those two and
    catches the third.

    THE STANDARD IS THE STRONGER ONE, and a positive control is why.

    The empty-project fixture accepts a bare COUNT as disclosure (see
    `_NUMBER_ONLY_DECISION`) — over a real tree, "scanned 0 files" is a
    denominator a reader can act on. Replayed here against the pre-fix program
    that motivated this fixture, that standard PASSES it:

        "checked 1 project(s) -- ALL_PASS"   discloses=True  (the "1")

    The count is not a denominator over a project that is not there; it is a
    false one, asserting that one project was opened when none was. So this
    fixture requires `discloses_a_reason` — the gate must say WHY it looked at
    nothing, not merely how much nothing it looked at.

    Measured on the three real strings:

        "checked 1 project(s) -- ALL_PASS"                  reason=False
        "[NOT CHECKED] no such project: ... nothing was examined"  reason=True
        "VACUOUS_PASS: no analog_block_list.json under ..."        reason=True

    Without that control this fixture would have shipped unable to fail, which
    is the defect it exists to catch.

    The path is passed as an ARGUMENT (not via cwd, which cannot be set to a
    directory that does not exist), so this drives the gate's argument-handling
    path — which is exactly where both defects lived.
    """
    # `timeout` is the STALL GRACE — see `_drive_on_empty_project`.
    try:
        r = _wd.run_host_supervised([sys.executable, str(prog), _ABSENT],
                                    stall_grace_s=float(timeout))
    except (OSError, subprocess.SubprocessError) as exc:
        return {"gate": prog.stem, "rc": None,
                "unrunnable": f"could not be driven: {exc}"}
    if r.outcome == "launch_error":
        return {"gate": prog.stem, "rc": None,
                "unrunnable": f"could not be driven: {r.err}"}
    if r.stalled:
        return {"gate": prog.stem, "rc": None,
                "unrunnable": f"made no forward progress for {timeout}s and "
                              f"was stopped as hung"}
    out = ((r.out or "") + (r.err or "")).strip()
    return {"gate": prog.stem, "rc": r.rc,
            "disclosed": _honest_about_an_absent_project(out),
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

    # --- the SECOND fixture: the same question over a project that is not there
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        absent_results = list(ex.map(
            lambda p: _drive_on_absent_project(p, timeout), progs))
    absent_rc0 = absent_silent = absent_honest_pass = 0
    #: #564 — REPORTED, NOT ENFORCED, and the count is why.
    #:
    #: The predicate finds 17 gates today. Some are certainly right: a gate
    #: whose output is `PASS -- no L4_REGMAP.json (gate not applicable)` is
    #: saying the project has no register map, which is a true statement a
    #: reader can act on. Others are the shape that was fixed by hand in
    #: v1.8.85/86/88. Telling them apart needs one measurement per gate, not a
    #: regex over the wording — a text proxy standing in for the property is
    #: the defect family this program exists for.
    #:
    #: Turning all 17 into FAIL today would block every landing on an unmade
    #: judgement, and a gate that blocks every landing gets switched off rather
    #: than answered. So the census is published and the verdict is not moved.
    #: Promoting these to findings is #564's remaining work, gate by gate.
    absent_honest_gates: List[Dict] = []
    for res in absent_results:
        if res.get("unrunnable") or res["rc"] != 0:
            continue
        absent_rc0 += 1
        if res["disclosed"]:
            # HONEST AND STILL WRONG (#564).
            #
            # This branch used to `continue`, and that is precisely how three
            # gates shipped a success verdict over an input that was not there:
            #
            #   interface_encoding_audit  "0 interfaces analyzed"      rc 0
            #   oe_pattern_check          "analyzed 0 file(s)"         rc 0
            #   fpga_qsf_lint             (no scope at all)            rc 1
            #
            # The first two are honest by the standard above — they state a
            # zero, a reader can act on it, and `_honest_about_an_absent_project`
            # returns True for both. They were still fixed, because the message
            # is not what aggregates. The P0 umbrella reads the EXIT CODE, so a
            # gate that says "0" in prose and returns 0 in rc contributes a
            # silent pass to a project-level verdict.
            #
            # Disclosing a zero denominator and REFUSING on one are two
            # different properties. The first has been enforced here since
            # v1.8.29; the second was enforced nowhere, and each of the three
            # was found by hand, one gate at a time.
            absent_honest_pass += 1
            absent_honest_gates.append({
                "gate": res["gate"],
                "kind": "HONEST_ZERO_BUT_EXIT_ZERO",
                "detail": ("disclosed that it examined nothing and still "
                           "returned rc 0 over a path that does not exist. The "
                           "disclosure is in the output; the aggregation reads "
                           "the exit code, so this is a silent pass one layer "
                           "up. rc 2 means 'could not check' and the CI "
                           "dispatcher already separates it from a finding"),
                "output_tail": res["output_tail"],
            })
            continue
        absent_silent += 1
        findings.append({
            "gate": res["gate"], "kind": "PASS_ON_A_PROJECT_THAT_IS_NOT_THERE",
            "detail": ("answered rc 0 for a path that does not exist, without "
                       "disclosing that nothing was opened. A caller cannot "
                       "tell a typo'd path from a clean chip, and the clean "
                       "answer is the one that gets acted on"),
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
        # The second fixture publishes its own census for the same reason the
        # first does: "0 findings" and "the fixture never ran" print the same.
        "absent_rc_zero": absent_rc0,
        "absent_rc_zero_silent": absent_silent,
        # #564: the honest ones that still passed. Split out from
        # `absent_rc_zero_silent` because the remedy differs — a silent gate
        # needs to start disclosing, this one already discloses and needs to
        # stop returning success.
        "absent_rc_zero_honest_but_passing": absent_honest_pass,
        "absent_rc_zero_honest_but_passing_gates": sorted(
            absent_honest_gates, key=lambda d: d["gate"]),
        "inventory_size": len(_EMPTY_PROJECT_SILENT_PASS),
        "inventory_measured_on": _MEASURED_ON,
        "undriveable_size": len(_UNDRIVEABLE),
        "silent_gates": sorted(silent),
        "number_only_gates": sorted(number_only),
        "rc_outside_convention": sorted(outside_convention,
                                        key=lambda d: d["gate"]),
    }
    return ("FAIL" if findings else "PASS"), findings, stats


# ---------------------------------------------------------------------------
# THE ROLL-UP MUST NOT RENAME WHAT IT COUNTS (vibe-ic#972)
#
# Both verdict lines below used to report `len(findings)` under ONE sentence
# describing ONE kind. MEASURED on the CI population: a run whose only finding
# was a `GATE_UNRUNNABLE` — a gate that could not be launched at all, so nothing
# was ever known about its disclosure — printed
#
#     [FAIL] 1 gate(s) of 50 probed (74 declared) answer PASS over an empty tree
#            without disclosing it.
#
# "could not be driven" and "answered PASS without disclosing" are different
# facts with different remedies, and the second is a claim about an output that
# in this case never existed. The line also NAMED NO GATE, so the one sentence a
# reader sees carried neither the right kind nor the subject.
#
# The kinds are DISCOVERED from the findings, never listed here: a kind added to
# `audit_ci` or `audit_project_gates` arrives in this roll-up already reported.
# Every kind names its gates, so the headline is actionable on its own.
_KIND_HEADLINE = {
    "PASS_WITHOUT_DENOMINATOR":
        "answered PASS over an empty tree without disclosing it",
    "GATE_UNRUNNABLE":
        "could not be driven at all — nothing is known about their disclosure",
    "PASS_ON_A_PROJECT_THAT_IS_NOT_THERE":
        "answered rc 0 for a path that does not exist, without disclosing it",
    "STALE_INVENTORY_ENTRY":
        "are on the known-silent inventory but no longer match it",
    "STALE_UNDRIVEABLE_ENTRY":
        "are on the undriveable list but can now be driven",
}


def summarise_findings(findings: List[Dict]) -> List[str]:
    """One line PER KIND, each naming its gates. Kinds come from the data.

    A kind with no entry in `_KIND_HEADLINE` is still reported — under its own
    name rather than under somebody else's sentence, which is the whole point.
    """
    by_kind: Dict[str, List[str]] = {}
    for f in findings:
        by_kind.setdefault(str(f.get("kind", "UNCLASSIFIED")), []).append(
            str(f.get("gate", "(unnamed)")))
    lines: List[str] = []
    for kind in sorted(by_kind):
        gates = sorted(by_kind[kind])
        what = _KIND_HEADLINE.get(kind, f"are reported as {kind}")
        lines.append(f"  {len(gates)} {kind}: {what} — {', '.join(gates)}")
    return lines


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
    honest = stats.get("absent_rc_zero_honest_but_passing", 0)
    if honest:
        # On stderr and in the headline path, not only in --json. A census that
        # lives solely in a file a human has to ask for is the same silence
        # this program exists to catch, one tool further out (#564).
        print(f"  HONEST ZERO BUT rc 0 (#564, reported not enforced): {honest} "
              f"gate(s) disclosed they examined nothing over an absent project "
              f"and still returned success", file=sys.stderr)
        for entry in stats.get("absent_rc_zero_honest_but_passing_gates", []):
            print(f"    {entry['gate']}: {entry['output_tail'][:96]}",
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
    print(f"  …and against a project path that DOES NOT EXIST: rc 0: "
          f"{stats['absent_rc_zero']} | not disclosing: "
          f"{stats['absent_rc_zero_silent']}", file=sys.stderr)
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
        for line in summarise_findings(findings):
            print(line, file=sys.stderr)
        print(f"[FAIL] {len(findings)} finding(s) over "
              f"{stats['gates_probed']} gate(s), by kind above.",
              file=sys.stderr)
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
    ap.add_argument("--budget", type=float, default=None,
                    help="AGGREGATE wall-clock budget for the whole CI sweep "
                         "in seconds. Unset = unbounded, which is what "
                         "vibe-ic#1181 measured at 192.9s on an idle host. "
                         "On exhaustion the sweep stops and reports "
                         "NOT_CHECKED, never PASS.")
    ap.add_argument(
        "--skip-host-excluded", action="store_true",
        help=("when this meta-gate is itself driven by host-independence, do "
              "not indirectly launch declarations carrying an adjacent "
              "host-independence EXCLUDE; every skip remains named"))
    a = ap.parse_args(argv)

    if a.population == "project":
        return _main_project_population(a)

    root = Path(a.repo_root).resolve() if a.repo_root else _PLUGIN.parents[2]
    res = audit_ci(root, timeout=a.timeout, budget=a.budget,
                   skip_host_excluded=a.skip_host_excluded)
    verdict, findings = res.verdict, res.findings

    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            {"verdict": verdict, "population": "ci",
             # DECLARED is the denominator — every gate the script wires.
             # PROBED is what this run could actually launch. They used to be
             # the same number under the name `gates_probed`, which is how 21
             # gates the interpreter never opened were reported as disclosing.
             "gates_declared": res.declared,
             "gates_probed": res.probed,
             "truncated": res.truncated,
             "not_driven": [{"gate": g, "why": w} for g, w in res.not_driven],
             "findings": findings}, indent=2) + "\n")

    # vibe-ic#1181 — a sweep the budget cut short exits 2 NOT CHECKED, never
    # 0. rc 0 from this program is read by the tier as "every CI gate discloses
    # what it examined"; over a truncated sweep that sentence is about how far
    # the loop got, not about the gates.
    if verdict == "NOT_CHECKED":
        print(f"NOT CHECKED: the CI sweep stopped after probing {res.probed} "
              f"of {res.declared} declared gate(s) — its aggregate budget ran "
              f"out. No finding was seen in what it did probe, but that is not "
              f"a clean result over the gate set (vibe-ic#1181).",
              file=sys.stderr)
        for g, w in res.not_driven:
            if "aggregate budget" in w:
                print(f"    NOT PROBED  {g}", file=sys.stderr)
        return 2

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

    # WHATEVER THE OUTCOME, SAY WHAT WAS NOT DRIVEN. A gate that leaves the
    # numerator without being named is how a set silently shrinks — the
    # sentence below used to claim the DECLARED count either way.
    for label, why in res.not_driven:
        print(f"  [NOT DRIVEN] {label} — {why}", file=sys.stderr)

    if findings:
        for line in summarise_findings(findings):
            print(line, file=sys.stderr)
        print(f"[FAIL] {len(findings)} finding(s) over {res.probed} probed CI "
              f"gate(s) of {res.declared} declared, by kind above.",
              file=sys.stderr)
        return 1
    print(f"[PASS] all {res.probed} probed CI gate(s) of {res.declared} "
          f"declared disclose what they examined (probed against an empty "
          f"tree); {len(res.not_driven)} could not be driven and are named "
          f"above.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
