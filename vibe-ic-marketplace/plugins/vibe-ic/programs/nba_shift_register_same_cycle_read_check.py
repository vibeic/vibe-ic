#!/usr/bin/env python3
"""nba_shift_register_same_cycle_read_check.py — v0.119.44 (Wave 12) plugin gate.

Closes the v0.119.43 <benchmark> fresh-agent root-cause: a TX-PHY (or any
serializer) whose shift register is **shifted via NBA** in the SAME
``always_ff`` block where a non-zero index of that shift register is
read to drive the *next* bit's timing / output. Because NBA assignments
fire at the END of the cycle, the read sees the OLD pre-shift value.
The bit at index 1 is the bit *before* the bit at index 0 — the cycle
in which we shift was already supposed to consume index 0, so the
"next bit" should be index 0 of the post-shift value. Reading
``sr[1]`` in the same block while issuing ``sr <= sr >> 1`` therefore
delivers a stale-by-one bit and corrupts every odd bit of the serial
stream (the canonical "every other bit looks wrong" symptom).

CHIP-AGNOSTIC. The gate is independent of any specific protocol /
chip / pin / opcode. It looks purely at the structural RTL pattern.

CANONICAL BAD (Pattern A)
-------------------------
::

    always_ff @(posedge clk) begin
      out <= tx_sr[1];        // BAD: reading post-shift, but NBA hasn't fired
      tx_sr <= tx_sr >> 1;    // shift not yet visible in this read
    end

CANONICAL BAD (Pattern B)
-------------------------
A combinational read of ``sr[K]`` (K >= 1) outside the ``always_ff``,
where the same ``always_ff`` block does ``sr <= sr >> 1``, downstream
captures the stale read.

CANONICAL GOOD (Pattern C)
--------------------------
::

    always_ff @(posedge clk) begin
      out <= tx_sr[0];        // OK: consume current bit 0
      tx_sr <= tx_sr >> 1;    // shift takes effect next cycle
    end

CANONICAL GOOD (Pattern D — explicit look-ahead)
------------------------------------------------
::

    always_ff @(posedge clk) begin
      tx_sr <= {1'b0, tx_sr[N-1:1]};  // explicit concat shift
      out <= tx_sr[1];                 // intentional 1-bit look-ahead
    end

Heuristic: when the shift uses concatenation form ``{1'b0, sr[N:1]}``
or carries a comment like ``// look-ahead`` / ``// next-bit setup`` the
read is treated as intentional and downgraded to WARN.

Detection algorithm
-------------------
1. Parse each ``module`` body. For every signal ``S`` assigned with
   NBA via right-shift (``S <= S >> N`` or ``S <= {.., S[..]}``) record
   the always_ff block index and the file:line.
2. Walk the SAME always_ff block looking for reads of ``S[K]`` with
   integer K >= 1 (LHS or RHS).
3. FAIL with file:line when (1) and (2) coincide AND the shift form is
   the simple ``S <= S >> N``.
4. WARN when the shift uses explicit concatenation OR a look-ahead
   comment is on the read line.
5. Also FAIL when ``S[K]`` (K >= 1) is read combinationally
   (``assign x = S[K];``) somewhere in the module AND the same module
   has the NBA shift — Pattern B.
6. Allow ``S[0]`` reads in the shifting always_ff (Pattern C).
7. SKIP (exit 0, "gate not applicable") when no shift register is
   detected in any RTL file.
8. Honors waiver ``nba_shift_register_intentional`` in
   ``<project>/waivers.json`` (>= 40 chars).

Usage
-----
    python3 nba_shift_register_same_cycle_read_check.py <project_dir>
        [--rtl-dir <path>] [--json <out>]

Exit codes
----------
    0 — PASS / SKIP / PASS_WITH_WAIVER / WARN
    1 — FAIL
    2 — input-missing
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Tuple
import _path_layout as _pl

try:
    from gate_utils import find_modules, find_rtl_files, read_text
except ImportError:  # script run directly without package on path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from gate_utils import find_modules, find_rtl_files, read_text  # type: ignore


WAIVER_KEY = "nba_shift_register_intentional"
WAIVER_MIN = 40

# v1.6.523 — bit-serial-family evidence-based waiver key. A bit-serial
# core (1-bit datapath) processes one bit per cycle by construction; a
# same-cycle look-ahead shift read is the *intended* topology, not a
# multi-bit NBA race. When the design is a known bit-serial core, the
# gate downgrades the FAIL to WARN. An explicit evidence waiver under
# this key forces the same downgrade.
BIT_SERIAL_WAIVER_KEY = "bit_serial_core_lookahead_intentional"


def _bit_serial_evidence(project_dir: Path) -> Tuple[bool, str]:
    """v1.6.523 — chip-AGNOSTIC: is this a known bit-serial core?

    Positive evidence (any one suffices):
      1. Explicit evidence waiver `bit_serial_core_lookahead_intentional`
         (>= 40 chars) in waivers.json.
      2. ic_class / ip_class in any L1/L2/L9 generated doc, the catalog
         manifest, or facts.yaml containing 'bit_serial' / 'bit-serial'
         / 'serial_core' / 'bit serial'.
      3. A declared 1-bit datapath width (W == 1 / DATA_WIDTH == 1 /
         datapath_width == 1) in an L doc or facts.

    Returns (is_bit_serial, evidence_string). Fail-closed: no positive
    evidence → (False, "") so genuine multi-bit NBA races still FAIL.
    """
    # 1. Explicit evidence waiver.
    waivers = project_dir / "waivers.json"
    if waivers.exists():
        try:
            d = json.loads(waivers.read_text())
            v = d.get(BIT_SERIAL_WAIVER_KEY)
            if isinstance(v, str) and len(v.strip()) >= WAIVER_MIN:
                return True, f"waiver {BIT_SERIAL_WAIVER_KEY}: {v.strip()[:80]}"
        except Exception:
            pass

    _BIT_SERIAL_RE = re.compile(
        r"bit[\s_\-]?serial|serial[\s_\-]?core|bitserial", re.IGNORECASE)

    def _scan_text_for_class(text: str) -> str:
        if _BIT_SERIAL_RE.search(text):
            m = _BIT_SERIAL_RE.search(text)
            return f"bit_serial marker: ...{text[max(0,m.start()-20):m.end()+20]!r}"
        return ""

    # 2. ic_class / ip_class markers in generated L docs / catalog /
    #    facts. Best-effort over a small candidate set.
    candidates: List[Path] = []
    try:
        gd = _pl.generated_docs_dir(project_dir)
        if gd.is_dir():
            for prefix in ("L1_", "L2_", "L9_"):
                candidates.extend(sorted(gd.glob(f"{prefix}*.json")))
    except Exception:
        pass
    for extra in ("facts.yaml", "catalog_manifest.json",
                  "ip_catalog_match.json"):
        p = project_dir / extra
        if p.is_file():
            candidates.append(p)
    for p in candidates:
        try:
            text = p.read_text(errors="ignore")
        except Exception:
            continue
        ev = _scan_text_for_class(text)
        if ev:
            return True, f"{p.name}: {ev}"

    # 3. 1-bit datapath width in an L doc / facts.
    _W1_RE = re.compile(
        r"\"?(?:data_?width|datapath_?width|word_?width|\bW\b)\"?"
        r"\s*[:=]\s*\"?1\"?(?!\d)",
        re.IGNORECASE)
    for p in candidates:
        try:
            text = p.read_text(errors="ignore")
        except Exception:
            continue
        if _W1_RE.search(text):
            m = _W1_RE.search(text)
            return True, (f"{p.name}: 1-bit datapath "
                          f"...{text[max(0,m.start()-10):m.end()+10]!r}")
    return False, ""


def _strip_comments_keep_lines(text: str) -> str:
    """Replace comments with whitespace but keep newlines so line numbers
    stay correct."""
    def _block(m):
        s = m.group(0)
        return "".join(c if c == "\n" else " " for c in s)
    text = re.sub(r"/\*.*?\*/", _block, text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), text)
    return text


_ALWAYS_FF_RE = re.compile(
    r"\balways(?:_ff|\s*@\s*\(\s*posedge\b|\s*@\s*\(\s*negedge\b)",
    re.IGNORECASE,
)


def _split_always_blocks(body: str) -> list[tuple[int, int, str]]:
    """Return list of (start_offset, end_offset, text) for each
    sequential always block in the body. Uses begin/end depth or single-
    statement form. Best-effort: handles both ``always @(posedge clk)``
    and ``always_ff``."""
    blocks: list[tuple[int, int, str]] = []
    for m in _ALWAYS_FF_RE.finditer(body):
        # Find the sensitivity-list close paren (if present), then begin
        i = m.end()
        # Skip @(...) sensitivity list if not consumed by the regex
        # (the regex consumed up to 'posedge' inside it; we still need
        # to find the matching `)` if any).
        # Find the next 'begin' OR a single statement terminated by `;`.
        # We scan up to 'begin' or the first `;` at top depth.
        depth_paren = 0
        j = i
        while j < len(body):
            c = body[j]
            if c == "(":
                depth_paren += 1
            elif c == ")":
                depth_paren -= 1
            elif depth_paren == 0:
                # Look ahead for "begin"
                if body.startswith("begin", j):
                    j += len("begin")
                    depth_begin = 1
                    while j < len(body) and depth_begin:
                        if body.startswith("begin", j) and (j == 0 or not body[j - 1].isalnum()):
                            depth_begin += 1
                            j += len("begin")
                        elif body.startswith("end", j) and (j + 3 >= len(body) or not body[j + 3].isalnum()):
                            depth_begin -= 1
                            j += len("end")
                        else:
                            j += 1
                    blocks.append((m.start(), j, body[m.start():j]))
                    break
                if c == ";":
                    j += 1
                    blocks.append((m.start(), j, body[m.start():j]))
                    break
            j += 1
        else:
            # ran off the end
            blocks.append((m.start(), j, body[m.start():j]))
    return blocks


_NBA_RSHIFT_RE = re.compile(
    r"(\w+)\s*<=\s*\1\s*>>\s*\d+", re.IGNORECASE
)
# Concat shift: signal <= {<lit/zero>, signal[<N>:<M>]}
_NBA_CONCAT_RE = re.compile(
    r"(\w+)\s*<=\s*\{[^}]*\b(\w+)\s*\[[^\]]+\]\s*\}", re.IGNORECASE
)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _find_shift_assignments(block_text: str) -> list[tuple[str, int, str]]:
    """Return list of (signal, line_in_block, form) for NBA shifts of
    a signal by itself. ``form`` is 'rshift' or 'concat'."""
    out: list[tuple[str, int, str]] = []
    for m in _NBA_RSHIFT_RE.finditer(block_text):
        out.append((m.group(1), _line_of(block_text, m.start()), "rshift"))
    for m in _NBA_CONCAT_RE.finditer(block_text):
        sig_lhs = m.group(1)
        sig_rhs = m.group(2)
        if sig_lhs == sig_rhs:
            out.append((sig_lhs, _line_of(block_text, m.start()), "concat"))
    return out


def _find_indexed_reads(block_text: str, signal: str) -> list[tuple[int, int]]:
    """Return list of (index, line_in_block) for ``signal[K]``
    occurrences with K an integer. Excludes the shift line itself
    where the LHS appears."""
    pat = re.compile(
        rf"\b{re.escape(signal)}\s*\[\s*(\d+)\s*\]"
    )
    out: list[tuple[int, int]] = []
    for m in pat.finditer(block_text):
        idx = int(m.group(1))
        ln = _line_of(block_text, m.start())
        out.append((idx, ln))
    return out


def _has_lookahead_comment(full_text: str, abs_offset_start: int,
                           abs_offset_end: int) -> bool:
    """Look for ``// look-ahead`` / ``// next-bit setup`` /
    ``// intentional pipeline`` etc. in the surrounding lines."""
    seg_start = full_text.rfind("\n", 0, abs_offset_start) + 1
    seg_end = full_text.find("\n", abs_offset_end)
    if seg_end < 0:
        seg_end = len(full_text)
    seg = full_text[seg_start:seg_end].lower()
    markers = (
        "look-ahead", "lookahead", "next-bit", "next_bit",
        "intentional pipeline", "post-shift", "post_shift",
        "explicit shift", "1-bit pipeline",
    )
    return any(mk in seg for mk in markers)


