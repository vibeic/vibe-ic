#!/usr/bin/env python3
"""cvdp_fail_triage.py — mechanical CVDP fail-mode classifier (ORGANIC #534).

Promotes the host-side run-local triage script into the harness: reads the
official scorer's `raw_result.json` + per-problem report logs and classifies
every failing problem into one MODE so close-loop dispatch can hand each
repair agent a BLIND-SAFE convention-level hint.

Modes (signatures distilled from the real 302-problem run's 92 fails; this
program's per-record classification is MORE precise than the original
run-local script — pytest bottom-line aggregation separates partial from
all-fail, and ELAB evidence is compile-step-anchored — so its distribution
on the reference run intentionally differs from the field script's):
    SYNTH_GATE    — harness yosys gate: `KeyError: 'Number of cells'`
    ELAB_ERROR    — iverilog compile/elaboration error lines
    FUNC_PARTIAL  — cocotb ran; SOME tests failed, some passed
    FUNC_ALL      — cocotb ran; ALL tests failed
    UNKNOWN       — none of the signatures matched

BLINDNESS BOUNDARY: the hint templates are FIXED in this program and carry
convention-level guidance only — never an oracle expectation value, never
content quoted from the hidden testbench. (That is what keeps a close-loop
agent fed by these hints blind-safe.)

Exit codes: 0 = triage written; 2 = bad input.

chip-AGNOSTIC: log-signature classification only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Fixed, blind-safe hint templates (convention-level only — no oracle data).
HINTS = {
    "SYNTH_GATE": ("題目 harness 含 yosys synthesis gate；你的 RTL 沒有成功"
                   "合成（或 top 名不符）——確保純 synthesizable 構造且 top "
                   "模組名照題目"),
    "ELAB_ERROR": ("iverilog 編譯/elaboration 失敗——檢查語法、port 對齊與"
                   "模組名；以 iverilog -g2012 自驗到乾淨"),
    "FUNC_PARTIAL": ("cocotb 功能測試部分失敗——演算法/時序部分錯，從 prompt "
                     "重導並窮舉自驗"),
    "FUNC_ALL": ("cocotb 功能測試全數失敗——介面語義或核心演算法整體錯讀，"
                 "回到 prompt 重新推導行為，再以自寫 TB 窮舉驗證"),
    "UNKNOWN": ("失敗模式無法從 log 機械判定——人工檢視該題 reports 後再"
                "dispatch"),
}

_SYNTH_RE = re.compile(r"KeyError: 'Number of (cells|wires)'")
# ELAB evidence must be ANCHORED on compile-step shapes — a bare `error: `
# alternative coincidentally matched Python exception names
# (AssertionError: …) in functional logs (adversarial-review LOW).
_ELAB_RE = re.compile(
    r"(CalledProcessError: Command '\[u?'iverilog'"
    r"|^[^:\n]+\.s?v:\d+:\s*(?:syntax\s+)?error"
    r"|\bI give up\b"
    r"|\d+ error\(s\) during elaboration)",
    re.IGNORECASE | re.MULTILINE)
_FAILED_OF_RE = re.compile(r"\bFailed\s+(\d+)\s+of\s+(\d+)\s+tests?", re.I)
# pytest bottom-line summary — problem-level truth in the dominant CVDP
# harness shape (pytest-parametrized, ONE cocotb test per invocation, every
# failing invocation prints "Failed 1 of 1 tests" — so a single Failed-of
# match can NEVER distinguish partial from all; adversarial-review HIGH).
_PYTEST_SUMMARY_RE = re.compile(
    r"=+\s*(\d+)\s+failed(?:,\s*(\d+)\s+passed)?[^=\n]*=+")


def classify_log(text: str) -> str:
    """Classify ONE report log's failure mode."""
    if _SYNTH_RE.search(text):
        return "SYNTH_GATE"
    # 1) pytest bottom-line(s): aggregate failed/passed across invocations.
    p_failed = p_passed = 0
    for m in _PYTEST_SUMMARY_RE.finditer(text):
        p_failed += int(m.group(1))
        p_passed += int(m.group(2) or 0)
    if p_failed and p_passed:
        return "FUNC_PARTIAL"
    # 2) compile-step kill (anchored evidence)
    if _ELAB_RE.search(text):
        return "ELAB_ERROR"
    # 3) aggregate ALL Failed-of matches (never trust the first alone)
    a_failed = a_total = 0
    for m in _FAILED_OF_RE.finditer(text):
        a_failed += int(m.group(1))
        a_total += int(m.group(2))
    if p_failed and not p_passed:
        return "FUNC_ALL"
    if a_failed:
        return "FUNC_ALL" if a_failed >= a_total else "FUNC_PARTIAL"
    return "UNKNOWN"


def triage(raw: Dict, reports_root: Optional[Path]) -> List[Dict]:
    """Walk raw_result.json; classify every problem with ≥1 failing test."""
    out: List[Dict] = []
    for pid, info in sorted(raw.items()):
        tests = info.get("tests") or []
        failing = [t for t in tests if t.get("result") not in (0, "0", None)]
        if not failing and not info.get("errors"):
            continue
        # read every failing test's log (fall back to reports_root rebase
        # when the recorded absolute path moved between hosts)
        blob = ""
        for t in failing or tests:
            lp = t.get("log")
            if not lp:
                continue
            p = Path(lp)
            if not p.is_file() and reports_root is not None:
                # rebase: .../work_score/<prob>/reports/N.txt
                parts = Path(lp).parts
                if "reports" in parts:
                    i = parts.index("reports")
                    p = reports_root / Path(*parts[i - 1:])
            if p.is_file():
                blob += p.read_text(errors="replace") + "\n"
        mode = classify_log(blob) if blob.strip() else "UNKNOWN"
        out.append({"id": pid, "mode": mode, "blind_safe_hint": HINTS[mode]})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="CVDP fail-mode triage (mechanical, blind-safe) — #534.")
    ap.add_argument("--raw", required=True, help="scorer raw_result.json")
    ap.add_argument("--reports", default=None,
                    help="work dir root for log-path rebase (optional)")
    ap.add_argument("--out", required=True, help="triage JSON output path")
    args = ap.parse_args(argv)
    raw_p = Path(args.raw)
    if not raw_p.is_file():
        print(f"ERROR: raw_result not found: {raw_p}", file=sys.stderr)
        return 2
    try:
        raw = json.loads(raw_p.read_text(errors="replace"))
    except json.JSONDecodeError as e:
        print(f"ERROR: bad raw_result.json: {e}", file=sys.stderr)
        return 2
    reports_root = Path(args.reports) if args.reports else None
    records = triage(raw, reports_root)
    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    summary = {}
    for r in records:
        summary[r["mode"]] = summary.get(r["mode"], 0) + 1
    outp.write_text(json.dumps(
        {"total_fails": len(records), "mode_summary": summary,
         "records": records}, indent=2, ensure_ascii=False) + "\n")
    print(f"cvdp_fail_triage: {len(records)} fail(s) classified "
          f"{summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
