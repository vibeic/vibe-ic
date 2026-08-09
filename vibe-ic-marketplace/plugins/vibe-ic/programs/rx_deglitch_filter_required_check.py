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
2. Identify EVERY candidate RX source signal in the project. Two
   routes, and the route decides where the seed is admissible:
     (a) the LHS of an `inout <bus>` — a bidirectional pad IS the
         half-duplex single-wire bus this gate is about, so route (a)
         seeds are admitted from ANY candidate file;
     (b) an input port matching rx_in / id_in / bus_in / kl_in /
         <name>_rx / <name>_in — admitted ONLY from a file whose NAME
         says it is the RX phy (`_FILENAME_HINTS`). A generic `*_in`
         port of an arbitrary module is not a noisy single-wire bus,
         and demanding a 3-stage + vote deglitch on every such port
         would fire on designs that have no such bus at all.
3. Walk the synchronizer chain by following `<dst> <= <src>` NBA
   assignments where `src` is the previous stage. Count chain length.
4. Inspect the consumer of the chain output:
     - assignment such as `assign <out> = <ff_a> & <ff_b>;` or
       `assign <out> = <ff_a> | <ff_b>;` where both `ff_a` and `ff_b`
       are members of the sync chain — this is a 2-of-2 deglitch.
     - a procedural N-of-N AND/OR over ≥2 chain members also counts.
5. Per-RX-path verdicts:
     PASS  — chain length ≥3 AND filter combines ≥2 chain stages
             via AND or OR.
     FAIL  — chain length <3 (silent-bug pattern: simple 2-FF sync).
     WARN  — chain length ≥3 but filter output is a single FF
             (deglitch missing — metastability OK, glitch not).
   The PROJECT verdict is the WORST verdict over every RX path, not
   the verdict of the best-looking one. See "Aggregation" below.
     SKIP  — no top-level wrapper / no recognisable bus pad, or no
             synchroniser chain reachable from any admissible seed.
6. Honors waiver `rx_deglitch_intentionally_omitted` (≥40 chars).

Aggregation — why WORST and not BEST
====================================
The umbrella (`flow_compliance_check._STRUCTURAL_RTL_GATES`) dispatches
this gate ONCE per PROJECT, as `<gate>.py <project_dir>`, over an
`rtl/` tree that normally holds many modules and more than one pad.

Until this fix the project verdict was the verdict of whichever
(file, seed) produced the LONGEST chain — `if len(chain) > len(best[3])`
— i.e. the greenest RX path in the whole design decided the verdict for
all of them. That made the FAIL verdict (`RX_SYNC_CHAIN_TOO_SHORT`)
unreachable for the shape this gate exists to catch: a project whose
top wrapper has the 2-FF anti-pattern and which ALSO contains one
compliant peripheral pad did not merely lose the FAIL, it printed
`PASS` and named the OTHER file as the RX path it had checked.

A gate whose subject is "every half-duplex single-wire RX path" cannot
be satisfied by its best path, so each admissible RX path is now scored
on its own and the project takes the worst. `summary["rx_paths"]` lists
every path that was scored, so the denominator is visible and a reader
can see exactly which pad is non-compliant.

This is the DEFAULT behaviour and there is deliberately no opt-in
strictness flag: the umbrella passes no flags, so a flag-gated verdict
would be exactly as unreachable as the one being fixed.

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

# Per-RX-path verdict severity. The PROJECT verdict is the worst over
# every admissible RX path — see the module docstring, "Aggregation".
_VERDICT_RANK = {"PASS": 0, "WARN": 1, "FAIL": 2}

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


def _candidate_rx_seeds(text: str) -> List[Tuple[str, str]]:
    """Return [(signal, route)] for every plausible RX source in this file.

    `route` is "inout_pad" for a bidirectional pad declaration and
    "rx_port" for an RX-shaped input port. The caller decides which
    routes are admissible in which file — see the module docstring,
    Detection §2. Keeping the routes distinct is what lets a generic
    `*_in` port stay out of the FAIL population without dropping it
    from the file scan.
    """
    seeds: List[Tuple[str, str]] = []
    for m in _INOUT_RE.finditer(text):
        seeds.append((m.group(1), "inout_pad"))
    for m in _RX_PORT_RE.finditer(text):
        seeds.append((m.group(1), "rx_port"))
    # Deduplicate on the signal name, keep order (first route wins).
    seen: Set[str] = set()
    uniq: List[Tuple[str, str]] = []
    for s, route in seeds:
        if s not in seen:
            seen.add(s)
            uniq.append((s, route))
    return uniq


def _filename_says_rx_phy(path: Path) -> bool:
    """True iff the FILE NAME declares this module to be the RX phy."""
    name = path.stem.lower()
    return any(h in name for h in _FILENAME_HINTS)


def _is_rx_phy_file(path: Path, text: str) -> bool:
    if _filename_says_rx_phy(path):
        return True
    if _INOUT_RE.search(text):
        return True
    return False


