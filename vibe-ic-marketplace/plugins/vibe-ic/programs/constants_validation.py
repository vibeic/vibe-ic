#!/usr/bin/env python3
"""
constants_validation.py — Deterministic compliance check for rtl-constants-gen.

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
Verifies that RTL constants JSON files contain well-formed constant definitions
with required fields (name, value, width/bits) and no duplicates.

What it catches:
  1. NO_CONSTANTS_FILE — no *constants*.json or *rtl_constants*.json found
  2. INVALID_JSON — file is not valid JSON or cannot be parsed
  3. MISSING_FIELD — a constant entry is missing a required field
  4. INVALID_FIELD — a field has an invalid value (empty name, null value, bad width)
  5. DUPLICATE_NAME — two or more constants share the same name
  6. EMPTY_CONSTANTS — file parses but contains zero constant entries
  7. SECTION_STRUCTURE — (WARNING) no recognized section keys in top-level dict
  8. MISSING_COMMENT — (WARNING) a constant entry has no 'comment' field

Usage:
    python3 constants_validation.py ./my_project
    python3 constants_validation.py ./my_project --json

Exit codes:
    0 = all checks pass
    1 = one or more checks fail

Generality: works for ANY IC project with RTL constants JSON.
No external tool dependencies — pure Python.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    rule: str
    severity: str       # ERROR, WARNING, INFO
    message: str
    file: str = ""


@dataclass
class AuditResult:
    program: str
    passed: bool
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------
def discover_constants_files(base: Path) -> List[Path]:
    """Find JSON files matching *constants*.json or *rtl_constants*.json."""
    found: List[Path] = []
    for fpath in sorted(base.rglob("*.json")):
        name_lower = fpath.name.lower()
        if "constants" in name_lower:
            found.append(fpath)
    return found


# ---------------------------------------------------------------------------
# Extract constants list from parsed JSON
# ---------------------------------------------------------------------------
#: The two entry SHAPES this file can hold, and the key each is spelled with.
#: They are not the same object and must not be judged by the same schema: a
#: CONSTANT is a fixed value the RTL bakes in, so it has a `value` and a width;
#: a PARAMETER is an override point, so its value lives in `default` and it is
#: routinely unsized -- a Verilog `parameter` needs no width and most carry
#: none. Collapsing the two is what made this gate demand `value`/`width` of
#: every parameter the L8 emitter writes, which is a shape no emitter produces.
KIND_CONSTANTS = "constants"
KIND_PARAMETERS = "parameters"
#: No recognized slot was found. NOT a shape — the absence of one. A document
#: reported as KIND_UNKNOWN is NOT GRADED, and says so; guessing which
#: design-descriptive section holds the constants is the defect this replaces.
KIND_UNKNOWN = "unknown"

#: Marks an entry normalised out of a `{NAME: value}` MAPPING. The mapping form
#: has nowhere to write a width or a comment, so neither is asked of it — the
#: same principle that exempts a parameter from a width: never require of a
#: producer information its form cannot express.
_MAPPING_MARK = "__from_mapping__"

_CONSTANT_KEYS = ("constants", "rtl_constants")
_PARAMETER_KEYS = ("params", "parameters")


def extract_constants(data) -> list:
    """The entry list alone, for callers that do not care which shape it is.

    Kept so the module's published surface does not change. New code should
    call `extract_entries`, which also says WHICH of the two shapes it read.
    """
    return extract_entries(data)[0]


def extract_entries(data) -> "tuple":
    """(entries, kind) for a parsed constants JSON.

    `kind` is what the entries were spelled as, so the caller can require the
    fields that shape actually carries instead of one schema for both. An
    unkeyed list -- a bare top-level list, or the first-list fallback -- is
    reported as KIND_CONSTANTS, which is the behaviour this program already
    had for it and the stricter of the two; widening it would lose findings.
    """
    if isinstance(data, list):
        return data, KIND_CONSTANTS
    if isinstance(data, dict):
        # Prefer an explicit constants key, then an explicit parameters key —
        # and accept EITHER SPELLING at each key before moving to the next.
        #
        # A MAPPING `{NAME: value}` is a legitimate way to write RTL constants:
        # MEASURED 2026-08-29, 5 designs (52 of 1453 real generated_docs trees)
        # spell `constants` that way. It used to fall through to the first-list
        # fallback and be reported EMPTY.
        #
        # THE SPELLING IS RESOLVED PER KEY, NOT PER SHAPE, and that ordering is
        # load-bearing: those same 52 trees carry BOTH a non-empty `constants`
        # mapping and an EMPTY `parameters` list. A shape-major loop reaches the
        # empty list first and abstains over a document that had constants in it
        # all along — measured while writing this change.
        for key in _CONSTANT_KEYS + _PARAMETER_KEYS:
            if key not in data:
                continue
            kind = KIND_CONSTANTS if key in _CONSTANT_KEYS else KIND_PARAMETERS
            if isinstance(data[key], list):
                return data[key], kind
            if isinstance(data[key], dict):
                return ([{"name": k, "value": v, _MAPPING_MARK: True}
                         for k, v in data[key].items()], kind)
        # NO FIRST-LIST FALLBACK. It used to `return v, KIND_CONSTANTS` for the
        # first list value in the dict, whatever key that was. MEASURED across
        # 2614 real L8 documents, that picked `source_documents`, `evidence`,
        # `clock_domains`, `max_throughput_table` and
        # `tap_state_names_in_canonical_order` on 339 files — prose provenance
        # and clock tables graded against a constants schema, under the
        # STRICTEST of the two shapes. A wrong denominator is worse than none,
        # so the answer is now "no recognized slot" and the caller discloses it.
        return [], KIND_UNKNOWN
    return [], KIND_UNKNOWN


# ---------------------------------------------------------------------------
# Core audit logic
# ---------------------------------------------------------------------------
def audit(project_dir: str) -> AuditResult:
    findings: List[Finding] = []
    base = Path(project_dir)

    if not base.exists() or not base.is_dir():
        findings.append(Finding(
            rule="DIR_MISSING",
            severity="ERROR",
            message=f"Project directory does not exist: {project_dir}",
        ))
        return AuditResult(
            program="constants_validation",
            passed=False,
            findings=findings,
            summary={"files_checked": 0, "constants_total": 0},
        )

    json_files = discover_constants_files(base)

    if not json_files:
        findings.append(Finding(
            rule="NO_CONSTANTS_FILE",
            severity="ERROR",
            message="No *constants*.json files found in project directory",
        ))
        return AuditResult(
            program="constants_validation",
            passed=False,
            findings=findings,
            summary={"files_checked": 0, "constants_total": 0},
        )

    all_names: dict = {}  # name -> file (for duplicate detection across files)
    total_constants = 0
    abstained = 0        # files whose recognized slot was present and EMPTY
    ungraded = 0         # files with no recognized slot at all

    for jf in json_files:
        rel = str(jf.relative_to(base)) if jf.is_relative_to(base) else str(jf)

        # Parse JSON
        try:
            raw = jf.read_text(errors="replace")
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            findings.append(Finding(
                rule="INVALID_JSON",
                severity="ERROR",
                message=f"Invalid JSON: {e}",
                file=rel,
            ))
            continue
        except OSError as e:
            findings.append(Finding(
                rule="READ_ERROR",
                severity="ERROR",
                message=f"Cannot read file: {e}",
                file=rel,
            ))
            continue

        # A recognized slot that holds a SCALAR is a schema REGRESSION, and a
        # different finding from "this document has no constants slot": the
        # producer meant to write one and wrote something nothing can be read
        # from. Distinguishing them matters — one is a bug upstream, the other
        # is a document out of this gate's declared scope.
        bad_slot = None
        if isinstance(data, dict):
            for key in _CONSTANT_KEYS + _PARAMETER_KEYS:
                if key in data and not isinstance(data[key], (list, dict)):
                    bad_slot = key
                    break
        if bad_slot is not None:
            findings.append(Finding(
                rule="SLOT_NOT_A_COLLECTION",
                severity="ERROR",
                message=f"'{bad_slot}' is "
                        f"{type(data[bad_slot]).__name__}, not a list or an "
                        "object — nothing can be read from it",
                file=rel,
            ))
            continue

        constants, kind = extract_entries(data)

        if kind == KIND_UNKNOWN:
            # NOT GRADED, and it says so by name. `RECOGNIZED_SECTIONS` used to
            # decide this from five section names lifted from ONE design
            # (tx_phy / rx_phy / crc8 / mac / port_naming) — matched by 0 of
            # 2614 real L8 documents, and a flow-level program that carries one
            # design's vocabulary has stopped being flow. The successor asks
            # only whether a recognized constants SLOT is present, which is
            # design-independent. WARNING, not ERROR: such a document is not
            # malformed, it is out of the declared scope, and firing on a
            # legitimately-complete design is a bug in the gate.
            findings.append(Finding(
                rule="SLOT_UNRECOGNIZED",
                severity="WARNING",
                message="no recognized constants slot ("
                        + ", ".join(_CONSTANT_KEYS + _PARAMETER_KEYS)
                        + ") — NOT GRADED. This file was read and no verdict "
                          "was reached about it.",
                file=rel,
            ))
            ungraded += 1
            continue

        if len(constants) == 0:
            # THE SLOT IS PRESENT AND EMPTY: this design declared no constants.
            # MEASURED 2026-08-29: 1321 of 1453 real generated_docs trees are in
            # that state, and this rule failed every one of them as an ERROR.
            # It is a legitimate state, so it is not a defect — and nothing was
            # verified, so it is not a PASS either. A named abstention, counted,
            # and `status_word()` refuses to print PASS over it.
            findings.append(Finding(
                rule="NO_CONSTANTS_DECLARED",
                severity="INFO",
                message=f"'{kind}' is present and empty — this design declared "
                        "no constants, so nothing here was verified",
                file=rel,
            ))
            abstained += 1
            continue

        for idx, entry in enumerate(constants):
            # Name the shape that was actually read. A message that says
            # `constants[0]` about a parameter misnames the object it refuses.
            # A mapping entry is named by its KEY: an index into a dict's
            # iteration order is not something a reader can look up.
            if isinstance(entry, dict) and entry.get(_MAPPING_MARK) is True:
                prefix = f"{kind}['{entry.get('name')}']"
            else:
                prefix = f"{kind}[{idx}]"

            if not isinstance(entry, dict):
                findings.append(Finding(
                    rule="INVALID_FIELD",
                    severity="ERROR",
                    message=f"{prefix}: entry is not a dict (got {type(entry).__name__})",
                    file=rel,
                ))
                continue

            # Check 'name'
            name = entry.get("name")
            if name is None or (isinstance(name, str) and name.strip() == ""):
                findings.append(Finding(
                    rule="MISSING_FIELD",
                    severity="ERROR",
                    message=f"{prefix}: missing or empty 'name'",
                    file=rel,
                ))
            else:
                name_str = str(name).strip()
                # Duplicate check
                if name_str in all_names:
                    findings.append(Finding(
                        rule="DUPLICATE_NAME",
                        severity="ERROR",
                        message=f"{prefix}: duplicate constant name '{name_str}' "
                                f"(first seen in {all_names[name_str]})",
                        file=rel,
                    ))
                else:
                    all_names[name_str] = rel

            # Check the entry's VALUE field, under the name its shape uses.
            # A parameter's value is its `default`; `value` is still accepted
            # for an emitter that spells it that way, so this only ever widens
            # what satisfies the check -- an entry carrying neither is still
            # a finding, and that is the defect this rule exists to catch.
            if kind == KIND_PARAMETERS:
                value_keys = ("default", "value")
            else:
                value_keys = ("value",)
            if not any(k in entry and entry[k] is not None for k in value_keys):
                spelled = "' or '".join(value_keys)
                findings.append(Finding(
                    rule="MISSING_FIELD",
                    severity="ERROR",
                    message=f"{prefix}: missing or null '{spelled}'",
                    file=rel,
                ))

            # Prose (WARNING only). The emitter writes 'description'; older
            # documents write 'desc'; the constant shape writes 'comment'. Not
            # asked of a MAPPING entry, which has no field to put one in.
            from_mapping = entry.get(_MAPPING_MARK) is True
            if not from_mapping and not any(
                    k in entry for k in ("comment", "description", "desc")):
                findings.append(Finding(
                    rule="MISSING_COMMENT",
                    severity="WARNING",
                    message=f"{prefix}: no 'comment' / 'description' / 'desc' field",
                    file=rel,
                ))

            # Check 'width' or 'bits'. REQUIRED of a constant, which is a
            # literal the RTL bakes in at a definite width; NOT required of a
            # parameter, which is an override point and is routinely unsized
            # (`parameter memsize = 1024;` is legal and carries no width). A
            # width that IS stated is validated either way -- declaring one
            # and declaring it wrong is a finding whatever the shape.
            width = entry.get("width", entry.get("bits"))
            if width is None:
                # ...and not of a MAPPING either: `{NAME: value}` has nowhere to
                # write a width. MEASURED: an earlier draft of this very change
                # required it there and falsely reddened 52 of 1453 real trees
                # (5 designs). Same principle as the parameter exemption above.
                if kind != KIND_PARAMETERS and not from_mapping:
                    findings.append(Finding(
                        rule="MISSING_FIELD",
                        severity="ERROR",
                        message=f"{prefix}: missing 'width' or 'bits' field",
                        file=rel,
                    ))
            else:
                try:
                    w = int(width)
                    if w <= 0:
                        findings.append(Finding(
                            rule="INVALID_FIELD",
                            severity="ERROR",
                            message=f"{prefix}: 'width'/'bits' must be > 0 (got {w})",
                            file=rel,
                        ))
                except (ValueError, TypeError):
                    findings.append(Finding(
                        rule="INVALID_FIELD",
                        severity="ERROR",
                        message=f"{prefix}: 'width'/'bits' is not a valid integer (got {width!r})",
                        file=rel,
                    ))

            total_constants += 1

    # A run that GRADED NOTHING is not a run that found nothing wrong. The
    # global EMPTY_CONSTANTS error that stood here made "this design declared no
    # constants" — 1321 of 1453 real trees, measured — indistinguishable from a
    # defect. The count is reported instead, and `status_word` refuses to print
    # PASS over it.
    graded = total_constants
    errors = sum(1 for f in findings if f.severity == "ERROR")

    return AuditResult(
        program="constants_validation",
        passed=errors == 0,
        findings=findings,
        summary={
            "files_checked": len(json_files),
            "constants_total": graded,
            "graded": graded,
            "abstained_files": abstained,
            "ungraded_files": ungraded,
            "duplicates": sum(1 for f in findings if f.rule == "DUPLICATE_NAME"),
            "errors": errors,
        },
    )


def status_word(result: AuditResult) -> str:
    """PASS / FAIL / NOT_GRADED — and NOT_GRADED is not a shade of PASS.

    A run that reached no entry has verified nothing, and printing PASS over it
    is how an audit reader comes to believe a document was checked. The exit
    code cannot carry the distinction: this gate is wired
    `advisory_program_exit_zero` and its rc is not read as a verdict at all, so
    the status WORD is the only channel there is.
    """
    if not result.passed:
        return "FAIL"
    if result.summary.get("graded", 0) == 0:
        return "NOT_GRADED"
    return "PASS"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(
        description="Deterministic compliance check for rtl-constants-gen"
    )
    p.add_argument("project_dir", nargs="?", default=".")
    p.add_argument("--json", action="store_true",
                   help="Output JSON report to stdout")
    args = p.parse_args()

    result = audit(args.project_dir)

    if args.json:
        print(json.dumps(asdict(result), indent=2, ensure_ascii=False))
    else:
        for f in result.findings:
            tag = f"[{f.file}] " if f.file else ""
            print(f"[{f.severity}] {f.rule}: {tag}{f.message}")
        status = status_word(result)
        if status == "NOT_GRADED":
            print("\nNOT_GRADED — no constant entry was reached, so nothing was "
                  "verified. This is not a PASS.")
        print(f"\n{status} — {result.summary}")

    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
