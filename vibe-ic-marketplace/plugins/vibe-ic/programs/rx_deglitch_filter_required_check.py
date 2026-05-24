#!/usr/bin/env python3
"""rx_deglitch_filter_required_check.py — Wave 22 silent-bug gate.

Half-duplex single-wire RX paths (id_bus / acc_id / kline / lin /
owire …) must use a ≥3-stage synchronizer + ≥2-of-2 (or N-of-N,
N≥2) deglitch filter before driving the bit decoder. A simple 2-FF
synchronizer (the textbook CDC pattern) resolves metastability but
does NOT filter 1-cycle glitches caused by EMI / cable noise /
open-drain edge ringing on a real silicon bus. Such glitches are
mis-classified by the bit decoder as BIT0 / BIT1 / BR / IBT, frame
state corrupts, the DUT silently fails to reply, and the host /
tester sees byte[6]=0x02 padding instead of the PASS verdict.

Detection
=========
1. Locate top-level wrapper / RX-phy module heuristically:
     - file declares an `inout` port (top wrapper), OR
     - filename matches rx_phy / rx_pad / rx_sample / id_phy / bus_phy.
2. Identify the candidate RX source signal — the first signal that
   feeds an FF chain via NBA assignments. Either:
     (a) the LHS of an `inout <bus>` (top wrapper case), or
     (b) any input port matching rx_in / id_in / bus_in / kl_in /
         <name>_rx / <name>_in fed into a chain.
3. Walk the synchronizer chain by following `<dst> <= <src>` NBA
   assignments where `src` is the previous stage. Count chain length.
4. Inspect the consumer of the chain output:
     - assignment such as `assign <out> = <ff_a> & <ff_b>;` or
       `assign <out> = <ff_a> | <ff_b>;` where both `ff_a` and `ff_b`
       are members of the sync chain — this is a 2-of-2 deglitch.
     - a procedural N-of-N AND/OR over ≥2 chain members also counts.
5. Verdicts:
     PASS  — chain length ≥3 AND filter combines ≥2 chain stages
             via AND or OR.
     FAIL  — chain length <3 (silent-bug pattern: simple 2-FF sync).
     WARN  — chain length ≥3 but filter output is a single FF
             (deglitch missing — metastability OK, glitch not).
     SKIP  — no top-level wrapper / no recognisable bus pad.
6. Honors waiver `rx_deglitch_intentionally_omitted` (≥40 chars).

Chip-AGNOSTIC: signal names auto-discovered from inout pad / sync FF
naming. No protocol / chip / vendor identifiers hardcoded.

Exit codes
==========
0 — PASS / SKIP / PASS_WITH_WAIVER / WARN
1 — FAIL
2 — usage error
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Set, Tuple
import _path_layout as _pl

WAIVER_KEY = "rx_deglitch_intentionally_omitted"
WAIVER_MIN_LEN = 40

_INOUT_RE = re.compile(
    r"\binout\s+(?:logic\s+|wire\s+|reg\s+)?(\w+)\b",
)

_FILENAME_HINTS = (
    "rx_phy", "rx_pad", "rx_sample", "rx_sync", "rx_input",
    "id_phy", "bus_phy", "kline_phy", "lin_phy", "owire_phy",
)

# RX-input port heuristic.
_RX_PORT_RE = re.compile(
    r"\binput\s+(?:logic\s+|wire\s+|reg\s+)?(\w*(?:rx_in|rx_pad|"
    r"id_in|id_pad|bus_in|bus_pad|kl_in|owire_in|line_in|"
    r"_rx|_in)\w*)\b",
    re.IGNORECASE,
)

# NBA chain: `dst <= src;` (handles spaces, async-reset blocks…).
_NBA_RE = re.compile(
    r"\b(\w+)\s*<=\s*([A-Za-z_]\w*)\s*;",
)

# AND/OR combinations across ≥2 single-identifier operands.
_FILTER_AND_RE = re.compile(
    r"assign\s+(\w+)\s*=\s*([A-Za-z_]\w*)\s*&\s*([A-Za-z_]\w*)"
    r"(?:\s*&\s*([A-Za-z_]\w*))?\s*;",
)
_FILTER_OR_RE = re.compile(
    r"assign\s+(\w+)\s*=\s*([A-Za-z_]\w*)\s*\|\s*([A-Za-z_]\w*)"
    r"(?:\s*\|\s*([A-Za-z_]\w*))?\s*;",
)

# Wave 36 (v0.119.68) — majority-of-3 voter pattern: `(a&b)|(b&c)|(a&c)`.
# Common for triple-voter deglitch on FPGA. Match three AND-pair terms
# OR-ed together (operand order doesn't matter — regex captures the
# structural shape).
_FILTER_MAJORITY3_RE = re.compile(
    r"\(\s*\w+\s*&\s*\w+\s*\)\s*\|\s*"
    r"\(\s*\w+\s*&\s*\w+\s*\)\s*\|\s*"
    r"\(\s*\w+\s*&\s*\w+\s*\)",
)
# Wave 36 — shift-counter / hold-counter pattern: `if (cnt > N)` or
# `if (cnt == N)` etc., guarding the bit decoder. Common alternative
# to AND/OR voting.
_FILTER_SHIFT_COUNTER_RE = re.compile(
    r"if\s*\(\s*\w*cnt\w*\s*[=><]+\s*\d+",
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


def _candidate_rx_seeds(text: str) -> List[str]:
    """Return list of plausible RX-source signal names in this file."""
    seeds: List[str] = []
    for m in _INOUT_RE.finditer(text):
        seeds.append(m.group(1))
    for m in _RX_PORT_RE.finditer(text):
        seeds.append(m.group(1))
    # Deduplicate, keep order.
    seen: Set[str] = set()
    uniq: List[str] = []
    for s in seeds:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def _is_rx_phy_file(path: Path, text: str) -> bool:
    name = path.stem.lower()
    if any(h in name for h in _FILENAME_HINTS):
        return True
    if _INOUT_RE.search(text):
        return True
    return False


def _build_sync_chain(text: str, seed: str) -> List[str]:
    """Follow NBA chain originating at `seed` (or anything derived
    from `seed` via a combinational `assign` rename). Return ordered
    chain of FF names (excluding the seed).
    """
    # Build a successor map: for each `dst <= src`, src→dst.
    succ: dict[str, List[str]] = {}
    for m in _NBA_RE.finditer(text):
        dst, src = m.group(1), m.group(2)
        if dst == src:
            continue
        succ.setdefault(src, []).append(dst)

    # Comb renames: `assign B = A;` and pad-instance `.C(B), .PAD(A)`
    # — treat B as derived from A so the chain can hop the rename.
    aliases: dict[str, Set[str]] = {}
    # `assign x = y;` (single identifier RHS).
    for m in re.finditer(
        r"assign\s+(\w+)\s*=\s*([A-Za-z_]\w*)\s*;", text
    ):
        dst, src = m.group(1), m.group(2)
        aliases.setdefault(src, set()).add(dst)
    # `wire <name> = <ident>;` declarations.
    for m in re.finditer(
        r"\bwire\s+(?:\[[^\]]+\]\s+)?(\w+)\s*=\s*([A-Za-z_]\w*)\s*;",
        text,
    ):
        dst, src = m.group(1), m.group(2)
        aliases.setdefault(src, set()).add(dst)

    # BFS-pick the longest chain reachable from seed (via succ),
    # allowing one alias hop before the first NBA stage.
    def _longest_from(start: str, banned: Set[str]) -> List[str]:
        best: List[str] = []
        stack: List[Tuple[str, List[str], Set[str]]] = [
            (start, [], set(banned) | {start})
        ]
        while stack:
            cur, path, vis = stack.pop()
            if len(path) > len(best):
                best = list(path)
            for nxt in succ.get(cur, []):
                if nxt in vis:
                    continue
                stack.append(
                    (nxt, path + [nxt], vis | {nxt})
                )
        return best

    seeds_to_try: List[str] = [seed]
    seeds_to_try.extend(sorted(aliases.get(seed, set())))
    # Also consider wires whose name contains the seed (e.g.
    # id_bus → id_bus_rx).
    for cand in succ.keys():
        if seed in cand and cand != seed and cand not in seeds_to_try:
            seeds_to_try.append(cand)

    best_chain: List[str] = []
    for s in seeds_to_try:
        ch = _longest_from(s, set())
        if len(ch) > len(best_chain):
            best_chain = ch
    return best_chain


def _filter_uses_chain(text: str, chain: Set[str]
                       ) -> Tuple[bool, str, int]:
    """Look for a deglitch filter that combines ≥2 chain members.
    Returns (found, evidence, n_terms).

    Wave 36 (v0.119.68) — also accepts:
      * majority-of-3 voter `(a&b)|(b&c)|(a&c)`
      * shift-counter / hold-counter `if (cnt > N)` style guard
    """
    for pat, sym in ((_FILTER_AND_RE, "&"), (_FILTER_OR_RE, "|")):
        for m in pat.finditer(text):
            terms = [t for t in m.groups()[1:] if t]
            in_chain = [t for t in terms if t in chain]
            if len(in_chain) >= 2:
                return True, m.group(0).strip(), len(in_chain)
    # Majority-of-3 voter (structural — chain membership not required
    # because the voter is intentionally redundant across 3 stages).
    m = _FILTER_MAJORITY3_RE.search(text)
    if m:
        return True, m.group(0).strip()[:120], 3
    # Shift-counter pattern.
    m = _FILTER_SHIFT_COUNTER_RE.search(text)
    if m:
        return True, m.group(0).strip()[:120], 2
    return False, "", 0


_L1_SCHMITT_RE = re.compile(
    r"iostandard[^\n]*\b(schmitt|hysteresis)\b",
    re.IGNORECASE,
)


def _l1_internal_schmitt(project: Path) -> bool:
    """Wave 36 — return True iff L1 datasheet documents an internal
    Schmitt-trigger / hysteresis I/O standard. Such pads filter
    glitches at the analog level, so a software deglitch chain is
    not required."""
    for sub in ("phase1/generated_docs", "generated_docs", "l_docs"):
        d = project / sub
        if not d.is_dir():
            continue
        for cand in sorted(d.glob("L1*.json")):
            try:
                txt = cand.read_text(errors="ignore")
            except OSError:
                continue
            if _L1_SCHMITT_RE.search(txt):
                return True
    return False


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


def inspect(project: Path) -> Tuple[List[str], List[str], dict]:
    """Returns (failures, warnings, summary)."""
    failures: List[str] = []
    warnings: List[str] = []
    summary: dict = {}

    rtl = _find_rtl_files(project)
    if not rtl:
        summary["skip_reason"] = "no rtl/ directory"
        return failures, warnings, summary

    # Wave 36 (v0.119.68) — L1 internal Schmitt-trigger SKIP.
    if _l1_internal_schmitt(project):
        summary["skip_reason"] = (
            "L1 documents internal Schmitt/hysteresis I/O standard; "
            "analog hysteresis filters glitches — software deglitch "
            "chain not required"
        )
        return failures, warnings, summary

    candidates: List[Tuple[Path, str, List[str]]] = []
    for f in rtl:
        try:
            raw = f.read_text(errors="ignore")
        except OSError:
            continue
        text = _strip_comments(raw)
        if not _is_rx_phy_file(f, text):
            continue
        seeds = _candidate_rx_seeds(text)
        if not seeds:
            continue
        candidates.append((f, text, seeds))

    if not candidates:
        summary["skip_reason"] = (
            "no top-level wrapper / RX-phy module with bus pad found"
        )
        return failures, warnings, summary

    # Pick the candidate with the longest sync chain (most likely
    # the real RX path); fall back to the first.
    best: Optional[Tuple[Path, str, str, List[str]]] = None
    for f, text, seeds in candidates:
        for seed in seeds:
            chain = _build_sync_chain(text, seed)
            if best is None or len(chain) > len(best[3]):
                best = (f, text, seed, chain)

    assert best is not None
    f, text, seed, chain = best
    try:
        rel = f.relative_to(project)
    except ValueError:
        rel = f

    summary["wrapper_file"] = str(rel)
    summary["rx_seed"] = seed
    summary["sync_chain"] = chain
    summary["chain_length"] = len(chain)

    if not chain:
        summary["skip_reason"] = (
            f"no synchronizer chain found from RX seed {seed!r}"
        )
        return failures, warnings, summary

    chain_set = set(chain)
    found, evidence, n_terms = _filter_uses_chain(text, chain_set)
    summary["filter_found"] = found
    summary["filter_evidence"] = evidence
    summary["filter_terms_in_chain"] = n_terms

    # Verdict matrix.
    if len(chain) < 3:
        # The dominant silent-bug pattern: simple 2-FF (or 1-FF)
        # synchroniser with no deglitch.
        # Locate file:line of the last NBA in the chain.
        last_ff = chain[-1]
        line_no = 0
        for idx, line in enumerate(text.splitlines(), start=1):
            if re.search(rf"\b{re.escape(last_ff)}\s*<=", line):
                line_no = idx
        loc = f"{rel}:{line_no}" if line_no else str(rel)
        failures.append(
            f"RX_SYNC_CHAIN_TOO_SHORT — {loc}: chain length "
            f"{len(chain)} < 3 from RX seed {seed!r} (chain="
            f"{chain!r}). A 2-FF synchroniser resolves metastability "
            f"but does not filter 1-cycle glitches; cable EMI / "
            f"open-drain edge ringing on real silicon will corrupt "
            f"frame decoding (sim-PASS / hardware-FAIL pattern). "
            f"See rig spec Layer 13 — RX deglitch filter required."
        )
        return failures, warnings, summary

    # Chain length ≥3.
    if not found:
        warnings.append(
            f"RX_DEGLITCH_FILTER_MISSING — {rel}: ≥3-stage "
            f"synchroniser present (chain={chain!r}) but no "
            f"AND/OR-based 2-of-2 deglitch filter detected on "
            f"the chain output. Add `assign rx_stable = "
            f"{chain[-1]} & {chain[-2]};` (or OR variant). "
            f"Without deglitch, single-cycle glitches still "
            f"propagate — see rig spec Layer 13."
        )
        return failures, warnings, summary

    # PASS.
    return failures, warnings, summary


def main(argv: List[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(
            "Usage: rx_deglitch_filter_required_check.py "
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

    failures, warnings, summary = inspect(project)
    is_waived, rationale = _waived(project)

    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps({
            "program": "rx_deglitch_filter_required_check",
            "passed": not failures,
            "warnings": warnings,
            "summary": summary,
            "failures": failures,
            "waived": is_waived,
        }, indent=2))

    if "skip_reason" in summary and not failures and not warnings:
        print(f"SKIP — {summary['skip_reason']}")
        return 0

    if not failures and not warnings:
        chain = summary.get("sync_chain", [])
        ev = summary.get("filter_evidence", "")
        print(
            f"PASS — RX path uses {len(chain)}-stage synchroniser + "
            f"deglitch filter ({ev[:80]})"
        )
        return 0

    if not failures and warnings:
        # WARN-only is non-blocking.
        for w in warnings:
            print(f"WARN — {w}")
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — silenced by waivers.{WAIVER_KEY}: "
            f"{rationale[:80]}…"
        )
        for fmsg in failures:
            print(f"  • {fmsg}")
        return 0

    print(f"FAIL — {len(failures)} RX deglitch filter issue(s):")
    for fmsg in failures:
        print(f"  • {fmsg}")
    for w in warnings:
        print(f"  • (WARN) {w}")
    print()
    print("Why this matters:")
    print("  Half-duplex single-wire buses (id_bus / kline / lin /")
    print("  owire / acc_id …) carry EMI + cable + open-drain edge")
    print("  noise. A 2-FF synchroniser resolves metastability but")
    print("  passes single-cycle glitches straight to the bit decoder,")
    print("  which mis-classifies them as BIT0/BIT1/BR/IBT and the")
    print("  frame state corrupts. DUT goes silent during the async")
    print("  response window → host sees byte[6]=0x02 padding.")
    print("  Sim PASSes (clean stimulus); hardware FAILes (real noise).")
    print()
    print("Vendor reference pattern (real PASS oracle):")
    print("    reg rx_syn1, rx_syn2, rx_syn3;")
    print("    always @(posedge clk) begin")
    print("      rx_syn1 <= rx_pad;")
    print("      rx_syn2 <= rx_syn1;")
    print("      rx_syn3 <= rx_syn2;")
    print("    end")
    print("    assign rx_stable_high = rx_syn3 & rx_syn2;  // 2-of-2")
    print()
    print(
        f"Or document an alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": "<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
