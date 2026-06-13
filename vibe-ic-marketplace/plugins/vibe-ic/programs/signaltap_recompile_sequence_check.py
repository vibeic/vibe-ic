#!/usr/bin/env python3
"""
signaltap_recompile_sequence_check.py — Validate that the Quartus
SignalTap-enabled recompile is the COMPLETE, CORRECTLY-ORDERED four-stage
pipeline that skills/fpga-signaltap/SKILL.md mandates.

To embed a SignalTap logic analyzer into a SOF you MUST run, in this order:

    1. quartus_stp   <proj> --stp_file=<x>.stp   (attach the .stp to the proj)
    2. quartus_map   <proj>                       (analysis + synthesis)
    3. quartus_fit   <proj>                       (fit / place & route)
    4. quartus_asm   <proj>                       (assemble -> .sof)

The silicon-debug defect this catches is REAL and common: an agent that
copy-pastes only `quartus_map / quartus_fit / quartus_asm` (omitting
`quartus_stp`) produces a perfectly valid SOF that contains NO logic analyzer
at all — you program the board, run the BIST, and SignalTap shows nothing,
costing a full ~30-minute re-fit. Equally, running `quartus_stp` AFTER
`quartus_fit` (wrong order) means the analyzer is attached too late and the
fit does not include it.

Deterministic checks (no judgment):
  STAGE_MISSING        a required stage command is absent
  WRONG_ORDER          a stage appears before a stage that must precede it
                       (canonical order: stp < map < fit < asm)
  STP_NO_STP_FILE      quartus_stp present but with no --stp_file=<...>.stp
  STP_FILE_MISMATCH    --stp_file points at a file that does not end in .stp
                       (or, when --expect-stp is given, does not match it)

chip-AGNOSTIC: the only fixed tokens are the four Quartus binary names, which
are vendor-tool constants, not chip/protocol names.

INPUT: a shell script, a recompile log, a Makefile fragment, or any text file
that contains the recompile command sequence. The check scans line-by-line
for the four quartus_* invocations.

HONESTY:
  - No input file, or a file containing NONE of the four quartus_* commands
    -> SKIP (exit 0): there is genuinely no recompile sequence to validate.
    (A partial sequence — at least one stage present — is validated and any
    missing/mis-ordered stage is a real FAIL.)

Usage:
    python3 signaltap_recompile_sequence_check.py recompile.sh
    python3 signaltap_recompile_sequence_check.py build.log \
        --expect-stp cd4013b_debug.stp --json out.json

Exit codes:
    0 = PASS (all four stages present, correctly ordered, stp has a .stp file)
        or SKIP (no recompile sequence present in the input)
    1 = FAIL (missing stage / wrong order / bad --stp_file)
    2 = usage / io error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Dict, Optional


# Canonical order; index = required position.
CANONICAL_STAGES = ("quartus_stp", "quartus_map", "quartus_fit", "quartus_asm")
STAGE_ORDER = {name: i for i, name in enumerate(CANONICAL_STAGES)}

# A stage invocation: the binary name as a command token (start of token,
# possibly preceded by a path or `&&`/`;`). We require it to be a command, not
# a substring of another word, by anchoring on a non-word boundary before it.
_STAGE_RE = {
    name: re.compile(r"(?:^|[\s;&|/])" + re.escape(name) + r"\b")
    for name in CANONICAL_STAGES
}
# --stp_file=<path>  (also tolerate `--stp_file <path>`)
_STP_FILE_RE = re.compile(
    r"--stp_file\s*[=\s]\s*(\S+)", re.IGNORECASE)


@dataclass
class StageHit:
    stage: str
    line: int
    text: str


@dataclass
class Finding:
    rule: str
    severity: str
    detail: str
    fix_hint: str


@dataclass
class Result:
    status: str                                   # PASS | FAIL | SKIP
    input_file: str = ""
    stages_found: List[str] = field(default_factory=list)
    stp_file: Optional[str] = None
    findings: List[Finding] = field(default_factory=list)


def scan_stages(text: str) -> List[StageHit]:
    """Find the FIRST occurrence (by line) of each required stage command."""
    hits: List[StageHit] = []
    seen: Dict[str, bool] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        # skip pure comment lines
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for name, rx in _STAGE_RE.items():
            if name in seen:
                continue
            if rx.search(line):
                hits.append(StageHit(stage=name, line=lineno, text=stripped))
                seen[name] = True
    # stable order by line
    hits.sort(key=lambda h: h.line)
    return hits


def find_stp_file(text: str) -> Optional[str]:
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        m = _STP_FILE_RE.search(line)
        if m:
            return m.group(1).strip().strip("\"'")
    return None


def validate(text: str, label: str, expect_stp: Optional[str]) -> Result:
    hits = scan_stages(text)
    found = [h.stage for h in hits]

    # Nothing recognisable -> honest SKIP (handled by caller via empty found).
    if not found:
        return Result(status="SKIP", input_file=label, stages_found=[],
                      stp_file=None, findings=[])

    findings: List[Finding] = []

    # STAGE_MISSING
    for name in CANONICAL_STAGES:
        if name not in found:
            findings.append(Finding(
                rule="STAGE_MISSING",
                severity="ERROR",
                detail=(f"Recompile stage '{name}' is absent. SignalTap is "
                        f"only embedded into the SOF when ALL four stages run "
                        f"in order ({' -> '.join(CANONICAL_STAGES)})."
                        + (" Omitting quartus_stp means the produced SOF has "
                           "NO logic analyzer at all."
                           if name == "quartus_stp" else "")),
                fix_hint=(f"Add the missing stage, e.g. `{name} <proj>"
                          + (" --stp_file=<x>.stp`" if name == "quartus_stp"
                             else "`")),
            ))

    # WRONG_ORDER — compare the observed line order to the canonical rank.
    last_rank = -1
    last_stage = None
    for h in hits:
        rank = STAGE_ORDER[h.stage]
        if rank < last_rank:
            findings.append(Finding(
                rule="WRONG_ORDER",
                severity="ERROR",
                detail=(f"Stage '{h.stage}' (line {h.line}) appears AFTER "
                        f"'{last_stage}' but must run before it. Canonical "
                        f"order is {' -> '.join(CANONICAL_STAGES)}; running "
                        f"quartus_stp after the fit attaches the analyzer too "
                        f"late."),
                fix_hint=(f"Re-order so {h.stage} runs before {last_stage}."),
            ))
        else:
            last_rank = rank
            last_stage = h.stage

    # STP_NO_STP_FILE / STP_FILE_MISMATCH
    stp_file = find_stp_file(text)
    if "quartus_stp" in found:
        if not stp_file:
            findings.append(Finding(
                rule="STP_NO_STP_FILE",
                severity="ERROR",
                detail=("quartus_stp is invoked without --stp_file=<x>.stp, "
                        "so no SignalTap configuration is attached."),
                fix_hint=("Append --stp_file=<module>_debug.stp to the "
                          "quartus_stp command."),
            ))
        else:
            if not stp_file.lower().endswith(".stp"):
                findings.append(Finding(
                    rule="STP_FILE_MISMATCH",
                    severity="ERROR",
                    detail=(f"--stp_file points at '{stp_file}', which is not "
                            f"a .stp SignalTap configuration file."),
                    fix_hint=("--stp_file must name the generated .stp file."),
                ))
            elif expect_stp and Path(stp_file).name != Path(expect_stp).name:
                findings.append(Finding(
                    rule="STP_FILE_MISMATCH",
                    severity="ERROR",
                    detail=(f"--stp_file is '{stp_file}' but the expected "
                            f"SignalTap config is '{expect_stp}'."),
                    fix_hint=(f"Point --stp_file at '{expect_stp}'."),
                ))

    status = "FAIL" if findings else "PASS"
    return Result(status=status, input_file=label, stages_found=found,
                  stp_file=stp_file, findings=findings)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.strip().split("\n")[0])
    ap.add_argument("input", nargs="?", default=None,
                    help="Recompile script / log / Makefile to validate")
    ap.add_argument("--expect-stp", default=None,
                    help="Expected .stp filename the recompile must attach")
    ap.add_argument("--json", type=Path, default=None,
                    help="Also write the result JSON to this path")
    args = ap.parse_args(argv)

    if not args.input:
        res = Result(status="SKIP")
        out = json.dumps(asdict(res), indent=2)
        if args.json:
            args.json.write_text(out)
        print(out)
        print("signaltap_recompile_sequence_check: SKIP — no input given",
              file=sys.stderr)
        return 0

    ip = Path(args.input)
    if not ip.is_file():
        print(f"ERROR: input not found: {ip}", file=sys.stderr)
        return 2
    text = ip.read_text(errors="replace")

    res = validate(text, str(ip), args.expect_stp)
    out = json.dumps(asdict(res), indent=2)
    if args.json:
        args.json.write_text(out)
    print(out)

    if res.status == "SKIP":
        print("signaltap_recompile_sequence_check: SKIP — no quartus_* "
              "recompile sequence found in input", file=sys.stderr)
        return 0

    if res.findings:
        print(f"signaltap_recompile_sequence_check: FAIL — "
              f"{len(res.findings)} finding(s)", file=sys.stderr)
        for f in res.findings:
            print(f"  [{f.rule}] {f.detail}", file=sys.stderr)
        return 1

    print(f"signaltap_recompile_sequence_check: PASS — all 4 stages present "
          f"in canonical order, .stp attached ({res.stp_file})",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
