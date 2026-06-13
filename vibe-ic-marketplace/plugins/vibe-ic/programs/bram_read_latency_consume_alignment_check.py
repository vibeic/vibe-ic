#!/usr/bin/env python3
"""bram_read_latency_consume_alignment_check.py — Wave 26 (v0.119.58) gate.

Purpose
-------
When RTL uses `altsyncram` (or a similar BRAM-inferred ROM/RAM),
ensure the consuming FSM waits at least `read_latency` cycles
after asserting the address before sampling the dout.

altsyncram parameters that drive read latency:
  - input  register (always present, +1 cycle)
  - `outdata_reg_a("UNREGISTERED")` → no output register (+0)
  - `outdata_reg_a("CLOCK0")`/default → output register (+1)

→ `outdata_reg_a("UNREGISTERED")` ⇒ read_latency = 2 cycles.
→ `outdata_reg_a("CLOCK0")` (or unset) ⇒ read_latency = 3 cycles.

If the consumer FSM has only `(addr_state)` → `(consume_state)` —
i.e. 1 cycle of wait — but altsyncram declares UNREGISTERED, the
read returns the PREVIOUS address content (off-by-one).  The
v0.119.57 fresh-agent OTP path failed exactly this way: ID byte
read off-by-one.

Scope
-----
Chip-AGNOSTIC.  Detects altsyncram instances by Megafunction name
(generic Altera/Intel keyword, present across every FPGA family
that ships it).  Synonym lists keep the detection
file-name-independent.

Verdicts
--------
- PASS               — consumer FSM waits ≥ required_latency cycles.
- FAIL               — consumer waits < required_latency cycles.
- SKIP               — no altsyncram / no consuming FSM identifiable.
- PASS_WITH_WAIVER   — waiver `bram_latency_intentional_offset`
                       (≥40 chars).

Usage
-----
    python3 bram_read_latency_consume_alignment_check.py <project_dir>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import _path_layout as _pl

# ----------------------------------------------------------------------
# Synonyms — chip-AGNOSTIC
# ----------------------------------------------------------------------
ALTSYNCRAM_RE = re.compile(
    r"\baltsyncram\s*#?\s*\(", re.IGNORECASE,
)

# Captures `.outdata_reg_a("VALUE")` parameter.
OUTDATA_REG_RE = re.compile(
    r"\.outdata_reg_a\s*\(\s*\"([A-Za-z0-9_]+)\"\s*\)",
    re.IGNORECASE,
)

# Captures `.q_a(<sig>)` to identify the dout net.
Q_A_RE = re.compile(
    r"\.q_a\s*\(\s*([A-Za-z_]\w*)\s*\)", re.IGNORECASE,
)

# Captures `.address_a(<sig>)` to identify the addr net.
ADDR_A_RE = re.compile(
    r"\.address_a\s*\(\s*([A-Za-z_]\w*)\s*\)", re.IGNORECASE,
)

# FSM module hints — files where the consumer state machine lives.
FSM_FILE_HINTS: Tuple[str, ...] = (
    "main_fsm", "fsm", "mac", "protocol_fsm",
    "ctrl", "control", "controller", "top",
    "fetch", "rom_ctrl",
)

# State-name patterns: addr-assertion vs consume.
ADDR_STATE_HINTS = re.compile(
    r"S_(?:OTP_REQUEST|FETCH_OTP|REQ|REQUEST|ADDR|READ_REQ|"
    r"ROM_REQ|MEM_REQ|FETCH(?:_ADDR)?)\b",
    re.IGNORECASE,
)
WAIT_STATE_HINTS = re.compile(
    r"S_(?:OTP_WAIT[12]?|FETCH_OTP_WAIT[12]?|WAIT[12]?|"
    r"READ_WAIT[12]?|ROM_WAIT[12]?|MEM_WAIT[12]?)\b",
    re.IGNORECASE,
)
CONSUME_STATE_HINTS = re.compile(
    r"S_(?:OTP_CONSUME|FETCH_OTP_CONSUME|CONSUME|"
    r"READ_DATA|LATCH|CAPTURE|FETCH_DATA|ROM_DATA)\b",
    re.IGNORECASE,
)

WAIVER_KEY = "bram_latency_intentional_offset"
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
    program: str = "bram_read_latency_consume_alignment_check"
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


def _list_rtl_files(project: Path) -> List[Path]:
    rtl_dirs = [_pl.rtl_dir(project), project]
    seen: set = set()
    out: List[Path] = []
    for d in rtl_dirs:
        if not d.is_dir():
            continue
        for ext in ("*.sv", "*.v"):
            for p in d.rglob(ext):
                if p in seen:
                    continue
                seen.add(p)
                out.append(p)
    return out


@dataclass
class AltsyncramInst:
    file: Path
    outdata_reg: str
    required_latency: int
    q_a_sig: Optional[str]
    addr_a_sig: Optional[str]


def _find_altsyncram_instances(files: List[Path]) -> List[AltsyncramInst]:
    out: List[AltsyncramInst] = []
    for fp in files:
        try:
            raw = fp.read_text(errors="replace")
        except OSError:
            continue
        src = _strip_comments(raw)
        for m in ALTSYNCRAM_RE.finditer(src):
            # Capture from m.start() to a balanced ");" — best-effort
            # by grabbing 4kB ahead.
            tail = src[m.start():m.start() + 4096]
            outdata = "CLOCK0"  # default = registered output
            mo = OUTDATA_REG_RE.search(tail)
            if mo:
                outdata = mo.group(1).upper()
            qa = Q_A_RE.search(tail)
            aa = ADDR_A_RE.search(tail)
            req = 2 if outdata == "UNREGISTERED" else 3
            out.append(AltsyncramInst(
                file=fp,
                outdata_reg=outdata,
                required_latency=req,
                q_a_sig=qa.group(1) if qa else None,
                addr_a_sig=aa.group(1) if aa else None,
            ))
    return out


def _find_fsm_consumer_files(project: Path,
                              q_a_sig: Optional[str]) -> List[Path]:
    """Find files that look like the FSM consumer of the BRAM dout."""
    out: List[Path] = []
    for fp in _list_rtl_files(project):
        name = fp.name.lower()
        if any(h in name for h in FSM_FILE_HINTS):
            out.append(fp)
            continue
        if q_a_sig:
            try:
                txt = fp.read_text(errors="replace")
            except OSError:
                continue
            if re.search(rf"\b{re.escape(q_a_sig)}\b", txt):
                out.append(fp)
    return out


def _arm_has_consume(body: str) -> bool:
    """Heuristic: does this arm body contain an NBA whose RHS
    references a dout-like signal name?  We accept any of:
      - rdata / *rdata* / *_dout / *_q_a / otp_rdata* / mem_q
    """
    consume_re = re.compile(
        r"<=\s*[^;]*\b("
        r"\w*rdata\w*|"
        r"\w*_dout\b|"
        r"q_a|q_b|"
        r"\w*_q_a\b|"
        r"\w*mem_q\b|"
        r"\w*rom_q\b|"
        r"\w*otp_q\b"
        r")\b",
        re.IGNORECASE,
    )
    return bool(consume_re.search(body))


def _count_wait_chain_length(src: str,
                             addr_match_re: re.Pattern,
                             consume_match_re: re.Pattern) -> Optional[int]:
    """Best-effort: scan FSM source for the chain
    addr_state → wait_state(s)... → consume_arm and return the cycle
    count between addr-assertion and dout-consume.

    Counting model
    --------------
      cycle 0 — addr-state body executes (addr assigned).  state_q
                 changes to next on this edge.
      cycle 1 — first successor arm body executes; if it performs a
                 dout-consume NBA OR is a recognised consume_match
                 state name, return 1.
      cycle 2 — second successor arm body, etc.

    Returns None when shape can't be determined.
    """
    state_arms = re.split(r"(?=^\s*S_[A-Z0-9_]+\s*:)", src,
                          flags=re.MULTILINE)
    arms_by_name: Dict[str, str] = {}
    for arm in state_arms:
        m = re.match(r"\s*(S_[A-Z0-9_]+)\s*:", arm)
        if m:
            arms_by_name[m.group(1).upper()] = arm

    # Find addr-state arm.
    addr_state = None
    for nm in arms_by_name:
        if addr_match_re.search(nm):
            addr_state = nm
            break
    if not addr_state:
        return None

    # Walk forward through state transitions; each step = 1 cycle.
    visited: set = set()
    cur = addr_state
    cycles = 0
    # We don't count the addr arm itself (cycle 0).
    while cur and cur not in visited and cycles < 16:
        visited.add(cur)
        body = arms_by_name.get(cur, "")
        # find next state
        nm = re.search(r"state_q\s*<=\s*(S_[A-Z0-9_]+)\s*;", body,
                       re.IGNORECASE)
        if not nm:
            return None
        nxt = nm.group(1).upper()
        cycles += 1
        # We're now in the cycle where `nxt` arm body executes.
        nxt_body = arms_by_name.get(nxt, "")
        if consume_match_re.search(nxt) or _arm_has_consume(nxt_body):
            return cycles
        # Continue walking only through wait-named states.  If the
        # next state is neither wait nor consume, stop and report
        # this cycle as the determined consume-distance (we can't see
        # further consume).
        if not WAIT_STATE_HINTS.search(nxt):
            return cycles
        cur = nxt
    return None


def _detect_consume_in_wait_state(src: str,
                                  q_a_sig: Optional[str]) -> Optional[Tuple[str, int]]:
    """Detect inline `<sig> <= q_a_sig` in a wait-named arm and infer
    its position from the addr arm.  Returns
    (wait_state_name, consume_distance_cycles) when it can — None
    otherwise."""
    if not q_a_sig:
        return None
    state_arms = re.split(r"(?=^\s*S_[A-Z0-9_]+\s*:)", src,
                          flags=re.MULTILINE)
    arms_by_name: Dict[str, str] = {}
    for arm in state_arms:
        m = re.match(r"\s*(S_[A-Z0-9_]+)\s*:", arm)
        if m:
            arms_by_name[m.group(1).upper()] = arm
    capture_re = re.compile(
        rf"\w+\s*<=\s*[^;]*\b{re.escape(q_a_sig)}\b",
    )
    # Find addr arm
    addr_state = None
    for nm in arms_by_name:
        if ADDR_STATE_HINTS.search(nm):
            addr_state = nm
            break
    if not addr_state:
        return None
    # Walk forward — cycle 0 is the addr-state body; cycle 1 is the
    # first successor arm body; etc.
    visited: set = set()
    cur = addr_state
    cycles = 0
    while cur and cur not in visited and cycles < 16:
        visited.add(cur)
        body = arms_by_name.get(cur, "")
        if cycles > 0 and capture_re.search(body):
            return (cur, cycles)
        nm = re.search(r"state_q\s*<=\s*(S_[A-Z0-9_]+)\s*;", body,
                       re.IGNORECASE)
        if not nm:
            return None
        cur = nm.group(1).upper()
        cycles += 1
    return None


# ----------------------------------------------------------------------
# Audit
# ----------------------------------------------------------------------
def run_audit(project: Path) -> AuditResult:
    result = AuditResult()
    files = _list_rtl_files(project)
    if not files:
        result.verdict = "SKIP"
        result.findings.append(Finding(
            rule="NO_RTL", severity="INFO",
            message="No RTL files found",
        ))
        result.summary = {"altsyncram_instances": 0}
        return result

    instances = _find_altsyncram_instances(files)
    if not instances:
        result.verdict = "SKIP"
        result.findings.append(Finding(
            rule="NO_ALTSYNCRAM",
            severity="INFO",
            message=("No altsyncram instance found; gate skipped"),
        ))
        result.summary = {"altsyncram_instances": 0}
        return result

    fails: List[str] = []
    passes = 0
    instance_summaries: List[dict] = []

    for inst in instances:
        consumer_files = _find_fsm_consumer_files(project, inst.q_a_sig)
        consume_cycles: Optional[int] = None
        consume_file: Optional[str] = None

        for cf in consumer_files:
            try:
                src = _strip_comments(cf.read_text(errors="replace"))
            except OSError:
                continue
            # Try inline q_a consume detection first (most accurate).
            inline = _detect_consume_in_wait_state(src, inst.q_a_sig)
            if inline:
                consume_cycles = inline[1]
                consume_file = str(cf.relative_to(project))
                break
            # Fall back to state-name chain.
            chain = _count_wait_chain_length(
                src, ADDR_STATE_HINTS, CONSUME_STATE_HINTS)
            if chain is not None:
                consume_cycles = chain
                consume_file = str(cf.relative_to(project))
                break

        instance_summaries.append({
            "file": str(inst.file.relative_to(project)),
            "outdata_reg_a": inst.outdata_reg,
            "required_latency": inst.required_latency,
            "consume_cycles": consume_cycles,
            "consumer_file": consume_file,
        })

        if consume_cycles is None:
            # Cannot prove FAIL nor PASS — skip silently for this inst.
            continue
        if consume_cycles >= inst.required_latency:
            passes += 1
        else:
            fails.append(
                f"{inst.file.name} altsyncram (outdata_reg_a="
                f"{inst.outdata_reg}, required={inst.required_latency} "
                f"cycles) consumed at {consume_file} after only "
                f"{consume_cycles} cycle(s) → off-by-one read"
            )

    if not instance_summaries or all(s["consume_cycles"] is None
                                     for s in instance_summaries):
        result.verdict = "SKIP"
        result.findings.append(Finding(
            rule="NO_CONSUMER_DETECTED",
            severity="INFO",
            message=("altsyncram present but FSM consumer pattern "
                     "could not be matched"),
        ))
        result.summary = {
            "altsyncram_instances": len(instances),
            "instances": instance_summaries,
        }
        return result

    if _is_waived(project):
        result.verdict = "PASS_WITH_WAIVER"
        result.findings.append(Finding(
            rule="WAIVED",
            severity="INFO",
            message=(f"Waiver '{WAIVER_KEY}' set; "
                     f"{len(fails)} latency mismatch(es) deferred"),
        ))
        result.summary = {
            "altsyncram_instances": len(instances),
            "instances": instance_summaries,
            "passes": passes,
            "fails": len(fails),
        }
        return result

    if fails:
        result.verdict = "FAIL"
        for f_msg in fails:
            result.findings.append(Finding(
                rule="BRAM_LATENCY_OFF_BY_ONE",
                severity="ERROR",
                message=(
                    f"FAIL — BRAM_LATENCY_OFF_BY_ONE\n"
                    f"{f_msg}\n"
                    "Add wait state(s), OR set "
                    "outdata_reg_a(\"UNREGISTERED\") AND consume "
                    "after 2 cycles."
                ),
            ))
    else:
        result.findings.append(Finding(
            rule="BRAM_LATENCY_ALIGNED",
            severity="INFO",
            message=(f"{passes} altsyncram instance(s) consumed at "
                     "or after their required latency"),
        ))

    result.summary = {
        "altsyncram_instances": len(instances),
        "instances": instance_summaries,
        "passes": passes,
        "fails": len(fails),
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
        print(f"[{result.verdict}] bram_read_latency_consume_alignment_check")
        print(f"  altsyncram instances: "
              f"{result.summary.get('altsyncram_instances', 0)}")
        for inst in result.summary.get("instances", []):
            print(f"  - {inst['file']}: outdata_reg_a={inst['outdata_reg_a']} "
                  f"required={inst['required_latency']} "
                  f"consume_cycles={inst['consume_cycles']}")
        for f in result.findings:
            print(f"  [{f.severity}] {f.rule}: {f.message}")

    return 1 if result.verdict == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