def _check_module(module_name: str, module_body: str,
                  file_path: str, file_offset_in_text: int,
                  whole_text: str) -> tuple[list[dict], list[dict], bool]:
    """Return (failures, warnings, found_any_shift)."""
    failures: list[dict] = []
    warnings: list[dict] = []
    found_any_shift = False

    body_clean = _strip_comments_keep_lines(module_body)
    blocks = _split_always_blocks(body_clean)

    # Track shifted signals per module for Pattern B (combinational read)
    all_shifted_signals: dict[str, str] = {}  # signal -> form

    # Pattern A check (same always_ff block)
    for blk_start, blk_end, blk_txt in blocks:
        shifts = _find_shift_assignments(blk_txt)
        if not shifts:
            continue
        found_any_shift = True
        for signal, shift_line, form in shifts:
            all_shifted_signals[signal] = form
            indexed_reads = _find_indexed_reads(blk_txt, signal)
            # Filter out the shift-LHS line itself and reads at index 0
            for idx, rd_line in indexed_reads:
                if rd_line == shift_line:
                    continue
                if idx == 0:
                    # Pattern C — OK
                    continue
                # K >= 1 read within same always_ff block as NBA shift.
                abs_offset = file_offset_in_text + blk_start + sum(
                    len(line) + 1
                    for line in blk_txt.split("\n")[:rd_line - 1]
                )
                file_line = _line_of(whole_text, abs_offset)
                if form == "concat":
                    warnings.append({
                        "rule": "NBA_SHIFT_REG_LOOKAHEAD",
                        "severity": "WARN",
                        "module": module_name,
                        "signal": signal,
                        "index": idx,
                        "file": file_path,
                        "line": file_line,
                        "message": (
                            f"`{signal}` shifted via concat AND read at "
                            f"index {idx} in same always_ff (look-ahead "
                            f"pattern). Verify the look-ahead is "
                            f"intentional, e.g. that the consumer expects "
                            f"the NEXT bit not the current one."
                        ),
                    })
                else:
                    if _has_lookahead_comment(
                            whole_text, abs_offset, abs_offset + 4):
                        warnings.append({
                            "rule": "NBA_SHIFT_REG_LOOKAHEAD",
                            "severity": "WARN",
                            "module": module_name,
                            "signal": signal,
                            "index": idx,
                            "file": file_path,
                            "line": file_line,
                            "message": (
                                f"`{signal}` <= `{signal}` >> N AND read "
                                f"at index {idx} in same always_ff but "
                                f"explicit comment marks intent — please "
                                f"audit."
                            ),
                        })
                    else:
                        failures.append({
                            "rule": "NBA_SHIFT_REG_SAME_CYCLE_READ",
                            "severity": "FAIL",
                            "module": module_name,
                            "signal": signal,
                            "index": idx,
                            "file": file_path,
                            "line": file_line,
                            "message": (
                                f"`{signal}` <= `{signal}` >> N (NBA) "
                                f"shifts at end-of-cycle, but the SAME "
                                f"always_ff block reads `{signal}["
                                f"{idx}]` for next-bit setup. The read "
                                f"sees the OLD pre-shift value — every "
                                f"odd-numbered bit will be served from "
                                f"the wrong source. Read `{signal}[0]` "
                                f"BEFORE the shift, OR change the shift "
                                f"to explicit concat form "
                                f"`{signal} <= {{1'b0, {signal}["
                                f"N-1:1]}};` if a 1-bit pipeline is "
                                f"intentional."
                            ),
                        })

    # Pattern B: combinational read of S[K>=1] outside always_ff
    if all_shifted_signals:
        # Strip out always_ff blocks first to look only at outside-block context
        stripped = body_clean
        for blk_start, blk_end, _txt in sorted(blocks, key=lambda b: -b[0]):
            stripped = stripped[:blk_start] + " " * (blk_end - blk_start) + stripped[blk_end:]
        for signal in all_shifted_signals:
            assign_pat = re.compile(
                rf"\bassign\s+\w+\s*=\s*[^;]*\b{re.escape(signal)}\s*\[\s*(\d+)\s*\][^;]*;",
                re.IGNORECASE | re.DOTALL,
            )
            for m in assign_pat.finditer(stripped):
                idx = int(m.group(1))
                if idx == 0:
                    continue
                abs_offset = file_offset_in_text + m.start()
                file_line = _line_of(whole_text, abs_offset)
                failures.append({
                    "rule": "NBA_SHIFT_REG_COMB_READ",
                    "severity": "FAIL",
                    "module": module_name,
                    "signal": signal,
                    "index": idx,
                    "file": file_path,
                    "line": file_line,
                    "message": (
                        f"combinational read of `{signal}[{idx}]` while "
                        f"`{signal}` is shifted by NBA elsewhere in the "
                        f"same module. Downstream consumer captures the "
                        f"stale pre-shift value. Either drive the read "
                        f"from the post-shift NBA target (use a separate "
                        f"register staged after the shift) or shift via "
                        f"concat form."
                    ),
                })

    return failures, warnings, found_any_shift


