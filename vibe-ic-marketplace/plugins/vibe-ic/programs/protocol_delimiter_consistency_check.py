#!/usr/bin/env python3
"""
protocol_delimiter_consistency_check.py — Verify the RTL FSM that validates
end-of-frame fires on the spec's canonical trailing delimiter, not a
proxy signal (idle_long, timeout, etc.).

THE PROBLEM
-----------
On the v0.99 vendor fresh-agent run, dispatcher.v gated its frame-validation
arm on `idle_long` (no traffic for N cycles) — but the spec's actual
end-of-frame symbol was a trailing BR pulse. The TB happened to drive
500_000 idle cycles after each cmd, so `idle_long` fired and the dispatcher
PASSed sim. On the rig (where the host doesn't sit idle that long after
issuing a cmd) the dispatcher never validated frames and shipped FAIL.

This is the static cousin of `trailing_delimiter_completeness_check`:
that one checks the TB; this one checks the RTL.

INPUTS
------
1. RTL file or directory.
2. Protocol delimiter (one of):
     a. ``--delimiter NAME`` on the command line (e.g. ``BR_HIGH``,
        ``trailing_br``, ``frame_end``).
     b. L3_CMD_PROTOCOL.json key ``trailing_delimiter`` /
        ``end_of_frame``.
     c. L9_INTEGRATION_SPEC.json key ``protocol.trailing_delimiter``.

USAGE
-----
    python3 protocol_delimiter_consistency_check.py rtl/ \
        --layer-l3 generated_docs/L3_CMD_PROTOCOL.json
    python3 protocol_delimiter_consistency_check.py rtl/dispatcher.v \
        --delimiter BR_HIGH
    python3 protocol_delimiter_consistency_check.py rtl/ \
        --delimiter BR_HIGH --json reports/gates/proto_delim.json

EXIT CODES
----------
    0 — every FSM module that validates frames references the declared
        delimiter signal.
    1 — at least one FSM validates on a non-delimiter proxy
        (idle_long, timeout, idle_count, etc.).
    2 — IO / argument error.

HEURISTICS
----------
We look for "frame validation" sites in the RTL — typically:
    - a `case` arm or `if` condition referencing a STATE_VALIDATE /
      STATE_DONE / FRAME_VALID-flavoured state name.
    - a sequential block whose RHS sets `*_valid`, `frame_done`,
      `cmd_valid`, etc.

Then we check whether the GUARD condition for that block references
the declared delimiter token (case-insensitive) or a forbidden proxy
(idle_long, idle_cnt, timeout, no_activity).

If a forbidden proxy fires the validation arm AND the canonical
delimiter is absent from the same module, the gate FAILs.

False positives are possible — designs may legitimately use BOTH a
delimiter AND a timeout. In that case the gate emits a WARN, not an
ERROR (i.e. exit 0 but with a notice).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import _path_layout as _pl


@dataclass
class Finding:
    severity: str  # "ERROR" | "WARN" | "INFO"
    rule: str
    file: str
    line: int
    message: str


# Regex hits that indicate the RTL is "validating a frame"
VALIDATION_NAMES = (
    r"frame_(?:done|valid|complete|good|ok)",
    r"cmd_(?:done|valid|complete|good|ok)",
    r"packet_(?:done|valid|complete)",
    r"(?:done|valid|complete)_q",
    r"STATE_(?:DONE|VALIDATE|VALID|DECODE|DISPATCH)",
)

VALIDATION_RE = re.compile(
    r"(" + "|".join(VALIDATION_NAMES) + r")", re.IGNORECASE,
)

# Forbidden proxies — if any of these GUARD a validation arm without
# the canonical delimiter being present, that's the bug class.
PROXY_NAMES = (
    r"idle_long",
    r"idle_cnt[a-z0-9_]*",
    r"idle_count[a-z0-9_]*",
    r"timeout[a-z0-9_]*",
    r"no_activity[a-z0-9_]*",
    r"silence[a-z0-9_]*",
    r"quiet[a-z0-9_]*",
)
PROXY_RE = re.compile(
    r"\b(" + "|".join(PROXY_NAMES) + r")\b", re.IGNORECASE,
)


def _resolve_delimiter(delim_arg, l3_path, l9_path):
    if delim_arg:
        return delim_arg.strip()
    for p in (l3_path, l9_path):
        if p and p.exists():
            try:
                d = json.loads(p.read_text())
            except Exception:
                continue
            for src in (d, d.get("protocol") if isinstance(d, dict) else None,
                         d.get("framing") if isinstance(d, dict) else None):
                if not isinstance(src, dict):
                    continue
                for key in ("trailing_delimiter", "end_of_frame",
                            "frame_end", "trailer"):
                    v = src.get(key)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
    return None


def _scan_file(path: Path, delimiter: str) -> List[Finding]:
    findings: List[Finding] = []
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return findings

    # Strip block + line comments to avoid false-positive matches inside doc.
    no_block = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    bare = re.sub(r"//[^\n]*", "", no_block)

    delim_lower = delimiter.lower()
    delim_present = delim_lower in bare.lower()
    has_validation = bool(VALIDATION_RE.search(bare))

    # Find every `if (... proxy ...)` style guard. We walk balanced parens
    # after each `if (` token.
    if not has_validation:
        return findings

    proxy_hits: List[tuple[str, int]] = []  # (proxy name, line number)
    for m in re.finditer(r"\b(?:if|while)\s*\(", bare):
        # find matching paren
        depth, j = 1, m.end()
        while j < len(bare) and depth > 0:
            if bare[j] == "(":
                depth += 1
            elif bare[j] == ")":
                depth -= 1
            j += 1
        guard_text = bare[m.end():j - 1]
        pm = PROXY_RE.search(guard_text)
        if pm:
            line_no = bare.count("\n", 0, m.start()) + 1
            proxy_hits.append((pm.group(1), line_no))

    if proxy_hits:
        if delim_present:
            for name, ln in proxy_hits:
                findings.append(Finding(
                    severity="WARN",
                    rule="proxy_alongside_delimiter",
                    file=str(path),
                    line=ln,
                    message=(
                        f"validation guard at line {ln} uses proxy "
                        f"{name!r} AND module also references "
                        f"{delimiter!r} — confirm the delimiter is the "
                        f"primary trigger and the proxy only a fallback "
                        f"(usually acceptable)."
                    ),
                ))
        else:
            for name, ln in proxy_hits:
                findings.append(Finding(
                    severity="ERROR",
                    rule="proxy_without_delimiter",
                    file=str(path),
                    line=ln,
                    message=(
                        f"validation guard at line {ln} uses proxy "
                        f"{name!r} but the declared protocol delimiter "
                        f"{delimiter!r} is NOT referenced anywhere in this "
                        f"module. Frames will be validated by idle/timeout, "
                        f"not by end-of-frame — the design will PASS sim "
                        f"with idle-padded TBs and FAIL on real traffic."
                    ),
                ))
    return findings


def audit(target: Path, delimiter: str) -> List[Finding]:
    findings: List[Finding] = []
    if target.is_file():
        files = [target]
    else:
        files = sorted(list(target.rglob("*.v")) + list(target.rglob("*.sv")))
    if not files:
        findings.append(Finding(
            "WARN", "no_rtl_files_found", str(target), 0,
            f"no .v or .sv files under {target}",
        ))
        return findings
    for f in files:
        findings.extend(_scan_file(f, delimiter))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    ap.add_argument("rtl", help="RTL file, directory, or project root (auto-derives rtl/ + L3)")
    ap.add_argument("--delimiter", default=None,
                    help="Override trailing delimiter token (case-insensitive)")
    ap.add_argument("--layer-l3", default=None)
    ap.add_argument("--layer-l9", default=None)
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH',
                    help="Emit JSON. With PATH writes to file; bare flag prints to stdout.")
    args = ap.parse_args(argv)

    # v1.6.7: positional <project> auto-derive (dead-wire fix). If the
    # positional points at a project root (has generated_docs/ or rtl/) and
    # no explicit --layer-l3, treat it as project mode.
    target = Path(args.rtl)
    proj_mode = False
    if target.is_dir() and _pl.generated_docs_dir(target).is_dir() and not args.layer_l3:
        proj_mode = True
        l3 = _pl.generated_docs_dir(target) / "L3_CMD_PROTOCOL.json"
        l9 = _pl.generated_docs_dir(target) / "L9_INTEGRATION_SPEC.json"
        if not l3.exists():
            skip = {"verdict": "SKIP", "pass": True,
                    "reason": f"no L3 at {l3}"}
            print(json.dumps(skip, indent=2))
            return 0
        args.layer_l3 = str(l3)
        if l9.exists() and not args.layer_l9:
            args.layer_l9 = str(l9)
        if _pl.rtl_dir(target).is_dir():
            target = _pl.rtl_dir(target)

    delim = _resolve_delimiter(
        args.delimiter,
        Path(args.layer_l3) if args.layer_l3 else None,
        Path(args.layer_l9) if args.layer_l9 else None,
    )
    if not delim:
        if proj_mode:
            skip = {"verdict": "SKIP", "pass": True,
                    "reason": "L3 has no delimiter field "
                              "(trailing_delimiter / end_of_frame / frame_end / trailer)"}
            print(json.dumps(skip, indent=2))
            return 0
        # v1.6.7: positional dir without any delimiter source → SKIP rc=0
        # (avoids FAIL on non-protocol or unwired targets)
        if target.is_dir() and not args.delimiter and not args.layer_l3 and not args.layer_l9:
            skip = {"verdict": "SKIP", "pass": True,
                    "reason": "no delimiter source provided "
                              "(no --delimiter / --layer-l3 / --layer-l9, "
                              "and target is not a project root with generated_docs/)"}
            print(json.dumps(skip, indent=2))
            return 0
        print("error: no trailing delimiter resolved (give --delimiter or --layer-l3/--layer-l9)",
              file=sys.stderr)
        return 2

    if not target.exists():
        print(f"error: target not found: {target}", file=sys.stderr)
        return 2

    findings = audit(target, delim)
    errors = [f for f in findings if f.severity == "ERROR"]

    report = {
        "target": str(target),
        "delimiter": delim,
        "total_findings": len(findings),
        "errors": len(errors),
        "warnings": sum(1 for f in findings if f.severity == "WARN"),
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
        print(f"\n{len(errors)} error(s); verdict: {report['verdict']}")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
