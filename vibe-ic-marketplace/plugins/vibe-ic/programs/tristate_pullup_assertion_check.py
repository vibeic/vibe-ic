#!/usr/bin/env python3
"""tristate_pullup_assertion_check.py — BACKLOG-v11 P1.1.

Verify that every `inout` port driven `1'bz` somewhere in the RTL has a
matching weak pull-up declared in the FPGA constraint file (Quartus
QSF / Vivado XDC) — or an explicit external pull-up declared in the
L11 board / packaging spec.

Motivation
==========

v0.116 <benchmark> declared `inout GPIO_id_bus` with `1'bz` tristate driver
but the project QSF had no `WEAK_PULL_UP_RESISTOR ON` assignment. With
no external pull-up, the floating bus made `rx_phy`'s 2-stage
synchroniser glitch on ambient noise, spuriously firing
`rx_bit_vld` and starving `wake_ctrl`'s tITO timer. Caught only after
scope showed random rx_bit_vld glitches with no host activity.

Gate behaviour
==============

For every top-level `inout` port:
  1. Scan all RTL files for `<port> <= 1'bz` (or `assign <port> = ...
     ? <expr> : 1'bz`) drivers. If none, port is always-driven —
     skip.
  2. If a tristate driver exists, check the FPGA constraint file
     (`*.qsf` or `*.xdc`) for one of:
       (a) Quartus QSF: `set_instance_assignment -name
           WEAK_PULL_UP_RESISTOR ON -to <pin>`
       (b) Vivado XDC: `set_property PULLUP true [get_ports <pin>]`
       OR the L11 board / packaging spec declares
       `external_pullup: [<pin>]`.
  3. If no pull-up evidence exists, emit `TRISTATE_NO_PULLUP` ERROR.

False-alert guards
==================

Silent in any of:
  - Project has no QSF / XDC (= ASIC target — different rules apply,
    package-level pull-ups are documented in L11/datasheet only).
  - `inout` port has no `1'bz` driver (always-driven bidir bus).
  - Constraint file declares pull-up for the matching pad.
  - L11 declares `external_pullup: [<pad_name>]` (board-side pull-up).
  - Top RTL module has no `inout` ports.

Severity: ERROR (silent floating-bus bugs are class-of-failure).

Exit codes: 0 PASS / 1 FAIL / 2 skip
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from gate_utils import find_modules, find_rtl_files as _rtl_files
from gate_utils import parse_io_ports, read_text as _read


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""


# ---------------------------------------------------------------------------
# Constraint file parsing
# ---------------------------------------------------------------------------

def _find_constraint_files(project: Path) -> list[Path]:
    out: list[Path] = []
    for ext in ("*.qsf", "*.xdc", "*.sdc"):
        for f in project.rglob(ext):
            if not f.is_file():
                continue
            # Skip generated dirs
            parts = set(f.relative_to(project).parts[:-1])
            if parts & {"db", "incremental_db", "output_files", "build",
                        ".git", "__pycache__"}:
                continue
            out.append(f)
    return out


_QSF_PULLUP_RE = re.compile(
    r"set_instance_assignment\s+-name\s+WEAK_PULL_UP_RESISTOR\s+ON"
    r"[\s\S]*?-to\s+(\S+)",
    re.IGNORECASE,
)
_XDC_PULLUP_RE = re.compile(
    # Capture token may include `[bit:bit]` slice form (e.g.
    # `gpio_bus[7:0]`) — Vivado very commonly declares pull-ups on
    # bus-slices. Pre-v0.118-stable used (\w+) which silently truncated
    # `gpio_bus[7:0]` → `gpio_bus` and produced false-ERROR if the RTL
    # inout port name was the bare `gpio_bus`.
    # Captures `name` or `name[bit:bit]` / `name[bit]`. Two-segment
    # form: bare word, then optional bracketed slice in a non-greedy
    # group so the trailing `]` of `[get_ports …]` doesn't get eaten.
    r"set_property\s+PULLUP\s+true\s+\[\s*get_ports\s+\{?\s*"
    r"(\w+(?:\[[^\]]+\])?)",
    re.IGNORECASE,
)


def _normalise_pad(name: str) -> str:
    """Strip trailing `[bit:bit]` / `[bit]` slice so a bus-slice
    constraint and a bare RTL inout port name compare equal.

    Examples:
        gpio_bus[7:0]  -> gpio_bus
        gpio_bus[3]    -> gpio_bus
        plain_pin      -> plain_pin
    """
    return re.sub(r"\[[^\]]*\]\s*$", "", name).strip()
# Detect FPGA target (any of these = FPGA, none = ASIC)
_QSF_FAMILY_RE = re.compile(
    r"set_global_assignment\s+-name\s+FAMILY\s+\"?([^\s\"]+)",
    re.IGNORECASE,
)


def _pullup_pads(constraint_files: list[Path]) -> set[str]:
    """Return the set of pad / port names with declared pull-ups.

    Both the raw-captured token AND the normalised form (slice
    stripped) are added — so downstream membership tests succeed
    whether the RTL inout port matches the slice form or the base
    name. Example: XDC declares `gpio_bus[7:0]` for an inout port
    declared `inout [7:0] gpio_bus` in RTL — both `gpio_bus[7:0]`
    AND `gpio_bus` end up in the returned set.
    """
    pads: set[str] = set()
    for f in constraint_files:
        text = _read(f)
        for m in _QSF_PULLUP_RE.finditer(text):
            raw = m.group(1).strip()
            pads.add(raw)
            pads.add(_normalise_pad(raw))
        for m in _XDC_PULLUP_RE.finditer(text):
            raw = m.group(1).strip()
            pads.add(raw)
            pads.add(_normalise_pad(raw))
    return pads


def _qsf_pin_to_signal(constraint_files: list[Path]) -> dict[str, str]:
    """Map QSF/XDC pad name -> RTL signal name via location assignment.
    QSF: `set_location_assignment PIN_X1 -to gpio_id_bus`
    XDC: `set_property PACKAGE_PIN X1 [get_ports gpio_id_bus]`
    """
    out: dict[str, str] = {}
    for f in constraint_files:
        text = _read(f)
        for m in re.finditer(
            r"set_location_assignment\s+(\S+)\s+-to\s+(\S+)",
            text, re.IGNORECASE,
        ):
            pin, sig = m.group(1), m.group(2)
            out[pin] = sig
            out[sig] = sig  # accept both pin name and signal name
        for m in re.finditer(
            r"set_property\s+PACKAGE_PIN\s+(\S+)\s+\[get_ports\s+(\S+)\s*\]",
            text, re.IGNORECASE,
        ):
            pin, sig = m.group(1), m.group(2)
            out[pin] = sig
            out[sig] = sig
    return out


def _is_fpga_target(constraint_files: list[Path]) -> bool:
    """True if any QSF/XDC/SDC declares an FPGA family or PACKAGE_PIN."""
    for f in constraint_files:
        text = _read(f)
        if _QSF_FAMILY_RE.search(text):
            return True
        if re.search(r"set_property\s+PACKAGE_PIN", text, re.IGNORECASE):
            return True
        if re.search(r"set_location_assignment", text, re.IGNORECASE):
            return True
    return False


# ---------------------------------------------------------------------------
# RTL scanning
# ---------------------------------------------------------------------------

def _top_module_inouts(rtl_files: list[Path]) -> list[tuple[str, Path]]:
    """Return [(inout_port_name, source_file)] for every inout port at any
    module top — heuristic: we don't pick a single top, so all inouts
    everywhere are candidates. Cross-checked against tristate drivers."""
    out: list[tuple[str, Path]] = []
    for f in rtl_files:
        rtl = _read(f)
        for spec in find_modules(rtl):
            _, _, inouts = parse_io_ports(spec.header)
            for sig in inouts:
                out.append((sig, f))
    return out


_TRISTATE_LITERAL = r"\d+\s*'\s*[bB]?[zZ]+"


def _has_tristate_driver(rtl_files: list[Path], sig: str) -> bool:
    """True if any RTL file has `<sig> <= <N>'bz...z` or
    `assign ... <N>'bz...z` referencing `sig`. Handles any bus width
    (1'bz, 8'bzzzzzzzz, etc.)."""
    for f in rtl_files:
        text = _read(f)
        if not text:
            continue
        # Non-blocking: `<sig> <= <N>'bz...`
        if re.search(rf"\b{re.escape(sig)}\s*<=\s*{_TRISTATE_LITERAL}", text):
            return True
        # Continuous: `assign <sig> = ... <N>'bz...` (single-line)
        if re.search(
            rf"assign\s+{re.escape(sig)}\s*=\s*[^;]*{_TRISTATE_LITERAL}",
            text,
        ):
            return True
        # Conditional `?:` form is covered by the above
    return False


# ---------------------------------------------------------------------------
# L11 board spec
# ---------------------------------------------------------------------------

def _l11_external_pullups(project: Path) -> set[str]:
    pads: set[str] = set()
    for cand in (
        list(project.glob("phase1/generated_docs/L11*.json"))
        + list(project.glob("L11*.json"))
        + list(project.glob("input/docs/L11*.json"))
    ):
        try:
            data = json.loads(_read(cand) or "{}")
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            ext = data.get("external_pullup")
            if isinstance(ext, list):
                pads.update(str(p) for p in ext)
            board = data.get("board") or {}
            if isinstance(board, dict):
                ext = board.get("external_pullup")
                if isinstance(ext, list):
                    pads.update(str(p) for p in ext)
    return pads


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------

def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "is_fpga_target": False,
        "inouts_examined": [],
        "tristate_drivers": [],
        "pullup_declared": [],
        "external_pullup": [],
        "skipped_reason": "",
    }

    constraint_files = _find_constraint_files(project)
    if not _is_fpga_target(constraint_files):
        summary["skipped_reason"] = (
            "no FPGA constraint file (no QSF/XDC) — ASIC target, "
            "package-level pull-ups documented in L11 / datasheet only"
        )
        return findings, summary
    summary["is_fpga_target"] = True

    rtl_files = _rtl_files(project)
    if not rtl_files:
        summary["skipped_reason"] = "no RTL files found"
        return findings, summary

    inouts = _top_module_inouts(rtl_files)
    if not inouts:
        summary["skipped_reason"] = "no inout ports declared in any module"
        return findings, summary

    pullup_pads = _pullup_pads(constraint_files)
    pin_to_sig = _qsf_pin_to_signal(constraint_files)
    external_pads = _l11_external_pullups(project)

    summary["pullup_declared"] = sorted(pullup_pads)
    summary["external_pullup"] = sorted(external_pads)

    # FPGA-pad scope: only validate inout ports that have a
    # `set_location_assignment` in the QSF (= they map to a physical FPGA
    # pad). Intermediate / chip-level inouts wired through the wrapper
    # are NOT FPGA pads — the wrapper-side inout (`GPIO[0]` in v099)
    # is the only one whose pull-up matters. This prevents false alerts
    # on chip-level RTL inouts (`id_bus` in v099) that flow through to
    # a properly-pulled-up wrapper pad.
    qsf_pads: set[str] = set()
    for f in constraint_files:
        text = _read(f)
        for m in re.finditer(
            r"set_location_assignment\s+\S+\s+-to\s+(\S+)",
            text, re.IGNORECASE,
        ):
            qsf_pads.add(m.group(1).strip())
        for m in re.finditer(
            r"set_property\s+PACKAGE_PIN\s+\S+\s+\[get_ports\s+(\S+)\s*\]",
            text, re.IGNORECASE,
        ):
            qsf_pads.add(m.group(1).strip())

    # Build the union of "covered" signal names — accept both QSF pin
    # name and the RTL signal name.
    covered: set[str] = set(pullup_pads) | set(external_pads)
    for pin in list(pullup_pads):
        if pin in pin_to_sig:
            covered.add(pin_to_sig[pin])

    # Dedupe inout names (a port can appear in multiple files via
    # hierarchical instantiation)
    seen: set[str] = set()
    for sig, src in inouts:
        if sig in seen:
            continue
        seen.add(sig)
        summary["inouts_examined"].append(
            f"{sig}@{src.relative_to(project)}"
        )
        if not _has_tristate_driver(rtl_files, sig):
            continue
        summary["tristate_drivers"].append(sig)
        if sig in covered:
            continue
        # Only fault inouts that map to a physical FPGA pad. Chip-level
        # inouts (no QSF pin assignment) are wired through to a wrapper
        # inout that IS a pad; its pull-up status is what matters.
        # If qsf_pads is non-empty AND `sig` isn't in it, skip (this is
        # an intermediate inout — the wrapper-pad gate covers the real
        # case).
        if qsf_pads and sig not in qsf_pads:
            continue
        findings.append(Finding(
            severity="ERROR",
            rule="TRISTATE_NO_PULLUP",
            message=(
                f"inout port `{sig}` is driven `1'bz` somewhere in RTL "
                f"but no `WEAK_PULL_UP_RESISTOR ON` (Quartus QSF) / "
                f"`PULLUP true` (Vivado XDC) is declared for this pad, "
                f"and L11 does not list `{sig}` under `external_pullup`. "
                f"v0.116 <benchmark> lesson: a floating tristate bus glitches "
                f"the 2-stage synchroniser on ambient noise, fires "
                f"spurious rx events and stalls FSMs that depend on bus "
                f"silence. Add a QSF pull-up assignment OR document an "
                f"external pull-up in L11."
            ),
            file=str(src.relative_to(project)),
        ))

    if not findings and not summary["tristate_drivers"]:
        summary["skipped_reason"] = (
            "no inout ports have tristate drivers — bus is "
            "always-driven, no float risk"
        )

    return findings, summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(prog="tristate_pullup_assertion_check")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2

    findings, summary = inspect(project)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "program": "tristate_pullup_assertion_check",
            "passed": not findings,
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2))

    print(f"=== tristate_pullup_assertion_check ({project.name}) ===")
    if summary["skipped_reason"]:
        print(f"  [skipped] {summary['skipped_reason']}")
        return 2
    if not findings:
        print(f"  [PASS] {len(summary['tristate_drivers'])} tristate "
              f"driver(s); all have pull-up evidence")
        return 0
    for f in findings:
        loc = f" ({f.file})" if f.file else ""
        print(f"  [{f.severity.lower()}] {f.rule}{loc}: {f.message}")
    print(f"\nOverall: FAIL ({len(findings)} unprotected tristate(s))")
    return 1


if __name__ == "__main__":
    sys.exit(main())