def _seed_is_admissible(route: str, name_says_rx_phy: bool) -> bool:
    """Detection §2 — which seeds may carry a project verdict.

    Route (a) `inout_pad`: a bidirectional pad IS the half-duplex
    single-wire bus, in any file.
    Route (b) `rx_port`: only where the FILE NAME says the module is
    the RX phy. `input wire cfg_in` on an arbitrary block is not a
    noisy single-wire bus and must not be able to mint a FAIL.
    """
    if route == "inout_pad":
        return True
    return name_says_rx_phy


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

    candidates: List[Tuple[Path, str, List[Tuple[str, str]]]] = []
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

    # Score EVERY admissible RX path on its own. The project verdict is
    # the worst of them (see module docstring, "Aggregation"): the old
    # `max(len(chain))` selection let the greenest pad in the design
    # answer for every other pad, which is what made the FAIL verdict
    # unreachable for a project that has both a compliant peripheral pad
    # and a non-compliant top-level bus.
    paths: List[dict] = []
    seen_chains: Set[Tuple[str, Tuple[str, ...]]] = set()
    seeds_examined = 0
    for f, text, seeds in candidates:
        name_says_rx_phy = _filename_says_rx_phy(f)
        try:
            rel = f.relative_to(project)
        except ValueError:
            rel = f
        for seed, route in seeds:
            if not _seed_is_admissible(route, name_says_rx_phy):
                continue
            seeds_examined += 1
            chain = _build_sync_chain(text, seed)
            if not chain:
                continue
            key = (str(rel), tuple(chain))
            if key in seen_chains:
                # Two seeds (pad + its comb rename) resolving to the
                # same flop chain are ONE RX path, not two.
                continue
            seen_chains.add(key)
            found, evidence, n_terms = _filter_uses_chain(text, set(chain))
            if len(chain) < 3:
                verdict = "FAIL"
            elif not found:
                verdict = "WARN"
            else:
                verdict = "PASS"
            # file:line of the last NBA in this chain.
            last_ff = chain[-1]
            line_no = 0
            for idx, line in enumerate(text.splitlines(), start=1):
                if re.search(rf"\b{re.escape(last_ff)}\s*<=", line):
                    line_no = idx
            paths.append({
                "wrapper_file": str(rel),
                "rx_seed": seed,
                "seed_route": route,
                "sync_chain": chain,
                "chain_length": len(chain),
                "filter_found": found,
                "filter_evidence": evidence,
                "filter_terms_in_chain": n_terms,
                "verdict": verdict,
                "loc": f"{rel}:{line_no}" if line_no else str(rel),
            })

    summary["rx_paths"] = paths
    summary["rx_paths_examined"] = len(paths)
    summary["rx_seeds_admissible"] = seeds_examined

    if not paths:
        summary["skip_reason"] = (
            f"no synchronizer chain found from any of the "
            f"{seeds_examined} admissible RX seed(s) in "
            f"{len(candidates)} candidate file(s)"
        )
        return failures, warnings, summary

    # Governing path = worst verdict; ties broken by the shortest chain
    # and then by file order, so the report names the most-degraded RX
    # path rather than an arbitrary one.
    worst = min(
        paths,
        key=lambda p: (-_VERDICT_RANK[p["verdict"]], p["chain_length"],
                       p["wrapper_file"]),
    )
    # Back-compatible top-level keys: they now describe the GOVERNING
    # path instead of the best-looking one.
    for k in ("wrapper_file", "rx_seed", "sync_chain", "chain_length",
              "filter_found", "filter_evidence", "filter_terms_in_chain"):
        summary[k] = worst[k]
    summary["verdict"] = worst["verdict"]

    for p in paths:
        if p["verdict"] == "FAIL":
            failures.append(
                f"RX_SYNC_CHAIN_TOO_SHORT — {p['loc']}: chain length "
                f"{p['chain_length']} < 3 from RX seed {p['rx_seed']!r} "
                f"(chain={p['sync_chain']!r}). A 2-FF synchroniser "
                f"resolves metastability but does not filter 1-cycle "
                f"glitches; cable EMI / open-drain edge ringing on real "
                f"silicon will corrupt frame decoding (sim-PASS / "
                f"hardware-FAIL pattern). See rig spec Layer 13 — RX "
                f"deglitch filter required."
            )
        elif p["verdict"] == "WARN":
            chain = p["sync_chain"]
            warnings.append(
                f"RX_DEGLITCH_FILTER_MISSING — {p['wrapper_file']}: "
                f"≥3-stage synchroniser present (chain={chain!r}) but "
                f"no AND/OR-based 2-of-2 deglitch filter detected on "
                f"the chain output. Add `assign rx_stable = "
                f"{chain[-1]} & {chain[-2]};` (or OR variant). "
                f"Without deglitch, single-cycle glitches still "
                f"propagate — see rig spec Layer 13."
            )

    return failures, warnings, summary


def _print_rx_path_table(summary: dict) -> None:
    """Print the denominator: every RX path that was scored, and its own
    verdict. Without this the reader cannot tell whether a project-level
    PASS covered one pad or ten."""
    paths = summary.get("rx_paths") or []
    if not paths:
        return
    print(f"  RX paths scored: {len(paths)} (project verdict = worst)")
    for p in paths:
        print(
            f"    [{p['verdict']:<4}] {p['wrapper_file']} "
            f"seed={p['rx_seed']!r} route={p['seed_route']} "
            f"chain={p['chain_length']} filter={p['filter_found']}"
        )


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
        n_paths = summary.get("rx_paths_examined", 0)
        print(
            f"PASS — {n_paths} RX path(s) examined, all compliant; "
            f"weakest uses {len(chain)}-stage synchroniser + "
            f"deglitch filter ({ev[:80]})"
        )
        _print_rx_path_table(summary)
        return 0

    if not failures and warnings:
        # WARN-only is non-blocking.
        for w in warnings:
            print(f"WARN — {w}")
        _print_rx_path_table(summary)
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — silenced by waivers.{WAIVER_KEY}: "
            f"{rationale[:80]}…"
        )
        for fmsg in failures:
            print(f"  • {fmsg}")
        _print_rx_path_table(summary)
        return 0

    print(f"FAIL — {len(failures)} RX deglitch filter issue(s):")
    for fmsg in failures:
        print(f"  • {fmsg}")
    for w in warnings:
        print(f"  • (WARN) {w}")
    _print_rx_path_table(summary)
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
