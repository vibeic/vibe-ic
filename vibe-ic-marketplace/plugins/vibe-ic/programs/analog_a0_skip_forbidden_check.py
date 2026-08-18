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
  1. Look for `A0_skip_decision.json` at one of THIS PROJECT'S OWN
     canonical analog roots (`_ANALOG_ROOTS`). Never `**/` — see
     "THREE MEASURED DEFECTS" below.
  2. If absent → PASS (the forbidden artefact was not produced).
  3. If present → it is forbidden ONLY when it actually encodes a SKIP
     decision, read from the DECISION-BEARING keys and with negation
     honoured. A file that happens to be named that but carries no skip
     verdict is reported but not a hard FAIL — we FAIL on the real defect
     (a top-level analog skip), not on the filename alone.
  4. When a real skip IS encoded, FAIL unless one of the two sanctioned
     replacements is present and substantive, AT A CANONICAL ANALOG ROOT
     OF THIS PROJECT:
        (a) `A0_implementation_status.json` with a per-block / per-step
            status object (non-empty `blocks` or `steps`), OR
        (b) an L5_ADI_SPEC.json carrying `analog_blocks_detected=false`.

THREE MEASURED DEFECTS THIS FILE REPAIRS
----------------------------------------
This gate had never been wired anywhere, so nothing outside its own unit
test had ever handed it a project tree. Run over nine synthetic trees it
answered FOUR of them wrongly. The common root is that each of the three
matchers was WIDER than the rule it implements.

  1. NEGATION. `_SKIP_RE` was a bare `skip` alternation with no negation
     handling. `{"decision": "NO_SKIP", "rationale": "2 analog blocks
     detected; the analog track runs in full"}` — a file recording the
     exact OPPOSITE of the forbidden state — returned rc 1 with the
     evidence `decision='NO_SKIP'`. A gate that fails a run for writing
     down that it did the right thing teaches the next run not to write
     it down.

  2. PROSE IS NOT A VERDICT. The same regex was applied to EVERY string
     value in the object (`for v in data.values()`), not to the
     decision-bearing keys, so `{"decision": "PROCEED", "note": "no
     A-step was skipped in this run"}` FAILed on its own explanation.

  3. UNBOUNDED SEARCH. `_FORBIDDEN_GLOBS` and `_STATUS_GLOBS` both ended
     in `**/`, so neither search was bounded to the project. One choice,
     two failures in opposite directions:
       * a fully-run analog project carrying an ARCHIVED
         `archive/old_run/analog/A0_skip_decision.json` FAILed on a
         decision that is not this run's;
       * a real top-level skip was EXCUSED (rc 0) by an
         `A0_implementation_status.json` belonging to an unrelated nested
         run — a false negative on the single defect this gate exists
         for.
     The published corpus is exactly that nested shape
     (`<project>/clean_run_*/` inside `<project>/`), so both were live.

The repair in each case is to narrow the matcher to what the rule says:
decision-bearing keys, negation-aware, this project's own analog roots.

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
from typing import Any, List, Optional, Tuple

# `skip` / `skipped`, as a word. Deliberately NOT an alternation containing
# `no.?analog`: those two families need OPPOSITE negation handling (see
# `_value_encodes_skip`), and folding them into one pattern is what made a
# negation guard impossible to write.
_SKIP_TOKEN_RE = re.compile(r"\bskip(?:ped|ping)?\b", re.IGNORECASE)

# A negation IMMEDIATELY BEFORE the skip token, allowing the separators a
# JSON enum uses (`NO_SKIP`, `no-skip`, `not skipped`, `never skipped`).
_NEG_BEFORE_RE = re.compile(r"\b(?:no|not|never|without|non|zero)[\s_\-]*$",
                            re.IGNORECASE)

# Phrases that ARE a skip in their own right and carry their own "no".
_NO_ANALOG_RE = re.compile(r"\bno[\s_\-]?analog\b|"
                           r"\bdigital[\s_\-]?only\b|"
                           r"\banalog[\s_\-]?(?:not[\s_\-]?)?"
                           r"(?:absent|omitted)\b",
                           re.IGNORECASE)

# The keys whose VALUE is a verdict. Everything else in the file is prose.
_DECISION_KEYS = ("decision", "status", "verdict", "result", "analog_decision",
                  "analog_status", "outcome")

# Boolean-shaped verdicts: `{"skip": true}` / `{"analog_skipped": false}`.
_BOOL_SKIP_KEYS = ("skip", "skipped", "analog_skip", "analog_skipped",
                   "is_skipped")

