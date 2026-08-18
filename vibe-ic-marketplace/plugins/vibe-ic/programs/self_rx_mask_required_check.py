#!/usr/bin/env python3
"""self_rx_mask_required_check.py — Wave 16 silent-bug gate.

v0.119.59 (Wave 27): upgraded from advisory → strict-blocking.  Any
failure mode now produces a hard FAIL (exit 1).  No WARN level is
emitted.  Honours the documented waiver (≥40 chars) only.

Top-level wrapper for a half-duplex single-wire bus must MASK the RX
path during DUT TX — otherwise the chip samples its own TX-LOW as
external bus traffic and the FSM treats it as a host BR / bit, which
re-classifies a real protocol byte as garbage.

Companion to (NOT a replacement for) `self_rx_mask_check`. The latter
walks every `*_oe` signal in the project and looks for a `~oe` gate.
This gate is targeted: it locates the TOP-LEVEL wrapper (the file that
declares `inout` + open-drain pad + drives an internal RX sync chain)
and verifies the canonical OR-mask pattern:

    wire <id_in> = (<tx_drive_low> | <wake_oe>) ? 1'b1 : <id_ff_sync>;

(Or AND-mask: `<id_in> = <id_ff_sync> | <oe>` — same effect on
open-drain bus where DUT-active = LOW.)

Detection
=========
1. Find candidate top-level wrappers — heuristic: file declares
   `inout` AND has an open-drain `assign <bus> = ... ? 1'b0 : 1'bz`
   (or `1'bZ`) pattern.
2. Identify the bus signal (the LHS of the open-drain assign).
3. Scan the same file for the RX sync chain — a `_ff1` / `_ff2` /
   `_q1` / `_q2` / `_sync` form fed from the bus signal.
4. **PASS** when the consumer of that sync output is masked HIGH
   during TX:
     (a) `assign <id_in> = (<oe>...) ? 1'b1 : <ff>;`
     (b) `wire   <id_in> = <ff> | <oe>;`
     (c) `if (!<oe>) <id_in> <= <ff>; else <id_in> <= 1'b1;`
   The mask must reference at least one of the OE-family signals
   discovered in the same file (`*_oe`, `*_drive_low`, `tx_drive_low`,
   `wake_oe`, `tx_active`, `bus_oe`).
5. **FAIL** when the bus sync output flows directly into the RX phy
   without any OE-family gate.
6. **SKIP** when no top-level wrapper / open-drain pad found.
7. Honors waiver `self_rx_no_mask_intentional` (≥40 chars).

Chip-AGNOSTIC: bus, OE, and sync-FF signal names are auto-discovered.

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
from typing import List, Optional, Set, Tuple
import _path_layout as _pl

WAIVER_KEY = "self_rx_no_mask_intentional"
WAIVER_MIN_LEN = 40


# Open-drain pattern: `assign <bus> = (<expr>) ? 1'b0 : 1'bz;`
# (variants: with/without parens, lowercase z).
_OPEN_DRAIN_RE = re.compile(
    r"assign\s+(\w+)\s*=\s*([^?;]+?)\s*\?\s*1'b0\s*:\s*1'b[zZ]\s*;",
)

_INOUT_RE = re.compile(r"\binout\s+(?:logic\s+|wire\s+|reg\s+)?(\w+)\b")

# Sync chain assignment: `<x>_ff1 <= <bus>;` or `<x>_q1 <= <bus>;`
# We capture the destination ff name so we can find downstream consumers.
_SYNC_FF_RE = re.compile(
    r"(\w+(?:_ff\d*|_q\d*|_sync\w*|_d\d*))\s*<=\s*(\w+)\s*;",
)

# OE family — `*_oe`, `*_drive_low`, `*_drive_lo`, `tx_active`, `tx_drv`,
# `wake_oe`, `bus_oe`, `tx_drive_low`, `wake_drv`. Case-insensitive.
#
# Wave 35 (v0.119.67) — extend with `*_busy`, `tx_busy`, and accept
# `*_drive_low_*` (with suffixes like `_pre`/`_d`/`_q`). The earlier
# regex required `drive_low\b` exactly; agents that pipeline the OE
# (`id_bus_drive_low_pre <= id_bus_drive_low_fsm | wake_oe`) emitted
# `*_drive_low_pre` and got missed.
_OE_FAMILY_RE = re.compile(
    r"\b("
    r"\w+_(?:oe|oen|drv|drive_low|drive_lo)(?:_\w+)?"
    r"|tx_active|wake_oe|wake_drv|tx_busy|rx_busy|\w+_busy"
    r")\b",
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


def _find_top_wrapper(rtl_files: List[Path]) -> Optional[Tuple[Path, str]]:
    """Return (path, source-no-comments) for the first file that has
    BOTH an `inout` port AND an open-drain assign."""
    for f in rtl_files:
        try:
            raw = f.read_text(errors="ignore")
        except OSError:
            continue
        text = _strip_comments(raw)
        if not _INOUT_RE.search(text):
            continue
        if not _OPEN_DRAIN_RE.search(text):
            continue
        return f, text
    return None


def _bus_signal_from_open_drain(text: str) -> Optional[str]:
    m = _OPEN_DRAIN_RE.search(text)
    if not m:
        return None
    return m.group(1)


def _oe_signals_in_file(text: str) -> Set[str]:
    return {m.group(1) for m in _OE_FAMILY_RE.finditer(text)}


def _sync_ff_chain(text: str, bus: str) -> List[str]:
    """Return list of FF names that capture the bus signal directly OR
    transitively (`ff2 <= ff1; ff1 <= bus;`)."""
    direct: Set[str] = set()
    indirect: dict[str, str] = {}
    for m in _SYNC_FF_RE.finditer(text):
        dst, src = m.group(1), m.group(2)
        if src == bus:
            direct.add(dst)
        else:
            indirect[dst] = src
    # Add transitive: any ff whose src is in `direct`
    chain = set(direct)
    changed = True
    while changed:
        changed = False
        for dst, src in indirect.items():
            if src in chain and dst not in chain:
                chain.add(dst)
                changed = True
    return sorted(chain)


def _has_mask(text: str, ff_names: List[str], oe_signals: Set[str],
              bus: str = "") -> Tuple[bool, str]:
    """Look for a mask pattern that consumes any ff_name and forces
    the result HIGH (or guards via !oe) using an oe-family signal.

    Wave 35 (v0.119.67) — behavior-based fix: also accept masks
    whose RHS-non-OE side is the bus signal itself (synchronizer is a
    module instance like `cdc_sync_pad u_sync(.async_in(id_bus_in_raw),
    .sync_out(id_bus_in));` and the mask reads `id_bus_in` directly,
    NOT a `*_ff*`-named signal). The earlier _SYNC_FF_RE only matched
    inline `<x>_ff* <= bus;` NBAs and missed module-instance
    synchronizers. The behavior is identical: any ternary that gates
    the bus value HIGH using an OE-family signal masks self-RX.

    Returns (has_mask, evidence_line).
    """
    if not oe_signals:
        return False, ""

    # Wave 35 — chain candidates include the FF chain AND any
    # post-sync alias name that derives from the bus (broadly: signals
    # named `<bus>_in*` / `<bus>_sync*` / `id_in` / `id_bus_in`).
    candidates: Set[str] = set(ff_names)
    if bus:
        # Common post-sync naming variants in fresh-agent RTL.
        for suf in ("_in", "_in_masked", "_sync", "_synced",
                    "_in_sync", "_q", "_d"):
            candidates.add(bus + suf)
        # Also add the bus name itself: top-level may pipeline as
        # `wire id_bus_in = id_bus;` then mask `id_bus_in`.
        candidates.add(bus)
    # Generic "post-sync" names that any agent might emit.
    candidates.update({
        "id_in", "rx_in", "bus_in", "id_bus_in", "rx_data",
        "rx_sync", "rx_q", "id_q", "rx_d",
    })

    if not candidates:
        return False, ""

    # Wave 35 — also include any signal that appears on the LHS of an
    # NBA whose RHS is a sync-named signal: covers the
    # `cdc_sync_pad u_pad(.sync_out(id_bus_in))` case where the consumer
    # of `id_bus_in` is the mask. The fact that bus_in is read inside
    # a ternary that produces a HIGH-on-oe value is what matters.
    cand_alt = "|".join(re.escape(n) for n in candidates)
    oe_alt = "|".join(re.escape(o) for o in oe_signals)

    # Pattern (a): `assign|wire X = (<oe-expr>) ? 1'b1 : <cand>;`
    pat_a = re.compile(
        rf"(?:assign|wire)\s+\w+\s*=\s*\(?\s*(?:[~!]?\s*(?:{oe_alt})"
        rf"(?:\s*(?:\|\||&&|\||&)\s*[~!]?\s*\w+)*)\s*\)?\s*\?\s*"
        rf"1'b1\s*:\s*(?:{cand_alt})",
        re.IGNORECASE,
    )
    m = pat_a.search(text)
    if m:
        return True, m.group(0)

    # Pattern (b): `wire|assign X = <cand> | <oe>` (or `<oe> | <cand>`)
    pat_b1 = re.compile(
        rf"(?:assign|wire)\s+\w+\s*=\s*(?:{cand_alt})\s*\|\s*"
        rf"(?:{oe_alt})\b",
        re.IGNORECASE,
    )
    pat_b2 = re.compile(
        rf"(?:assign|wire)\s+\w+\s*=\s*(?:{oe_alt})\s*\|\s*"
        rf"(?:{cand_alt})\b",
        re.IGNORECASE,
    )
    for pat in (pat_b1, pat_b2):
        m = pat.search(text)
        if m:
            return True, m.group(0)

    # Pattern (c): `if (!<oe>) <cand>` (procedural mask)
    pat_c = re.compile(
        rf"if\s*\(\s*[~!]\s*(?:{oe_alt})\s*\).*?(?:{cand_alt})",
        re.IGNORECASE | re.DOTALL,
    )
    m = pat_c.search(text)
    if m:
        snippet = m.group(0)
        if len(snippet) < 200:
            return True, snippet.replace("\n", " ").strip()

    return False, ""


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

    top = _find_top_wrapper(rtl)
    if top is None:
        summary["skip_reason"] = "no top-level inout + open-drain wrapper found"
        return failures, summary

    f, text = top
    try:
        rel = f.relative_to(project)
    except ValueError:
        rel = f
    bus = _bus_signal_from_open_drain(text)
    summary["wrapper_file"] = str(rel)
    summary["bus_signal"] = bus or ""

    oe_signals = _oe_signals_in_file(text)
    summary["oe_signals"] = sorted(oe_signals)

    if not bus or not oe_signals:
        summary["skip_reason"] = (
            "no usable bus / OE-family signals identified in wrapper"
        )
        return failures, summary

    ff_names = _sync_ff_chain(text, bus)
    summary["sync_ff_names"] = ff_names

    has_mask, evidence = _has_mask(text, ff_names, oe_signals, bus=bus)
    summary["mask_evidence"] = evidence

    if has_mask:
        return failures, summary

    failures.append(
        f"SELF_RX_MASK_MISSING — {rel}: top-level wrapper drives bus "
        f"{bus!r} via open-drain (oe={sorted(oe_signals)!r}), but the "
        f"RX path consuming {ff_names!r} is NOT masked HIGH while the "
        f"DUT is driving. The chip will sample its own TX-LOW as a "
        f"host BR/bit. Insert one of:\n"
        f"    wire id_in = (tx_drive_low | wake_oe) ? 1'b1 : id_ff2;\n"
        f"    wire id_in = id_ff2 | tx_drive_low;\n"
        f"    if (!tx_drive_low) id_in <= id_ff2; else id_in <= 1'b1;"
    )
    return failures, summary


def main(argv: List[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(
            "Usage: self_rx_mask_required_check.py "
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
            "program": "self_rx_mask_required_check",
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
            f"PASS — top-level wrapper masks RX path during DUT TX "
            f"({summary.get('mask_evidence', '')[:80]})"
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

    print(f"FAIL — {len(failures)} self-RX mask issue(s):")
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
