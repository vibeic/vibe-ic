#!/usr/bin/env python3
"""analog_a0_skip_forbidden_check.py — forbidden-artefact gate (Wave 47).

Extracts the forbidden-artefact rule embedded in the
`analog-spec-extract` skill:

    Forbidden: `analog/A0_skip_decision.json` as a top-level skip.
    Replace with `analog/A0_implementation_status.json` listing each
    block's per-step (A1-A8) status, OR rely on
    `L5.analog_blocks_detected=false` when the keyword scan PASSes empty.

This is a pure file-presence / shape assertion — deterministic, no
inference.

Algorithm (chip-AGNOSTIC):
  1. Look for `analog/A0_skip_decision.json` anywhere under the project
     (both `analog/` and `phase3/analog/`).
  2. If absent → PASS (the forbidden artefact was not produced).
  3. If present → it is forbidden ONLY when it actually encodes a SKIP
     decision, read from the NAMED decision fields (`decision` /
     `status` / `verdict` / `result` / `analog_decision`, top-level or
     one level down under `analog`). A file that happens to be named
     that but carries no skip verdict is reported but not a hard FAIL —
     we FAIL on the real defect (a top-level analog skip), not on the
     filename alone.
  4. When a real skip IS encoded, FAIL unless one of the two sanctioned
     replacements is present and substantive:
        (a) `analog/A0_implementation_status.json` with a per-block /
            per-step status object (non-empty `blocks` or `steps`), OR
        (b) an L5_ADI_SPEC.json carrying `analog_blocks_detected=false`.

MEASURED DEFECTS REPAIRED 2026-08-03 (vibe-ic#693 analog-corner family).
This gate had never run outside its own unit test. Exercised against
fixtures before wiring, it FAILED on state that is not the defect and
PASSED on state that is:

  * `{"decision": "NO_SKIP", "rationale": "2 analog blocks detected;
    the analog track runs in full"}` → rc 1. The skip regex was bare
    `skip` with no negation handling, so a file recording the OPPOSITE
    of a skip was read as a skip. Repaired: `_NEGATED_SKIP_RE` is
    consulted first, and an explicitly-negated verdict is a PASS.
  * `{"decision": "PROCEED", "note": "no A-step was skipped in this
    run"}` → rc 1, evidence `value='no A-step was skipped in this run'`.
    The old code looped over EVERY string value in the file, so free
    prose in an unrelated field decided the verdict. Repaired: only the
    NAMED decision fields are read (plus a nested `analog` object).
  * A project whose analog track ran in full but which retains
    `archive/old_run/analog/A0_skip_decision.json` → rc 1, naming the
    archived file. The globs ended in `**/`, so any nested historical
    run anywhere under the project was judged as if it were this run's.
  * The mirror-image FALSE NEGATIVE: a REAL top-level skip excused by an
    `A0_implementation_status.json` belonging to an unrelated nested run
    → rc 0. Same unbounded `**/` glob, now deciding the wrong way.
    Repaired: both globs are bounded to this project's OWN analog roots
    (`analog/`, `phase1|phase2|phase3/analog/`). The published corpus is
    itself the nested shape (a run dir inside its parent project), so
    this was not a hypothetical.

Usage:
    python3 analog_a0_skip_forbidden_check.py <project_dir> [--json out.json]

Exit codes:
    0  PASS — forbidden artefact absent, OR present-but-no-skip-verdict,
       OR a sanctioned replacement exists.
    1  FAIL — A0_skip_decision.json encodes a top-level analog skip and
       NO sanctioned replacement is present.
    2  IO / usage error (missing arg, not a directory).

chip-AGNOSTIC. No vendor / chip / block-name hardcoded.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple


_SKIP_RE = re.compile(r"skip|skipped|skipped[\-_ ]?condition|no[\s_\-]?analog|"
                      r"digital[\s_\-]?only", re.IGNORECASE)

# Consulted BEFORE `_SKIP_RE`. A verdict that says a skip did NOT happen
# contains the substring `skip` and matched the rule it is the negation of.
# `no.?analog` / `digital.only` are deliberately NOT negatable here: those
# ARE the forbidden verdict, and "no analog" is not "not skipped".
_NEGATED_SKIP_RE = re.compile(
    r"\b(?:no|not|non|never)[_\-\s]*skip"      # NO_SKIP, not-skipped, never skip
    r"|\bskip(?:ped)?[_\-\s]*(?:=|:)?[_\-\s]*(?:false|none|no)\b"
    r"|\bnot\s+skipped\b",
    re.IGNORECASE,
)

# The named fields a decision is actually recorded in. Free prose in any
# OTHER field is not a verdict — reading it as one made an unrelated note
# decide this gate (see the docstring's measured defects).
_DECISION_KEYS = ("decision", "status", "verdict", "result",
                  "analog_decision")

# BOUNDED to this project's own analog roots. A trailing `**/` reached into
# archived / nested historical runs and judged them as this run's, in both
# directions (false FAIL on an archived skip, false PASS on a nested status).
_ANALOG_ROOTS = ("analog", "phase1/analog", "phase2/analog", "phase3/analog")

_FORBIDDEN_GLOBS = tuple(f"{r}/A0_skip_decision.json" for r in _ANALOG_ROOTS)

_STATUS_GLOBS = tuple(
    f"{r}/A0_implementation_status.json" for r in _ANALOG_ROOTS)

_L5_GLOBS = (
    "phase1/generated_docs/L5_ADI_SPEC.json",
    "phase1/generated_docs/L5*.json",
)


def _find_first(project: Path, globs) -> Optional[Path]:
    for pat in globs:
        for h in sorted(project.glob(pat)):
            if h.is_file():
                return h
    return None


def _encodes_skip(path: Path) -> Tuple[bool, str]:
    """Return (True, evidence) iff the file encodes a top-level skip.

    Robust: inspects the parsed `decision`/`status`/`verdict` fields if
    JSON-parsable; falls back to a raw-text scan otherwise (a garbage /
    unparsable A0_skip_decision.json is treated as encoding a skip,
    since its very name + presence is the failure pattern — honest FAIL,
    never vacuous PASS).
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return True, f"unreadable ({exc}) — treated as skip"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Unparsable but present + named skip_decision → treat raw text.
        if _SKIP_RE.search(raw):
            return True, "unparsable JSON but skip token in raw text"
        return True, "unparsable JSON named A0_skip_decision (presence)"

    def _verdict(scope: dict, prefix: str = "") -> Optional[Tuple[bool, str]]:
        """Read the NAMED decision fields of one object. Returns None when
        this object records no verdict at all, so the caller can look one
        level down instead of guessing from unrelated prose."""
        for key in _DECISION_KEYS:
            v = scope.get(key)
            if isinstance(v, bool):
                # `{"skipped": false}` shape carried on a decision key.
                return (v, f"{prefix}{key}={v!r}")
            if not isinstance(v, str):
                continue
            if _NEGATED_SKIP_RE.search(v):
                return False, f"{prefix}{key}={v!r} explicitly records NO skip"
            if _SKIP_RE.search(v):
                return True, f"{prefix}{key}={v!r}"
            # A named decision field that parses and says something else
            # (e.g. "PROCEED") is a real verdict and it is not a skip.
            return False, f"{prefix}{key}={v!r} is not a skip verdict"
        return None

    if isinstance(data, dict):
        got = _verdict(data)
        if got is not None:
            return got
        nested = data.get("analog")
        if isinstance(nested, dict):
            got = _verdict(nested, prefix="analog.")
            if got is not None:
                return got
    elif isinstance(data, str):
        if _NEGATED_SKIP_RE.search(data):
            return False, f"top-level string={data!r} records NO skip"
        if _SKIP_RE.search(data):
            return True, f"top-level string={data!r}"
    return False, "no skip verdict in parsed content"


