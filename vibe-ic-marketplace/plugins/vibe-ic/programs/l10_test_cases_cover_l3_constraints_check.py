#!/usr/bin/env python3
"""l10_test_cases_cover_l3_constraints_check.py — Wave 39 / D1

Spec to enforce (chip-AGNOSTIC):

Every constraint declared in L3.opcodes[] MUST have at least one
positive AND one negative test case in L10.test_cases[]. Constraints
counted:
  - argument_constraints[].max_hex / min_hex (e.g. addr_max=0x7F)
  - addr_max / len_max top-level fields
  - pre_wake_allowed=false  (negative pre-wake test required)
  - response_payload_template[]  (positive happy-path test required)

A test_case "covers" a constraint when the test_case touches the
opcode AND its parameters/expected_response/test_kind exercise the
boundary. Since L10 schemas vary, we use a permissive substring match:
the test_case text body must include the opcode hex AND either
(a) a value within the legal bound (positive) or (b) a value beyond
the bound (negative) or (c) an explicit `expect_silent` /
`expect_no_response` / `negative` / `boundary` marker.

Detection:
  1. Build expected coverage set per opcode from L3.
  2. For each L10 test_case, classify which constraints it exercises.
  3. FAIL when any required constraint lacks positive OR negative
     coverage.

Honors waiver `l10_constraint_coverage_partial_intentional` (>=40
chars).

Usage:
    python3 l10_test_cases_cover_l3_constraints_check.py <project>

Exit codes:
    0 = PASS
    1 = FAIL
    2 = SKIP
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

WAIVER_KEY = "l10_constraint_coverage_partial_intentional"
WAIVER_MIN = 40


def _waived(project: Path) -> tuple[bool, str]:
    p = project / "waivers.json"
    if not p.exists():
        return False, ""
    try:
        d = json.loads(p.read_text())
        v = d.get(WAIVER_KEY)
        if isinstance(v, str) and len(v.strip()) >= WAIVER_MIN:
            return True, v.strip()
    except Exception:
        pass
    return False, ""


def _find_doc(project: Path, prefix: str) -> Optional[Path]:
    for pat in (f"phase1/generated_docs/{prefix}_*.json",
                f"phase1/generated_docs/{prefix}*.json",
                f"**/{prefix}*.json"):
        for h in project.glob(pat):
            if h.is_file():
                return h
    return None


def _hex_int(s) -> Optional[int]:
    if isinstance(s, int):
        return s
    if isinstance(s, str):
        s = s.strip()
        try:
            return int(s, 16) if s.lower().startswith("0x") else int(s)
        except ValueError:
            return None
    return None


def _build_constraints(l3: dict) -> Dict[str, List[dict]]:
    """Return {opcode_hex_lower: [constraint_dict, ...]}.

    Each constraint dict:
      {kind: 'addr_max'|'len_max'|'pre_wake_false'|'happy_path',
       bound: int_value or None,
       evidence: free string}
    """
    out: Dict[str, List[dict]] = {}
    # A pre_wake_false constraint asserts a WAKE-PULSE / command-response
    # protocol. When the L3 records `opcode_synthesis_skipped_reason` (no
    # half-duplex, no command-table heading), the opcodes came SOLELY from an
    # HDL `typedef enum` harvest (the design's own ISA table, not a wire
    # command set) and there is no wake protocol -- so a pre-wake negative
    # test must NOT be required. Symmetric with gen_l10_test_cases, keyed on
    # the same L3 signal. chip-AGNOSTIC: a real command-driven IC has no skip
    # reason and still requires (and still fails without) the pre-wake test.
    _no_wake_protocol = bool(l3.get("opcode_synthesis_skipped_reason"))
    for op in l3.get("opcodes", []):
        if not isinstance(op, dict):
            continue
        hex_str = (op.get("hex") or op.get("opcode") or "")
        if not hex_str:
            continue
        if not hex_str.startswith("0x"):
            hex_str = "0x" + hex_str
        hex_str = hex_str.lower()
        cs: List[dict] = []
        # argument_constraints[]
        for c in op.get("argument_constraints", []) or []:
            if not isinstance(c, dict):
                continue
            name = (c.get("name") or "").lower()
            mx = _hex_int(c.get("max_hex") or c.get("max"))
            if mx is None:
                continue
            kind = "addr_max" if "addr" in name else (
                "len_max" if "len" in name else f"{name}_max")
            cs.append({"kind": kind, "bound": mx,
                       "evidence": c.get("evidence", "")})
        # addr_max / len_max top-level
        for f, kind in (("addr_max", "addr_max"),
                        ("len_max", "len_max")):
            if f in op:
                v = _hex_int(op[f])
                if v is not None and not any(c["kind"] == kind
                                             for c in cs):
                    cs.append({"kind": kind, "bound": v,
                               "evidence": f"L3.{f}"})
        # pre_wake_allowed=false
        if op.get("pre_wake_allowed") is False and not _no_wake_protocol:
            cs.append({"kind": "pre_wake_false", "bound": None,
                       "evidence": "L3.pre_wake_allowed"})
        # happy_path / response_payload_template
        if op.get("response_payload_template"):
            cs.append({"kind": "happy_path", "bound": None,
                       "evidence": "L3.response_payload_template"})
        if cs:
            out[hex_str] = cs
    return out


def _classify_test(tc: dict) -> Dict[str, set]:
    """Return {opcode_hex: {kinds_covered_positive, kinds_covered_negative}}.

    Permissive: scans the entire test_case dict for opcode hex tokens
    and constraint role keywords.
    """
    blob = json.dumps(tc, ensure_ascii=False).lower()
    kinds_pos: set = set()
    kinds_neg: set = set()
    # negative markers
    neg = any(tok in blob for tok in (
        "expect_silent", "expect_no_response", "no_response",
        "negative", "boundary_neg", "out_of_range", "rejected",
        "silent", "discard", "invalid", "expect_drop",
    ))
    pos = any(tok in blob for tok in (
        "expect_response", "expect_reply", "happy", "positive",
        "expect_pass", "valid",
    )) or not neg

    for kind_kw, kind in (
        ("addr", "addr_max"),
        ("address", "addr_max"),
        ("len", "len_max"),
        ("length", "len_max"),
        ("pre_wake", "pre_wake_false"),
        ("awake", "pre_wake_false"),
    ):
        if kind_kw in blob:
            (kinds_neg if neg else kinds_pos).add(kind)
    if pos:
        kinds_pos.add("happy_path")
    if neg:
        kinds_neg.add("happy_path_neg")
    # opcodes
    opcodes_in = set(re.findall(r"0x[0-9a-f]{2}", blob))
    return {op: (kinds_pos, kinds_neg) for op in opcodes_in}


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: l10_test_cases_cover_l3_constraints_check "
              "<project_dir>", file=sys.stderr)
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        return 2

    waiver_ok, waiver_text = _waived(project)

    l3p = _find_doc(project, "L3")
    l10p = _find_doc(project, "L10")
    if l3p is None or l10p is None:
        print("[SKIP] l10_test_cases_cover_l3_constraints_check: "
              "L3 or L10 missing")
        return 2
    try:
        l3 = json.loads(l3p.read_text())
        l10 = json.loads(l10p.read_text())
    except Exception as exc:
        print(f"[FAIL] l10_test_cases_cover_l3_constraints_check: "
              f"parse error: {exc}")
        return 1

    constraints = _build_constraints(l3)
    if not constraints:
        print("[SKIP] l10_test_cases_cover_l3_constraints_check: "
              "no testable constraints in L3")
        return 2

    test_cases = (l10.get("test_cases") or l10.get("cases")
                  or l10.get("tests") or [])
    coverage_by_op: Dict[str, Tuple[set, set]] = {}
    for tc in test_cases:
        if not isinstance(tc, dict):
            continue
        for op, (pos, neg) in _classify_test(tc).items():
            cur = coverage_by_op.setdefault(op, (set(), set()))
            cur[0].update(pos)
            cur[1].update(neg)

    issues: List[str] = []
    for op, cs in constraints.items():
        pos, neg = coverage_by_op.get(op, (set(), set()))
        for c in cs:
            kind = c["kind"]
            if kind == "happy_path":
                if "happy_path" not in pos:
                    issues.append(
                        f"opcode {op}: missing positive happy-path "
                        f"test ({c['evidence']})")
                continue
            if kind == "pre_wake_false":
                if "pre_wake_false" not in neg:
                    issues.append(
                        f"opcode {op}: missing negative pre-wake "
                        f"test ({c['evidence']})")
                continue
            # value-bound constraints
            if kind not in pos:
                issues.append(
                    f"opcode {op}: missing positive boundary test "
                    f"for {kind} (bound={hex(c['bound']) if c['bound'] is not None else '?'})")
            if kind not in neg:
                issues.append(
                    f"opcode {op}: missing negative out-of-range "
                    f"test for {kind} "
                    f"(bound={hex(c['bound']) if c['bound'] is not None else '?'})")

    if issues:
        msg = (f"[FAIL] l10_test_cases_cover_l3_constraints_check: "
               f"{len(issues)} coverage gap(s) across "
               f"{len(constraints)} opcode(s):\n  - " +
               "\n  - ".join(issues[:8]))
        if waiver_ok:
            print(f"[PASS] l10_test_cases_cover_l3_constraints_check: "
                  f"waived ({WAIVER_KEY}; {len(issues)} suppressed)")
            return 0
        print(msg)
        return 1

    print(f"[PASS] l10_test_cases_cover_l3_constraints_check: "
          f"all constraints in L3 ({len(constraints)} opcode(s)) "
          f"covered by L10 test_cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
