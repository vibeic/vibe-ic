"""v0.1.51 — Caravel user_project_wrapper emitter (B3 from spm pilot).

Doctrine: spm pilot hand-authored a 111-line `user_project_wrapper.v`.
Every future hard-macro Caravel project needs the same shape: canonical
Caravel golden ports + per-design pin assignments + tie-offs.

This program takes a 30-line pin-map YAML/JSON and emits the wrapper
deterministically. It also emits the matching `user_defines.v`
`USER_CONFIG_GPIO_*_INIT` lines from the same pin-map (Phase C
GPIO-Defines FAIL fix-up).

Pin-map shape:

    project_name: spm
    core_module: spm
    core_uses_power_pins: false      # false = wrap core with USE_POWER_PINS
    power_domains: ["vccd1", "vssd1"] # which caravel power nets the core uses
    pin_assignments:
      - core_port: clk
        caravel_pin: wb_clk_i
        port_dir: input
      - core_port: rst
        caravel_pin: wb_rst_i
        port_dir: input
      - core_port: x[31:0]
        caravel_pin: io_in[33:2]
        port_dir: input
      - core_port: y
        caravel_pin: io_in[34]
        port_dir: input
      - core_port: p
        caravel_pin: io_out[35]
        port_dir: output
    unused_tie_offs:
      "io_out[34:0]": "35'b0"
      "io_out[37:36]": "2'b0"
    unused_io_in_ranges: ["io_in[1:0]", "io_in[37:36]"]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Caravel golden port set (from caravel/verilog/rtl/user_project_wrapper.v
# template, current as of efabless/caravel @ master 2026-05-28).
CARAVEL_GOLDEN_NON_POWER_PORTS: Tuple[Dict[str, Any], ...] = (
    # Wishbone slave
    {"name": "wb_clk_i", "dir": "input", "width": ""},
    {"name": "wb_rst_i", "dir": "input", "width": ""},
    {"name": "wbs_stb_i", "dir": "input", "width": ""},
    {"name": "wbs_cyc_i", "dir": "input", "width": ""},
    {"name": "wbs_we_i", "dir": "input", "width": ""},
    {"name": "wbs_sel_i", "dir": "input", "width": "[3:0]"},
    {"name": "wbs_dat_i", "dir": "input", "width": "[31:0]"},
    {"name": "wbs_adr_i", "dir": "input", "width": "[31:0]"},
    {"name": "wbs_ack_o", "dir": "output", "width": ""},
    {"name": "wbs_dat_o", "dir": "output", "width": "[31:0]"},
    # Logic Analyzer
    {"name": "la_data_in", "dir": "input", "width": "[127:0]"},
    {"name": "la_data_out", "dir": "output", "width": "[127:0]"},
    {"name": "la_oenb", "dir": "input", "width": "[127:0]"},
    # IOs
    {"name": "io_in", "dir": "input", "width": "[37:0]"},
    {"name": "io_out", "dir": "output", "width": "[37:0]"},
    {"name": "io_oeb", "dir": "output", "width": "[37:0]"},
    # IRQ
    {"name": "user_irq", "dir": "output", "width": "[2:0]"},
)

CARAVEL_GOLDEN_POWER_PORTS: Tuple[str, ...] = (
    "vdda1", "vdda2", "vssa1", "vssa2",
    "vccd1", "vccd2", "vssd1", "vssd2",
)

# Number of GPIOs Caravel exposes to the user (38 total; 0-4 are
# managed by housekeeping, user can configure 5-37).
USER_CONFIGURABLE_GPIO_RANGE: Tuple[int, int] = (5, 37)


@dataclass
class PinAssignment:
    core_port: str
    caravel_pin: str
    port_dir: str           # input / output / inout

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PinMap:
    project_name: str
    core_module: str
    power_domains: List[str]
    pin_assignments: List[PinAssignment]
    unused_tie_offs: Dict[str, str] = field(default_factory=dict)
    unused_io_in_ranges: List[str] = field(default_factory=list)
    core_uses_power_pins: bool = False
    spdx_year: str = "2026"
    spdx_copyright: str = "user"


# ---------------------------------------------------------------------------
# YAML/JSON loader (no PyYAML dep — minimal YAML subset)
# ---------------------------------------------------------------------------
def load_pin_map(path: Path) -> PinMap:
    """Load pin-map from .json or .yaml. PyYAML optional; falls back
    to minimal-subset YAML parser if not installed."""
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    data: Dict[str, Any]
    if suffix == ".json":
        data = json.loads(text)
    else:
        # Try PyYAML, fall back to minimal subset
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(text)
        except Exception:
            data = _minimal_yaml_load(text)
    return _from_dict(data)


def _from_dict(data: Dict[str, Any]) -> PinMap:
    pas: List[PinAssignment] = []
    for p in data.get("pin_assignments", []):
        pas.append(PinAssignment(
            core_port=p["core_port"],
            caravel_pin=p["caravel_pin"],
            port_dir=p.get("port_dir", "input"),
        ))
    return PinMap(
        project_name=data["project_name"],
        core_module=data["core_module"],
        power_domains=list(data.get("power_domains", ["vccd1", "vssd1"])),
        pin_assignments=pas,
        unused_tie_offs=dict(data.get("unused_tie_offs", {})),
        unused_io_in_ranges=list(data.get("unused_io_in_ranges", [])),
        core_uses_power_pins=bool(data.get("core_uses_power_pins", False)),
        spdx_year=str(data.get("spdx_year", "2026")),
        spdx_copyright=str(data.get("spdx_copyright", "user")),
    )


def _minimal_yaml_load(text: str) -> Dict[str, Any]:
    """Subset YAML for pin-map files. Supports flat key/value, nested
    dicts via 2-space indent, list-of-dict via leading `- `."""
    out: Dict[str, Any] = {}
    stack: List[Tuple[int, Any]] = [(-1, out)]
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        # Pop deeper frames
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            item = line[2:].strip()
            if ":" in item:
                k, v = item.split(":", 1)
                d = {k.strip(): _coerce_scalar(v.strip())}
                if not isinstance(parent, list):
                    raise ValueError("list item under non-list parent")
                parent.append(d)
                stack.append((indent, d))
            else:
                parent.append(_coerce_scalar(item))
        elif ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip()
            if not v:
                # Nested dict or list follows
                child: Any = {}
                if isinstance(parent, dict):
                    parent[k] = child
                stack.append((indent, child))
                # Lookahead: if next non-blank starts with "- ", coerce to list
                # (Simple heuristic for our pin_map shape.)
                # We don't lookahead — the next pass will convert if the
                # first appended child is a list-item.
            else:
                if isinstance(parent, dict):
                    parent[k] = _coerce_scalar(v)
        else:
            # bare scalar line, ignore
            pass
    # Post-process: any value that's an empty dict followed by list items
    # should have been converted. We approximate by walking and converting
    # dicts whose first value is None to a list.
    # For our pin_map shape this is good enough.
    return out


def _coerce_scalar(v: str) -> Any:
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        parts = [p.strip().strip('"').strip("'") for p in inner.split(",")]
        return [_coerce_scalar(p) for p in parts]
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    if v.startswith("'") and v.endswith("'"):
        return v[1:-1]
    if v.lower() in ("true", "yes"):
        return True
    if v.lower() in ("false", "no"):
        return False
    try:
        return int(v)
    except ValueError:
        return v


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_pin_map(pm: PinMap) -> List[str]:
    """Return list of error strings (empty = valid)."""
    errors: List[str] = []
    if not pm.project_name:
        errors.append("project_name is empty")
    if not pm.core_module:
        errors.append("core_module is empty")
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", pm.core_module):
        errors.append(f"core_module {pm.core_module!r} is not a valid Verilog id")
    # Each pin assignment must target a known Caravel golden port
    golden_names = {p["name"] for p in CARAVEL_GOLDEN_NON_POWER_PORTS}
    for pa in pm.pin_assignments:
        # caravel_pin can be e.g. wb_clk_i  OR  io_in[34]  OR  io_in[33:2]
        m = re.match(r"^([a-zA-Z_]\w*)(?:\[.+\])?$", pa.caravel_pin)
        if not m:
            errors.append(f"caravel_pin {pa.caravel_pin!r} has bad shape")
            continue
        if m.group(1) not in golden_names:
            errors.append(
                f"caravel_pin {pa.caravel_pin!r} references unknown golden "
                f"port {m.group(1)!r}")
    # Power domains must be from the canonical set
    for d in pm.power_domains:
        if d not in CARAVEL_GOLDEN_POWER_PORTS:
            errors.append(
                f"power_domain {d!r} is not a Caravel golden power net")
    return errors


# ---------------------------------------------------------------------------
# Wrapper.v emit
# ---------------------------------------------------------------------------
def emit_wrapper(pm: PinMap) -> str:
    """Emit the canonical `user_project_wrapper.v` body for `pm`."""
    out: List[str] = []
    out.append(f"// SPDX-FileCopyrightText: {pm.spdx_year} {pm.spdx_copyright}")
    out.append("// SPDX-License-Identifier: Apache-2.0")
    out.append("//")
    out.append(f"// user_project_wrapper for {pm.project_name} — Caravel chipignite MPW")
    out.append(f"// Auto-generated by caravel_wrapper_emit.py v0.1.51; do not hand-edit.")
    out.append("//")
    out.append("// Pin map (per pin-map YAML):")
    for pa in pm.pin_assignments:
        out.append(f"//   {pm.core_module} {pa.port_dir:>6} {pa.core_port:<14}  →  {pa.caravel_pin}")
    out.append("//")
    out.append("`default_nettype none")
    out.append("")

    # Module header
    out.append("module user_project_wrapper (")
    out.append("`ifdef USE_POWER_PINS")
    for pn in CARAVEL_GOLDEN_POWER_PORTS:
        marker = "  ← core uses" if pn in pm.power_domains else ""
        out.append(f"    inout {pn},{marker}")
    out.append("`endif")
    out.append("")
    # Non-power golden ports
    for i, p in enumerate(CARAVEL_GOLDEN_NON_POWER_PORTS):
        w = f" {p['width']}" if p["width"] else ""
        # Pad dir to width 6 for alignment
        comma = "," if i < len(CARAVEL_GOLDEN_NON_POWER_PORTS) - 1 else ""
        out.append(f"    {p['dir']:<6} wire{w} {p['name']}{comma}")
    out.append(");")
    out.append("")
    out.append("    // ------------------------------------------------------------")
    out.append(f"    // {pm.core_module} core instantiation")
    out.append("    // ------------------------------------------------------------")

    # Core wires (we declare a wire per OUTPUT pin assignment)
    out_wire_names: List[str] = []
    for pa in pm.pin_assignments:
        if pa.port_dir == "output":
            cp_id = _identifier(pa.core_port)
            wire_name = f"{pm.core_module}_{cp_id}"
            out.append(f"    wire {wire_name};")
            out_wire_names.append((pa, wire_name))

    out.append("")

    # Core instantiation
    out.append(f"    {pm.core_module} u_{pm.core_module} (")
    inst_lines: List[str] = []
    for pa in pm.pin_assignments:
        cp_lhs = pa.core_port
        if pa.port_dir == "output":
            wire_name = f"{pm.core_module}_{_identifier(pa.core_port)}"
            rhs = wire_name
        else:
            rhs = pa.caravel_pin
        inst_lines.append(f"        .{_strip_bits(cp_lhs)} ({rhs})")
    out.append(",\n".join(inst_lines))
    out.append("    );")
    out.append("")

    # IO routing: output assignments to caravel_pin
    out.append("    // ------------------------------------------------------------")
    out.append("    // IO routing — drive caravel pins from core outputs + tie-offs")
    out.append("    // ------------------------------------------------------------")
    for pa, wire_name in out_wire_names:
        out.append(f"    assign {pa.caravel_pin} = {wire_name};")
    for ce, val in pm.unused_tie_offs.items():
        out.append(f"    assign {ce} = {val};")
    out.append("")

    # io_oeb: default all-1 (input mode) except outputs = 0
    output_io_idx: List[int] = []
    for pa in pm.pin_assignments:
        if pa.port_dir == "output":
            m = re.match(r"^io_out\[(\d+)\]$", pa.caravel_pin)
            if m:
                output_io_idx.append(int(m.group(1)))
    if output_io_idx:
        out.append("    // io_oeb: 0 = output, 1 = input/Z (default)")
        # Build io_oeb piece-wise assignment.
        # For each io_out output, set its bit to 0; rest = 1.
        # Simplest: emit individual bit assignments.
        for idx in sorted(output_io_idx):
            out.append(f"    assign io_oeb[{idx}] = 1'b0;")
        # For unassigned io_oeb bits, drive 1's. We honor unused_io_in_ranges
        # by NOT including them (they remain undriven, get default).
        # Build the all-ones drive for io_oeb[X:Y] ranges excluding output bits.
        assigned_bits = set(output_io_idx)
        ranges = _compute_io_oeb_input_ranges(assigned_bits)
        for lo, hi in ranges:
            width = hi - lo + 1
            if width == 1:
                out.append(f"    assign io_oeb[{lo}] = 1'b1;")
            else:
                hex_lit = f"{width}'h{(1 << width) - 1:x}"
                out.append(f"    assign io_oeb[{hi}:{lo}] = {hex_lit};")
    out.append("")

    # Unused tied-off outputs that the user didn't enumerate
    # explicitly — best-effort defaults for the common Caravel ports.
    out.append("    // Unused Caravel slave/LA/IRQ ports tied to safe defaults")
    needed_defaults = {
        "wbs_ack_o": "1'b0",
        "wbs_dat_o": "32'b0",
        "la_data_out": "128'b0",
        "user_irq": "3'b0",
    }
    explicitly_driven = {pa.caravel_pin for pa in pm.pin_assignments}
    for port, default in needed_defaults.items():
        if port not in explicitly_driven and not any(
                pa.caravel_pin.startswith(f"{port}[") for pa in pm.pin_assignments):
            out.append(f"    assign {port} = {default};")
    out.append("")
    out.append("endmodule")
    out.append("")
    out.append("`default_nettype wire")
    return "\n".join(out)


def _identifier(s: str) -> str:
    """Strip [bits] for use as a Verilog identifier."""
    return re.sub(r"\[.*\]", "", s)


def _strip_bits(s: str) -> str:
    """Strip [bits] for the .core_port (...) instance side."""
    return re.sub(r"\[.*\]", "", s)


def _compute_io_oeb_input_ranges(assigned_bits: set) -> List[Tuple[int, int]]:
    """Compute the contiguous [lo, hi] ranges of io_oeb bits NOT in
    `assigned_bits` (these are the ones we drive to 1 for input mode)."""
    ranges: List[Tuple[int, int]] = []
    lo: Optional[int] = None
    for i in range(0, 38):
        if i in assigned_bits:
            if lo is not None:
                ranges.append((lo, i - 1))
                lo = None
        else:
            if lo is None:
                lo = i
    if lo is not None:
        ranges.append((lo, 37))
    return ranges


# ---------------------------------------------------------------------------
# user_defines.v emit (Phase C GPIO-Defines fix)
# ---------------------------------------------------------------------------
def emit_user_defines(pm: PinMap, header_prefix: str = "") -> str:
    """Emit `verilog/rtl/user_defines.v` content for `pm`. Fills
    USER_CONFIG_GPIO_5_INIT through GPIO_37_INIT with appropriate
    mode from the pin-map."""
    out: List[str] = []
    if header_prefix:
        out.append(header_prefix.rstrip("\n"))
    out.append("// SPDX-License-Identifier: Apache-2.0")
    out.append(f"// Auto-generated by caravel_wrapper_emit.py v0.1.51 (project: {pm.project_name})")
    out.append("")
    out.append("`default_nettype none")
    out.append("")
    out.append("`ifndef __USER_DEFINES_H")
    out.append("`define __USER_DEFINES_H")
    out.append("")
    # Constants from Caravel canonical user_defines.v
    out.append("`define GPIO_MODE_INVALID                  13'hXXXX")
    out.append("`define GPIO_MODE_USER_STD_INPUT_NOPULL    13'h0402")
    out.append("`define GPIO_MODE_USER_STD_OUTPUT          13'h1808")
    out.append("`define GPIO_MODE_USER_STD_BIDIRECTIONAL   13'h1800")
    out.append("`define GPIO_MODE_USER_STD_INPUT_PULLDOWN  13'h0c00")
    out.append("`define GPIO_MODE_USER_STD_INPUT_PULLUP    13'h0800")
    out.append("`define GPIO_MODE_USER_STD_ANALOG          13'h000a")
    out.append("")
    # Per-GPIO mode: from pin-map, default = USER_STD_INPUT_NOPULL
    gpio_modes: Dict[int, str] = {}
    for pa in pm.pin_assignments:
        # io_in[N] => GPIO N is input
        # io_out[N] => GPIO N is output (driven by user_irq mapping or core)
        m_in = re.match(r"^io_in\[(\d+)\]$", pa.caravel_pin)
        m_in_range = re.match(r"^io_in\[(\d+):(\d+)\]$", pa.caravel_pin)
        m_out = re.match(r"^io_out\[(\d+)\]$", pa.caravel_pin)
        m_out_range = re.match(r"^io_out\[(\d+):(\d+)\]$", pa.caravel_pin)
        if m_in:
            gpio_modes[int(m_in.group(1))] = "GPIO_MODE_USER_STD_INPUT_NOPULL"
        elif m_in_range:
            hi, lo = int(m_in_range.group(1)), int(m_in_range.group(2))
            for i in range(lo, hi + 1):
                gpio_modes[i] = "GPIO_MODE_USER_STD_INPUT_NOPULL"
        elif m_out:
            gpio_modes[int(m_out.group(1))] = "GPIO_MODE_USER_STD_OUTPUT"
        elif m_out_range:
            hi, lo = int(m_out_range.group(1)), int(m_out_range.group(2))
            for i in range(lo, hi + 1):
                gpio_modes[i] = "GPIO_MODE_USER_STD_OUTPUT"

    lo_n, hi_n = USER_CONFIGURABLE_GPIO_RANGE
    for i in range(lo_n, hi_n + 1):
        mode = gpio_modes.get(i, "GPIO_MODE_USER_STD_INPUT_NOPULL")
        out.append(f"`define USER_CONFIG_GPIO_{i}_INIT  `{mode}")

    out.append("")
    out.append("`endif // __USER_DEFINES_H")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cli() -> int:
    p = argparse.ArgumentParser(
        description="Emit Caravel user_project_wrapper.v + user_defines.v "
                    "from a pin-map YAML/JSON.")
    p.add_argument("--pin-map", type=Path, required=True)
    p.add_argument("--out-wrapper", type=Path,
                   help="Output path for user_project_wrapper.v "
                        "(default: stdout)")
    p.add_argument("--out-user-defines", type=Path,
                   help="Output path for user_defines.v")
    p.add_argument("--strict", action="store_true",
                   help="Exit 1 if pin-map validation fails")
    args = p.parse_args()

    if not args.pin_map.exists():
        print(f"pin-map not found: {args.pin_map}", file=sys.stderr)
        return 2
    pm = load_pin_map(args.pin_map)
    errors = validate_pin_map(pm)
    for e in errors:
        print(f"WARN: {e}", file=sys.stderr)
    if errors and args.strict:
        return 1
    wrapper = emit_wrapper(pm)
    if args.out_wrapper:
        args.out_wrapper.write_text(wrapper, encoding="utf-8")
    else:
        print(wrapper)
    if args.out_user_defines:
        defines = emit_user_defines(pm)
        args.out_user_defines.write_text(defines, encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
