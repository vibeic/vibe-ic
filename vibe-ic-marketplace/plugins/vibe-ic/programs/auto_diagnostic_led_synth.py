#!/usr/bin/env python3
"""
auto_diagnostic_led_synth.py — v0.114 (BACKLOG-v6 D1).

Code-gen helper (NOT a gate — emits advisory proposal). Scans an FPGA
wrapper RTL file, identifies FSM state registers, and emits a `.patch`
file proposing LED diagnostic port additions for board-level FSM
stuck-state visibility. Useful when you can't ssh into the FPGA but
can read 8 LEDs visually.

Heuristic (chip-AGNOSTIC):
  1. Find FPGA wrapper file: prefer `*_fpga_top.{v,sv}` or any RTL
     containing `LEDR[` (DE10-Lite naming) or `LED[` ports.
  2. Inside the wrapper module, find FSM state regs: signals matching
     `\\b(\\w*state|\\w*_fsm|\\w*_st)\\b` with assignment patterns
     `state <= S_*` or `state <= 4'dN`.
  3. Find unassigned LED indices (LEDR / LED arrays not yet used).
  4. Emit a patch proposal: `assign LEDR[N] = (state == S_X);` for
     each candidate FSM state.

False-positive design (NO false alerts):
  - This helper EMITS A PROPOSAL FILE — never modifies RTL directly.
  - Output: `<project>/analog/diagnostic/led_synth_proposal.patch` +
    `led_synth_proposal.md` with rationale.
  - Agent decides whether to apply via standard patch tooling.
  - If no FPGA wrapper found OR no FSM state regs OR no spare LEDs →
    emit "no proposal" rationale, exit 0 anyway.

Usage:
  python3 auto_diagnostic_led_synth.py <project_dir> [--out PATH]
Exit 0 always (advisory tool, never fails CI).
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple
import _path_layout as _pl


_LED_PORT_RE = re.compile(r"\b(LED[Rr]?)\s*\[\s*(\d+)", re.IGNORECASE)
_STATE_REG_RE = re.compile(
    r"\b(\w*(state|_fsm|_st))\s*(?:\[[^\]]+\])?\s*[;,]",
    re.IGNORECASE,
)
_STATE_ENUM_RE = re.compile(r"^\s*S_([A-Z0-9_]+)\s*[=,]", re.MULTILINE)
_FPGA_WRAPPER_HINT_RE = re.compile(r"_fpga_top|MAX10_CLK1_50|GPIO_0", re.IGNORECASE)


def _find_fpga_wrapper(project: Path) -> Optional[Path]:
    """Search rtl/, fpga/, and project root for a wrapper file. Multiple
    fallbacks for naming convention variability."""
    candidates = []
    for d in (_pl.rtl_dir(project), _pl.fpga_early_dir(project), project):
        if not d.is_dir():
            continue
        for path in d.rglob("*"):
            if path.suffix.lower() not in (".v", ".sv"):
                continue
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            if _FPGA_WRAPPER_HINT_RE.search(text) or _LED_PORT_RE.search(text):
                candidates.append(path)
    return sorted(candidates)[0] if candidates else None


def _find_state_regs(text: str) -> List[str]:
    found = set()
    for m in _STATE_REG_RE.finditer(text):
        # Avoid matching inside a comment line
        line_start = text.rfind("\n", 0, m.start()) + 1
        line = text[line_start:m.end()]
        if "//" in line[:line.find(m.group(0))]:
            continue
        name = m.group(1)
        # Filter trivial captures
        if len(name) < 3 or name.lower() in ("state", "fsm", "st"):
            continue
        found.add(name)
    return sorted(found)


def _find_state_enum_values(text: str) -> List[str]:
    return [m.group(1) for m in _STATE_ENUM_RE.finditer(text)]


def _find_used_leds(text: str) -> List[int]:
    used = set()
    # Match `assign LEDR[N] = ...` or `LEDR[N] <= ...`
    for m in re.finditer(r"\b(?:assign\s+)?LED[Rr]?\s*\[\s*(\d+)\s*\]\s*[=<]", text):
        used.add(int(m.group(1)))
    return sorted(used)


def _find_led_max_index(text: str) -> Optional[int]:
    # Look for `output ... LEDR[N:0]` declarations
    for m in re.finditer(r"\boutput\s+(?:\w+\s+)?\[(\d+)\s*:\s*0\s*\]\s*LED[Rr]?", text):
        return int(m.group(1))
    return None


def _generate_proposal(wrapper_path: Path, project: Path) -> Tuple[str, str, dict]:
    text = wrapper_path.read_text(errors="replace")
    state_regs = _find_state_regs(text)
    state_enums = _find_state_enum_values(text)
    used_leds = _find_used_leds(text)
    max_led = _find_led_max_index(text)

    info = {
        "wrapper_file": str(wrapper_path.relative_to(project)),
        "state_regs_found": state_regs[:5],
        "state_enum_values_sampled": state_enums[:5],
        "led_array_max_index": max_led,
        "leds_already_used": used_leds,
    }

    if not state_regs:
        return ("", "no FSM state registers detected — no LED proposal generated", info)
    if max_led is None:
        return ("", "no LED port array detected (looking for `output [N:0] LEDR`) — no proposal", info)

    spare_leds = [i for i in range(max_led + 1) if i not in used_leds]
    if not spare_leds:
        return ("", f"all LEDs 0..{max_led} already assigned — no spare for diagnostics", info)

    # Emit proposal: per state reg, suggest LED indices
    proposal_lines = []
    proposal_lines.append("// auto_diagnostic_led_synth proposal — APPLY MANUALLY")
    proposal_lines.append(f"// generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    proposal_lines.append(f"// wrapper: {wrapper_path.relative_to(project)}")
    proposal_lines.append(f"// state regs found: {', '.join(state_regs[:3])}")
    proposal_lines.append(f"// spare LED indices: {spare_leds}")
    proposal_lines.append("")

    led_iter = iter(spare_leds)
    for sr in state_regs[:min(len(state_regs), len(spare_leds))]:
        try:
            led_idx = next(led_iter)
        except StopIteration:
            break
        proposal_lines.append(f"// Diagnostic for FSM '{sr}' on LEDR[{led_idx}]")
        proposal_lines.append(f"assign LEDR[{led_idx}] = |{sr};  // any non-zero state → LED on")

    if state_enums:
        proposal_lines.append("")
        proposal_lines.append("// Per-state-value LEDs (uncomment + map to specific S_* enums):")
        for s_name in state_enums[:min(len(state_enums), len(spare_leds) - len(state_regs[:1]))]:
            try:
                led_idx = next(led_iter)
            except StopIteration:
                break
            proposal_lines.append(f"// assign LEDR[{led_idx}] = ({state_regs[0]} == S_{s_name});")

    patch = "\n".join(proposal_lines) + "\n"
    rationale = (
        f"# auto_diagnostic_led_synth — proposal\n\n"
        f"Wrapper: `{wrapper_path.relative_to(project)}`\n\n"
        f"## What this proposal does\n\n"
        f"Adds LED diagnostic outputs so the FPGA's FSM state is visible "
        f"on board LEDs without needing JTAG / scope / serial.\n\n"
        f"## Findings\n\n"
        f"- **FSM state registers detected**: `{', '.join(state_regs)}`\n"
        f"- **State enum values sampled**: `{', '.join(state_enums[:8]) or '(none)'}`\n"
        f"- **LED array max index**: `LEDR[0..{max_led}]`\n"
        f"- **LEDs already used**: `{used_leds}`\n"
        f"- **LEDs available for diagnostics**: `{spare_leds}`\n\n"
        f"## Proposed additions\n\n"
        f"```verilog\n{patch}```\n\n"
        f"## How to apply\n\n"
        f"This file is advisory only — review the proposal then either:\n"
        f"  1. Append the assignments inside the FPGA wrapper module body, OR\n"
        f"  2. Edit your `*_fpga_top.sv` and incorporate per the proposal.\n\n"
        f"After applying, recompile Quartus and verify the new LEDs light "
        f"up on board for the expected FSM transitions.\n"
    )
    return (patch, rationale, info)


def main():
    ap = argparse.ArgumentParser(description=(
        "Generate LED diagnostic proposal patch from FPGA wrapper RTL. "
        "Advisory only — never modifies RTL directly."
    ))
    ap.add_argument("project_dir")
    ap.add_argument("--out-dir", default=None,
                    help="Output dir (default: <project>/analog/diagnostic/)")
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[ERROR] project_dir not found: {project}", file=sys.stderr)
        return 2

    wrapper = _find_fpga_wrapper(project)
    if wrapper is None:
        print(f"[OK] auto_diagnostic_led_synth — no FPGA wrapper detected, no proposal generated.")
        return 0

    patch, rationale, info = _generate_proposal(wrapper, project)
    if not patch:
        print(f"[OK] auto_diagnostic_led_synth — {rationale}")
        return 0

    # RESOLVED AGAINST THE PROJECT, not against the cwd. `project` is
    # `.resolve()`d above and the two `relative_to(project)` calls below raise
    # ValueError on a relative path — so a caller who passed `--out-dir
    # reports/...` (the shape a flow clause has to use: the gate runs with cwd
    # = the project and cannot spell an absolute path) crashed instead of
    # emitting. `project / abs` yields `abs`, so an absolute --out-dir is
    # unchanged.
    out_dir = (project / args.out_dir).resolve() if args.out_dir \
        else (_pl.analog_dir(project) / "diagnostic")
    out_dir.mkdir(parents=True, exist_ok=True)
    patch_path = out_dir / "led_synth_proposal.patch"
    md_path = out_dir / "led_synth_proposal.md"
    patch_path.write_text(patch)
    md_path.write_text(rationale)

    print(f"[OK] auto_diagnostic_led_synth — proposal generated")
    print(f"     wrapper: {wrapper.relative_to(project)}")
    print(f"     state regs: {info['state_regs_found']}")
    print(f"     spare LEDs: {info['leds_already_used'] = }, max_idx={info['led_array_max_index']}")
    print(f"     output:")
    print(f"       {patch_path.relative_to(project)}")
    print(f"       {md_path.relative_to(project)}")
    print(f"     APPLY MANUALLY — this tool emits proposal, never modifies RTL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
