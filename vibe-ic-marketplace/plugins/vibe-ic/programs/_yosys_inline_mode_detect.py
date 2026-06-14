"""v1.6.180 (#72 P2-8) — confirm-inline-mode helper for the two
Step 14 Yosys gates (`yosys_hilomap_required_check`,
`yosys_script_template_check`).

Both gates emit `verdict: VACUOUS_PASS` when no `.ys` script is
found under the project's canonical search globs, on the
assumption that the project is using the
`phase3_one_shot_runner` inline `yosys -p '<commands>'` mode.

Field-agent's P2-8 question: how does a reviewer know whether the
VACUOUS_PASS is legitimate ("project genuinely uses inline mode")
or a bug ("the gate didn't find a `.ys` script it expected to find,
masking a real synthesis failure")? Pre-v1.6.180 the verdict alone
gave no answer.

v1.6.180 positively confirms the inline-mode case by inspecting
project state for any of:

  (a) `phase3_one_shot_runner.py` artefacts:
      - `reports/phase3_one_shot.json` (the runner's own report)
      - `phase3/stage2/synth/yosys.log`
      - `phase3/stage2/synth/synth.log`
  (b) `yosys -p` invocation in any shell / tcl / makefile under
      `phase3/`, `phase2/stage2/synth/`, `scripts/`, or
      `Makefile`-style top-level files.

If at least one positive marker is found, the verdict becomes
`VACUOUS_PASS` with `reason_class: inline_yosys_p_mode_confirmed`.

If none, the gate stays rc=0 but reports
`verdict: VACUOUS_PASS_UNCONFIRMED` so audit reviewers can see the
gate's vacuousness was not positively justified.

chip-AGNOSTIC: looks for structural markers, never chip-class
literals.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple


_RUNNER_ARTEFACTS = (
    "reports/phase3_one_shot.json",
    "reports/orchestrator/phase3_one_shot.json",
    "phase3/reports/phase3_one_shot.json",
    "phase3/stage2/synth/yosys.log",
    "phase3/stage2/synth/synth.log",
    "phase2/stage2/synth/yosys.log",
    "phase2/stage2/synth/synth.log",
)

_INLINE_SEARCH_DIRS = (
    "phase3",
    "phase2/stage2/synth",
    "scripts",
)

# Match `yosys -p ...`, `yosys --commands ...`, `yosys --command ...`
# in any shell / tcl / makefile / py blob. Word boundary on the left
# keeps it from matching `xyosys`.
_INLINE_CMD_RE = re.compile(
    r"\byosys\s+(?:-p|--commands?|--command)\b",
    re.IGNORECASE,
)


def _file_has_inline_marker(path: Path) -> bool:
    try:
        head = path.open("r", errors="replace").read(64 * 1024)
    except OSError:
        return False
    return bool(_INLINE_CMD_RE.search(head))


def detect_inline_mode(project: Path) -> Tuple[str, List[str]]:
    """Return (status, evidence_paths_rel).

    status ∈ {"confirmed", "unconfirmed"}.

    evidence_paths_rel is a list of project-relative paths whose
    presence (or content) confirms inline mode. When status is
    "unconfirmed" the list is empty.
    """
    evidence: List[str] = []

    # (a) Runner artefacts.
    for rel in _RUNNER_ARTEFACTS:
        p = project / rel
        if p.is_file() and p.stat().st_size > 0:
            evidence.append(rel)

    # (b) Inline-command grep.
    for sub in _INLINE_SEARCH_DIRS:
        d = project / sub
        if not d.is_dir():
            continue
        for ext in ("*.sh", "*.tcl", "*.py", "Makefile", "makefile",
                     "*.mk"):
            for f in d.rglob(ext):
                if _file_has_inline_marker(f):
                    try:
                        evidence.append(str(f.relative_to(project)))
                    except ValueError:
                        evidence.append(str(f))
                    if len(evidence) >= 8:
                        break
            if len(evidence) >= 8:
                break
        if len(evidence) >= 8:
            break

    if evidence:
        return "confirmed", evidence
    return "unconfirmed", []


# ---------------------------------------------------------------------------
# ORGANIC #649 — extract the ACTUAL inline `yosys -p '<cmds>'` command from
# the runner's own synth logs and verify hilomap/-flatten conformance against
# THAT command, instead of returning a VACUOUS_PASS just because no `.ys`
# file exists. Pre-#649 the two Step-14 Yosys gates were structurally bypassed
# for every inline-yosys flow: file-existence "confirmed" inline mode, the
# command itself was never inspected, so a synth that skipped hilomap shipped a
# netlist that OpenROAD detailed_route then crashes on (DRT-0305 zero_ GROUND).
#
# chip-AGNOSTIC: parses the runner's structural log lines and a generic
# `-liberty <path>` real-PDK marker — never any chip / cell / vendor literal.
# ---------------------------------------------------------------------------

# yosys echoes every command it runs as a line:
#   -- Running command `<cmd>` --
# The command body is enclosed in backticks. (Yosys never nests a backtick
# inside the echoed command, so a non-greedy capture to the next backtick is
# exact.)
_RUNNING_CMD_RE = re.compile(r"--\s*Running command\s*`(.+?)`", re.DOTALL)

# Logs in which the runner echoes its inline `yosys -p` command. The real-PDK
# synth (the one that MUST run hilomap) and the simulation-only synth are both
# emitted under phase{2,3}/stage2/synth/; we scan every candidate and classify
# each command individually so a sim-only command never masks a real-PDK one.
_INLINE_LOG_CANDIDATES = (
    "phase3/stage2/synth/yosys.log",
    "phase3/stage2/synth/synth.log",
    "phase2/stage2/synth/yosys.log",
    "phase2/stage2/synth/synth.log",
)

# A command targets a real PDK (and therefore MUST contain hilomap) when it
# binds a Liberty library — `dfflibmap -liberty <lib>`, `abc -liberty <lib>`,
# `stat -liberty <lib>`, etc. A simulation-only synth (`-DSIMULATION`, no
# Liberty) maps to generic gates and legitimately needs no tie-cell hilomap,
# mirroring yosys_script_template_check's --simulation-only waiver. Word
# boundary keeps it from matching `--no-liberty`-style negations.
_LIBERTY_RE = re.compile(r"(?<![\w-])-liberty\b", re.IGNORECASE)
# Tokens that mark a command as a SYNTHESIS command at all (as opposed to a
# pure read/stat/clean utility invocation). Mirrors the .ys-script `is_synth`
# guard in yosys_hilomap_required_check / yosys_script_template_check.
_SYNTH_TOKEN_RE = re.compile(r"\b(?:synth|dfflibmap|abc|techmap)\b",
                             re.IGNORECASE)
_HILOMAP_RE = re.compile(r"\bhilomap\b", re.IGNORECASE)
_FLATTEN_RE = re.compile(r"(?:\bflatten\b|-flatten\b)", re.IGNORECASE)


def extract_inline_yosys_commands(project: Path) -> List[Tuple[str, str]]:
    """Return ``[(rel_log_path, command_string), ...]`` for every
    ``-- Running command `...` `` line found across the candidate synth
    logs. Empty list when no log echoes an inline yosys command — that is
    the genuine "inline mode not actually exercised" case.

    chip-AGNOSTIC: structural log parsing only.
    """
    out: List[Tuple[str, str]] = []
    for rel in _INLINE_LOG_CANDIDATES:
        p = project / rel
        if not (p.is_file() and p.stat().st_size > 0):
            continue
        try:
            text = p.open("r", errors="replace").read(2 * 1024 * 1024)
        except OSError:
            continue
        for m in _RUNNING_CMD_RE.finditer(text):
            cmd = m.group(1).strip()
            if _SYNTH_TOKEN_RE.search(cmd):
                out.append((rel, cmd))
    return out


def check_inline_command_conformance(
    cmd: str,
) -> Tuple[bool, str, List[str]]:
    """Verify a single extracted inline yosys command against CLAUDE.md
    rule-4 conformance.

    Returns ``(passed, classification, reasons)`` where ``classification``
    ∈ {"real_pdk", "simulation_only"}:

      * real_pdk (binds a Liberty library): MUST contain hilomap AND a
        flatten directive. Missing hilomap → passed=False (this is the
        #649 case that previously VACUOUS_PASSed).
      * simulation_only (no Liberty): hilomap is legitimately waived,
        mirroring yosys_script_template_check --simulation-only; passes.
    """
    reasons: List[str] = []
    is_real_pdk = bool(_LIBERTY_RE.search(cmd))
    classification = "real_pdk" if is_real_pdk else "simulation_only"

    if not is_real_pdk:
        # Simulation-only inline synth (no Liberty binding): hilomap is
        # not applicable. Pass, but note the classification so reviewers
        # can see WHY the tie-cell requirement was waived.
        return True, classification, []

    if not _HILOMAP_RE.search(cmd):
        reasons.append(
            "MISSING hilomap: inline real-PDK `yosys -p` command binds a "
            "Liberty library but issues no `hilomap` — OpenROAD "
            "detailed_route will trip DRT-0305 'zero_ GROUND' on the "
            "unmapped tie nets. Add `hilomap -hicell <TIEHI_CELL> <PORT> "
            "-locell <TIELO_CELL> <PORT>` to the inline command."
        )
    if not _FLATTEN_RE.search(cmd):
        reasons.append(
            "MISSING -flatten: inline real-PDK `yosys -p` command has "
            "neither `synth -flatten` nor a standalone `flatten` — "
            "hierarchical names bleed through and break downstream "
            "OpenROAD / ATPG on backslash-escaped paths."
        )
    return (len(reasons) == 0), classification, reasons


def audit_inline_yosys(project: Path) -> Tuple[str, List[str], List[str]]:
    """Top-level #649 inline-yosys conformance audit.

    Returns ``(verdict, evidence_logs, reasons)`` where verdict ∈:

      * "PASS"                  — at least one real-PDK inline command
                                  found and ALL real-PDK commands conform
                                  (hilomap + flatten present); OR only
                                  simulation-only inline commands found.
      * "FAIL"                  — a real-PDK inline command is missing
                                  hilomap / flatten. ``reasons`` lists the
                                  specifics.
      * "NO_INLINE_COMMAND"     — no `-- Running command` line echoing a
                                  synthesis command was found in any log;
                                  caller decides what to do (the existing
                                  file-existence confirmer still applies).

    chip-AGNOSTIC.
    """
    cmds = extract_inline_yosys_commands(project)
    if not cmds:
        return "NO_INLINE_COMMAND", [], []

    evidence_logs: List[str] = []
    reasons: List[str] = []
    saw_real_pdk = False
    any_fail = False
    for rel, cmd in cmds:
        passed, classification, sub_reasons = \
            check_inline_command_conformance(cmd)
        if classification == "real_pdk":
            saw_real_pdk = True
            if rel not in evidence_logs:
                evidence_logs.append(rel)
            if not passed:
                any_fail = True
                for r in sub_reasons:
                    reasons.append(f"{rel}: {r}")

    if any_fail:
        return "FAIL", evidence_logs, reasons
    # All real-PDK commands conformed, OR only simulation-only commands
    # were present — both are legitimate passes.
    if not saw_real_pdk:
        # Only sim-only inline synth ran; record the logs we did see so the
        # caller can still treat inline mode as positively exercised.
        evidence_logs = [rel for rel, _ in cmds]
    return "PASS", evidence_logs, []


__all__ = [
    "detect_inline_mode",
    "extract_inline_yosys_commands",
    "check_inline_command_conformance",
    "audit_inline_yosys",
]
