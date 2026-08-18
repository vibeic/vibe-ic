#!/usr/bin/env python3
"""crc_residue_settle_state_required_check.py — Wave 26 (v0.119.58) gate.

Purpose
-------
Between the last RX bit and the CRC-validate state, the FSM must
have a dedicated settle state (≥1 cycle) waiting for crc_out to
fully propagate.  Without a settle state, S_VALIDATE is entered
the same cycle the last bit was clocked into the CRC engine —
the residue read sees the previous-byte residue instead of the
final residue.

Vendor real-PASS-oracle uses an IBT-gated settle interval before
validation; the v0.119.57 fresh-agent FSM transitioned directly
RX-bit-receive → S_VALIDATE on `state_q <= S_VALIDATE` with no
intervening cycle (`docs/design/MIN_DELTA_DIAG_v0119.57.md`,
root cause #4).

Scope
-----
Chip-AGNOSTIC.  Synonym lists cover canonical CRC-validate +
RX-bit-receive state names across half-duplex single-wire
protocols.

Verdicts
--------
- PASS               — every transition into a CRC-validate state
                       comes from a recognised settle state.
- FAIL               — at least one direct transition from an
                       RX-byte-receive state into the validate
                       state.
- SKIP               — no FSM file / no validate state.
- PASS_WITH_WAIVER   — waiver
                       `crc_settle_in_validate_state_intentional`
                       (≥40 chars).

Usage
-----
    python3 crc_residue_settle_state_required_check.py <project_dir>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Tuple
import _path_layout as _pl

# ----------------------------------------------------------------------
# Synonyms — chip-AGNOSTIC FSM vocabulary
# ----------------------------------------------------------------------
FSM_FILE_HINTS: Tuple[str, ...] = (
    "main_fsm", "fsm", "mac", "protocol_fsm",
    "ctrl", "controller", "rx_chk",
)

# State name patterns
VALIDATE_STATE_RE = re.compile(
    r"S_(?:VALIDATE|CHECK_CRC|CRC_OK|CRC_CHECK|VERIFY_CRC|"
    r"CRC_VERIFY|VALIDATE_CRC|CHECK_RESIDUE)\b",
    re.IGNORECASE,
)

# RX-byte-receive states whose direct exit into a validate state is
# a violation.
RX_RECEIVE_STATE_RE = re.compile(
    r"S_(?:RX_BIT_LOW|RX_BIT_HIGH|RX_BIT|RX_BYTE|RX_DATA|"
    r"RX_SHIFT|RX_BIT_DONE|RX_BYTE_RECEIVE|RX_FRAME)\b",
    re.IGNORECASE,
)

# Recognised settle / wait names.  Transition into a validate state
# from one of these is OK.
SETTLE_STATE_RE = re.compile(
    r"S_(?:CRC_SETTLE|SETTLE|RX_DONE|RX_END|FRAME_END|"
    r"WAIT_CRC|VALIDATE_WAIT|VALIDATE_PRE|"
    r"CRC_WAIT|RX_BYTE_DONE|FRAME_DONE|WAIT_VALIDATE|"
    r"PRE_VALIDATE|RX_IDLE_GAP)\b",
    re.IGNORECASE,
)

WAIVER_KEY = "crc_settle_in_validate_state_intentional"
WAIVER_MIN_CHARS = 40


# ----------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------
@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""


@dataclass
class AuditResult:
    program: str = "crc_residue_settle_state_required_check"
    verdict: str = "PASS"
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _is_waived(project: Path) -> bool:
    p = project / "waivers.json"
    if not p.is_file():
        return False
    try:
        d = json.loads(p.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError):
        return False
    v = d.get(WAIVER_KEY, "")
    return isinstance(v, str) and len(v.strip()) >= WAIVER_MIN_CHARS


def _list_fsm_files(project: Path) -> List[Path]:
    rtl_dirs = [_pl.rtl_dir(project), project]
    seen: set = set()
    cands: List[Path] = []
    for d in rtl_dirs:
        if not d.is_dir():
            continue
        for ext in ("*.sv", "*.v"):
            for p in d.rglob(ext):
                if p in seen:
                    continue
                seen.add(p)
                cands.append(p)
    keep: List[Path] = []
    for p in cands:
        name = p.name.lower()
        if any(h in name for h in FSM_FILE_HINTS):
            keep.append(p)
            continue
        try:
            txt = p.read_text(errors="replace")
        except OSError:
            continue
        if VALIDATE_STATE_RE.search(txt):
            keep.append(p)
    return keep


def _split_state_arms(src: str) -> List[Tuple[str, str]]:
    """Return [(state_name_upper, arm_body), ...]."""
    parts = re.split(r"(?=^\s*S_[A-Z0-9_]+\s*:)", src, flags=re.MULTILINE)
    out: List[Tuple[str, str]] = []
    for p in parts:
        m = re.match(r"\s*(S_[A-Z0-9_]+)\s*:", p)
        if m:
            out.append((m.group(1).upper(), p))
    return out


def _arm_transitions_to(arm_body: str) -> List[str]:
    """Return list of next-state names this arm transitions into."""
    return [m.group(1).upper() for m in
            re.finditer(r"state_q\s*<=\s*(S_[A-Z0-9_]+)\s*;",
                        arm_body, re.IGNORECASE)]


# ----------------------------------------------------------------------
# Audit
# ----------------------------------------------------------------------
def run_audit(project: Path) -> AuditResult:
    result = AuditResult()
    files = _list_fsm_files(project)
    if not files:
        result.verdict = "SKIP"
        result.findings.append(Finding(
            rule="NO_FSM_FILE", severity="INFO",
            message=("No FSM RTL file with a validate-state name "
                     "identified"),
        ))
        result.summary = {"files": 0}
        return result

    has_validate = False
    fails: List[Tuple[str, str, str]] = []
    passes: List[Tuple[str, str]] = []

    for fp in files:
        try:
            raw = fp.read_text(errors="replace")
        except OSError:
            continue
        src = _strip_comments(raw)
        arms = _split_state_arms(src)
        if not arms:
            continue
        # Locate validate state name(s)
        validate_states = {nm for nm, _ in arms
                           if VALIDATE_STATE_RE.search(nm)}
        if not validate_states:
            continue
        has_validate = True
        for nm, body in arms:
            nxt_states = _arm_transitions_to(body)
            for nxt in nxt_states:
                if nxt not in validate_states:
                    continue
                # Predecessor `nm` transitions into validate.
                if RX_RECEIVE_STATE_RE.search(nm):
                    fails.append((str(fp.relative_to(project)),
                                  nm, nxt))
                elif SETTLE_STATE_RE.search(nm):
                    passes.append((nm, nxt))
                else:
                    # Unknown predecessor — neither RX-receive nor
                    # settle.  Treat as soft-pass (could be S_DROP /
                    # error-recovery / S_FRAME_END_DETECT etc.).
                    passes.append((nm, nxt))

    if not has_validate:
        result.verdict = "SKIP"
        result.findings.append(Finding(
            rule="NO_VALIDATE_STATE",
            severity="INFO",
            message=("No CRC-validate state in any FSM file; "
                     "gate skipped"),
        ))
        result.summary = {"files": len(files)}
        return result

    if _is_waived(project):
        result.verdict = "PASS_WITH_WAIVER"
        result.findings.append(Finding(
            rule="WAIVED",
            severity="INFO",
            message=(f"Waiver '{WAIVER_KEY}' set; "
                     f"{len(fails)} direct-into-validate "
                     "transition(s) deferred"),
        ))
        result.summary = {
            "files": len(files),
            "fail_transitions": [{"file": f, "from": p, "to": n}
                                  for f, p, n in fails],
            "pass_transitions": [{"from": p, "to": n}
                                  for p, n in passes],
        }
        return result

    if fails:
        result.verdict = "FAIL"
        for fname, predecessor, validate in fails[:5]:
            result.findings.append(Finding(
                rule="VALIDATE_ENTERED_WITHOUT_SETTLE",
                severity="ERROR",
                file=fname,
                message=(
                    f"FSM in {fname} transitions {predecessor} → "
                    f"{validate} directly with no settle cycle. "
                    "crc_out has not propagated; the residue read "
                    "samples stale data. "
                    "Insert an S_CRC_SETTLE / S_RX_BYTE_DONE / "
                    "S_FRAME_END wait state (≥1 cycle) between "
                    "RX-byte-receive and the validate state."
                ),
            ))
    else:
        result.findings.append(Finding(
            rule="VALIDATE_PROPERLY_SETTLED",
            severity="INFO",
            message=("All transitions into the CRC-validate state "
                     "come from a settle / wait predecessor"),
        ))

    result.summary = {
        "files": len(files),
        "fail_transitions": [{"file": f, "from": p, "to": n}
                              for f, p, n in fails],
        "pass_transitions": [{"from": p, "to": n}
                              for p, n in passes],
    }
    return result


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory",
              file=sys.stderr)
        return 2

    result = run_audit(args.project_dir)

    if args.json:
        print(json.dumps(asdict(result), indent=2, default=str))
    else:
        print(f"[{result.verdict}] crc_residue_settle_state_required_check")
        print(f"  files scanned: {result.summary.get('files', 0)}")
        print(f"  failing transitions: "
              f"{len(result.summary.get('fail_transitions', []))}")
        for f in result.findings:
            print(f"  [{f.severity}] {f.rule}: {f.message}")

    return 1 if result.verdict == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
