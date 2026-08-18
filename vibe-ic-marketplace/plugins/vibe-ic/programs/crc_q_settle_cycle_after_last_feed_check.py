#!/usr/bin/env python3
"""crc_q_settle_cycle_after_last_feed_check.py — Wave 16 silent-bug gate.

When a CRC engine is fed serially with a `crc_feed` / `crc_en` /
`crc_update` strobe, the FSM that consumes `crc_out` / `crc_q` /
`crc_result` must wait at least one cycle after the LAST feed pulse
before sampling — otherwise `crc_q` is stale (off-by-one byte).

The classic bug:

    S_TX_BYTE_WAIT: begin
        if (last_byte) begin
            crc_feed <= 1'b1;          // feed the LAST byte
            tx_byte  <= crc_q;          // <-- READS stale crc_q (still
                                       //     the prior byte's residue!)
            state    <= S_TX_CRC;
        end
    end

The fix:

    S_TX_BYTE_WAIT: begin
        if (last_byte) begin
            crc_feed <= 1'b1;
            state    <= S_TX_CRC_SETTLE;   // <-- 1-cycle wait
        end
    end
    S_TX_CRC_SETTLE: begin
        tx_byte <= crc_q;                 // crc_q is now stable
        state   <= S_TX_CRC;
    end

Detection
=========
1. Find any RTL with both a `crc_feed`-family strobe (`crc_feed`,
   `crc_en`, `crc_update`, `crc_strobe`, `crc_in_valid`) AND a
   `crc_q`-family read (`crc_q`, `crc_out`, `crc_result`, `crc_value`).
2. For every always_ff block, find statements where BOTH the strobe
   is asserted (`<feed> <= 1'b1;`) AND `crc_q` is sampled into a
   register (`<r> <= crc_q;`) in the SAME cycle of the SAME state arm.
3. **FAIL** when this same-cycle pattern is present without an
   intervening settle state.
4. **PASS** when crc_q sampling is in a state arm that does NOT also
   pulse the feed signal in that same arm — i.e., there's a
   transition state separating them.
5. **SKIP** when the project has no CRC module / no crc_feed family /
   the CRC module exposes a combinational `crc_out` (no clock, no
   register — settle cycle is not necessary).
6. Honors waiver `crc_settle_unnecessary_combinational_crc`
   (≥40 chars).

Chip-AGNOSTIC: signal names auto-discovered from RTL.

Exit codes
==========
0 — PASS / SKIP / PASS_WITH_WAIVER
1 — FAIL
2 — usage error
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple
import _path_layout as _pl

WAIVER_KEY = "crc_settle_unnecessary_combinational_crc"
WAIVER_MIN_LEN = 40

# Strobe families
_FEED_NAMES_RE = re.compile(
    r"\b(crc_feed|crc_en|crc_update|crc_strobe|crc_in_valid|crc_valid_in)\b",
    re.IGNORECASE,
)
# Read families — the CRC output that the consumer FSM reads
_CRC_OUT_NAMES_RE = re.compile(
    r"\b(crc_q|crc_out|crc_result|crc_value|crc_o|crc_data)\b",
    re.IGNORECASE,
)


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _find_rtl_files(project: Path) -> List[Path]:
    rtl_dir = _pl.rtl_dir(project)
    if not rtl_dir.exists():
        return []
    out: List[Path] = []
    for p in rtl_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".v", ".sv", ".svh", ".vh"):
            out.append(p)
    return sorted(out)


def _is_crc_combinational(rtl_files: List[Path]) -> bool:
    """Heuristic: if the CRC module declares `crc_out`/`crc_q` as a
    `assign crc_q = ...` (continuous combinational assign) and has NO
    `<feed> <= 1'b1` non-blocking — treat as combinational."""
    for f in rtl_files:
        try:
            text = _strip_comments(f.read_text(errors="ignore"))
        except OSError:
            continue
        if not _CRC_OUT_NAMES_RE.search(text):
            continue
        # Module declares the output as continuous?
        if re.search(
            r"assign\s+(?:crc_q|crc_out|crc_result|crc_value|crc_o|crc_data)"
            r"\s*=\s*[^?;]+;",
            text,
            re.IGNORECASE,
        ):
            # Must also lack any always_ff that registers crc_q
            if not re.search(
                r"always_ff[\s\S]+?(?:crc_q|crc_out|crc_result|crc_value)"
                r"\s*<=",
                text,
                re.IGNORECASE,
            ):
                return True
    return False


# Find a state-machine arm: `Sxxx: begin ... end` (heuristic).
_STATE_ARM_RE = re.compile(
    r"\b(S_\w+|[A-Z][A-Z0-9_]+)\s*:\s*begin\b([\s\S]+?)\bend\b",
)


def _find_violations(rtl_files: List[Path],
                     project: Path) -> List[Tuple[Path, int, str, str, str]]:
    """Return list of (file, line, state_name, feed_evidence, read_evidence).

    Same-cycle violation: a state arm that asserts a feed strobe AND
    reads crc_q into a register in the same cycle.
    """
    violations: List[Tuple[Path, int, str, str, str]] = []
    for f in rtl_files:
        try:
            text = _strip_comments(f.read_text(errors="ignore"))
        except OSError:
            continue
        if not _FEED_NAMES_RE.search(text) or not _CRC_OUT_NAMES_RE.search(text):
            continue
        for arm in _STATE_ARM_RE.finditer(text):
            state_name = arm.group(1)
            body = arm.group(2)
            # Need a feed-pulse non-blocking: `<feed> <= 1'b1;`
            feed_match = re.search(
                r"\b(crc_feed|crc_en|crc_update|crc_strobe|crc_in_valid|"
                r"crc_valid_in)\s*<=\s*1'b1\s*;",
                body,
                re.IGNORECASE,
            )
            if not feed_match:
                continue
            # Need a crc_q sample into another register (NBA assign whose
            # RHS is crc_q-family).
            read_match = re.search(
                r"(\w+)\s*<=\s*\b(crc_q|crc_out|crc_result|crc_value|"
                r"crc_o|crc_data)\b",
                body,
                re.IGNORECASE,
            )
            if not read_match:
                continue
            # Same-cycle violation: state-arm transition is
            # `state <= S_NEXT` going DIRECTLY to a TX-ish state, or
            # there is no next state assignment (the CRC byte is
            # already being assigned in this arm). Either way the
            # crc_q read is stale because the feed only takes effect
            # at the next clock edge.
            line_no = text[:arm.start() + arm.group(0).find(read_match.group(0))].count("\n") + 1
            violations.append((
                f,
                line_no,
                state_name,
                feed_match.group(0).strip(),
                read_match.group(0).strip(),
            ))
    return violations


def _waived(project: Path) -> Tuple[bool, str]:
    waivers = project / "waivers.json"
    if not waivers.exists():
        return False, ""
    try:
        d = json.loads(waivers.read_text())
    except Exception:
        return False, ""
    raw = d.get(WAIVER_KEY)
    if isinstance(raw, str) and len(raw.strip()) >= WAIVER_MIN_LEN:
        return True, raw.strip()
    if isinstance(raw, dict):
        rationale = raw.get("rationale") or raw.get("reason") or ""
        if isinstance(rationale, str) and \
           len(rationale.strip()) >= WAIVER_MIN_LEN:
            return True, rationale.strip()
    return False, ""


def inspect(project: Path) -> Tuple[List[str], dict]:
    failures: List[str] = []
    summary: dict = {}

    rtl = _find_rtl_files(project)
    if not rtl:
        summary["skip_reason"] = "no rtl/ directory"
        return failures, summary

    # Detect at all?
    has_feed = False
    has_out = False
    for f in rtl:
        try:
            t = _strip_comments(f.read_text(errors="ignore"))
        except OSError:
            continue
        if _FEED_NAMES_RE.search(t):
            has_feed = True
        if _CRC_OUT_NAMES_RE.search(t):
            has_out = True
    if not (has_feed and has_out):
        summary["skip_reason"] = (
            "no CRC feed-strobe + crc_q pair detected"
        )
        return failures, summary

    if _is_crc_combinational(rtl):
        summary["skip_reason"] = (
            "CRC module is combinational (assign crc_q = ...) — "
            "settle cycle is not required"
        )
        return failures, summary

    violations = _find_violations(rtl, project)
    summary["violation_count"] = len(violations)

    for f, ln, state_name, feed_ev, read_ev in violations:
        try:
            rel = f.relative_to(project)
        except ValueError:
            rel = f
        failures.append(
            f"CRC_SETTLE_MISSING — {rel}:{ln} (state {state_name}): "
            f"the same FSM arm pulses {feed_ev!r} AND samples "
            f"{read_ev!r} in the same cycle. The crc_q value read this "
            f"cycle is the BYTE-N-1 residue (the new feed only takes "
            f"effect at the next clock edge). Insert a 1-cycle settle "
            f"state between feed and read:\n"
            f"    {state_name}: begin\n"
            f"        <feed> <= 1'b1;\n"
            f"        state  <= {state_name}_SETTLE;\n"
            f"    end\n"
            f"    {state_name}_SETTLE: begin\n"
            f"        <reg> <= crc_q;     // now stable\n"
            f"        state <= ...;\n"
            f"    end"
        )
    return failures, summary


def main(argv: List[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(
            "Usage: crc_q_settle_cycle_after_last_feed_check.py "
            "<project_dir> [--json <out>]"
        )
        return 0 if (len(argv) >= 2 and argv[1] in ("-h", "--help")) else 2

    project = Path(argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 1

    json_out: Optional[Path] = None
    if "--json" in argv:
        idx = argv.index("--json")
        if idx + 1 < len(argv):
            json_out = Path(argv[idx + 1])

    failures, summary = inspect(project)
    is_waived, rationale = _waived(project)

    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps({
            "program": "crc_q_settle_cycle_after_last_feed_check",
            "passed": not failures,
            "summary": summary,
            "failures": failures,
            "waived": is_waived,
        }, indent=2))

    if "skip_reason" in summary and not failures:
        print(f"SKIP — {summary['skip_reason']}")
        return 0

    if not failures:
        print(
            "PASS — CRC feed/read are separated by a settle cycle "
            "in every state arm"
        )
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — silenced by waivers.{WAIVER_KEY}: "
            f"{rationale[:80]}…"
        )
        for fmsg in failures:
            print(f"  • {fmsg}")
        return 0

    print(f"FAIL — {len(failures)} CRC settle-cycle violation(s):")
    for fmsg in failures:
        print(f"  • {fmsg}")
        print()
    print(
        f"Or document an alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": "<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
