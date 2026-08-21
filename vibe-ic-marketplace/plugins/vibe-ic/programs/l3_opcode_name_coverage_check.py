#!/usr/bin/env python3
"""l3_opcode_name_coverage_check.py — v1.6.131 (#51 Fix 6)

Phase 1 verify gate that fails when L3.opcodes contains structurally-
present entries (count > 0) but per-entry names are predominantly
placeholders. Closes the false-PASS path field-agent observed at
v1.6.130:

  L3.opcodes = 18 entries
  9 entries:  name="OPCODE_NAME_UNKNOWN"
  9 entries:  real names

Without this gate, downstream consumers see ``len(L3.opcodes) == 18``
and assume the dispatcher table is complete; phase2 spec-to-RTL emit
then runs against half-placeholder data and emits a default-only
dispatcher that leaves the DUT silent on every opcode in reference_tb.

Verdict tiers (chip-AGNOSTIC):

  PASS         — placeholder ratio == 0 (every opcode has a real name).
  FAIL         — any placeholder name (ratio > 0).
                 v1.6.132 (#51 Fix 7c) tightened from 5% to 0%
                 because protocol-spec docs always declare a name
                 for every opcode; any UNKNOWN means the extractor
                 missed it, not a legitimate vendor quirk.
  VACUOUS_PASS — len(L3.opcodes) == 0 (no command protocol in input,
                 covered by `no_opcodes_in_input: true`).

WHAT THIS GATE DOES NOT MEASURE (#454 follow-up)
------------------------------------------------
It measures whether a name is a PLACEHOLDER. It cannot measure whether
the row the name came from was a command at all. When the L3 walker
scrapes a table that has a command table's two-column shape but declares
no commands — a connector pin-assignment chapter, a figure's bit-position
axis — the scraped SIGNAL name reads as a perfectly good name, and this
gate reported `PASS — 0/18 opcode(s) carry placeholder names` over 18
fabricated ones. Measured over the committed corpus: 12 designs verdict
PASS, blessing 188 opcodes, of which at least 18 are that artefact.

The L3 emitter now refuses those rows at source and COUNTS the refusals
in `non_command_row_refusal_count`. This gate READS that counter and
DISCLOSES it, because two of its statements are otherwise false on a
document that had rows refused:

  * `VACUOUS_PASS — no command protocol in input` is not what an empty
    `opcodes[]` means when the walker saw candidate rows and judged none
    of them commands. That is a REFUSAL, not an absence.
  * `PASS — 0/N carry placeholder names` reads as an endorsement of N
    rows, when the same document is on record as having had rows refused
    as non-commands — so name quality was measured on the survivors of a
    filter, not on a verified command set.

The disclosure does NOT change the verdict and does NOT introduce a new
FAIL. Measured over the 62 corpus designs that ship their input document,
ZERO have both a non-empty `opcodes[]` and a non-zero refusal count, so a
FAIL-on-refusal rule has no measured true positive to justify it and a
document that legitimately carries both a command table and a pinout
chapter is an ordinary, correct design.

Exit codes:
  0 PASS / PASS_WITH_WAIVERS / VACUOUS_PASS
  1 FAIL
  2 input error / silent skip (L3 absent — phase1 hadn't run yet) /
    NOT_CHECKED (empty L3 but the input was not fully read — #499)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

GATE = "l3_opcode_name_coverage_check"
# v1.6.137 (#51 Fix 12) — `RESERVED` is the canonical protocol-spec
# mnemonic for unimplemented / placeholder rows in command tables
# (the v1.6.136 `無` → RESERVED alias surfaces this), NOT an
# extractor-miss sentinel. Treating it as placeholder caused a
# false-FAIL on rows that have a perfectly valid mnemonic.
# Real placeholder names = TODO / TBD / TBA / UNKNOWN / "" / null /
# the OPCODE_NAME_UNKNOWN sentinel from `_infer_opcode_name`.
PLACEHOLDER_NAMES = frozenset({
    "OPCODE_NAME_UNKNOWN", "TODO", "TBD", "TBA",
    "UNKNOWN", "PLACEHOLDER", "",
})
PLACEHOLDER_THRESHOLD = 0.0  # v1.6.132 — 100% coverage required

import _path_layout as _pl
# v1.7.72 — for #499. VACUOUS_PASS asserts something about the INPUT
# ("no command protocol in input"). That assertion is only available
# once the input has actually been read.
import _input_ingest as _ingest


def _is_placeholder(op: Dict[str, Any]) -> bool:
    name = op.get("name")
    if name is None:
        return True
    if isinstance(name, str) and name.upper() in PLACEHOLDER_NAMES:
        return True
    return False


# #454 follow-up — the L3 emitter's honest-uncertainty counter. A row the
# opcode walker matched and then refused because the row is structurally
# not a command-table row. Absent / non-int on documents emitted before
# the counter existed, which is NOT the same as zero — say so.
REFUSAL_COUNT_KEY = "non_command_row_refusal_count"


def _refusal_count(l3: Dict[str, Any]):
    """Return the emitter's non-command-row refusal count, or None when the
    document does not carry the counter at all."""
    n = l3.get(REFUSAL_COUNT_KEY)
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        return None
    return n


def _refusal_disclosure(refused, empty: bool) -> str:
    """The sentence appended to the verdict reason. Pure function of the
    counter and of whether `opcodes[]` came out empty."""
    if refused is None:
        return (" This L3 carries no "
                f"`{REFUSAL_COUNT_KEY}`, so whether the walker refused any "
                "candidate row is UNKNOWN — not zero.")
    if refused == 0:
        return ""
    if empty:
        return (f" NOT AN ABSENCE: the walker matched {refused} candidate "
                "row(s) in this document and refused every one as "
                "structurally not a command row, so `opcodes[]` is empty by "
                "REFUSAL. Read `non_command_row_refusals` before concluding "
                "the input declares no command protocol.")
    return (f" DISCLOSURE: {refused} row(s) in the same document were "
            "refused as structurally not command rows. Name quality is "
            "measured on the rows that survived that filter; a non-"
            "placeholder name is not evidence that its row is a command.")


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=GATE, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None,
                    help="write JSON verdict to this path")
    args = ap.parse_args(argv)

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    l3_path = _pl.generated_docs_dir(project) / "L3_CMD_PROTOCOL.json"
    if not l3_path.is_file():
        print(f"SILENT_SKIP: {l3_path} not found "
              f"(phase1 hasn't run yet?)", file=sys.stderr)
        return 2

    try:
        l3 = json.loads(l3_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: cannot parse {l3_path}: {e}", file=sys.stderr)
        return 2

    opcodes = l3.get("opcodes") or []
    # #454 follow-up — read the emitter's refusal counter so neither branch
    # below can state an absence or an endorsement the document contradicts.
    refused = _refusal_count(l3)
    # v1.7.72 — for #499. Whether the ingester read every staged
    # document. Measured on a real CPU: both L3 gates reported
    # VACUOUS_PASS — "no command protocol in input" — while the document
    # declaring its eleven opcodes had been dropped by the converter and
    # recorded as dropped in the ingester's own skip log. The gate could
    # not have known; now it can, and it says so instead of certifying
    # an absence over input it never read.
    unread_docs = _ingest.unread_input_documents(project)
    if not isinstance(opcodes, list) or not opcodes:
        if unread_docs:
            verdict = "NOT_CHECKED"
            report = {
                "gate": GATE, "verdict": verdict,
                "reason": "L3.opcodes empty, but the input was not fully "
                          "read — no conclusion about the design is "
                          "available."
                          + _ingest.absence_claim_disclosure(project)
                          + _refusal_disclosure(refused, empty=True),
                "total": 0, "placeholders": 0, "placeholder_ratio": 0.0,
                "threshold": PLACEHOLDER_THRESHOLD,
            }
        else:
            # No opcodes — this is the no_opcodes_in_input case.
            verdict = "VACUOUS_PASS"
            report = {
                "gate": GATE, "verdict": verdict,
                "reason": "L3.opcodes empty — no command protocol in input "
                          "(structurally correct for non-protocol IPs)."
                          + _refusal_disclosure(refused, empty=True),
                "total": 0, "placeholders": 0, "placeholder_ratio": 0.0,
                "threshold": PLACEHOLDER_THRESHOLD,
            }
        report["unread_input_documents"] = unread_docs
    else:
        total = len(opcodes)
        placeholders = sum(1 for op in opcodes
                            if isinstance(op, dict) and _is_placeholder(op))
        ratio = placeholders / total
        if ratio <= PLACEHOLDER_THRESHOLD:
            # ratio == 0 — every opcode has a real name.
            verdict = "PASS"
        else:
            verdict = "FAIL"
        report = {
            "gate": GATE, "verdict": verdict,
            "reason": (f"{placeholders}/{total} opcode(s) carry placeholder "
                       f"names (threshold {PLACEHOLDER_THRESHOLD:.0%})."
                       + _refusal_disclosure(refused, empty=False)),
            "total": total, "placeholders": placeholders,
            "placeholder_ratio": round(ratio, 4),
            "threshold": PLACEHOLDER_THRESHOLD,
            "placeholder_hexes": [
                op.get("hex") for op in opcodes
                if isinstance(op, dict) and _is_placeholder(op)
            ][:32],
        }
    # #454 follow-up — machine-readable form of the same disclosure, so a
    # consumer does not have to parse `reason` prose. `null` means the L3
    # predates the counter (UNKNOWN), which is not the same as 0.
    report["non_command_rows_refused"] = refused
    report["measures"] = "opcode NAME placeholder-ness only"
    report["does_not_measure"] = (
        "whether the source row was a command row at all")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False)
                        + "\n", encoding="utf-8")

    if verdict == "FAIL":
        print(f"FAIL: {report['reason']}", file=sys.stderr)
        return 1
    # v1.7.72 — for #499. NOT_CHECKED is rc 2, the gate's documented
    # "could not check" code — deliberately NOT rc 0. The design is not
    # accused of anything; the gate simply declines to certify an
    # absence over input it never read. Blocking on unread input is the
    # ingest-completeness check's job, not this gate's.
    if verdict == "NOT_CHECKED":
        print(f"NOT_CHECKED: {report['reason']}", file=sys.stderr)
        return 2
    if verdict == "VACUOUS_PASS":
        print(f"VACUOUS_PASS: {report['reason']}")
        return 0
    print(f"{verdict}: {report['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