def waived(project_dir: Path) -> tuple[bool, str]:
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return False, ""
    try:
        d = json.loads(waivers.read_text())
        text = d.get(WAIVER_KEY)
        if isinstance(text, str) and len(text.strip()) >= WAIVER_MIN:
            return True, text.strip()
    except Exception:
        pass
    return False, ""


def check(project_dir: Path, rtl_dir: Path) -> dict:
    failures: list[dict] = []
    warnings: list[dict] = []
    found_any_shift = False
    files_scanned: list[str] = []

    rtl_files = find_rtl_files(project_dir) if not rtl_dir else [
        f for f in find_rtl_files(project_dir)
        if str(f).startswith(str(rtl_dir))
    ]
    if rtl_dir and rtl_dir.exists():
        rtl_files = sorted(
            list(rtl_dir.glob("*.v")) + list(rtl_dir.glob("*.sv"))
        )

    for f in rtl_files:
        text = read_text(f)
        if not text:
            continue
        files_scanned.append(str(f))
        for span in find_modules(text):
            mod_failures, mod_warnings, has_shift = _check_module(
                span.name,
                span.body,
                str(f),
                span.start,
                text,
            )
            failures.extend(mod_failures)
            warnings.extend(mod_warnings)
            if has_shift:
                found_any_shift = True

    # Dedupe identical (file,line,signal,index,rule) findings.
    def _dedupe(entries: list[dict]) -> list[dict]:
        seen = set()
        out = []
        for e in entries:
            key = (e.get("file"), e.get("line"), e.get("signal"),
                   e.get("index"), e.get("rule"))
            if key in seen:
                continue
            seen.add(key)
            out.append(e)
        return out

    failures = _dedupe(failures)
    warnings = _dedupe(warnings)

    return {
        "program": "nba_shift_register_same_cycle_read_check",
        "found_shift_register": found_any_shift,
        "files_scanned": len(files_scanned),
        "failures": failures,
        "warnings": warnings,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir")
    ap.add_argument("--rtl-dir", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.exists():
        print(f"FAIL — project dir not found: {project}", file=sys.stderr)
        return 2

    rtl_dir = Path(args.rtl_dir).resolve() if args.rtl_dir else (_pl.rtl_dir(project))
    # Tolerant: still scan project-level rtl files via find_rtl_files
    result = check(project, rtl_dir)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(result, indent=2))

    if not result["found_shift_register"]:
        print("PASS_SKIP — no NBA shift register detected; gate not applicable")
        return 0

    if result["failures"]:
        is_waived, why = waived(project)
        if is_waived:
            print(
                f"PASS_WITH_WAIVER — {len(result['failures'])} NBA shift "
                f"register same-cycle-read finding(s); waiver "
                f"`{WAIVER_KEY}` set: {why[:80]}..."
            )
            for fnd in result["failures"]:
                print(f"  • {fnd['file']}:{fnd['line']} "
                      f"[{fnd['rule']}] {fnd['signal']}[{fnd['index']}] — "
                      f"{fnd['message'][:120]}")
            return 0
        # v1.6.523 — bit-serial-family suppression. A 1-bit-datapath /
        # known bit-serial core processes one bit/cycle by construction;
        # a same-cycle look-ahead shift read is the intended topology,
        # not a multi-bit NBA race. Downgrade FAIL → WARN (exit 0) with
        # the supporting evidence. Genuine MULTI-BIT races on non-bit-
        # serial designs keep FAILing (fail-closed default below).
        is_bit_serial, bs_evidence = _bit_serial_evidence(project)
        if is_bit_serial:
            print(
                f"WARN — {len(result['failures'])} NBA shift register "
                f"same-cycle-read finding(s) DOWNGRADED to WARN: design is "
                f"a bit-serial core ({bs_evidence}); a 1-bit-datapath "
                f"core's same-cycle look-ahead shift read is the intended "
                f"topology, not a multi-bit NBA race. Audit the look-ahead "
                f"is the consumer's intent."
            )
            for fnd in result["failures"]:
                print(f"WARN: {fnd['rule']} at {fnd['file']}:{fnd['line']} — "
                      f"{fnd['message'][:160]}")
            for w in result["warnings"]:
                print(f"WARN: {w['rule']} at {w['file']}:{w['line']} — "
                      f"{w['message'][:160]}")
            return 0
        print(
            f"FAIL — {len(result['failures'])} NBA shift register same-cycle-"
            f"read race(s) detected"
        )
        for fnd in result["failures"]:
            print(f"FAIL: {fnd['rule']} at {fnd['file']}:{fnd['line']} — "
                  f"{fnd['message']}")
        for w in result["warnings"]:
            print(f"WARN: {w['rule']} at {w['file']}:{w['line']} — "
                  f"{w['message']}")
        return 1

    if result["warnings"]:
        print(
            f"WARN — {len(result['warnings'])} NBA shift register look-ahead "
            f"pattern(s) flagged; review for intentional pipeline"
        )
        for w in result["warnings"]:
            print(f"WARN: {w['rule']} at {w['file']}:{w['line']} — "
                  f"{w['message']}")
        return 0

    print("PASS — no NBA shift-register same-cycle-read race detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
