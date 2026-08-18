#!/usr/bin/env python3
"""function_void_with_output_check.py — Wave 29 (v0.119.61) gate.

Detects illegal SystemVerilog `function ... void` blocks containing
``output`` / ``inout`` arguments.

Background
----------
SystemVerilog LRM (IEEE-1800-2017) §13.4 explicitly forbids
``output`` / ``inout`` formal arguments inside a ``function`` — only
``input`` and ``ref`` are allowed.  Anything that needs to return
multiple values via formal-argument side-effects must be a ``task``.

Wave 28 reference TB (v0.119.60) caught the v0.119.59 bug:

    rtl/main_fsm.sv:259-270:
        function automatic void dispatch_setup;
          input  [7:0] op;
          output [7:0] rop;
          output [4:0] payload_len;
          ...
        endfunction

Quartus accepts this as a vendor extension; iverilog crashes with
``net_scope.cc:492 Assertion type_ == TASK failed.``  Real silicon
synthesis is non-deterministic.

Detection algorithm
-------------------
1. Scan all ``.sv`` / ``.v`` files under ``<project>/rtl/`` (or
   ``src/``, ``hdl/``) — recursive.
2. Locate every ``function`` ... ``endfunction`` block.  Match
   ``function`` optionally preceded by ``automatic`` / ``static`` and
   optionally followed by ``automatic`` / ``static`` and a return
   type which may be ``void``.  Classify the function as
   ``return_kind = void`` only when an explicit ``void`` token
   follows ``function``.
3. Within the parameter list (between the function header and the
   first ``;`` or ``)`` closing the port list) look for ``output``
   / ``inout`` keywords.  Both legacy ``function NAME; input ...;
   output ...;`` form and ANSI-style ``function void NAME(input,
   output, ...);`` form are covered.
4. **FAIL** when an ``output`` / ``inout`` is found inside ANY
   function (the LRM violation isn't actually limited to ``void``;
   non-void functions returning a value via the return-type still
   cannot accept output/inout args).  We report the function header
   line and suggest replacing ``function`` → ``task``.
5. SKIP gracefully when no RTL files are present.
6. Honors waiver ``function_void_output_intentional`` (≥40 chars).

Usage
-----
    python3 function_void_with_output_check.py <project_dir>
        [--json <out>]

Exit codes
----------
    0 — PASS / SKIP / PASS_WITH_WAIVER
    1 — FAIL
    2 — usage / IO error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


WAIVER_KEY = "function_void_output_intentional"
WAIVER_MIN = 40


# Match a function header.  We tokenize after the `function` keyword
# rather than try to glob-then-regex, because qualifiers
# (`automatic`/`static`) and return types (`void`, `[7:0]`, `bit`,
# `logic`, etc.) interleave freely.
#
# Examples we want to catch (header up to first `;` or first `(`):
#   function automatic void dispatch_setup;
#   function void NAME(input a, output b);
#   function automatic [7:0] foo (input a);
#   function NAME;
#
# Strategy: locate `function` keyword, then parse forward token by
# token to find the function name (last identifier before `;` or `(`)
# and detect `void` and qualifier tokens in between.
_FUNCTION_KEYWORD_RE = re.compile(r"\bfunction\b")

# Reserved tokens we should NOT treat as the function name when they
# appear in the qualifier/return-type prefix.
_FUNCTION_PREFIX_TOKENS = {
    "automatic", "static", "void", "signed", "unsigned",
    "bit", "logic", "byte", "shortint", "int", "longint", "integer",
    "time", "real", "shortreal", "string", "chandle", "event",
    "reg", "wire",
    # `protected`, `local`, etc. (class members) — extremely rare in
    # synthesizable RTL but keep them out anyway.
    "protected", "local", "extern", "virtual", "pure", "rand",
    "randc", "const", "var",
}

# Detect a packed-vector range like `[7:0]` or parameterized like
# `[WIDTH-1:0]` — we'll skip past these when scanning for the name.
_VECTOR_RANGE_RE = re.compile(r"\[[^\]]*\]")

# Whole function body: function ... endfunction
_FUNCTION_BLOCK_RE = re.compile(
    r"\bfunction\b.*?\bendfunction\b",
    re.MULTILINE | re.DOTALL,
)

# `output` / `inout` keyword as a standalone token (not inside a
# longer identifier).  Used both for ANSI port list inside (...) and
# for legacy form (declarations between header `;` and first
# statement / `begin`).
_OUTPUT_KW_RE = re.compile(r"\b(output|inout)\b")


def _strip_comments(text: str) -> str:
    """Strip // and /* */ comments so we don't accidentally hit
    `output` or `function` inside doc text."""
    # Block comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # Line comments
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _line_no(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def waived(project: Path) -> tuple[bool, str]:
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


def _find_rtl_dir(project: Path) -> Path | None:
    for cand in ("phase2/stage1/rtl", "rtl", "src", "hdl"):
        d = project / cand
        if d.is_dir():
            files = list(d.rglob("*.v")) + list(d.rglob("*.sv"))
            if files:
                return d
    if any(project.glob("*.v")) or any(project.glob("*.sv")):
        return project
    return None


def _list_rtl_files(rtl_dir: Path) -> list[Path]:
    files = sorted(list(rtl_dir.rglob("*.v")) + list(rtl_dir.rglob("*.sv")))
    out: list[Path] = []
    for f in files:
        n = f.name.lower()
        # Skip TB / sim-only files.
        if "_tb" in n or n.startswith("tb_") or "testbench" in n:
            continue
        out.append(f)
    return out


def _parse_function_header(block: str
                            ) -> tuple[str, bool, int, str] | None:
    """Parse one ``function ... endfunction`` block's header.

    Returns ``(name, is_void, header_end_idx, decl_region)`` or None
    if the header could not be parsed.

    ``decl_region`` is the substring containing port declarations —
    either the ANSI port list inside ``(...)`` OR the legacy region
    between header ``;`` and ``begin`` / ``endfunction``.
    """
    # Locate the `function` keyword inside the block.
    m_kw = _FUNCTION_KEYWORD_RE.search(block)
    if not m_kw:
        return None
    cursor = m_kw.end()

    # Walk tokens until we hit the function NAME.  The name is the
    # last identifier-token before either ';' or '(', skipping over
    # qualifier/return-type tokens in `_FUNCTION_PREFIX_TOKENS` and
    # skipping over `[...]` vector ranges.
    name = None
    is_void = False
    after_name_idx = None
    i = cursor
    while i < len(block):
        ch = block[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "[":
            # skip vector range
            m = _VECTOR_RANGE_RE.match(block, i)
            if m:
                i = m.end()
                continue
            else:
                i += 1
                continue
        if ch in (";", "("):
            after_name_idx = i
            break
        # Identifier?
        m_id = re.match(r"[A-Za-z_]\w*", block[i:])
        if m_id:
            tok = m_id.group(0)
            tok_low = tok.lower()
            if tok_low == "void":
                is_void = True
                i += len(tok)
                continue
            if tok_low in _FUNCTION_PREFIX_TOKENS:
                i += len(tok)
                continue
            # candidate name — keep walking; if a later identifier
            # appears (e.g. `function bit foo` — `bit` was already
            # consumed as prefix; if not, we'd overwrite), the last
            # identifier before `;`/`(` wins.
            name = tok
            i += len(tok)
            continue
        # Non-identifier punctuation we don't recognise — bail.
        i += 1

    if name is None:
        return None
    if after_name_idx is None:
        return None

    # decl region — ANSI form `(...)` or legacy `; ... begin`.
    decl_region = ""
    if block[after_name_idx] == "(":
        # find matching ')' (depth-aware, accounts for nested parens)
        depth = 0
        j = after_name_idx
        while j < len(block):
            if block[j] == "(":
                depth += 1
            elif block[j] == ")":
                depth -= 1
                if depth == 0:
                    decl_region = block[after_name_idx + 1:j]
                    break
            j += 1
    else:
        # legacy ';' form — decl region is from after ';' to first
        # 'begin' / 'endfunction'.
        rest = block[after_name_idx + 1:]
        m_begin = re.search(r"\bbegin\b", rest)
        end_idx = m_begin.start() if m_begin else len(rest)
        decl_region = rest[:end_idx]

    return name, is_void, after_name_idx, decl_region


def _scan_file(path: Path) -> list[dict]:
    """Return list of finding dicts for this file."""
    findings: list[dict] = []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings
    text = _strip_comments(raw)

    # Iterate every function...endfunction block.
    for blk in _FUNCTION_BLOCK_RE.finditer(text):
        block = blk.group(0)
        block_start = blk.start()
        parsed = _parse_function_header(block)
        if parsed is None:
            continue
        name, is_void, _end_idx, decl_region = parsed

        # Look for output/inout keywords as port directions.
        m_kw = _OUTPUT_KW_RE.search(decl_region)
        if not m_kw:
            continue
        kw = m_kw.group(1)
        findings.append({
            "file": str(path),
            "header_line": _line_no(text, block_start),
            "function_name": name,
            "violation_kw": kw,
            "is_void": is_void,
        })

    return findings


def check(project: Path) -> dict:
    out: dict = {
        "program": "function_void_with_output_check",
        "pass": True,
        "findings": [],
        "warnings": [],
    }
    rtl_dir = _find_rtl_dir(project)
    if rtl_dir is None:
        out["skip_reason"] = "no RTL directory found"
        return out
    files = _list_rtl_files(rtl_dir)
    if not files:
        out["skip_reason"] = "no .v / .sv files under rtl/"
        return out

    findings: list[dict] = []
    for f in files:
        findings.extend(_scan_file(f))

    if findings:
        out["pass"] = False
        for fnd in findings:
            kind = "void" if fnd["is_void"] else "non-void"
            rel = fnd["file"]
            try:
                rel = str(Path(fnd["file"]).relative_to(project))
            except ValueError:
                pass
            msg = (
                f"FAIL — FUNCTION_VOID_WITH_OUTPUT\n"
                f"  {rel}:{fnd['header_line']} — `function "
                f"automatic {kind} {fnd['function_name']}(...)` "
                f"declares an `{fnd['violation_kw']}` argument.\n"
                f"  SV LRM (IEEE-1800-2017 §13.4): functions cannot "
                f"have output/inout args. Must be `task`.\n"
                f"  Quartus tolerates this; iverilog crashes; real "
                f"silicon may produce non-deterministic synthesis.\n"
                f"  Fix: replace `function automatic void NAME(...)` "
                f"with `task automatic NAME(...);` and `endfunction` "
                f"with `endtask`."
            )
            out["findings"].append({
                "rule": "FUNCTION_VOID_WITH_OUTPUT",
                "severity": "FAIL",
                "message": msg,
                "file": rel,
                "line": fnd["header_line"],
                "function_name": fnd["function_name"],
                "violation_kw": fnd["violation_kw"],
            })
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}", file=sys.stderr)
        return 2

    result = check(project)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(result, indent=2))

    if "skip_reason" in result:
        print(f"PASS_SKIP — {result['skip_reason']}")
        return 0

    if result["pass"]:
        print("PASS — no SV function declares output/inout args")
        return 0

    is_waived, why = waived(project)
    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(result['findings'])} finding(s); "
            f"waiver `{WAIVER_KEY}` set: {why[:80]}…")
        for f in result["findings"]:
            print(f"  • {f['rule']} — {f['file']}:{f['line']} "
                  f"function {f['function_name']} ({f['violation_kw']})")
        return 0

    print(f"FAIL — {len(result['findings'])} function(s) with "
          f"output/inout args (must be `task`)")
    for f in result["findings"]:
        print(f"FAIL: {f['rule']} — {f['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
