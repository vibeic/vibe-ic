#!/usr/bin/env python3
"""A triage note that describes BEHAVIOUR does not say why the behaviour is OK.

THIS GATE BLOCKS (rc=1) on a NEW behaviour-only triage note.

WHY (vibe-ic#659)
-----------------
`checker_execution_wiring_baseline.json` records checkers that nothing but their
own unit test runs, and MAY ONLY SHRINK. 25 of its 31 entries carry a variant of

    rc=2 SKIPs / refuses without its input — [--json JSON]

For most checkers that is correct and benign: an analog ENOB gate on a design
with no ADC has nothing to measure. For some it is exactly backwards, and the
note cannot tell the two apart because it describes the MECHANISM and not the
REASON.

The proof that it can be backwards is `pdk_consistency_check`, triaged with that
exact note. It is written for "the synthesis tool targeted a different PDK than
the one specified", and `--pdk-lib` is REQUIRED — so when a run lost its staged
PDK and completed four rounds against the image's built-in one, the checker
written for that failure could not fire, because the failure removed its input.
A guard switched off by the very condition it exists to catch has never once
been able to catch it, and being on a known-and-triaged list is what made that
invisible: the entry looked handled.

WHAT IT MEASURES
----------------
Not a semantic judgement about each checker — a program that guessed would
produce confident wrong answers. It asks the question the note's own premise
can be checked against: CAN A REAL RUN LACK THIS INPUT AT ALL?

Read by RUNNING each checker with no arguments and taking argparse's own list of
what it requires — from the program, not from the note, since the note is the
thing under audit and believing it would make the audit circular.

MEASURED over the 31 entries:

    needs ONLY the run's own context (project_dir, run_dir, target, ...)  24
    needs a SPECIFIC artefact that can be absent                           7
        hw_vs_rtl_verdict_check          --responses-dir
        lesson_consumption_check         --prompt, --digest
        level_hysteresis_flag_oracle     --prompt, --rtl
        pdk_consistency_check            --netlist, --pdk-lib
        protocol_turnaround_audit        --rtl-dir, --l2-json, --clock-period-ns
        skill_doc_section_present_check  --doc
        verilator_timing_fallback_check  --tb, --golden, --tb-top, --dut-name

So for 24 of them the note's premise is FALSE. `project_dir` is the run's own
directory; the flow always has one. "Refuses without its input" describes
running the program bare from a shell, which is not a state the flow is ever in.
Those checkers do not lack an INPUT — they lack a CALLER, and the note has been
standing in for that.

The question #659 asks — is a missing input NORMAL, or is it the finding? — is
real, and it applies to the OTHER seven. One of those, `pdk_consistency_check`,
is the case the issue was raised about, and it is the one already answered:
#655/#656 replaced it with a question the defect cannot disable.

chip-AGNOSTIC: pure JSON structure and subprocess behaviour. No design, PDK,
vendor or value literal appears here.

USAGE
-----
    triage_note_answers_the_question_check.py [--baseline PATH] [--json OUT]

    exit 0 = no note claims a missing input that a real run always has
    exit 1 = at least one does not (BLOCKING)
    exit 2 = could not be determined (no baseline, unreadable) — never a
             vacuous pass
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_DEFAULT_BASELINE = "checker_execution_wiring_baseline.json"

#: Arguments that are the RUN'S OWN CONTEXT — a real caller always has them.
#: A checker whose only required arguments are these does not "lack its input"
#: in any real run; it lacks a CALLER, and the note has been standing in for
#: that.
_CONTEXT_ARGS = re.compile(
    r"^(project_dir|run_dir|target|parity_root|projects|rtl|tb|--project-json)$")

_REQUIRED_RE = re.compile(r"error: the following arguments are required: (.+)")

#: A note that names only what the program DOES when run bare.
_BEHAVIOUR_ONLY = re.compile(r"rc=\d|skips?\b|refus", re.I)

#: Text inside quotes is being DISCUSSED, not asserted. Without this the gate
#: matched its own remedy: a corrected note that explains "the previous note
#: said it 'skips without its input', which is not a state the flow is ever in"
#: was read as making that claim. Same shape as an assertion that scans its own
#: docstring — the fix and the defect are indistinguishable by substring.
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"|`[^`]*`")


def asserts_behaviour_only(note: str) -> bool:
    """True when the note offers the program's bare-shell behaviour AS ITS
    REASON — quoted text stripped first, so a note that quotes the old wording
    in order to correct it is not mistaken for one that repeats it."""
    return bool(_BEHAVIOUR_ONLY.search(_QUOTED.sub(" ", note or "")))


def required_args(checker: str, programs: Path) -> Optional[List[str]]:
    """What the checker refuses without, by RUNNING it with no arguments.

    Read from the program, not from the triage note — the note is the thing
    under audit here, so believing it would make the audit circular."""
    p = programs / checker
    if not p.is_file():
        return None
    try:
        r = subprocess.run([sys.executable, str(p)], capture_output=True,
                           text=True, errors="replace", timeout=45)
    except (OSError, subprocess.SubprocessError):
        return None
    m = _REQUIRED_RE.search((r.stderr or "") + (r.stdout or ""))
    if not m:
        return []                      # ran without arguments: nothing required
    return [a.strip() for a in m.group(1).split(",") if a.strip()]


def input_can_be_absent(args: Optional[List[str]]) -> Optional[bool]:
    """Can a REAL run genuinely lack this checker's input?

    None when it could not be determined. False when every required argument is
    the run's own context — the flow always has a project directory, so
    "refuses without its input" describes running the program bare from a shell,
    which is not a state the flow is ever in."""
    if args is None:
        return None
    if not args:
        return False
    return not all(_CONTEXT_ARGS.match(a) for a in args)


def load_baseline(path: Path) -> Optional[dict]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and "triage" in d else None


def audit(baseline: dict, programs: Path) -> Tuple[List[dict], Dict[str, int]]:
    rows, tally = [], {"context-only": 0, "artefact": 0, "undetermined": 0}
    for checker, note in sorted((baseline.get("triage") or {}).items()):
        args = required_args(checker, programs)
        can = input_can_be_absent(args)
        kind = ("undetermined" if can is None
                else "artefact" if can else "context-only")
        tally[kind] += 1
        rows.append({"checker": checker, "requires": args,
                     "input_can_be_absent": can, "kind": kind,
                     "triage": str(note)})
    return rows, tally


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)

    programs = Path(__file__).resolve().parent
    path = Path(a.baseline) if a.baseline else programs / _DEFAULT_BASELINE
    baseline = load_baseline(path)
    if baseline is None:
        print(f"[CANNOT DETERMINE] triage_note_answers_the_question: no readable "
              f"baseline with a `triage` map at {path}. NOT a pass.",
              file=sys.stderr)
        return 2

    rows, tally = audit(baseline, programs)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            {"tally": tally, "rows": rows}, indent=2) + "\n")

    print(f"  needs ONLY the run's own context (always present): "
          f"{tally['context-only']}")
    print(f"  needs a SPECIFIC artefact that can be absent     : "
          f"{tally['artefact']}")
    if tally["undetermined"]:
        print(f"  could not be determined                          : "
              f"{tally['undetermined']}")

    vacuous = [r for r in rows
               if r["kind"] == "context-only"
               and asserts_behaviour_only(r["triage"])]
    if vacuous:
        print(f"\n[FAIL] {len(vacuous)} triage note(s) say the checker 'skips "
              f"without its input' when a real run ALWAYS has that input:")
        for r in vacuous:
            print(f"   {r['checker']}  (requires: {', '.join(r['requires']) or 'nothing'})")
        print("\n  These do not lack an INPUT — they lack a CALLER, and the note "
              "has been\n  standing in for that. `project_dir` is the run's own "
              "directory; the flow\n  always has one. Say why nothing calls it, "
              "or wire it.\n\n"
              "  The question vibe-ic#659 asks — is a missing input NORMAL, or is "
              "it the\n  finding? — applies to the OTHER bucket, where the input "
              "genuinely can be\n  absent from a real run.")
        return 1

    print(f"\n[PASS] triage_note_answers_the_question: {len(rows)} entr(ies), "
          f"no note claims a missing input that a real run always has.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
