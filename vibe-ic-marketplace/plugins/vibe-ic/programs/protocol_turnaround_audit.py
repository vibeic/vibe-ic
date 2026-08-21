"""v0.1.50 — Half-duplex protocol turnaround audit (Type-A extraction).

Doctrine: the user's 2026-05-29 audit flagged `skills/protocol-turnaround-audit/`
as a textbook Type-A violation — 100% deterministic algorithm (grep
regex catalog + state-machine walk + a ceiling formula) was sitting in
SKILL.md asking an LLM to apply it by reading prose. This program
moves the entire algorithm to tool-space; the skill is retired.

Algorithm (verbatim from the former SKILL.md § 1–4)
===================================================

  Step 1 — Identify TX-start signals:
    /tx.?start|tx.?req|resp.?start|reply.?start|drv.?en/i

  Step 2 — Identify RX-completion triggers:
    /rx.?done|.?delim.?seen|.?eof|cmd.?valid|frame.?complete|trailing.?(br|delim)/i

  Step 3 — Compute path length (state-machine walk, backward):
    minimum number of state transitions between RX-completion trigger
    and TX-start assertion.

  Step 4 — Compare against L2 timing:
    min_safe_cycles = ceil((delimiter_max - delimiter_detect_threshold
                           + t_turnaround_min) / clock_period)
    path_length < min_safe_cycles  →  ERROR

Inputs
======

  --rtl-dir       — directory of .v/.sv (recursive)
  --l2-json       — L2 timing JSON (or L8_TIMING_WAVEFORM.json)
  --clock-period-ns — fabric clock period in ns

Outputs
=======

  Markdown report (matches SKILL.md § Output template) AND
  JSON report (machine readable for downstream gating).
  Per-finding verdict: PASS | ERROR.

Unit tests
==========

  programs/tests/test_protocol_turnaround_audit.py
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


# ---------------------------------------------------------------------------
# Regex catalogs — verbatim from the retired skill
# ---------------------------------------------------------------------------
TX_START_RE = re.compile(
    r"\b(tx[._]?start|tx[._]?req|resp[._]?start|reply[._]?start|drv[._]?en)\b",
    re.IGNORECASE,
)
RX_TRIGGER_RE = re.compile(
    r"\b(rx[._]?done|[a-z_]*delim[._]?seen|[a-z_]*eof|"
    r"cmd[._]?valid|frame[._]?complete|trailing[._]?(?:br|delim))\b",
    re.IGNORECASE,
)


# L2 timing JSON field-name catalogs — keys we accept on read.
DELIMITER_MAX_KEYS = (
    "delimiter_max_duration", "delimiter_max", "BR_max", "break_max",
    "trailing_delimiter_max", "br_max_ns",
)
DELIMITER_DETECT_KEYS = (
    "delimiter_detect_threshold", "delim_detect_threshold",
    "break_detect_threshold",
)
TURNAROUND_MIN_KEYS = (
    "t_turnaround_min", "turnaround_min", "tSRS_min",
    "tResponseDelay_min", "tBusGuard_min", "reply_gap_min",
    "t_turnaround.min_ns", "turnaround.min_ns",
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class TxStartHit:
    """One hit from grep-step 1 (a TX-start signal assignment)."""
    file: str
    line: int
    signal: str
    line_text: str


@dataclass
class RxTriggerHit:
    """One hit from grep-step 2 (an RX-completion trigger)."""
    file: str
    line: int
    signal: str
    line_text: str


@dataclass
class AuditFinding:
    """One audit verdict for a (tx_start, rx_trigger) pair."""
    tx_file: str
    tx_line: int
    tx_signal: str
    rx_signal: str
    path_length_cycles: int
    min_safe_cycles: int
    verdict: str         # PASS | ERROR | UNKNOWN
    notes: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuditReport:
    rtl_dir: str
    files_scanned: List[str]
    l2_json_path: str
    clock_period_ns: float
    parameters: Dict[str, Any]   # extracted L2 timing values
    findings: List[AuditFinding]
    error_count: int
    pass_count: int
    unknown_count: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rtl_dir": self.rtl_dir,
            "files_scanned": self.files_scanned,
            "l2_json_path": self.l2_json_path,
            "clock_period_ns": self.clock_period_ns,
            "parameters": self.parameters,
            "findings": [f.as_dict() for f in self.findings],
            "error_count": self.error_count,
            "pass_count": self.pass_count,
            "unknown_count": self.unknown_count,
            "verdict": "ERROR" if self.error_count else "PASS",
            "emitted_by": _pmd.emitted_by("protocol_turnaround_audit"),
        }


# ---------------------------------------------------------------------------
# Step 1 + Step 2 — grep
# ---------------------------------------------------------------------------
ASSIGN_RE = re.compile(
    r"(?P<signal>[A-Za-z_][A-Za-z0-9_]*)\s*(?:<=|=)\s*[^=;]+",
)


def grep_tx_starts(rtl_files: List[Path]) -> List[TxStartHit]:
    hits: List[TxStartHit] = []
    for f in rtl_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in ASSIGN_RE.finditer(line):
                signal = m.group("signal")
                if TX_START_RE.search(signal):
                    hits.append(TxStartHit(
                        file=str(f), line=lineno,
                        signal=signal, line_text=line.strip()))
                    break
    return hits


def grep_rx_triggers(rtl_files: List[Path]) -> List[RxTriggerHit]:
    hits: List[RxTriggerHit] = []
    for f in rtl_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in RX_TRIGGER_RE.finditer(line):
                # Skip pure comments
                if re.match(r"^\s*(?://|/\*)", line):
                    continue
                signal = m.group(0)
                hits.append(RxTriggerHit(
                    file=str(f), line=lineno,
                    signal=signal, line_text=line.strip()))
    return hits


# ---------------------------------------------------------------------------
# Step 3 — state-machine path length (heuristic; matches the skill's note)
# ---------------------------------------------------------------------------
STATE_TRANS_RE = re.compile(
    r"\bstate\s*(?:<=|=)\s*(?P<target>[A-Za-z_][A-Za-z0-9_]*)",
)


def estimate_path_length(rtl_text: str,
                          rx_trigger_signal: str,
                          tx_start_signal: str) -> Optional[int]:
    """Count state transitions between an RX trigger and a TX start.

    Heuristic per the retired skill: count `state <= NEXT_STATE`
    assignments that appear between an `rx_trigger_signal`-mentioning
    line and a `tx_start_signal`-mentioning line, in source order.
    Returns None when the structure is too irregular for the heuristic.
    """
    lines = rtl_text.splitlines()
    rx_lines = [i for i, l in enumerate(lines) if rx_trigger_signal in l]
    tx_lines = [i for i, l in enumerate(lines) if tx_start_signal in l]
    if not rx_lines or not tx_lines:
        return None
    # The simplest worst-case path: count state assignments between the
    # FIRST rx-trigger mention and the FIRST tx-start mention.
    rx0 = min(rx_lines)
    # Allow same-line (direct combinational assertion): path length is 0
    # if rx-trigger and tx-start appear on the same line.
    tx_candidates = [i for i in tx_lines if i >= rx0]
    if not tx_candidates:
        return None
    tx0 = min(tx_candidates)
    if tx0 == rx0:
        return 0
    region = "\n".join(lines[rx0:tx0])
    transitions = len(STATE_TRANS_RE.findall(region))
    return transitions


# ---------------------------------------------------------------------------
# Step 4 — min_safe_cycles computation (the verbatim ceiling formula)
# ---------------------------------------------------------------------------
def _lookup(data: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[float]:
    """Walk a possibly-nested dict looking for any of `keys`."""
    if not isinstance(data, dict):
        return None
    for k in keys:
        if "." in k:
            head, tail = k.split(".", 1)
            if head in data and isinstance(data[head], dict):
                inner = _lookup(data[head], (tail,))
                if inner is not None:
                    return inner
        elif k in data:
            v = data[k]
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, dict):
                # try .ns / .typical / .min
                for inner_k in ("min_ns", "ns", "typical_ns", "max_ns", "value"):
                    if inner_k in v and isinstance(v[inner_k], (int, float)):
                        return float(v[inner_k])
    # Recursive walk for nested objects
    for v in data.values():
        if isinstance(v, dict):
            r = _lookup(v, keys)
            if r is not None:
                return r
    return None


def extract_l2_parameters(l2_data: Dict[str, Any]) -> Dict[str, Any]:
    """Surface the three numbers the formula needs from L2 JSON.

    Returns {delimiter_max_ns, delimiter_detect_ns, t_turnaround_min_ns}.
    Any missing value is None (caller emits UNKNOWN verdict).
    """
    return {
        "delimiter_max_ns": _lookup(l2_data, DELIMITER_MAX_KEYS),
        "delimiter_detect_ns": _lookup(l2_data, DELIMITER_DETECT_KEYS),
        "t_turnaround_min_ns": _lookup(l2_data, TURNAROUND_MIN_KEYS),
    }


def compute_min_safe_cycles(
    delimiter_max_ns: float,
    delimiter_detect_ns: float,
    t_turnaround_min_ns: float,
    clock_period_ns: float,
) -> int:
    """The verbatim formula from the retired skill.

    min_safe = ceil(
      (delimiter_max - delimiter_detect_threshold + t_turnaround_min)
      / clock_period)
    """
    if clock_period_ns <= 0:
        raise ValueError("clock_period_ns must be > 0")
    budget_ns = delimiter_max_ns - delimiter_detect_ns + t_turnaround_min_ns
    if budget_ns < 0:
        budget_ns = 0
    return int(math.ceil(budget_ns / clock_period_ns))


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def audit_rtl_dir(
    rtl_dir: Path,
    l2_json: Path,
    clock_period_ns: float,
) -> AuditReport:
    rtl_files = sorted(
        [p for p in rtl_dir.rglob("*")
         if p.suffix in (".v", ".sv") and p.is_file()])

    l2_data: Dict[str, Any] = {}
    if l2_json.exists():
        try:
            l2_data = json.loads(l2_json.read_text(encoding="utf-8"))
        except Exception:
            l2_data = {}

    params = extract_l2_parameters(l2_data)

    if (params["delimiter_max_ns"] is not None
            and params["delimiter_detect_ns"] is not None
            and params["t_turnaround_min_ns"] is not None):
        min_safe_cycles = compute_min_safe_cycles(
            params["delimiter_max_ns"],
            params["delimiter_detect_ns"],
            params["t_turnaround_min_ns"],
            clock_period_ns,
        )
    else:
        min_safe_cycles = -1  # unknown sentinel

    tx_starts = grep_tx_starts(rtl_files)
    rx_triggers = grep_rx_triggers(rtl_files)

    findings: List[AuditFinding] = []
    for tx in tx_starts:
        try:
            rtl_text = Path(tx.file).read_text(
                encoding="utf-8", errors="replace")
        except Exception:
            rtl_text = ""

        best_rx: Optional[RxTriggerHit] = None
        path_length: Optional[int] = None
        for rx in rx_triggers:
            if rx.file != tx.file:
                continue
            pl = estimate_path_length(rtl_text, rx.signal, tx.signal)
            if pl is not None:
                if path_length is None or pl < path_length:
                    path_length = pl
                    best_rx = rx

        rx_signal = best_rx.signal if best_rx else "<not found>"

        if path_length is None or min_safe_cycles < 0:
            verdict = "UNKNOWN"
            notes = ("path length not determinable" if path_length is None
                     else "L2 timing parameters missing")
            findings.append(AuditFinding(
                tx_file=tx.file, tx_line=tx.line, tx_signal=tx.signal,
                rx_signal=rx_signal,
                path_length_cycles=path_length or 0,
                min_safe_cycles=max(0, min_safe_cycles),
                verdict=verdict, notes=notes))
            continue

        if path_length < min_safe_cycles:
            verdict = "ERROR"
            notes = (f"turnaround {path_length} cycles "
                     f"< {min_safe_cycles} cycles minimum")
        else:
            verdict = "PASS"
            notes = (f"turnaround {path_length} cycles "
                     f">= {min_safe_cycles} cycles minimum")
        findings.append(AuditFinding(
            tx_file=tx.file, tx_line=tx.line, tx_signal=tx.signal,
            rx_signal=rx_signal,
            path_length_cycles=path_length,
            min_safe_cycles=min_safe_cycles,
            verdict=verdict, notes=notes))

    error_count = sum(1 for f in findings if f.verdict == "ERROR")
    pass_count = sum(1 for f in findings if f.verdict == "PASS")
    unknown_count = sum(1 for f in findings if f.verdict == "UNKNOWN")

    return AuditReport(
        rtl_dir=str(rtl_dir),
        files_scanned=[str(p.relative_to(rtl_dir)) for p in rtl_files],
        l2_json_path=str(l2_json),
        clock_period_ns=clock_period_ns,
        parameters=params,
        findings=findings,
        error_count=error_count,
        pass_count=pass_count,
        unknown_count=unknown_count,
    )


# ---------------------------------------------------------------------------
# Markdown emit (matches the retired skill's § Output template)
# ---------------------------------------------------------------------------
def report_to_markdown(rep: AuditReport) -> str:
    out: List[str] = []
    out.append(f"# Protocol turnaround audit — {rep.rtl_dir or 'unspecified'}")
    out.append("")
    out.append(
        f"_Emitted by `protocol_turnaround_audit.py` "
        f"(Vibe-IC plugin v{_pmd.running_plugin_version()}). Algorithm "
        f"verbatim from the retired "
        f"`atpg-name-harmonize`-style skill; refuse to overclaim the "
        f"verdict._")
    out.append("")
    out.append("## Summary")
    out.append("")
    out.append(f"- ERROR : {rep.error_count}")
    out.append(f"- PASS  : {rep.pass_count}")
    out.append(f"- UNKNOWN: {rep.unknown_count}")
    out.append(f"- L2 parameters: {rep.parameters}")
    out.append(f"- clock_period_ns: {rep.clock_period_ns}")
    out.append("")
    out.append("## Findings")
    out.append("")
    for f in rep.findings:
        out.append(f"### `{f.tx_signal}` @ `{f.tx_file}:{f.tx_line}`")
        out.append("")
        out.append(f"- RX trigger : `{f.rx_signal}`")
        out.append(f"- Path length: {f.path_length_cycles} cycles")
        out.append(f"- Min safe   : {f.min_safe_cycles} cycles")
        out.append(f"- Verdict    : **{f.verdict}**")
        if f.notes:
            out.append(f"- Notes      : {f.notes}")
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cli() -> int:
    p = argparse.ArgumentParser(
        description="Half-duplex protocol turnaround audit "
                    "(deterministic; retired skills/protocol-turnaround-audit).")
    p.add_argument("--rtl-dir", type=Path, required=True)
    p.add_argument("--l2-json", type=Path, required=True)
    p.add_argument("--clock-period-ns", type=float, required=True)
    p.add_argument("--out-md", type=Path)
    p.add_argument("--out-json", type=Path)
    p.add_argument("--strict", action="store_true",
                   help="Exit non-zero if any ERROR")
    args = p.parse_args()

    if not args.rtl_dir.exists():
        print(f"rtl-dir does not exist: {args.rtl_dir}", file=sys.stderr)
        return 2

    rep = audit_rtl_dir(args.rtl_dir, args.l2_json, args.clock_period_ns)
    md = report_to_markdown(rep)
    if args.out_md:
        args.out_md.write_text(md, encoding="utf-8")
    else:
        print(md)
    if args.out_json:
        args.out_json.write_text(
            json.dumps(rep.as_dict(), indent=2), encoding="utf-8")

    if args.strict and rep.error_count > 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
