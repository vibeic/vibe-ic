#!/usr/bin/env python3
"""verify_fail_triage.py — mechanical CVDP fail-mode classifier (ORGANIC #534).

Promotes the host-side run-local triage script into the harness: reads the
official scorer's `raw_result.json` + per-problem report logs and classifies
every failing problem into one MODE so close-loop dispatch can hand each
repair agent a BLIND-SAFE convention-level hint.

Modes (field round-2 revision — evidence aggregated across the cocotb
`TESTS=n PASS=p FAIL=f` summary, `Failed X of Y`, the pytest bottom line,
AND the problem-level passing siblings recorded in raw_result itself;
FUNC_ALL requires ZERO pass evidence everywhere):
    SYNTH_GATE      — harness yosys gate: `KeyError: 'Number of cells'`
    SYNTH_THRESHOLD — RTL synthesizes but misses the harness quality
                      threshold (`No upgrades in synthesis` /
                      `Optimization failed`)
    ELAB_ERROR      — genuine iverilog compile kill (anchored evidence,
                      no test-level verdict ran)
    FUNC_PARTIAL    — some hidden tests pass, some fail (any family)
    FUNC_ALL        — every verdict is a fail, zero pass evidence
    TRUNCATED       — log cut off before any verdict (infra flakiness)
    TRUNCATED_BUT_PASSED — (v1.2.46) TRUNCATED INFRA + score-final PASS:
                      passrate.json says the problem PASSes BUT we have
                      no per-test verdict in our local logs. Likely log-
                      sync failure or runner watchdog truncation, NOT a
                      genuine hang. Absolutely does NOT go on the repair
                      queue — archive-only audit-trail.
    UNKNOWN         — verdict evidence present but unclassifiable

HONESTY NOTE: per-record verification on the reference final run showed the
host's run-local triage script over-counted FUNC_PARTIAL (e.g. a 10×
`TESTS=1 PASS=0 FAIL=1` log and a log whose only "passed" tokens are
in-flight diagnostic prose were both labelled partial there); this program
classifies those FUNC_ALL with the log lines as evidence, and its ELAB
records are verified real `CalledProcessError: ['iverilog' …` kills. The
distributions therefore intentionally differ; the flagship partial case
(`TESTS=10 PASS=9 FAIL=1`) and the 4 TRUNCATED records match the host
exactly.

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
    "TRUNCATED": ("harness log 在 verdict 前被截斷（infra flakiness，非設計"
                  "判決）——單獨重跑該題確認；headline 仍計 FAIL（不挑櫻桃）"),
    "TRUNCATED_BUT_PASSED": ("（v1.2.46）harness log 在 verdict 前被截斷，但"
                              "score-final PASS——infra 同步錯誤，進料非設計"
                              "判決。不入 repair queue；archive-only。"),
    "SYNTH_THRESHOLD": ("題目 harness 要求合成品質門檻（cell/wire 縮減比例）"
                        "——RTL 可合成但未達門檻，屬真實優化缺口；重讀 prompt "
                        "的優化目標再重構"),
}

_SYNTH_RE = re.compile(r"KeyError: 'Number of (cells|wires)'")
# Synthesis QUALITY-threshold failure (field round-2): the harness demands a
# cell/wire reduction the RTL synthesizes but does not meet — a real
# optimization gap, distinct from "did not synthesize".
_SYNTH_THRESHOLD_RE = re.compile(
    r"No upgrades in synthesis|Optimization failed", re.I)
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
# cocotb regression-summary row (field round-2 FLAGSHIP counter-evidence):
# `** TESTS=10 PASS=9 FAIL=1 SKIP=0 …` carries the per-test granularity the
# pytest bottom line hides (pytest wraps the whole cocotb run as ONE test, so
# its summary says "1 failed" even when 9/10 cocotb tests passed).
_COCOTB_SUMMARY_RE = re.compile(
    r"TESTS=(\d+)\s+PASS=(\d+)\s+FAIL=(\d+)", re.I)
_PYTEST_SUMMARY_RE = re.compile(
    r"=+\s*(\d+)\s+failed(?:,\s*(\d+)\s+passed)?[^=\n]*=+")


def classify_log(text: str) -> str:
    """Classify ONE report log's failure mode.

    FUNC_ALL is only ever returned on ZERO pass evidence across EVERY
    summary family (cocotb TESTS=, `Failed X of Y`, pytest bottom line) —
    the field round-2 flagship (`TESTS=10 PASS=9 FAIL=1` judged FUNC_ALL)
    pinned this requirement. A log with NO terminal verdict evidence at all
    is TRUNCATED (infra flakiness), not UNKNOWN."""
    if _SYNTH_RE.search(text):
        return "SYNTH_GATE"
    if _SYNTH_THRESHOLD_RE.search(text):
        return "SYNTH_THRESHOLD"
    # aggregate pass/fail evidence across ALL three summary families
    fail_ev = pass_ev = 0
    verdict_seen = False
    for m in _COCOTB_SUMMARY_RE.finditer(text):
        verdict_seen = True
        pass_ev += int(m.group(2))
        fail_ev += int(m.group(3))
    for m in _FAILED_OF_RE.finditer(text):
        verdict_seen = True
        failed, total = int(m.group(1)), int(m.group(2))
        fail_ev += failed
        pass_ev += max(0, total - failed)
    for m in _PYTEST_SUMMARY_RE.finditer(text):
        verdict_seen = True
        fail_ev += int(m.group(1))
        pass_ev += int(m.group(2) or 0)
    if fail_ev and pass_ev:
        return "FUNC_PARTIAL"
    # compile-step kill: anchored evidence AND no test-level verdict ran
    if _ELAB_RE.search(text) and not (_COCOTB_SUMMARY_RE.search(text)
                                      or _FAILED_OF_RE.search(text)):
        return "ELAB_ERROR"
    if fail_ev:
        return "FUNC_ALL"
    if not verdict_seen:
        return "TRUNCATED"
    return "UNKNOWN"


def _load_passrate_map(path: Optional[Path]) -> Optional[Dict[str, bool]]:
    """Return a `{pid: pass_bool}` map if `path` is provided and parseable.

    Accepts either the v1.2.45 `cvdp_gate.py` `passrate.json` shape
    (`{pid: {"pass": true/false, ...}}` or `{pid: true/false}`) or a
    flat `score.json` (`{pid: score}` where `score >= 1.0` ⇒ pass).
    Returns `None` when `path` is None — the canonical TRIAGE behavior
    is unchanged in that case (no leak)."""
    if path is None:
        return None
    if not path.is_file():
        print(f"WARN: passrate-json not found: {path} — pass-aware "
              f"demotion off", file=sys.stderr)
        return None
    try:
        data = json.loads(path.read_text(errors="replace"))
    except json.JSONDecodeError as e:
        print(f"WARN: bad passrate-json: {e}", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        return None
    out: Dict[str, bool] = {}
    for k, v in data.items():
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, dict):
            if "pass" in v:
                out[k] = bool(v["pass"])
            elif "score" in v:
                try:
                    out[k] = float(v["score"]) >= 1.0
                except Exception:
                    pass
            elif "result" in v:
                out[k] = bool(v["result"]) in (0, "0")
        elif isinstance(v, (int, float)):
            out[k] = float(v) >= 1.0
    return out


def triage(raw: Dict, reports_root: Optional[Path],
           passrate_map: Optional[Dict[str, bool]] = None) -> List[Dict]:
    """Walk raw_result.json; classify every problem with ≥1 failing test.

    PROBLEM-LEVEL pass evidence (field round-2): the failing tests' logs
    alone CANNOT prove partiality — the passing invocations' evidence lives
    in raw_result itself (tests[].result == 0). A problem with passing
    sibling tests is FUNC_PARTIAL by definition ("some hidden tests pass,
    some fail"), regardless of what the failing log says — except the
    synth-gate classes (the harness quality gate is its own axis).

    v1.2.46: pass-aware TRUNCATED demotion — when `passrate_map` is
    provided and `pid` is in the pass-list, a record whose local
    classification would have been `TRUNCATED` is demoted to
    `TRUNCATED_BUT_PASSED`. This does NOT change verdict counts
    (headline passrate is `passrate.json`'s job); it ONLY removes
    legitimate-but-truncated problems from the close-loop repair queue.
    Such a demoted record is NOT a fail mode — recorded only for audit
    next-layer visibility. Pass-aware demotion is a no-op when
    passrate_map is None — older callers get exactly the v1.2.45
    behavior with zero drift."""
    out: List[Dict] = []
    pass_demoted = 0
    for pid, info in sorted(raw.items()):
        tests = info.get("tests") or []
        failing = [t for t in tests if t.get("result") not in (0, "0", None)]
        passing = [t for t in tests if t.get("result") in (0, "0")]
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
        # a missing/empty log for a recorded FAIL is itself the truncated
        # shape (no verdict ever landed), not "unclassifiable".
        mode = classify_log(blob) if blob.strip() else "TRUNCATED"
        if passing and mode in ("FUNC_ALL", "ELAB_ERROR", "UNKNOWN"):
            mode = "FUNC_PARTIAL"
        # v1.2.46: pass-aware demotion of pure-TRUNCATED records
        is_pass_in_passrate = (
            passrate_map is not None
            and passrate_map.get(pid) is True)
        if mode == "TRUNCATED" and is_pass_in_passrate:
            mode = "TRUNCATED_BUT_PASSED"
            pass_demoted += 1
        out.append({"id": pid, "mode": mode, "blind_safe_hint": HINTS[mode]})
    # The first element of the returned list is normally the records;
    # the second is the audit-only demotion counter. To preserve the
    # v1.2.45 `List[Dict]` signature, attach the counter to the records
    # by reading it externally — but the cleaner approach is to return
    # a small dataclass. Without changing the public shape, we surface
    # the count via a separate keyword in `main()` only — the
    # regression test pins the v1.2.45 (records-only) shape, so
    # returning `records` from the function is unchanged.
    if pass_demoted:
        # Stash on the dict subclass so `main()` can read it without
        # altering `List[Dict]` typing. Returns can be `(records, count)`
        # if we want — but to keep BC we encode on a `__pass_demoted__`
        # attribute on the returned list (a list subclass is overkill).
        out_pass_demoted_marker = getattr(triage, "_last_pass_demoted", 0)
        triage._last_pass_demoted = (out_pass_demoted_marker
                                      if out_pass_demoted is None
                                      else out_pass_demoted)
    else:
        triage._last_pass_demoted = getattr(
            triage, "_last_pass_demoted", 0)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="CVDP fail-mode triage (mechanical, blind-safe) — #534.")
    ap.add_argument("--raw", required=True, help="scorer raw_result.json")
    ap.add_argument("--reports", default=None,
                    help="work dir root for log-path rebase (optional)")
    ap.add_argument("--passrate-json", default=None,
                    help="optional passrate.json — TRUNCATED records with a "
                         "recorded PASS are demoted to TRUNCATED_BUT_PASSED "
                         "(audit-only; never blocks)")
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
    passrate_map = _load_passrate_map(
        Path(args.passrate_json) if args.passrate_json else None)
    records = triage(raw, reports_root, passrate_map=passrate_map)
    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    summary = {}
    for r in records:
        summary[r["mode"]] = summary.get(r["mode"], 0) + 1
    pass_demoted = summary.get("TRUNCATED_BUT_PASSED", 0)
    import _atomic_artefact as _atomic  # noqa: PLC0415
    _atomic.write_json(outp, {"total_fails": len(records),
                              "mode_summary": summary,
                              "pass_demoted_truncated": pass_demoted,
                              "records": records})
    print(f"verify_fail_triage: {len(records)} fail(s) classified "
          f"{summary}"
          + (f" (truncated→pass_demoted: {pass_demoted})"
             if pass_demoted else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
