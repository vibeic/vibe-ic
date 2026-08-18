#!/usr/bin/env python3
"""rx_byte_valid_requires_ibt_gate_check.py — Wave 26 (v0.119.58) gate.

Purpose
-------
In a half-duplex single-wire RX path the per-byte completion strobe
(`byte_valid` / `byte_complete` / `rx_byte_strobe`) MUST be gated on
an inter-byte-time (IBT) settle counter — not just on
`bit_idx == 8` / final-bit detection.  When the strobe fires
purely on bit-count, the chip latches the byte before the line has
quiesced for the IBT window: a host-side trailing transition / EMI
edge / host re-arm pulse leaks into the next byte's first bit and
shifts the receive frame by 200+ ticks.

Vendor real-PASS-oracle (`RX_PHY.v:686`) gates byte_valid on
`rx_data_byte_valid_2p5m` which fires only after a full IBT_MIN
HIGH window (≥234 ticks @ 50 MHz).  Surfaced by the v0.119.57
diagnosis (`docs/design/MIN_DELTA_DIAG_v0119.57.md`, root cause #2).

Scope
-----
Chip-AGNOSTIC.  We only look at synonym-named signals and signals
that match generic protocol-FSM vocabulary.  No vendor / chip /
PDK-specific identifier hard-coded.

Verdicts
--------
- PASS               — byte_valid emit references an IBT counter ≥
                       an IBT_MIN-class threshold.
- FAIL               — byte_valid emit triggers purely on
                       bit_idx-class equality with no IBT gate.
- SKIP               — no RX assembler / no byte_valid signal found.
- PASS_WITH_WAIVER   — waiver
                       `rx_byte_valid_no_ibt_gate_intentional`
                       (≥40 chars).

Usage
-----
    python3 rx_byte_valid_requires_ibt_gate_check.py <project_dir>
    python3 rx_byte_valid_requires_ibt_gate_check.py <project_dir> --json
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

# Kimi-scale fix — the assembler-file discovery audits AUTHORED RTL SOURCE.
# It routes through the shared collector (canonical phase2/stage1/rtl
# preferred; generated netlist/sim/verify outputs + >8MB files excluded on
# fallback) so a 342 MB emitted netlist can never enter the body-heuristic
# read_text scan again (see _specrtl_common.rtl_source_files for the full
# scale rationale). The gate's OTHER inputs — phase1/generated_docs L2*/L8*
# JSON, waivers.json, and the rtl_dir-only inout-id_bus cross-check — are
# untouched.
try:
    from _specrtl_common import rtl_source_files
except ImportError:                      # packaged relative import
    from ._specrtl_common import rtl_source_files

# ----------------------------------------------------------------------
# Synonyms — generic vocabulary
# ----------------------------------------------------------------------
ASSEMBLER_FILE_HINTS: Tuple[str, ...] = (
    "bit_assembler", "rx_chk", "rx_assembler",
    "byte_assembler", "rx_byte", "rx_phy",
    "phy_rx", "rx_classifier", "main_fsm",
    "mac", "protocol_fsm", "id_phy",
)

BYTE_STROBE_NAMES: Tuple[str, ...] = (
    "byte_valid", "byte_complete", "rx_byte_strobe",
    "rx_byte_vld", "byte_done", "rx_byte_done",
    "byte_strobe", "rx_data_byte_valid",
    # Functionally-equivalent strobes that are the byte commit:
    # CRC-feed pulse, byte-buffer write, byte-counter increment guards.
    "crc_feed_vld", "crc_feed_valid", "crc_feed_pulse",
    "rx_byte_we", "byte_we",
)

IBT_COUNTER_HINTS = re.compile(
    r"\b(ibt[_a-z0-9]*|inter[_a-z0-9]*bit[_a-z0-9]*|gap_cnt[a-z0-9_]*|"
    r"high_cnt[a-z0-9_]*|rx_high_cnt[a-z0-9_]*|idle_cnt[a-z0-9_]*|"
    r"ibg_cnt[a-z0-9_]*|inter_byte[_a-z0-9]*|byte_gap[_a-z0-9]*)\b",
    re.IGNORECASE,
)

IBT_THRESHOLD_HINTS = re.compile(
    r"\b(IBT_MIN[A-Z0-9_]*|T_IBT[A-Z0-9_]*|INTER_BYTE_MIN[A-Z0-9_]*|"
    r"BYTE_GAP_MIN[A-Z0-9_]*|GAP_MIN[A-Z0-9_]*|RX_IBT[A-Z0-9_]*|"
    r"T_GAP_MIN[A-Z0-9_]*)\b",
)

BIT_IDX_HINTS = re.compile(
    r"\b(bit_idx[a-z0-9_]*|bit_count[a-z0-9_]*|bit_cnt[a-z0-9_]*|"
    r"rx_bit_idx[a-z0-9_]*|rx_bit_cnt[a-z0-9_]*)\b",
    re.IGNORECASE,
)

WAIVER_KEY = "rx_byte_valid_no_ibt_gate_intentional"
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
    program: str = "rx_byte_valid_requires_ibt_gate_check"
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


_NON_AID_PROTO_TOKENS: Tuple[str, ...] = (
    "spi", "i2c", "uart", "rs_232", "rs232", "smbus", "lin",
    "kwp2000", "kwp_2000", "k_line", "kline", "iso14230",
    "iso_14230", "iso9141", "fast_init",
)


def _l2_protocol_blob(project: Path) -> str:
    """Return concatenated lower-case L2 protocol/interface text."""
    for sub in ("phase1/generated_docs", "generated_docs", "l_docs"):
        d = project / sub
        if not d.is_dir():
            continue
        for cand in sorted(d.glob("L2*.json")):
            try:
                j = json.loads(cand.read_text(errors="ignore"))
            except Exception:
                continue
            parts: list = []
            for path in (
                ("protocol_type",),
                ("protocol",),
                ("interface_type",),
                ("frs_doc", "protocol_type"),
                ("frs_doc", "interface"),
                ("physical_layer", "interface"),
            ):
                cur: object = j
                ok = True
                for k in path:
                    if isinstance(cur, dict) and k in cur:
                        cur = cur[k]
                    else:
                        ok = False
                        break
                if ok and isinstance(cur, str) and cur:
                    parts.append(cur.lower())
            if parts:
                return " ".join(parts)
    return ""


def _l8_has_ibt(project: Path) -> bool:
    """Wave 36 — True iff any L8 doc mentions ibt_min / ibt_max /
    ibt_us in some form."""
    for sub in ("phase1/generated_docs", "generated_docs", "l_docs"):
        d = project / sub
        if not d.is_dir():
            continue
        for cand in sorted(d.glob("L8*.json")):
            try:
                txt = cand.read_text(errors="ignore").lower()
            except OSError:
                continue
            if "ibt_min" in txt or "ibt_max" in txt or "ibt_us" in txt:
                return True
    return False


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


def _discover_assembler_files(project: Path) -> List[Path]:
    # Kimi-scale fix: the old [rtl_dir, project] dual rglob unioned the whole
    # project tree in (emitted netlists included). The shared collector keeps
    # the same effective candidate set — canonical phase2/stage1/rtl when it
    # exists (which the old rtl_dir pass already prioritised), else a
    # generated-output-excluded project scan.
    cands: List[Path] = rtl_source_files(project)
    keep: List[Path] = []
    for p in cands:
        name = p.name.lower()
        if any(h in name for h in ASSEMBLER_FILE_HINTS):
            keep.append(p)
            continue
        # body heuristic: contains a byte-strobe synonym
        try:
            txt = p.read_text(errors="replace")
        except OSError:
            continue
        if any(re.search(rf"\b{re.escape(s)}\b", txt)
               for s in BYTE_STROBE_NAMES):
            keep.append(p)
    return keep


def _find_strobe_assignments(src: str) -> List[Tuple[str, int, str]]:
    """Return (signal_name, char_offset, surrounding_block) for every
    NBA assignment to a byte-strobe synonym.  surrounding_block is the
    enclosing top-level if/case-arm body (best-effort by scanning back
    to the matching `if` / case-arm head)."""
    out: List[Tuple[str, int, str]] = []
    for sig in BYTE_STROBE_NAMES:
        pat = re.compile(
            rf"\b{re.escape(sig)}\s*<=\s*(?:1'b1|1'd1|1'h1|1)\s*[;,]",
        )
        for m in pat.finditer(src):
            start = max(0, m.start() - 800)
            end = min(len(src), m.end() + 200)
            block = src[start:end]
            out.append((sig, m.start(), block))
    return out


def _classify_block(block: str) -> Tuple[bool, bool]:
    """Return (has_ibt_gate, has_bit_idx_only).
    has_ibt_gate    — block references an IBT counter AND an IBT threshold.
    has_bit_idx_only — block references bit_idx-class signal but NO IBT
                       counter+threshold pair.
    """
    has_ibt_counter = bool(IBT_COUNTER_HINTS.search(block))
    has_ibt_thresh = bool(IBT_THRESHOLD_HINTS.search(block))
    has_ibt_gate = has_ibt_counter and has_ibt_thresh
    has_bit_idx = bool(BIT_IDX_HINTS.search(block))
    return has_ibt_gate, (has_bit_idx and not has_ibt_gate)


# ----------------------------------------------------------------------
# Audit
# ----------------------------------------------------------------------
def run_audit(project: Path) -> AuditResult:
    result = AuditResult()

    # Wave 36 (v0.119.68) — protocol_class guard.  This gate is
    # specific to AID-class half-duplex byte framing where IBT
    # (inter-byte time) is part of the protocol contract.  SPI /
    # UART / I2C do NOT have an IBT phase.  Skip when L2 declares
    # one of those AND L8 carries no ibt_min/ibt_max anchor.
    #
    # Wave 42 (v0.119.70) / SF4 — fault-injection hardening: before
    # SKIPping on non-AID protocol token, cross-check whether RTL
    # exposes an `inout id_bus` (AID-class hardware).  If so, FAIL
    # with a protocol-type / RTL inconsistency message instead of
    # silent SKIP — this catches faked L2.protocol_type='lin'/'kwp2000'
    # on an AID-class IC.
    proto_blob = _l2_protocol_blob(project)
    matched_non_aid = next(
        (tok for tok in _NON_AID_PROTO_TOKENS if tok in proto_blob),
        None,
    )
    if matched_non_aid is not None:
        # Compile an inout-id-bus regex local to this module; we don't
        # share the cmd-buf gate's compiled object to keep modules
        # independent.
        _inout_re = re.compile(
            r"\binout\b[^,;)]*\b(id_bus|id_io|idbus|id_data)\b",
            re.IGNORECASE,
        )
        rtl_dir = _pl.rtl_dir(project)
        has_inout_id_bus = False
        if rtl_dir.is_dir():
            for ext in (".v", ".sv"):
                for p in rtl_dir.rglob(f"*{ext}"):
                    try:
                        if _inout_re.search(p.read_text(errors="ignore")):
                            has_inout_id_bus = True
                            break
                    except OSError:
                        continue
                if has_inout_id_bus:
                    break
        if (
            matched_non_aid in ("lin", "kwp2000", "kwp_2000",
                                "k_line", "kline", "iso14230",
                                "iso_14230", "iso9141", "fast_init")
            and has_inout_id_bus
        ):
            result.verdict = "FAIL"
            result.findings.append(Finding(
                rule="PROTOCOL_RTL_INCONSISTENCY",
                severity="ERROR",
                message=(
                    f"L2.protocol_type='{matched_non_aid}' (non-AID), "
                    f"but RTL exposes inout id_bus (AID-class "
                    f"hardware). protocol-type / RTL inconsistency. "
                    f"Wave 42 / SF4 fault-injection hardening — "
                    f"fail-closed instead of silent SKIP."
                ),
            ))
            result.summary = {
                "files": 0,
                "strobes_found": 0,
                "fault_injection_caught":
                    f"L2={matched_non_aid} but RTL has inout id_bus",
            }
            return result
        if not _l8_has_ibt(project):
            result.verdict = "SKIP"
            result.findings.append(Finding(
                rule="PROTOCOL_NOT_AID_CLASS",
                severity="INFO",
                message=(f"L2 protocol_type matches non-AID-class "
                         f"synonym in `{proto_blob[:60]}...` and L8 "
                         f"has no ibt_min / ibt_max — gate not "
                         f"applicable"),
            ))
            result.summary = {"files": 0, "strobes_found": 0}
            return result

    files = _discover_assembler_files(project)
    if not files:
        result.verdict = "SKIP"
        result.findings.append(Finding(
            rule="NO_RX_ASSEMBLER",
            severity="INFO",
            message="No RX assembler / byte-strobe RTL identified",
        ))
        result.summary = {"files": 0, "strobes_found": 0}
        return result

    total_strobes = 0
    pass_strobes = 0
    fail_strobes: List[Tuple[str, str, str]] = []

    for fpath in files:
        try:
            raw = fpath.read_text(errors="replace")
        except OSError:
            continue
        src = _strip_comments(raw)
        for sig, _ofs, block in _find_strobe_assignments(src):
            total_strobes += 1
            has_ibt, bit_idx_only = _classify_block(block)
            if has_ibt:
                pass_strobes += 1
            elif bit_idx_only:
                fail_strobes.append((str(fpath.relative_to(project)), sig,
                                     block.strip()[:200]))
            else:
                # neither — combinational continuous assign without
                # context.  Still requires IBT gate; flag as FAIL.
                fail_strobes.append((str(fpath.relative_to(project)), sig,
                                     block.strip()[:200]))

    if total_strobes == 0:
        result.verdict = "SKIP"
        result.findings.append(Finding(
            rule="NO_BYTE_STROBE_ASSIGNMENT",
            severity="INFO",
            message=("No NBA assignment to a byte-strobe synonym in "
                     "any candidate file"),
        ))
        result.summary = {"files": len(files), "strobes_found": 0}
        return result

    if _is_waived(project):
        result.verdict = "PASS_WITH_WAIVER"
        result.findings.append(Finding(
            rule="WAIVED",
            severity="INFO",
            message=(f"Waiver '{WAIVER_KEY}' set; "
                     f"{len(fail_strobes)} ungated strobe(s) "
                     "deferred"),
        ))
        result.summary = {
            "files": len(files),
            "strobes_found": total_strobes,
            "ibt_gated": pass_strobes,
            "ungated": len(fail_strobes),
        }
        return result

    if fail_strobes:
        result.verdict = "FAIL"
        for fname, sig, snippet in fail_strobes[:5]:
            result.findings.append(Finding(
                rule="BYTE_STROBE_NO_IBT_GATE",
                severity="ERROR",
                file=fname,
                message=(
                    f"`{sig}` emit at {fname} does not gate on an "
                    "IBT-window counter.  Vendor real-PASS-oracle "
                    "uses `rx_data_byte_valid_2p5m` (≥234 ticks "
                    "settle) — without IBT gate the byte latches "
                    "before the line has quiesced and frame timing "
                    "is off by 200+ ticks. "
                    "Add `<ibt_counter> >= IBT_MIN` to the strobe's "
                    "guard expression."
                ),
            ))
    else:
        result.findings.append(Finding(
            rule="BYTE_STROBE_IBT_GATED",
            severity="INFO",
            message=(f"All {pass_strobes} byte-strobe assignments "
                     "are IBT-gated"),
        ))

    result.summary = {
        "files": len(files),
        "strobes_found": total_strobes,
        "ibt_gated": pass_strobes,
        "ungated": len(fail_strobes),
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
        print(f"[{result.verdict}] rx_byte_valid_requires_ibt_gate_check")
        print(f"  files scanned: {result.summary.get('files', 0)}")
        print(f"  strobes found: "
              f"{result.summary.get('strobes_found', 0)}")
        print(f"  IBT-gated: {result.summary.get('ibt_gated', 0)}")
        print(f"  ungated:   {result.summary.get('ungated', 0)}")
        for f in result.findings:
            print(f"  [{f.severity}] {f.rule}: {f.message}")

    return 1 if result.verdict == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
