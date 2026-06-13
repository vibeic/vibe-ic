#!/usr/bin/env python3
"""
half_duplex_wrapper_open_drain_check.py — structural-RTL gate that
catches the FPGA-wrapper anti-pattern for half-duplex open-drain pins.

Why this gate exists
====================
For a half-duplex single-wire protocol (Apple Lightning ID-bus, K-line,
LIN, 1-Wire, etc.), the FPGA wrapper that drives the inout pin must
expose a wrapper expression Quartus / Vivado / Lattice synth can
recognise as an open-drain IO buffer:

    assign GPIO_id_bus = (oe && !tx) ? 1'b0 : 1'bz;     // OK — open-drain
    assign GPIO_id_bus = oe ? tx : 1'bz;                 // OK — open-drain
    assign GPIO_id_bus = oe ? 1'b0 : 1'bz;               // FAIL — tristate

The first two forms reveal a separate data signal (`!tx` or `tx`) the
synth tool uses to allocate the pin as OPEN_DRAIN_OUTPUT, which has
asymmetric edge characteristics and a clean recovery to high-Z.

The third form looks logically equivalent — it always drives 1'b0 when
the OE control is true, otherwise high-Z — but the synth tool has
nothing to bind as the data input, so it infers a normal tristate
buffer with the constant 0 hard-wired to the data pin. The resulting
FPGA pad has subtly different power-up state, edge slew, and bus-hold
behavior that the host controller's analog front-end detects.

Concrete failure mode (caught against <half-duplex-tester> oracle):
    1. Both forms produce identical-looking 24us LOW pulses on a scope
       at 100 ns/sample.
    2. The host's hardware bit receiver still distinguishes them.
    3. Single-signal form returns connect_test byte[6]=0x02 FAIL;
       split-signal form returns byte[6]=0xF2 PASS — same RTL core,
       same chip logic, only the wrapper assign differs.

The rule is GENERAL — chip-agnostic, applies to any half-duplex
single-wire protocol where the chip drives an `inout` pin via a
top-level tristate assign. The gate scans the project's wrapper /
fpga_top RTL for the bus pin's tristate assign and verifies its
RHS uses a split-signal pattern.

Usage
-----
python3 half_duplex_wrapper_open_drain_check.py <project_dir>

Honors waivers.json with key "wrapper_open_drain_alternative" if
the project intentionally uses a non-open-drain pad.

Returns 0 on PASS, 1 on FAIL.
"""

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


def is_half_duplex(project_dir: Path) -> bool:
    candidates = [project_dir, project_dir / "phase1/generated_docs", _pl.generated_docs_dir(project_dir)]
    l2_keys = ("tSRS_us", "ibt_us", "frame_end_gap_us",
               "tSRS_min_us", "tSRS_max_us")
    for base in candidates:
        l2 = base / "L2_FRS.json"
        l3 = base / "L3_CMD_PROTOCOL.json"
        try:
            if l2.exists():
                d = json.loads(l2.read_text())
                if any(k in d for k in l2_keys):
                    return True
            if l3.exists():
                d = json.loads(l3.read_text())
                if isinstance(d.get("command_table"), list) and d["command_table"]:
                    return True
        except Exception:
            pass
    return False


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


# Names that look like a half-duplex bus pin at the wrapper level.
PIN_NAME_HINTS = (
    "id_bus", "GPIO_id_bus",
    "lin_bus", "kline_bus", "owire", "1wire",
    "single_wire", "halfduplex_bus",
)


def find_pin_assigns(src: str):
    """Return list of (pin_name, rhs_expression) for tristate-style assigns
    whose LHS name matches PIN_NAME_HINTS."""
    out = []
    pat = re.compile(
        r"assign\s+(\w+)\s*=\s*([^;]+);",
        re.IGNORECASE,
    )
    for m in pat.finditer(src):
        name = m.group(1)
        nl = name.lower()
        if any(h.lower() in nl for h in PIN_NAME_HINTS):
            rhs = m.group(2).strip()
            # Only consider tristate-shaped RHS (contains 1'bz or just z).
            if "1'bz" in rhs.replace(" ", "") or "1'bZ" in rhs.replace(" ", ""):
                out.append((name, rhs))
    return out


