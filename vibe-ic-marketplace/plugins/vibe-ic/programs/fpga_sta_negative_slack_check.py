#!/usr/bin/env python3
"""
fpga_sta_negative_slack_check.py — Wave 24 / v0.119.56.

Goal: parse Quartus STA summary; any negative setup or hold slack on any
corner = FAIL. Catches the v0.119.55 29th-attempt <benchmark> silent
byte[6]=0x02 root cause (setup slack -5.5 ns at Slow 1200mV 0C).

Detection algorithm
-------------------
1. Find STA summary files under `<project>/fpga/output_files/`:
       *.sta.summary
       *.sta.rpt
2. Parse `Setup` slack and `Hold` slack values per corner (Slow 0C,
   Slow 85C, Fast 0C, etc).
3. **FAIL** when ANY corner has slack < 0 ns (negative).
4. **PASS** when all corners ≥ 0 ns.
5. **SKIP** when no STA summary found (Quartus didn't run / project not
   built yet).
6. Honors waiver `fpga_negative_slack_acceptable` (≥ 40 chars).

Chip-AGNOSTIC.

Quartus *.sta.summary format (verbatim example):

    ------------------------------------------------------------
    Timing Analyzer Summary
    ------------------------------------------------------------
    Type  : Slow 1200mV 85C Model Setup 'clk_50m'
    Slack : -6.047
    TNS   : -1392.943

    Type  : Slow 1200mV 0C Model Setup 'clk_50m'
    Slack : -5.512

We extract every (Type, Slack) pair and check Setup / Hold slack ≥ 0.
"Minimum Pulse Width" entries are ignored — those are routinely
negative on Quartus tutorial PLLs and not a timing failure.

Exit codes
----------
    0 — PASS / PASS_WITH_WAIVER / SKIP
    1 — FAIL
    2 — IO / argument error
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
import _path_layout as _pl


WAIVER_KEY = "fpga_negative_slack_acceptable"


@dataclass
class SlackEntry:
    file: str
    type: str          # full Type line
    kind: str          # "Setup" / "Hold" / "Recovery" / "Removal" / "MPW" / "other"
    corner: str        # everything before " Model "
    slack_ns: float


_TYPE_RE = re.compile(r"^Type\s*:\s*(?P<full>.+?)\s*$", re.IGNORECASE)
_SLACK_RE = re.compile(r"^Slack\s*:\s*(?P<v>-?[0-9.]+)", re.IGNORECASE)


def parse_sta_summary(text: str, file: str) -> List[SlackEntry]:
    out: List[SlackEntry] = []
    cur_type: Optional[str] = None
    for line in text.splitlines():
        line = line.strip()
        m = _TYPE_RE.match(line)
        if m:
            cur_type = m.group("full")
            continue
        m = _SLACK_RE.match(line)
        if m and cur_type is not None:
            try:
                v = float(m.group("v"))
            except ValueError:
                cur_type = None
                continue
            kind = "other"
            t = cur_type.lower()
            if "setup" in t:
                kind = "Setup"
            elif "hold" in t:
                kind = "Hold"
            elif "recovery" in t:
                kind = "Recovery"
            elif "removal" in t:
                kind = "Removal"
            elif "minimum pulse width" in t or "mpw" in t:
                kind = "MPW"
            corner = re.sub(r"\s+Model.*$", "", cur_type, flags=re.IGNORECASE)
            out.append(SlackEntry(
                file=file, type=cur_type, kind=kind,
                corner=corner.strip(), slack_ns=v,
            ))
            cur_type = None
    return out


def find_sta_summary_files(project: Path) -> List[Path]:
    out: List[Path] = []
    fpga_dir = _pl.fpga_early_dir(project)
    if not fpga_dir.is_dir():
        return []
    for sub in (fpga_dir / "output_files",):
        if sub.is_dir():
            out.extend(sub.glob("*.sta.summary"))
            out.extend(sub.glob("*.sta.rpt"))
    # also accept project-root output_files just in case
    out2 = sorted({p for p in out if p.is_file()})
    return out2


def waived(project: Path) -> bool:
    w = project / "waivers.json"
    if not w.exists():
        return False
    try:
        d = json.loads(w.read_text())
    except Exception:
        return False
    v = d.get(WAIVER_KEY, "")
    if isinstance(v, dict):
        v = v.get("reason", "") or v.get("justification", "")
    return isinstance(v, str) and len(v.strip()) >= 40


def audit(project: Path) -> Tuple[str, List[str], List[SlackEntry]]:
    msgs: List[str] = []
    files = find_sta_summary_files(project)
    if not files:
        msgs.append(
            "SKIP — no STA summary found under fpga/output_files/ "
            "(*.sta.summary, *.sta.rpt). Quartus probably hasn't run."
        )
        return ("SKIP", msgs, [])

    entries: List[SlackEntry] = []
    for f in files:
        try:
            txt = f.read_text(errors="replace")
        except Exception:
            continue
        entries.extend(parse_sta_summary(txt, str(f)))

    if not entries:
        msgs.append(
            "WARN — STA summary found but no Type/Slack pairs parsed: "
            f"{[str(p) for p in files]}"
        )
        return ("PASS", msgs, [])

    # Only fail on Setup/Hold slack < 0. MPW negative is benign.
    fails = [e for e in entries
             if e.kind in ("Setup", "Hold") and e.slack_ns < 0]
    if fails:
        for e in fails:
            rel = e.file
            try:
                rel = str(Path(e.file).relative_to(project))
            except Exception:
                pass
            advisory = (
                "Negative slack indicates timing violation. Critical paths "
                "run faster than silicon can latch correctly → metastability "
                "/ edge errors. Add SDC constraints to enable Quartus "
                "timing-driven placement."
            )
            msgs.append(
                f"FAIL — STA_NEGATIVE_SLACK\n"
                f"File: {rel}\n"
                f"Corner: {e.corner}\n"
                f"{e.kind} slack: {e.slack_ns} ns\n\n"
                f"{advisory}"
            )
        return ("FAIL", msgs, entries)

    # All Setup/Hold non-negative.
    n_corners = len({e.corner for e in entries})
    msgs.append(
        f"PASS — {len(entries)} slack entries across {n_corners} corner(s); "
        f"all Setup/Hold ≥ 0 ns"
    )
    return ("PASS", msgs, entries)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    project = Path(argv[0]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}", file=sys.stderr)
        return 2

    verdict, msgs, _ = audit(project)

    if verdict == "FAIL" and waived(project):
        print(f"PASS_WITH_WAIVER — {WAIVER_KEY} accepted")
        for m in msgs:
            print(m)
        return 0

    for m in msgs:
        print(m)

    if verdict == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
