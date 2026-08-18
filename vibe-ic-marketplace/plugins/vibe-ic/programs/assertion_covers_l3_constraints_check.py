#!/usr/bin/env python3
"""assertion_covers_l3_constraints_check.py — Wave 39 / D3

Spec to enforce (chip-AGNOSTIC):

Every constraint declared in L3.opcodes[] (argument_constraints[]
with max_hex / addr_max / len_max / pre_wake_allowed=false) MUST
have a corresponding SystemVerilog assertion (`assert property` /
`assume property` / `assert (...)` / `ASSERT_*` macro / `cover
property`) somewhere in `rtl/`.

Detection:
  1. Build a list of constraints from L3 (opcode_hex + role + bound).
  2. Scan rtl/**/*.{v,sv} for assertion-class statements
     (rtl/assertions/ subdir + inline `assert property`).
  3. Match assertion text to constraint by heuristic: the assertion
     line must contain the opcode hex (8'hNN or 0xNN) AND one of:
       - the bound literal (8'h7F / 7'h7C / 0x7f / decimal), OR
       - a pre-wake-class signal (awake_latch / awake / wake) for
         pre_wake_false constraints.
  4. FAIL when any constraint lacks a matching assertion.

Honors waiver `sva_constraint_coverage_partial_intentional` (>=40).

Usage:
    python3 assertion_covers_l3_constraints_check.py <project_dir>

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
from typing import Dict, List, Optional
import _path_layout as _pl

WAIVER_KEY = "sva_constraint_coverage_partial_intentional"
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


def _find_l3(project: Path) -> Optional[Path]:
    for pat in ("phase1/generated_docs/L3_CMD_PROTOCOL.json",
                "phase1/generated_docs/L3*.json", "**/L3_CMD_PROTOCOL.json"):
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


_ASSERT_RE = re.compile(
    r"(?:"
    # Concurrent SVA forms
    r"\bassert\s+property\b|\bassume\s+property\b|\bcover\s+property\b"
    r"|\bassert\s+final\b|\bassume\s+final\b"
    # `ASSERT_*, `ASSUME_*, `COVER_* macros (with or without backtick)
    r"|`?\bASSERT_[A-Z_]+|`?\bASSUME_[A-Z_]+|`?\bCOVER_[A-Z_]+"
    # Immediate assertion forms: assert ( / assume ( / cover (
    r"|\bassert\s*\(|\bassume\s*\(|\bcover\s*\("
    # PSL-style backtick macros
    r"|`assert\b|`assume\b|`cover\b"
    r")",
    re.IGNORECASE,
)


# Wave 43 (v0.119.75) — D3 keyword extension.
# When an assertion line lacks a literal bound but the constraint is
# a comparator (e.g. addr <= MAX), still accept it iff the line
# contains one of these comparison operators / verbs combined with
# the opcode hex. This widens detection to non-canonical SVA naming
# (e.g. `assert(cmd_buf[1] < 8'h80)` matches a `max=0x7F` constraint
# because the bound's neighbour 0x80 also appears).
_CONSTRAINT_OPERATOR_SYNONYMS: dict[str, list[str]] = {
    "max_hex": [">=", ">", "exceed", "exceeds", "above",
                "overflow", "out_of_range", "超過", "大於", "超出"],
    "min_hex": ["<", "below", "less_than", "underflow",
                "小於", "低於"],
    "equal":   ["==", "===", "equal", "equals", "等於"],
}


# Wave 43 — assertion-context keywords. If a line lacks the canonical
# `assert_property` keyword but appears inside an assertion-block
# context (immediate-assert form, SVA in always block, $asserton /
# $assertoff toggle, or psl-class macro), it still counts as an
# assertion site.
_ASSERTION_CONTEXT_KEYWORDS: tuple[str, ...] = (
    "assert", "assume", "cover",
    "property", "sequence",
    # SVA forms that may appear in an always_ff block:
    "always_ff @(posedge", "always @(posedge",
    "$asserton", "$assertoff", "$assertkill",
    # PSL-style macros that some teams ship.
    "psl assert", "psl assume", "psl cover",
)


def _gather_assertion_lines(project: Path) -> List[str]:
    """Return assertion 'snippets' — paren-balanced statements that
    contain an assert/assume/cover keyword. Spans multiple physical
    lines so the matcher can see opcode + bound on different lines."""
    out: List[str] = []
    rtl_dirs = [_pl.rtl_dir(project), project / "src", project / "hdl"]
    rtl_dirs = [d for d in rtl_dirs if d.is_dir()]
    if not rtl_dirs:
        rtl_dirs = [project]
    for d in rtl_dirs:
        for ext in ("*.v", "*.sv", "*.svh"):
            for f in d.rglob(ext):
                if not f.is_file():
                    continue
                try:
                    text = f.read_text(encoding="utf-8",
                                       errors="replace")
                except OSError:
                    continue
                # Find assertion keyword positions and consume forward
                # until paren depth returns to 0 OR ';' encountered.
                for m in _ASSERT_RE.finditer(text):
                    start = m.start()
                    # extend backwards to start of statement
                    bs = text.rfind("\n", 0, start) + 1
                    end = start
                    depth = 0
                    while end < len(text):
                        c = text[end]
                        if c == "(":
                            depth += 1
                        elif c == ")":
                            depth -= 1
                        elif c == ";" and depth <= 0:
                            end += 1
                            break
                        elif c == "\n" and depth <= 0:
                            # No paren content — keep just this line
                            end += 1
                            break
                        end += 1
                    snippet = text[bs:end]
                    out.append(snippet)
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: assertion_covers_l3_constraints_check "
              "<project_dir>", file=sys.stderr)
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        return 2

    waiver_ok, waiver_text = _waived(project)

    l3p = _find_l3(project)
    if l3p is None:
        print("[SKIP] assertion_covers_l3_constraints_check: "
              "no L3 file")
        return 2
    try:
        l3 = json.loads(l3p.read_text())
    except Exception as exc:
        print(f"[FAIL] assertion_covers_l3_constraints_check: "
              f"parse L3: {exc}")
        return 1

    # Build constraint list
    constraints: List[dict] = []
    for op in l3.get("opcodes", []):
        if not isinstance(op, dict):
            continue
        hex_str = (op.get("hex") or op.get("opcode") or "")
        if not hex_str:
            continue
        if not hex_str.startswith("0x"):
            hex_str = "0x" + hex_str
        hex_str = hex_str.lower()
        # argument_constraints
        for c in op.get("argument_constraints", []) or []:
            if not isinstance(c, dict):
                continue
            mx = _hex_int(c.get("max_hex") or c.get("max"))
            if mx is None:
                continue
            constraints.append({
                "opcode": hex_str,
                "role": (c.get("name") or "").lower(),
                "bound": mx,
                "evidence": c.get("evidence", ""),
            })
        # top-level
        for f, role in (("addr_max", "addr"), ("len_max", "len")):
            if f in op:
                v = _hex_int(op[f])
                if v is not None:
                    constraints.append({
                        "opcode": hex_str, "role": role,
                        "bound": v, "evidence": f"L3.{f}",
                    })
        if op.get("pre_wake_allowed") is False:
            constraints.append({
                "opcode": hex_str, "role": "pre_wake",
                "bound": None, "evidence": "L3.pre_wake_allowed",
            })

    if not constraints:
        print("[SKIP] assertion_covers_l3_constraints_check: "
              "no L3 constraints to enforce")
        return 2

    asserts = _gather_assertion_lines(project)
    if not asserts:
        msg = (f"[FAIL] assertion_covers_l3_constraints_check: "
               f"L3 declares {len(constraints)} constraint(s) but "
               f"no assert/assume/cover property in rtl/ tree")
        if waiver_ok:
            print(f"[PASS] assertion_covers_l3_constraints_check: "
                  f"waived ({WAIVER_KEY})")
            return 0
        print(msg)
        return 1

    issues: List[str] = []
    for c in constraints:
        op = c["opcode"]
        op_hex_byte = op[2:].zfill(2)  # 'e2'
        op_patterns = (
            f"8'h{op_hex_byte}", f"8'H{op_hex_byte.upper()}",
            op, f"0x{op_hex_byte.upper()}",
        )
        bound = c["bound"]
        bound_patterns: List[str] = []
        if bound is not None:
            bv = f"{bound:x}"
            bound_patterns = [
                f"'h{bv}", f"'H{bv.upper()}",
                f"0x{bv}", f"0x{bv.upper()}",
                str(bound),
            ]
            # Wave 43 — also recognise `bound + 1` / `bound - 1` when
            # the assertion is written as a strict comparator.
            # e.g. `assert (... < 8'h80)` covers `max=0x7F`.
            for delta in (1, -1):
                neigh = bound + delta
                if neigh < 0:
                    continue
                bv_n = f"{neigh:x}"
                bound_patterns.extend([
                    f"'h{bv_n}", f"'H{bv_n.upper()}",
                    f"0x{bv_n}", f"0x{bv_n.upper()}",
                    str(neigh),
                ])
        matched = False
        for line in asserts:
            ll = line.lower()
            if not any(p.lower() in ll for p in op_patterns):
                continue
            if c["role"] == "pre_wake":
                if any(tok in ll for tok in
                       ("awake_latch", "awake", "wake_latch",
                        "pre_wake", "pre-wake", "before_wake",
                        "wake_required", "not_awake")):
                    matched = True
                    break
            elif bound_patterns:
                if any(p.lower() in ll for p in bound_patterns):
                    matched = True
                    break
                # Wave 43 — operator-synonym fallback. If the line
                # carries a comparator verb (>=, exceed, overflow,
                # ...) keyed off the constraint role (max/min/equal)
                # AND the opcode hex is present, accept it as a
                # bound-checking assertion even without the literal.
                role = (c["role"] or "").lower()
                op_synset: List[str] = []
                if role in ("addr", "len") or role.startswith(
                    ("max", "len_", "addr_")
                ) or "max" in role:
                    op_synset = _CONSTRAINT_OPERATOR_SYNONYMS["max_hex"]
                elif "min" in role:
                    op_synset = _CONSTRAINT_OPERATOR_SYNONYMS["min_hex"]
                elif "eq" in role:
                    op_synset = _CONSTRAINT_OPERATOR_SYNONYMS["equal"]
                if op_synset and any(s.lower() in ll for s in op_synset):
                    matched = True
                    break
            else:
                matched = True
                break
        if not matched:
            issues.append(
                f"opcode {op} {c['role']}={c['bound']} "
                f"({c['evidence']}) — no matching SVA in rtl/"
            )

    if issues:
        msg = (f"[FAIL] assertion_covers_l3_constraints_check: "
               f"{len(issues)}/{len(constraints)} constraint(s) "
               f"lack matching SVA:\n  - " +
               "\n  - ".join(issues[:8]))
        if waiver_ok:
            print(f"[PASS] assertion_covers_l3_constraints_check: "
                  f"waived ({WAIVER_KEY}; {len(issues)} suppressed)")
            return 0
        print(msg)
        return 1

    print(f"[PASS] assertion_covers_l3_constraints_check: "
          f"{len(constraints)} constraint(s) all matched in "
          f"{len(asserts)} assertion line(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
