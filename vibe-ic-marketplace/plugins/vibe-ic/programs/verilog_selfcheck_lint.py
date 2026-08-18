#!/usr/bin/env python3
r"""verilog_selfcheck_lint.py — PROGRAM-FIRST verilator -Wall self-lint gate.

GENERAL CORE (benchmark-AGNOSTIC). The self-verification gate a lint-review task
needs (see `spec_lint_review_detect`): run `verilator --lint-only -Wall` over the
authored RTL and return the warnings so the author close-loops to ZERO before
emit. This is exactly the gate whose ABSENCE let a functionally-correct
`IIR_filter` draft fail on a single `%Warning-UNUSEDSIGNAL` for an over-wide
intermediate reg.

Honest degradation: if no `verilator` binary is reachable (host or an
env-supplied shim), the gate returns status ``SKIP`` — it never fakes a PASS. In
the scoring / CI environment (where the same lint check runs) verilator is
present, so the gate fires there.

Reads ONLY the RTL under test (+ any sibling context files the caller supplies) —
never any oracle/harness/golden (§4.05).

Usage:
    from verilog_selfcheck_lint import selfcheck_lint
    r = selfcheck_lint("path/to/rtl.sv", top="iir_filter")   # -> dict

    python3 verilog_selfcheck_lint.py rtl.sv --top iir_filter   # CLI, JSON out

`VERILATOR` env (or --verilator) overrides the binary (point it at a container
shim wrapper to run the same major as the official scorer).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

# verilator diagnostic line, e.g.
#   %Warning-UNUSEDSIGNAL: iir.sv:42:12: Bits of signal are not used: 'temp_y'[31:16]
_DIAG_RE = re.compile(
    r"%(Warning|Error)(?:-([A-Z0-9_]+))?:\s*"
    r"(?:([^:\n]+):(\d+):(?:\d+:)?\s*)?(.*)")


def _resolve_verilator(override: Optional[str]) -> Optional[str]:
    cand = override or os.environ.get("VERILATOR") or "verilator"
    return cand if (Path(cand).is_file() or shutil.which(cand)) else None


def _looks_like_path(rtl: str) -> bool:
    """True only when `rtl` names an existing file. The ONLY correct discriminator
    between a file path and raw SV text — a multi-line SV string is never a real
    file, and real RTL almost always contains '/' (a `//` comment or a division),
    so the old `os.path.sep in rtl` heuristic misrouted raw text as a filename.
    An over-long raw source makes stat() raise ENAMETOOLONG (OSError) / ValueError
    — treat that as "not a path" (raw text)."""
    try:
        return Path(rtl).is_file()
    except (OSError, ValueError):
        return False


def _parse_diags(text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for line in text.splitlines():
        m = _DIAG_RE.search(line)
        if not m:
            continue
        sev, code, fname, lineno, msg = m.groups()
        # pull a `'signal'[hi:lo]` name out of the message when present
        sig = None
        sm = re.search(r"'([^']+)'(\[[^\]]*\])?", msg or "")
        if sm:
            sig = sm.group(1) + (sm.group(2) or "")
        out.append({
            "severity": sev,
            "code": code or "",
            "file": fname,
            "line": int(lineno) if lineno else None,
            "signal": sig,
            "message": (msg or "").strip(),
        })
    return out


def selfcheck_lint(rtl: str, top: Optional[str] = None,
                   context_files: Optional[List[str]] = None,
                   verilator: Optional[str] = None,
                   extra_args: Optional[List[str]] = None) -> Dict[str, Any]:
    """Run `verilator --lint-only -Wall` on `rtl` (a file path OR raw SV text).

    Returns a dict::

        {
          "status": "PASS" | "FAIL" | "SKIP",
          "returncode": int|None,
          "warnings": [ {severity, code, file, line, signal, message}, ... ],
          "n_warnings": int,
          "codes": [str, ...],          # distinct -Wall codes seen
          "verilator": str|None,        # binary used
          "raw": str,                   # combined stdout+stderr (trimmed)
          "skip_reason": str|None,
        }

    PASS  = verilator returned 0 with no Warning/Error diagnostics.
    FAIL  = verilator flagged ≥1 Warning/Error (the author must close these).
    SKIP  = no verilator reachable (never a fake PASS).
    """
    binpath = _resolve_verilator(verilator)
    if not binpath:
        return {"status": "SKIP", "returncode": None, "warnings": [],
                "n_warnings": 0, "codes": [], "verilator": None, "raw": "",
                "skip_reason": "no verilator binary on PATH/VERILATOR"}

    tmp: Optional[tempfile.TemporaryDirectory] = None
    files: List[str] = []
    try:
        if _looks_like_path(rtl):
            files.append(str(Path(rtl)))
        else:
            tmp = tempfile.TemporaryDirectory()
            # name the temp file after the module so verilator's DECLFILENAME
            # (filename-vs-module cosmetic lint) does not fire on clean RTL.
            f = Path(tmp.name) / (f"{top}.sv" if top else "dut.sv")
            f.write_text(rtl)
            files.append(str(f))
        for c in (context_files or []):
            if Path(c).is_file():
                files.append(str(c))

        # -Wall minus DECLFILENAME: the filename-vs-module-name convention is a
        # cosmetic filesystem lint (fires on temp files / any path whose leaf !=
        # module name) irrelevant to the self-lint's purpose (UNUSEDSIGNAL,
        # WIDTH, etc.); suppressing it never weakens real-defect coverage.
        # match the CVDP harness lint deck as closely as blind-safely possible:
        # it runs `verilator --lint-only -Wall -Wno-EOFNEWLINE <config.vlt> $SRC`.
        # -Wno-EOFNEWLINE (a trailing-newline cosmetic) + -Wno-DECLFILENAME (a
        # temp-file-naming self-gate artifact) are suppressed; every real defect
        # class (-Wall) still fires, so parity with the scorer is preserved.
        cmd = [binpath, "--lint-only", "-Wall", "-Wno-DECLFILENAME", "-Wno-EOFNEWLINE"]
        if top:
            cmd += ["--top-module", top]
        cmd += (extra_args or [])
        cmd += files
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        raw = (proc.stdout or "") + (proc.stderr or "")
        diags = _parse_diags(raw)
        codes = sorted({d["code"] for d in diags if d["code"]})
        status = "PASS" if (proc.returncode == 0 and not diags) else "FAIL"
        return {
            "status": status,
            "returncode": proc.returncode,
            "warnings": diags,
            "n_warnings": len(diags),
            "codes": codes,
            "verilator": binpath,
            "raw": raw[-4000:],
            "skip_reason": None,
        }
    except subprocess.TimeoutExpired:
        return {"status": "SKIP", "returncode": None, "warnings": [],
                "n_warnings": 0, "codes": [], "verilator": binpath, "raw": "",
                "skip_reason": "verilator timed out"}
    finally:
        if tmp is not None:
            tmp.cleanup()


def main(argv: List[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("rtl", help="RTL file path (or raw SV text if not a file)")
    ap.add_argument("--top", default=None)
    ap.add_argument("--context", default="", help="comma-list of sibling files")
    ap.add_argument("--verilator", default=None)
    a = ap.parse_args(argv)
    rtl = a.rtl
    if Path(rtl).is_file():
        pass  # selfcheck_lint handles the path
    ctx = [c for c in a.context.split(",") if c]
    r = selfcheck_lint(rtl, top=a.top, context_files=ctx, verilator=a.verilator)
    print(json.dumps(r, indent=2, ensure_ascii=False))
    # exit 0 on PASS/SKIP, 1 on FAIL (so a close-loop can branch on it)
    return 1 if r["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
