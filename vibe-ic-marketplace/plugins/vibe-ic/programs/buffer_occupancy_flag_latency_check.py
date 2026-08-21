#!/usr/bin/env python3
"""buffer_occupancy_flag_latency_check.py — chip-AGNOSTIC structural gate.

A storage buffer (FIFO / LIFO / stack / queue / ring) exposes occupancy
status flags — ``empty`` / ``full`` and their programmable / almost
variants — that BY UNIVERSAL CONVENTION report the buffer's CURRENT
occupancy. They are a pure function of the occupancy pointer / counter:
``EMPTY == (ptr == EMPTY_LEVEL)``, ``FULL == (ptr == FULL_LEVEL)``.

The canonical bug this gate catches: the flag is a registered output
assigned by a **non-blocking** assignment inside the SAME sequential
``always`` block (or another ``posedge`` block) that ALSO advances the
pointer by NBA, and the flag's right-hand side reads the pointer
**bare** — i.e. the OLD, pre-advance value::

    always @(posedge Clk) begin
      ...
      SP <= SP - 1;          // push: pointer advances at end of cycle
      FULL <= (SP == 0);     // BAD: samples the OLD SP -> FULL asserts
      EMPTY <= (SP == 4);    //      one cycle LATE relative to the push
    end

Because NBA fires at the end of the cycle, ``FULL`` reflects the pointer
value from BEFORE this cycle's push/pop. The flag therefore lags the
occupancy it names by exactly one clock. A testbench that samples the
flag on the cycle the buffer becomes full/empty sees the stale value and
rejects — the classic "one boundary vector out of N fails, deterministically"
symptom.

CANONICAL GOOD — same-cycle settle, either idiom is accepted:

  (A) combinational flag (settles the instant the pointer settles)::

        assign FULL  = (SP == 0);
        assign EMPTY = (SP == 4);
      or ``always @(*) FULL = (SP == 0);``

  (B) next-state registered flag (computed from the advanced pointer)::

        SP   <= SP - 1;
        FULL <= ((SP - 1) == 0);     // uses the NEXT SP, not the stale one

CHIP-AGNOSTIC. The gate keys only on (1) a top-level OUTPUT port whose
name is a well-known occupancy-flag stem (empty/full/almost_*/prog_*/
a(empty|full)/half_full) and (2) a same-module pointer/counter register
advanced by ``ptr <= ptr +/- k`` NBA. It contains no design / PDK /
protocol literal. It SKIPs (exit 0) on any design without such a flag.

Detection
---------
Per module:
  1. Collect pointer registers ``P`` advanced by NBA to a changed value
     (``P <= P + k`` or ``P <= P - k``) in ANY sequential always block.
  2. Collect NBA assignments ``F <= <expr>`` where ``F`` is a 1-bit
     output whose name matches an occupancy-flag stem, inside ANY
     sequential always block.
  3. FAIL when such an ``F`` has an ``<expr>`` that (a) references a
     collected pointer ``P`` in a comparison / reduction AND (b) does
     NOT apply the advance arithmetic (no ``P + ..`` / ``P - ..`` in the
     expr) — i.e. it samples the STALE pointer.
  4. A constant-only RHS (reset init ``F <= 1'b0``) never triggers.
  5. A combinational driver (``assign F = ..`` / blocking ``F = ..``)
     is never a stale-NBA read, so it is not collected in step 2.

SKIP (exit 0, gate not applicable) when no occupancy flag is present.

Waiver: ``occupancy_flag_latency_intentional`` (>= 40 chars) in
``<project>/waivers.json`` downgrades FAIL -> PASS_WITH_WAIVER.

Usage
-----
    python3 buffer_occupancy_flag_latency_check.py <project_dir> [--json OUT]

Exit codes
----------
    0 — PASS / SKIP / PASS_WITH_WAIVER
    1 — FAIL
    2 — project dir not found
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

try:
    from gate_utils import find_modules, find_rtl_files, read_text
except ImportError:  # run directly without package on path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from gate_utils import find_modules, find_rtl_files, read_text  # type: ignore

WAIVER_KEY = "occupancy_flag_latency_intentional"
WAIVER_MIN = 40

# Universal occupancy-flag name stems (case-insensitive, whole-name match
# after stripping common prefixes). These are storage-buffer conventions,
# not chip-specific: any FIFO / LIFO / stack / queue / ring buffer.
_FLAG_STEMS = (
    "empty", "full",
    "almost_empty", "almost_full", "almostempty", "almostfull",
    "aempty", "afull",
    "prog_empty", "prog_full", "progempty", "progfull",
    "half_full", "halffull", "half_empty", "halfempty",
    "overflow", "underflow",
)


def _strip_comments_keep_lines(text: str) -> str:
    def _block(m):
        return "".join(c if c == "\n" else " " for c in m.group(0))
    text = re.sub(r"/\*.*?\*/", _block, text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), text)
    return text


def _is_flag_name(name: str) -> bool:
    n = name.strip().lower()
    # tolerate common wrapping like o_full / full_o / full_flag / fifo_empty
    n2 = re.sub(r"^(o|i|w|r)_", "", n)
    n2 = re.sub(r"_(o|i|reg|flag|out)$", "", n2)
    for stem in _FLAG_STEMS:
        if n2 == stem or n == stem:
            return True
        # suffix / prefix match e.g. fifo_full, buf_empty, full_flag
        if n2.endswith("_" + stem) or n2.startswith(stem + "_"):
            return True
    return False


_OUTPUT_1BIT_RE = re.compile(
    r"\boutput\b(?P<qual>(?:\s+(?:reg|wire|logic|signed))*)\s*"
    r"(?P<range>\[[^\]]*\]\s*)?"
    r"(?P<names>[\w\s,]+?)\s*(?=;|\)|\binput\b|\boutput\b|\binout\b)",
    re.IGNORECASE,
)


def _find_output_flags(header: str, body: str) -> Dict[str, bool]:
    """Return {flag_name: is_1bit} for output ports whose name is an
    occupancy-flag stem. Scans both ANSI header and non-ANSI body decls."""
    flags: Dict[str, bool] = {}
    for chunk in (header, body):
        for m in _OUTPUT_1BIT_RE.finditer(chunk):
            rng = (m.group("range") or "").strip()
            # 1-bit means no range, or an explicit [0:0]
            is_1bit = (rng == "" or re.match(r"\[\s*0\s*:\s*0\s*\]", rng) is not None)
            for raw in m.group("names").split(","):
                nm = raw.strip()
                if not nm or not re.match(r"^\w+$", nm):
                    continue
                if _is_flag_name(nm):
                    flags[nm] = is_1bit
    return flags


_SEQ_ALWAYS_RE = re.compile(
    r"\balways(?:_ff)?\b\s*@\s*\(\s*(?:posedge|negedge)\b",
    re.IGNORECASE,
)


def _seq_always_blocks(body: str) -> List[Tuple[int, str]]:
    """Return (start_offset, text) for each sequential always block."""
    out: List[Tuple[int, str]] = []
    for m in _SEQ_ALWAYS_RE.finditer(body):
        j = m.end()
        # advance to end of sensitivity list
        depth = 1
        while j < len(body) and depth:
            if body[j] == "(":
                depth += 1
            elif body[j] == ")":
                depth -= 1
            j += 1
        # skip whitespace
        while j < len(body) and body[j] in " \t\n\r":
            j += 1
        if body.startswith("begin", j):
            k = j + len("begin")
            d = 1
            while k < len(body) and d:
                if body.startswith("begin", k) and (k == 0 or not body[k - 1].isalnum()):
                    d += 1
                    k += len("begin")
                elif body.startswith("end", k) and (k + 3 >= len(body) or not body[k + 3].isalnum()):
                    d -= 1
                    k += len("end")
                else:
                    k += 1
            out.append((m.start(), body[m.start():k]))
        else:
            # single-statement always
            semi = body.find(";", j)
            end = semi + 1 if semi >= 0 else len(body)
            out.append((m.start(), body[m.start():end]))
    return out


# ptr <= ptr + k  /  ptr <= ptr - k   (pointer advance)
_PTR_ADVANCE_RE = re.compile(
    r"(\w+)\s*<=\s*\1\s*([+\-])\s*[\w'\d]+", re.IGNORECASE
)


def _find_advanced_pointers(blocks_text: str) -> Dict[str, str]:
    """Return {ptr_name: '+'|'-'} for pointers advanced by NBA."""
    ptrs: Dict[str, str] = {}
    for m in _PTR_ADVANCE_RE.finditer(blocks_text):
        ptrs[m.group(1)] = m.group(2)
    return ptrs


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _check_module(name: str, header: str, body: str,
                  file_path: str, file_offset: int,
                  whole_text: str) -> Tuple[List[dict], bool]:
    failures: List[dict] = []
    body_clean = _strip_comments_keep_lines(body)
    header_clean = _strip_comments_keep_lines(header)

    flags = _find_output_flags(header_clean, body_clean)
    if not flags:
        return failures, False  # gate not applicable to this module

    seq_blocks = _seq_always_blocks(body_clean)
    seq_all = "\n".join(t for _, t in seq_blocks)
    ptrs = _find_advanced_pointers(seq_all)
    if not ptrs:
        # flag present but no advancing pointer -> nothing to race against
        return failures, True

    ptr_alt = "|".join(re.escape(p) for p in ptrs)
    ptr_ref_re = re.compile(rf"\b(?:{ptr_alt})\b")
    # advance arithmetic present in the expr => next-state, not stale
    ptr_advance_in_expr_re = re.compile(
        rf"\b(?:{ptr_alt})\b\s*[+\-]"
    )

    # For each sequential block, find NBA assignments to a flag.
    for blk_start, blk_txt in seq_blocks:
        for fname in flags:
            nba_re = re.compile(
                rf"\b{re.escape(fname)}\s*<=\s*([^;]+);",
                re.IGNORECASE,
            )
            for m in nba_re.finditer(blk_txt):
                rhs = m.group(1)
                if not ptr_ref_re.search(rhs):
                    continue  # RHS doesn't read a pointer (e.g. reset const)
                if ptr_advance_in_expr_re.search(rhs):
                    continue  # next-state form: uses ptr +/- ... -> OK
                # stale read: flag <= f(bare pointer) while pointer advances
                abs_off = file_offset + blk_start + m.start()
                fline = _line_of(whole_text, abs_off)
                failures.append({
                    "rule": "OCCUPANCY_FLAG_STALE_POINTER_LATENCY",
                    "severity": "FAIL",
                    "module": name,
                    "flag": fname,
                    "pointer": ",".join(sorted(ptrs)),
                    "file": file_path,
                    "line": fline,
                    "message": (
                        f"occupancy flag `{fname}` is registered (NBA) from "
                        f"the stale pointer `{rhs.strip()[:40]}` in the same "
                        f"sequential block that advances the pointer "
                        f"({'/'.join(sorted(ptrs))} <= {'/'.join(sorted(ptrs))} "
                        f"+/- k). NBA samples the OLD pointer, so `{fname}` "
                        f"asserts ONE CYCLE LATE relative to the push/pop that "
                        f"changed occupancy. Make `{fname}` combinational "
                        f"(`assign {fname} = ...ptr...;`) or register it from "
                        f"the NEXT-state pointer (`{fname} <= ((ptr-1)==LVL);`) "
                        f"so it settles in the same cycle as the pointer it "
                        f"describes."
                    ),
                })
    return failures, True


def waived(project_dir: Path) -> Tuple[bool, str]:
    w = project_dir / "waivers.json"
    if not w.exists():
        return False, ""
    try:
        d = json.loads(w.read_text())
        t = d.get(WAIVER_KEY)
        if isinstance(t, str) and len(t.strip()) >= WAIVER_MIN:
            return True, t.strip()
    except Exception:
        pass
    return False, ""


def check(project_dir: Path, rtl_dir: Path | None) -> dict:
    failures: List[dict] = []
    applicable = False
    files_scanned = 0

    if rtl_dir and rtl_dir.exists():
        rtl_files = sorted(list(rtl_dir.glob("*.v")) + list(rtl_dir.glob("*.sv")))
    else:
        rtl_files = find_rtl_files(project_dir)

    for f in rtl_files:
        text = read_text(f)
        if not text:
            continue
        files_scanned += 1
        for span in find_modules(text):
            mod_fail, applic = _check_module(
                span.name, span.header, span.body, str(f), span.start, text)
            failures.extend(mod_fail)
            applicable = applicable or applic

    # dedupe
    seen = set()
    deduped = []
    for e in failures:
        k = (e["file"], e["line"], e["flag"], e["rule"])
        if k in seen:
            continue
        seen.add(k)
        deduped.append(e)

    return {
        "program": "buffer_occupancy_flag_latency_check",
        "applicable": applicable,
        "files_scanned": files_scanned,
        "failures": deduped,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir")
    ap.add_argument("--rtl-dir", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.exists():
        print(f"FAIL — project dir not found: {project}", file=sys.stderr)
        return 2

    rtl_dir = Path(args.rtl_dir).resolve() if args.rtl_dir else None
    result = check(project, rtl_dir)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json), json.dumps(result, indent=2))

    if not result["applicable"]:
        print("PASS_SKIP — no occupancy (empty/full) flag detected; "
              "gate not applicable")
        return 0

    if result["failures"]:
        is_waived, why = waived(project)
        if is_waived:
            print(f"PASS_WITH_WAIVER — {len(result['failures'])} occupancy-flag "
                  f"latency finding(s); waiver `{WAIVER_KEY}` set: {why[:80]}...")
            for fnd in result["failures"]:
                print(f"  • {fnd['file']}:{fnd['line']} [{fnd['rule']}] "
                      f"{fnd['flag']} — {fnd['message'][:100]}")
            return 0
        print(f"FAIL — {len(result['failures'])} occupancy flag(s) registered "
              f"from a stale pointer (one-cycle-late empty/full)")
        for fnd in result["failures"]:
            print(f"FAIL: {fnd['rule']} at {fnd['file']}:{fnd['line']} — "
                  f"{fnd['message']}")
        return 1

    print("PASS — occupancy flags settle in lockstep with the pointer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