def is_open_drain_pattern(rhs: str) -> tuple[bool, str]:
    """
    Decide whether the tristate RHS exposes a separate data signal
    (open-drain pattern) or hardcoded 1'b0 (tristate pattern).

    Returns (is_open_drain, classification).
    """
    s = rhs.replace(" ", "").lower()
    # Strip any 1'bz to focus on the active branch.
    # Common shapes:
    #   (oe && !tx) ? 1'b0 : 1'bz       open-drain (oe + separate tx)
    #   (oe & !tx) ? 1'b0 : 1'bz        open-drain
    #   oe ? tx : 1'bz                  open-drain (tx is the data)
    #   oe ? 1'b0 : 1'bz                tristate (data hardcoded)
    #   oe ? data : 1'bz where data is a signal — open-drain
    m = re.search(r"(.+?)\?(.+?):", s)
    if not m:
        return False, "not-ternary"
    cond = m.group(1)
    true_branch = m.group(2).strip()
    if "1'b0" == true_branch or "1'h0" == true_branch or "0" == true_branch:
        # True branch is hardcoded 0. Check whether condition has
        # multiple signals (oe + data combined).
        # Pattern: (oe && !data) — has both an OE-like name and a NOT data.
        if "&&" in cond and "!" in cond:
            return True, "split-via-condition"
        if "&" in cond and "~" in cond:
            return True, "split-via-condition"
        # Otherwise it's just oe ? 1'b0 : 1'bz — tristate pattern.
        return False, "single-oe-hardcoded-zero"
    # True branch is a signal (e.g. tx) — open-drain via data input.
    if re.match(r"[a-z_][\w]*", true_branch):
        return True, "split-via-data"
    return False, "unknown"


def waived(project_dir: Path) -> bool:
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return False
    try:
        d = json.loads(waivers.read_text())
        return bool(d.get("wrapper_open_drain_alternative"))
    except Exception:
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: half_duplex_wrapper_open_drain_check.py <project_dir>")
        sys.exit(2)

    project_dir = Path(sys.argv[1]).resolve()
    if not project_dir.exists():
        print(f"FAIL — project dir not found: {project_dir}")
        sys.exit(1)

    if not is_half_duplex(project_dir):
        print("PASS — project not half-duplex (gate not applicable)")
        sys.exit(0)

    rtl_dir = _pl.rtl_dir(project_dir)
    if not rtl_dir.exists():
        print("PASS — no rtl/ directory")
        sys.exit(0)

    failures = []
    for rtl in sorted(list(rtl_dir.glob("*.sv")) + list(rtl_dir.glob("*.v"))):
        try:
            src = strip_comments(rtl.read_text())
        except Exception:
            continue
        for pin, rhs in find_pin_assigns(src):
            ok, classification = is_open_drain_pattern(rhs)
            if not ok:
                failures.append({
                    "file": str(rtl.relative_to(project_dir)),
                    "pin": pin,
                    "rhs": rhs,
                    "classification": classification,
                })

    if not failures:
        print("PASS — half-duplex bus pin uses open-drain wrapper pattern")
        sys.exit(0)

    if waived(project_dir):
        print(f"PASS_WITH_WAIVER — {len(failures)} non-open-drain wrapper(s)")
        for f in failures:
            print(f"  • {f['file']}: assign {f['pin']} = {f['rhs']}")
        sys.exit(0)

    print(f"FAIL — {len(failures)} bus-pin wrapper assign(s) use the "
          "tristate pattern instead of the open-drain pattern:")
    for f in failures:
        print(f"  • {f['file']}: assign {f['pin']} = {f['rhs']}")
        print(f"    classification: {f['classification']}")
    print()
    print("Why this matters:")
    print("  Quartus / Vivado / Lattice synth tools infer the FPGA pad")
    print("  type from the wrapper expression shape:")
    print()
    print("    assign pin = (oe && !tx) ? 1'b0 : 1'bz;   -> OPEN_DRAIN_OUTPUT")
    print("    assign pin =  oe ? tx    : 1'bz;          -> OPEN_DRAIN_OUTPUT")
    print("    assign pin =  oe ? 1'b0  : 1'bz;          -> regular TRISTATE")
    print()
    print("  Both produce identical waveforms on a scope at 100 ns/sample,")
    print("  but the host controller's analog front-end detects subtle")
    print("  differences in pad startup state, edge slew, and bus-hold —")
    print("  enough to flip a connect_test verdict from byte[6]=0xF2 PASS")
    print("  to byte[6]=0x02 FAIL (confirmed against <half-duplex-tester> oracle by")
    print("  controlled wrapper-flip experiment).")
    print()
    print("Fix: split the data signal out of the tristate condition. Add")
    print("a `<pin>_tx` output to the chip's top-level FSM (driven LOW")
    print("when the chip is asserting LOW, HIGH when releasing) and use:")
    print()
    print("    assign GPIO_<pin> = (<pin>_oe && !<pin>_tx) ? 1'b0 : 1'bz;")
    print()
    print("Or document an alternative in waivers.json:")
    print('    {"wrapper_open_drain_alternative": "<reason>"}')
    sys.exit(1)


if __name__ == "__main__":
    main()