# One nesting level the rule's own wording allows: `{"analog": {...}}`.
_NESTED_KEYS = ("analog", "a0", "analog_track")

# THIS PROJECT'S canonical analog roots. Fixed relative paths, never a
# recursive glob: an artefact belonging to a DIFFERENT run is not this
# project's decision, in either direction (defect 3 above).
_ANALOG_ROOTS = ("phase3/analog", "phase2/analog", "phase1/analog", "analog")

_FORBIDDEN_NAME = "A0_skip_decision.json"
_STATUS_NAME = "A0_implementation_status.json"

_L5_GLOBS = (
    "phase1/generated_docs/L5_ADI_SPEC.json",
    "phase1/generated_docs/L5*.json",
)


def _analog_root_file(project: Path, name: str) -> Optional[Path]:
    """First `<project>/<analog root>/<name>` that exists. Bounded on
    purpose — see defect 3."""
    for root in _ANALOG_ROOTS:
        cand = project / root / name
        if cand.is_file():
            return cand
    return None


def _find_first(project: Path, globs) -> Optional[Path]:
    for pat in globs:
        for h in sorted(project.glob(pat)):
            if h.is_file():
                return h
    return None


def _value_encodes_skip(value: str) -> bool:
    """True iff this verdict STRING states an analog skip.

    Negation-aware for the `skip` family, because `NO_SKIP` and `SKIPPED`
    differ by exactly the two characters the old matcher ignored. The
    `no analog` / `digital only` family is a skip in its own right and
    carries its own leading `no`, which is why the two are matched
    separately rather than by one alternation.
    """
    if _NO_ANALOG_RE.search(value):
        return True
    for m in _SKIP_TOKEN_RE.finditer(value):
        if not _NEG_BEFORE_RE.search(value[:m.start()]):
            return True
    return False


def _scan_object(data: dict, prefix: str = "") -> Tuple[bool, str]:
    """Verdict-bearing scan of one decision object (one nesting level)."""
    for key in _DECISION_KEYS:
        v = data.get(key)
        if isinstance(v, str) and _value_encodes_skip(v):
            return True, f"{prefix}{key}={v!r}"
    for key in _BOOL_SKIP_KEYS:
        v = data.get(key)
        if v is True:
            return True, f"{prefix}{key}=true"
    for key in _NESTED_KEYS:
        v = data.get(key)
        if isinstance(v, dict):
            hit, ev = _scan_object(v, prefix=f"{prefix}{key}.")
            if hit:
                return True, ev
    return False, ""


def _encodes_skip(path: Path) -> Tuple[bool, str]:
    """Return (True, evidence) iff the file encodes a top-level skip.

    Reads the DECISION-BEARING keys only (defects 1 and 2). Falls back to
    a raw-text scan when the JSON does not parse: an unparsable
    A0_skip_decision.json is treated as encoding a skip, since its very
    name + presence is the failure pattern — honest FAIL, never vacuous
    PASS.
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return True, f"unreadable ({exc}) — treated as skip"
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError:
        # Unparsable but present + named skip_decision → treat raw text.
        if _SKIP_TOKEN_RE.search(raw) or _NO_ANALOG_RE.search(raw):
            return True, "unparsable JSON but skip token in raw text"
        return True, "unparsable JSON named A0_skip_decision (presence)"
    if isinstance(data, dict):
        return _scan_object(data)
    if isinstance(data, str) and _value_encodes_skip(data):
        return True, f"top-level string={data!r}"
    return False, "no skip verdict in the decision-bearing keys"


def _status_replacement_ok(project: Path) -> Tuple[bool, str]:
    p = _analog_root_file(project, _STATUS_NAME)
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
        rel = p.relative_to(project)
        return True, f"{rel} (per-block/step status present)"
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
    report: dict = {"gate": "analog_a0_skip_forbidden_check",
                    # DISCLOSE THE DENOMINATOR. A reader of a PASS must be
                    # able to see WHERE this gate looked, because the whole
                    # repair above is about the search being bounded.
                    "searched_roots": list(_ANALOG_ROOTS),
                    "forbidden_artefact_name": _FORBIDDEN_NAME}

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

    forbidden = _analog_root_file(project, _FORBIDDEN_NAME)
    if forbidden is None:
        report["status"] = "PASS"
        report["detail"] = (f"{_FORBIDDEN_NAME} not present at any of "
                            f"{'/'.join(_ANALOG_ROOTS)}")
        print(f"[PASS] analog_a0_skip_forbidden_check: forbidden "
              f"{_FORBIDDEN_NAME} not present at any of "
              f"{'/'.join(_ANALOG_ROOTS)}")
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
