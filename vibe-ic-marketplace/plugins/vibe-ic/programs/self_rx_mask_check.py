#!/usr/bin/env python3
"""
self_rx_mask_check.py — Verify any *_oe / *_drive_low output that drives a
tristate / open-drain pin has the corresponding RX path masked HIGH (or
otherwise gated) while the driver is active.

THE PROBLEM
-----------
Open-drain / tristate buses are common (I2C, single-wire, ID-bus). When
the device drives the wire LOW with `pin_oe=1`, the RX path on the same
device sees its OWN drive — and unless the RX is gated, the FSM treats
its own LOW as an external start-of-frame, corrupting the next byte.

The vendor run shipped a self-RX issue exactly because the agent never
masked the RX path during TX-active windows.

Heuristic
---------
For each `<sig>_oe` (or `<sig>_drive_low`, `<sig>_drive_lo`) found as an
RTL signal:
  - Look for the corresponding RX-side path. By naming convention, the
    RX comes from a synchronised input named like `<sig>_pin_*sync*` /
    `<sig>_in_*` / `<sig>_rx*`.
  - Verify that any sequential or combinational use of the RX signal is
    gated by `~<sig>_oe` (or `<sig>_oe == 0`, or `!<sig>_oe`,
    or `<sig>_oe == 1'b0`) somewhere in the path. The simplest pattern
    is an AND with `~<sig>_oe` or an `if (!<sig>_oe)` guard.

USAGE
-----
    python3 self_rx_mask_check.py rtl/ \\
        --pair "id_bus" --pair "sda_pin" \\
        --json reports/gates/self_rx_mask.json

EXIT CODES
----------
    0 — every detected `*_oe` signal has its matching RX path masked.
    1 — at least one OE has no detectable RX-side gate.
    2 — IO / argument error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Kimi-scale fix — this gate audits AUTHORED RTL SOURCE. Directory targets
# route through the shared collector (canonical phase2/stage1/rtl preferred;
# generated netlist/sim/verify outputs + >8MB files excluded on fallback) so a
# 342 MB emitted netlist can never enter the per-line alias/mask scan again
# (see _specrtl_common.rtl_source_files for the full scale rationale).
try:
    from _specrtl_common import rtl_source_files
except ImportError:                      # packaged relative import
    from ._specrtl_common import rtl_source_files


@dataclass
class Finding:
    severity: str
    rule: str
    file: str
    line: int
    message: str


def _read(p: Path) -> str:
    try:
        return p.read_text(errors="replace")
    except OSError:
        return ""


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _find_oe_signals(text: str) -> List[str]:
    """Find every signal whose name ends in _oe / _drive_low / _drive_lo /
    _drive_low_q (case-insensitive)."""
    out: Set[str] = set()
    pat = re.compile(
        r"\b([A-Za-z_]\w*?(?:_oe|_drive_low|_drive_lo|_oen))\b",
        re.IGNORECASE,
    )
    for m in pat.finditer(text):
        out.add(m.group(1))
    return sorted(out)


# v1.6.92 (issue #24): walk wire-alias chains so both `~<alias>` and
# `~<literal>` count as evidence of masking. The phase2 emitter
# oscillated across v1.6.88-91 between writing the literal name
# (`id_bus_drive_low`) and the alias (`id_bus_oe = id_bus_drive_low`)
# inside the mask expression; the gate's one-directional canonicalization
# meant it would accept one form and reject the other in lock-step with
# the emitter, producing 4 release cycles of fixture-flipping with no
# durable PASS. Fix is gate-side: build alias equivalence classes from
# `wire <a> = <b>;` declarations and accept `~<x>` for any `x` in the
# OE's class.
_RE_WIRE_ALIAS = re.compile(
    r"\bwire\s+(?:\[[^\]]*\]\s*)?(\w+)\s*=\s*(\w+)\s*;",
    re.MULTILINE,
)
_RE_ASSIGN_ALIAS = re.compile(
    r"\bassign\s+(\w+)\s*=\s*(\w+)\s*;",
    re.MULTILINE,
)


def _build_alias_equivalence(rtl_text: str) -> Dict[str, Set[str]]:
    """For each `wire <a> = <b>;` or `assign <a> = <b>;` declaration,
    build a bidirectional equivalence map. Returns dict mapping each
    name to the set of all names in its connected component."""
    edges: Dict[str, Set[str]] = {}
    for pat in (_RE_WIRE_ALIAS, _RE_ASSIGN_ALIAS):
        for m in pat.finditer(rtl_text):
            a, b = m.group(1), m.group(2)
            edges.setdefault(a, set()).add(b)
            edges.setdefault(b, set()).add(a)
    eq: Dict[str, Set[str]] = {}
    for start in edges:
        if start in eq:
            continue
        component: Set[str] = set()
        queue = [start]
        while queue:
            n = queue.pop()
            if n in component:
                continue
            component.add(n)
            queue.extend(edges.get(n, set()) - component)
        for n in component:
            eq[n] = component
    return eq


def _names_in_class(name: str, eq: Dict[str, Set[str]]) -> Set[str]:
    """Return the set of all names equivalent to `name` (always
    includes `name` itself, even if it has no aliases)."""
    return eq.get(name, {name})


def _likely_rx_signal(oe_name: str, all_idents: Set[str]) -> Optional[str]:
    """Given an OE name (e.g. 'id_bus_oe'), guess the corresponding RX
    signal name by stripping the suffix and searching for `<base>_rx*`,
    `<base>_in_sync`, `<base>_pin_sync*`, `<base>_synced`, or a registered
    form `<base>_d`/`<base>_q`/`<base>_q1`/`<base>_<n>`. The registered
    forms catch the vendor-benchmark case where the agent named the
    sync'd bus signal `id_bus_rx_q1` — which the literal-suffix list
    silently missed."""
    base = re.sub(r"_(?:oe|drive_low|drive_lo|oen)$", "", oe_name,
                  flags=re.IGNORECASE)
    candidates = []
    for ident in all_idents:
        if ident == oe_name:
            continue
        l = ident.lower()
        b = base.lower()
        if l.startswith(b + "_") or l.startswith(b):
            # Original input/sync hints
            if any(tok in l for tok in
                   ("_rx", "_in", "_synced", "_sync", "_pin")):
                candidates.append(ident)
                continue
            # Registered / pipeline forms: <base>_d, <base>_q, <base>_q<n>
            tail = l[len(b):].lstrip("_")
            if tail and re.fullmatch(r"(?:d|q\d*|r|reg|ff)\d*", tail):
                candidates.append(ident)
    # Prefer the shortest / most "synced" name
    candidates.sort(key=lambda s: ("synced" not in s.lower(), len(s)))
    return candidates[0] if candidates else None


def audit(rtl_target: Path,
          pair_hints: List[str]) -> List[Finding]:
    findings: List[Finding] = []
    if rtl_target.is_file():
        files = [rtl_target]
    else:
        # Kimi-scale fix: shared authored-RTL collector (canonical
        # phase2/stage1/rtl preferred; generated outputs excluded on
        # fallback). The v0.119.27/28 testbench filter below still applies —
        # tb-named files can live INSIDE the canonical rtl dir too.
        files = rtl_source_files(rtl_target)
        # v0.119.27: exclude testbench files. The agent often invokes
        # this gate against the project root rather than rtl/, which
        # pulls in `tb/tb_*.v` / `*_tb.sv` — and any `*_drive_low`
        # signal in a sim-only file would be wrongly treated as RTL.
        # Filter on standard testbench naming conventions.
        def _is_tb(p: Path) -> bool:
            n = p.name.lower()
            if n.startswith("tb_") or n.endswith("_tb.v") or \
               n.endswith("_tb.sv") or n.endswith("_tb.svh"):
                return True
            # v0.119.28: extend dir-name set with `verification`,
            # `sim_unit`, `sva` so common alternative testbench layouts
            # are also excluded. Match exact directory components only —
            # we do NOT substring-match on `verif*` because that would
            # accidentally exclude legitimately-named modules like
            # `verifier_axi.v` if used as a directory name.
            for parent in p.parts:
                pl = parent.lower()
                if pl in ("phase2/stage1/tb", "phase2/stage1/sim", "tb", "tests", "testbench", "sim", "simulation", "verif", "verification", "sim_unit", "sva"):
                    return True
            return False
        files = [p for p in files if not _is_tb(p)]
    if not files:
        findings.append(Finding(
            "WARN", "no_rtl_files", str(rtl_target), 0,
            f"no .v/.sv under {rtl_target}",
        ))
        return findings

    # Build a global identifier set (across all files) for RX-name guessing.
    all_idents: Set[str] = set()
    file_texts: Dict[Path, str] = {}
    for f in files:
        text = _strip_comments(_read(f))
        file_texts[f] = text
        for m in re.finditer(r"\b([A-Za-z_]\w*)\b", text):
            all_idents.add(m.group(1))

    # v1.6.92 (issue #24): build alias equivalence classes across all
    # files so the proximity-scan can accept any alias of an OE name in
    # the mask expression. Concatenate file texts so cross-file aliases
    # also collapse into one class (rare in practice — chip_top usually
    # owns the alias declaration — but cheap to support).
    alias_eq = _build_alias_equivalence("\n".join(file_texts.values()))

    # Aggregate OE list — from --pair hints + auto-detected suffix names
    oe_signals: Set[str] = set()
    for f, text in file_texts.items():
        for s in _find_oe_signals(text):
            oe_signals.add(s)
    for hint in pair_hints:
        # Hint is the BASE (e.g. "id_bus"); look for id_bus_oe or id_bus_drive_low
        for ident in all_idents:
            if ident.lower().startswith(hint.lower()) and re.search(
                r"_(?:oe|drive_low|drive_lo|oen)$", ident, re.IGNORECASE):
                oe_signals.add(ident)

    if not oe_signals:
        findings.append(Finding(
            "INFO", "no_oe_signals_found", str(rtl_target), 0,
            "no `*_oe` / `*_drive_low` / `*_oen` signals detected; nothing "
            "to check.",
        ))
        return findings

    for oe in sorted(oe_signals):
        rx = _likely_rx_signal(oe, all_idents)
        if rx is None:
            findings.append(Finding(
                "WARN", "rx_signal_not_found", "(none)", 0,
                f"detected OE {oe!r} but could not auto-find a matching "
                f"RX signal — pass `--pair <base>` to disambiguate, or "
                f"verify the design intentionally does not have an RX "
                f"path for this driver.",
            ))
            continue

        # Look for usage of `rx` that is GATED by `~oe`, `!oe`, or
        # `oe == 0`. We accept any of:
        #   ... rx ... & ~oe
        #   ... rx ... && !oe
        #   if (!oe) ... rx ...
        #
        # v1.6.92 (issue #24): accept any name in the OE's alias
        # equivalence class. The phase2 emitter has historically
        # vacillated between writing the literal OE name
        # (`id_bus_drive_low`) and a wire alias of it
        # (`id_bus_oe = id_bus_drive_low;` — "alias for human readability"
        # then `~id_bus_oe` in the mask). Either form should satisfy the
        # gate as long as the alias chain is declared.
        oe_aliases = _names_in_class(oe, alias_eq)
        oe_alt = "(?:" + "|".join(re.escape(n) for n in sorted(oe_aliases)) + ")"
        # Likewise accept the rx side under any alias (rare in practice
        # but symmetric — keeps the | branch general).
        rx_aliases = _names_in_class(rx, alias_eq)
        rx_alt = "(?:" + "|".join(re.escape(n) for n in sorted(rx_aliases)) + ")"
        gated = False
        for f, text in file_texts.items():
            # Find every line that mentions `rx` (or any alias of it)
            for line_no, line in enumerate(text.splitlines(), start=1):
                if any(n in line for n in rx_aliases):
                    # Check ~/!oe presence in nearby lines (3 lines)
                    around_start = max(0, line_no - 4)
                    around = "\n".join(text.splitlines()[around_start:line_no + 2])
                    if (re.search(r"[~!]\s*\b" + oe_alt + r"\b", around)
                        or re.search(r"\b" + oe_alt + r"\s*==\s*1'?\s*b?0",
                                     around)
                        or re.search(r"\b" + oe_alt + r"\s*==\s*0\b", around)
                        # OR-with-OE: rx_masked = rx | oe (force HIGH while driving)
                        or re.search(r"\|\s*\b" + oe_alt + r"\b", around)
                        or re.search(r"\b" + oe_alt + r"\s*\|\s*\b" + rx_alt + r"\b",
                                     around)):
                        gated = True
                        break
            if gated:
                break

        if not gated:
            findings.append(Finding(
                "ERROR",
                "self_rx_not_masked",
                "(none)", 0,
                f"OE {oe!r} drives a tristate/open-drain pin but the "
                f"corresponding RX signal {rx!r} is not gated by "
                f"~{oe} / !{oe} / {oe}==0 anywhere in the design. The "
                f"FSM will see the device's own drive as external traffic "
                f"and corrupt the next byte. Insert `assign rx_masked = "
                f"{rx} | {oe};` (or equivalent) and consume rx_masked.",
            ))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    ap.add_argument("rtl", help="RTL file or directory")
    ap.add_argument("--pair", action="append", default=[],
                    help="Hint signal base (e.g. 'id_bus' or 'sda_pin'); repeatable")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH')
    args = ap.parse_args(argv)

    target = Path(args.rtl)
    if not target.exists():
        print(f"error: target not found: {target}", file=sys.stderr)
        return 2

    findings = audit(target, args.pair)
    errors = [f for f in findings if f.severity == "ERROR"]

    report = {
        "target": str(target),
        "errors": len(errors),
        "findings": [asdict(f) for f in findings],
        "verdict": "PASS" if not errors else "FAIL",
    }

    if args.json:
        _txt = json.dumps(report, indent=2)
        if args.json == '-':
            print(_txt)
        else:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(_txt + "\n")
    else:
        for f in findings:
            print(f"[{f.severity}] {f.rule} @ {f.file}:{f.line}: {f.message}")
        print(f"\n{len(errors)} error(s); verdict: {report['verdict']}")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
