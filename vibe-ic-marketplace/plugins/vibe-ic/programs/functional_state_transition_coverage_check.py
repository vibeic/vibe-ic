#!/usr/bin/env python3
"""
functional_state_transition_coverage_check.py — Verify TBs exercise the
state-changing side-effects of every cmd opcode, not just byte-stream
correctness.

THE PROBLEM
-----------
The vendor dispatcher TB drove every cmd opcode through and confirmed
the response bytes matched. The TB never checked:
  - awake-state register set/cleared after the right opcodes
  - register echo back on read commands
  - periodic timers starting/stopping after enable/disable opcodes
Bugs in those side-effect paths shipped to FPGA undetected.

This gate cross-references a "coverage spec" (the side-effects each
opcode is required to produce) against TB content and reports any
opcode whose matching side-effect is not asserted in the TB.

INPUTS
------
A coverage spec JSON or repeat-CLI:
  ``--coverage <coverage.json>``::
    [
      {"opcode": "0x74",
       "must_assert_set": ["awake_q == 1'b1"]},
      {"opcode": "0x70",
       "must_assert_set": ["reg_q == data_in"]},
      {"opcode": "0x76",
       "must_assert_set": ["wake_pulse_active == 1'b0"]}
    ]

  ``--cov "0x74:awake_q == 1'b1"`` (may repeat)

USAGE
-----
    python3 functional_state_transition_coverage_check.py sim/ \\
        --coverage tb_coverage.json \\
        --json reports/gates/state_cov.json

EXIT CODES
----------
    0 — at least one TB was READ, and every opcode's required state
        assertion appears in it.
    1 — at least one opcode lacks the required assertion, OR no TB source
        was found at all (coverage is then zero, not complete).
    2 — IO / argument error.

WHY "NO TB FOUND" IS A FAILING VERDICT, NOT A WARNING
-----------------------------------------------------
This gate used to answer "no TB under <dir>" with a WARN finding and an
early return. WARN does not feed the verdict, so the report said
``"errors": 0, "verdict": "PASS"`` — i.e. it certified "every opcode's
required state assertion appears in some TB" having read no TB at all.
FAIL was structurally unreachable for that entire class of input, which
is precisely the class where measured coverage is zero.

That was not a corner case. TB discovery matched only ``tb_*.v``,
``tb_*.sv``, ``*_tb.v`` and ``*_tb.sv``, and the two most common
testbench filenames written in this tree are the bare stems ``tb.v`` and
``tb.sv`` — neither of which any of those four globs matches. A
directory holding a real testbench named ``tb.v`` scored PASS.

So both halves are repaired here: discovery now recognises a testbench by
its stem (a strict superset of the four old globs, so it can only ever
ADD text to the scanned blob), and a genuinely empty testbench corpus is
an ERROR that reaches the FAIL verdict.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Finding:
    severity: str
    rule: str
    file: str
    line: int
    message: str
    # Which coverage entry this is about, so the report can count
    # unverified opcodes without re-parsing its own prose.
    opcode: str = ""


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _parse_inline(s: str) -> Optional[Dict[str, Any]]:
    # Format: "OPCODE:assertion text"
    m = re.match(r"^\s*(0x[0-9a-fA-F]+|\d+)\s*:\s*(.+)$", s)
    if not m:
        return None
    return {"opcode": m.group(1), "must_assert_set": [m.group(2).strip()]}


# A testbench is recognised by its STEM, not by four hand-written globs.
# This matches every stem the old globs matched (``tb_x`` via ``^tb[_-]``,
# ``x_tb`` via ``[_-]tb$``) and additionally the bare ``tb`` stem, the
# infix ``x_tb_y`` form, and ``testbench*``. Strictly a superset: widening
# discovery can only ADD source text to the scanned blob, and every
# finding this gate emits is an ABSENCE, so no target that passes today
# can be turned red by the widening alone.
_TB_STEM_RE = re.compile(r"^tb$|^tb[_-]|[_-]tb$|[_-]tb[_-]|testbench", re.IGNORECASE)
_TB_SUFFIXES = (".v", ".sv")


def discover_tb_files(tb_target: Path) -> List[Path]:
    """Every testbench source under ``tb_target`` (or the file itself)."""
    if tb_target.is_file():
        return [tb_target]
    found: List[Path] = []
    for suffix in _TB_SUFFIXES:
        for p in tb_target.rglob("*" + suffix):
            if p.is_file() and _TB_STEM_RE.search(p.stem):
                found.append(p)
    return sorted(set(found))


def _opcode_hex_body(op: str) -> Optional[str]:
    """Normalise an opcode to its bare hex digits, or None if not numeric.

    ``0x74`` -> ``74``; ``0x0A`` -> ``a``; decimal ``116`` -> ``74``.
    The old code used ``op.lower().lstrip("0x")``, which strips EVERY
    leading ``0`` and ``x`` character: ``0x0a`` became ``a`` and the
    resulting pattern could not match the ``8'h0a`` literal actually
    written in the TB, so a driven opcode was reported as never driven.
    """
    s = op.strip().lower()
    if s.startswith("0x"):
        body = s[2:]
    elif re.fullmatch(r"[0-9]+", s):
        body = format(int(s, 10), "x")
    else:
        body = s
    if not re.fullmatch(r"[0-9a-f]+", body or ""):
        return None
    return body.lstrip("0") or "0"


def audit(tb_target: Path, coverage: List[Dict[str, Any]],
          files: Optional[List[Path]] = None) -> List[Finding]:
    findings: List[Finding] = []
    if files is None:
        files = discover_tb_files(tb_target)
    if not files:
        # NOT a WARN. WARN never reaches the verdict, so answering this
        # input class with WARN made "PASS" the only verdict the gate
        # could emit for a target it had read nothing from.
        findings.append(Finding(
            "ERROR", "no_tb_files", str(tb_target), 0,
            f"no testbench source found under {tb_target} — "
            f"{len(coverage)} coverage entr"
            f"{'y is' if len(coverage) == 1 else 'ies are'} therefore "
            f"UNVERIFIED, and the state-transition coverage measured here "
            f"is zero. This is a failing verdict, not a clean one: the "
            f"gate cannot certify assertions it never read. Point the `tb` "
            f"argument at the directory that holds the testbench sources.",
        ))
        return findings

    blob = "\n\n".join(_strip_comments(f.read_text(errors="replace"))
                        for f in files)

    for idx, entry in enumerate(coverage):
        op = str(entry.get("opcode", "")).strip()
        asserts = entry.get("must_assert_set") or []
        if not op:
            findings.append(Finding(
                "ERROR", "coverage_malformed", "(none)", 0,
                f"coverage entry missing opcode: {entry!r}",
                opcode=f"<entry #{idx}>",
            ))
            continue

        # An entry that demands nothing can only ever be reported PASS —
        # the same unearned green as the no-TB path, one level up in the
        # spec. Say so instead of scoring it.
        if not [a for a in asserts if str(a).strip()]:
            findings.append(Finding(
                "ERROR", "coverage_entry_asserts_nothing", "(none)", 0,
                f"opcode {op!r}: must_assert_set is empty, so this gate has "
                f"no side-effect to look for and could only ever report PASS "
                f"for this opcode. State the register/flag change the opcode "
                f"is required to produce, or remove the entry.",
                opcode=op,
            ))
            continue

        body = _opcode_hex_body(op)
        if body is None:
            findings.append(Finding(
                "ERROR", "coverage_malformed", "(none)", 0,
                f"opcode {op!r} is not a numeric literal, so no TB literal "
                f"can be derived from it and its coverage cannot be measured.",
                opcode=op,
            ))
            continue

        # The opcode should appear in the TB (either as send_cmd(0x..) or
        # `cmd = 0x..` or written into a packet). If absent, the test
        # never exercises the opcode at all. Leading zeros are tolerated on
        # both sides, and the sized-literal form accepts any width, not
        # just `8'h`.
        core = r"0*" + re.escape(body)
        op_pattern = re.compile(
            r"\b(?:0x" + core + r"|\d*'h" + core + r")\b",
            re.IGNORECASE,
        )
        if not op_pattern.search(blob):
            findings.append(Finding(
                "ERROR", "opcode_not_exercised", "(none)", 0,
                f"opcode {op!r} is not driven by any TB (no send_cmd, "
                f"no 8'h... literal). The state-transition coverage for "
                f"this opcode is zero by definition.",
                opcode=op,
            ))
            continue

        # Each assertion needs both operands (LHS and RHS of the
        # comparison) to appear close together (within ~120 chars) in
        # at least one TB. This tolerates `==` / `!==` / `!=` swaps
        # that always happen in `if (x !== expected) $fatal;`-style
        # checks.
        for assertion in asserts:
            tok = assertion.strip()
            if not tok:
                continue
            split = re.split(r"\s*(?:==|!=|!==|>=|<=|>|<)\s*", tok, maxsplit=1)
            if len(split) == 2:
                lhs, rhs = split[0].strip(), split[1].strip()
            else:
                lhs, rhs = tok, ""
            if not lhs:
                continue
            lhs_re = re.compile(re.escape(lhs), re.IGNORECASE)
            present = False
            for m in lhs_re.finditer(blob):
                window = blob[max(0, m.start() - 60):m.end() + 60]
                if not rhs or rhs.lower() in window.lower():
                    present = True
                    break
            if not present:
                findings.append(Finding(
                    "ERROR", "assertion_missing", "(none)", 0,
                    f"opcode {op!r}: required side-effect assertion "
                    f"{tok!r} is NOT present in any TB (looked for "
                    f"{lhs!r} in proximity to {rhs!r}). The TB drives "
                    f"the opcode but never checks the state change the "
                    f"spec requires.",
                    opcode=op,
                ))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    ap.add_argument("tb", help="TB file or directory")
    ap.add_argument("--coverage", help="JSON list of {opcode, must_assert_set}")
    ap.add_argument("--cov", action="append", default=[],
                    help="Inline 'OPCODE:assertion' (repeatable)")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH')
    args = ap.parse_args(argv)

    coverage: List[Dict[str, Any]] = []
    if args.coverage:
        try:
            payload = json.loads(Path(args.coverage).read_text())
            if isinstance(payload, list):
                coverage.extend(payload)
        except Exception as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    for s in args.cov:
        norm = _parse_inline(s)
        if norm is None:
            print(f"error: cannot parse --cov {s!r}", file=sys.stderr)
            return 2
        coverage.append(norm)

    if not coverage:
        print("error: no coverage entries (--coverage or --cov)", file=sys.stderr)
        return 2

    target = Path(args.tb)
    if not target.exists():
        print(f"error: target not found: {target}", file=sys.stderr)
        return 2

    files = discover_tb_files(target)
    findings = audit(target, coverage, files)
    errors = [f for f in findings if f.severity == "ERROR"]
    unverified = {f.opcode for f in errors if f.opcode}

    report = {
        "target": str(target),
        # The verdict is only worth as much as the corpus it was measured
        # on. A reader must be able to see that a PASS read something.
        "tb_files_scanned": len(files),
        "tb_files": [str(p) for p in files],
        "coverage_entries": len(coverage),
        "opcodes_unverified": len(coverage) if not files else len(unverified),
        "errors": len(errors),
        "findings": [asdict(f) for f in findings],
        "verdict": "PASS" if not errors else "FAIL",
    }

    if args.json:
        _txt = json.dumps(report, indent=2)
        if args.json == '-':
            print(_txt)
        else:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(_txt + "\n")
    else:
        for f in findings:
            print(f"[{f.severity}] {f.rule} @ {f.file}:{f.line}: {f.message}")
        print(f"\n{len(files)} TB file(s) scanned; {len(errors)} error(s); "
              f"verdict: {report['verdict']}")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