def _status_replacement_ok(project: Path) -> Tuple[bool, str]:
    p = _find_first(project, _STATUS_GLOBS)
    if p is None:
        return False, ""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False, f"{p.name} present but unparsable"
    if not isinstance(data, dict):
        return False, f"{p.name} present but not an object"
    blocks = data.get("blocks")
    steps = data.get("steps")
    has_blocks = isinstance(blocks, (list, dict)) and len(blocks) > 0
    has_steps = isinstance(steps, (list, dict)) and len(steps) > 0
    if has_blocks or has_steps:
        return True, f"{p.name} (per-block/step status present)"
    return False, f"{p.name} present but empty blocks/steps"


def _l5_detected_false(project: Path) -> Tuple[bool, str]:
    p = _find_first(project, _L5_GLOBS)
    if p is None:
        return False, ""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False, ""
    if isinstance(data, dict) and data.get("analog_blocks_detected") is False:
        return True, f"{p.name}: analog_blocks_detected=false"
    return False, ""


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="analog_a0_skip_forbidden_check",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("project_dir", type=Path,
                    help="project root (holds analog/, phase1/, ...)")
    ap.add_argument("--json", default=None, help="write JSON report")
    args = ap.parse_args(argv)

    project = args.project_dir.resolve()
    report: dict = {"gate": "analog_a0_skip_forbidden_check"}

    def _emit(rc: int) -> int:
        if args.json:
            try:
                outp = Path(args.json)
                outp.parent.mkdir(parents=True, exist_ok=True)
                outp.write_text(json.dumps(report, indent=2,
                                           ensure_ascii=False) + "\n")
            except OSError as exc:
                print(f"error writing --json: {exc}", file=sys.stderr)
                return 2
        return rc

    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        report["status"] = "ERROR"
        return 2

    forbidden = _find_first(project, _FORBIDDEN_GLOBS)
    if forbidden is None:
        report["status"] = "PASS"
        report["detail"] = "A0_skip_decision.json not present"
        print("[PASS] analog_a0_skip_forbidden_check: forbidden "
              "A0_skip_decision.json not present")
        return _emit(0)

    rel = str(forbidden.relative_to(project))
    report["forbidden_artefact"] = rel
    encodes, evidence = _encodes_skip(forbidden)
    report["encodes_skip"] = encodes
    report["skip_evidence"] = evidence

    if not encodes:
        report["status"] = "PASS"
        report["detail"] = (f"{rel} present but encodes no skip verdict "
                            f"({evidence})")
        print(f"[PASS] analog_a0_skip_forbidden_check: {rel} present but "
              f"no top-level skip verdict ({evidence})")
        return _emit(0)

    # A real top-level skip is encoded — require a sanctioned replacement.
    status_ok, status_ev = _status_replacement_ok(project)
    l5_ok, l5_ev = _l5_detected_false(project)
    report["status_replacement_ok"] = status_ok
    report["l5_detected_false"] = l5_ok

    if status_ok or l5_ok:
        report["status"] = "PASS_WITH_REPLACEMENT"
        repl = status_ev if status_ok else l5_ev
        report["detail"] = (f"{rel} encodes skip but sanctioned "
                            f"replacement present: {repl}")
        print(f"[PASS] analog_a0_skip_forbidden_check: {rel} encodes skip "
              f"but sanctioned replacement present ({repl})")
        return _emit(0)

    report["status"] = "FAIL"
    report["detail"] = (
        f"{rel} encodes a top-level analog SKIP ({evidence}) with NO "
        f"sanctioned replacement. Replace with "
        f"analog/A0_implementation_status.json (per-block A1-A8 status) "
        f"OR set L5.analog_blocks_detected=false when the keyword scan "
        f"PASSes empty."
    )
    print(f"[FAIL] analog_a0_skip_forbidden_check: {report['detail']}")
    return _emit(1)


if __name__ == "__main__":
    sys.exit(main())
