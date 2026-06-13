#!/usr/bin/env python3
"""
single_bus_driver_check.py — structural-RTL gate that catches the
"two parallel bus drivers" anti-pattern in half-duplex protocol ICs.

What "single bus driver" means
==============================
For a half-duplex single-wire protocol (Apple Lightning ID-bus, K-line,
LIN, 1-Wire, etc.) the bus net itself MUST be driven by exactly one
RTL site — typically a single tristate:

    assign id_bus = id_bus_oe ? 1'b0 : 1'bz;   // single tristate

This single tristate IS the one physical bus driver. Multiple
internal FSMs MAY contribute to its enable via OR — that is the
standard open-drain topology and is correct:

    assign id_bus_oe = wake_drv | tx_drv_low;  // OK — OR of LOW pull-down enables
    assign id_bus    = id_bus_oe ? 1'b0 : 1'bz;

In the OR-of-enables pattern the bus net `id_bus` still has exactly
one driver (the tristate); `id_bus_oe` is a control input, not a
parallel driver.

What this gate FAILs on
=======================
1. Two `assign <bus_net> = ...` statements driving the same physical
   bus net.
2. Two `always_ff @(posedge clk) <bus_net> <= ...` blocks writing to
   the same physical bus net.
3. An `assign <bus_oe> = a | b | ...` whose result is NOT consumed
   by a single tristate driving a bus net (i.e. the OR result feeds
   into multiple parallel drivers — the original Wave-7 anti-pattern).

What this gate PASSes
=====================
- Single tristate `assign bus = oe ? 1'b0 : 1'bz` regardless of how
  many FSM-controlled signals are OR-ed into `oe`.
- Single FSM-driven bus net (one `always_ff` or one `assign`).
- Tristate via ternary even with OR-ed enables (Wave 10 / v0.119.42:
  this was previously FAILed by the naïve OR-only counter).

The gate is GENERAL — chip-agnostic. Bus net names matched via the
heuristic OE / BUS name table; works for any half-duplex single-wire
protocol that follows the open-drain tristate convention.

Usage
-----
python3 single_bus_driver_check.py <project_dir>

Honors waivers.json with key "single_bus_driver_alternative" if the
project deliberately uses a multi-driver scheme (rare; would require
a written reason).

Returns 0 on PASS, 1 on FAIL.
"""

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


def is_half_duplex(project_dir: Path) -> bool:
    """Same heuristic the other half-duplex gates use."""
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


# Names that look like a half-duplex bus output-enable signal.
OE_NAMES = (
    "id_bus_oe",
    "bus_oe",
    "drv_oe",
    "drive_oe",
    "id_oe",
    "lin_oe",
    "kline_oe",
    "owire_oe",
)

# Heuristic suffixes for OE-style nets (so we can spot OR-of-enables
# patterns even when the bus name does not match OE_NAMES exactly).
OE_SUFFIXES = ("_oe", "_drive", "_pulldown", "_drv", "_low_drv")

# Heuristic name fragments for the half-duplex bus net itself.
# Used to detect single-tristate consumers and multi-driver violations.
BUS_NAME_HINTS = (
    "id_bus", "idbus", "bus_io", "bus_phy", "kline", "lin_bus",
    "owire", "one_wire", "1wire", "iso7816", "ibus", "data_bus",
    "io_bus",
)


def find_oe_assignments(src: str):
    """
    Return list of (oe_signal_name, rhs_expression) for any
    `assign <oe> = <rhs>;` whose LHS looks like an OE / drive enable.
    """
    out = []
    pat = re.compile(
        r"assign\s+(\w+)\s*=\s*([^;]+);",
        re.IGNORECASE,
    )
    for m in pat.finditer(src):
        name = m.group(1)
        name_l = name.lower()
        if name_l in OE_NAMES or name_l.endswith(OE_SUFFIXES):
            out.append((name, m.group(2).strip()))
    return out


def looks_like_bus_net(name: str) -> bool:
    """Heuristic — does this identifier look like a half-duplex bus net?"""
    n = name.lower()
    if any(h in n for h in BUS_NAME_HINTS):
        # Exclude obvious enable / control / clock variants.
        bad = ("_oe", "_drv", "_drive", "_pulldown", "_clk", "_rst",
               "_in", "_out_d", "_sync", "_ff", "_q", "_d", "_pre")
        # Allow the bare bus name; reject the *_oe / *_drv / *_in variants.
        for b in bad:
            if n.endswith(b):
                return False
        return True
    return False


def find_bus_net_assigns(src: str):
    """
    Return list of (bus_net_name, rhs_expression) for any
    `assign <bus> = <rhs>;` whose LHS looks like a bus net (not an OE).
    """
    out = []
    pat = re.compile(r"assign\s+(\w+)\s*=\s*([^;]+);", re.IGNORECASE)
    for m in pat.finditer(src):
        name = m.group(1)
        if looks_like_bus_net(name):
            out.append((name, m.group(2).strip()))
    return out


_ALWAYS_FF_RE = re.compile(
    r"always(?:_ff|_latch)?\s*@[^\n]*?\n"   # always_ff @(...) header
    r".*?"                                   # body (non-greedy)
    r"(?=\bend\b|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def find_always_drivers(src: str) -> dict[str, int]:
    """
    Find sequential blocks driving anything that looks like a bus net.
    Returns {bus_net_name: count_of_distinct_always_blocks_writing_it}.

    We look for `<bus> <= ...;` inside any `always` block.
    """
    counts: dict[str, int] = {}
    # Walk all `always*` blocks. We use a coarse approach: split on
    # `always` keyword occurrences and inspect each chunk's nonblocking
    # assignments to bus-looking nets.
    chunks = re.split(r"(?=\balways(?:_ff|_comb|_latch)?\s*@)", src)
    for chunk in chunks[1:]:  # first chunk is preamble
        # Track which bus nets are written in THIS block.
        seen_in_block: set[str] = set()
        for m in re.finditer(r"\b(\w+)\s*<=", chunk):
            name = m.group(1)
            if looks_like_bus_net(name):
                seen_in_block.add(name)
        for n in seen_in_block:
            counts[n] = counts.get(n, 0) + 1
    return counts


def split_or_terms(rhs: str) -> list[str]:
    """Tokenise `rhs` into top-level OR terms, ignoring literals."""
    # Strip parens to a flat string for term counting purposes only.
    flat = rhs.replace("(", " ").replace(")", " ").strip()
    # Skip ternaries entirely — those are mutually-exclusive selects.
    if "?" in flat and ":" in flat:
        return [flat]
    parts = re.split(r"\s*\|\|?\s*", flat)
    return [p.strip() for p in parts
            if p.strip() and not re.match(r"^\d+'\w?[01x]+$", p.strip())
            and not re.fullmatch(r"\d+", p.strip())
            and p.strip().lower() not in ("or",)]


def count_or_drivers(rhs: str) -> tuple[int, list[str]]:
    """Legacy helper retained for tests / callers — count top-level
    OR terms in `rhs` after stripping parens and literals."""
    parts = split_or_terms(rhs)
    return len(parts), parts


def is_oe_consumed_by_single_tristate(oe_name: str, src: str) -> bool:
    """
    Detect the legitimate open-drain tristate pattern:

        assign <bus> = <oe> ? 1'b0 : 1'bz;
        assign <bus> = !<oe> ? 1'bz : 1'b0;     // equivalent
        assign <bus> = <oe> ? 1'bz : 1'b0;      // active-low oe

    where `<bus>` is a bus net (BUS_NAME_HINTS) and the OE is the
    LHS we just analysed. If we can find exactly ONE such tristate
    consumer for `<oe>` AND no other `assign <bus> = ...` exists for
    the same bus net, the OR-of-enables pattern is structurally
    safe.
    """
    # Find every `assign <something> = ... <oe_name> ...;` ternary.
    pat = re.compile(
        r"assign\s+(\w+)\s*=\s*([^;]*?\b" + re.escape(oe_name) + r"\b[^;]*?);",
        re.IGNORECASE,
    )
    bus_consumers: list[str] = []
    for m in pat.finditer(src):
        lhs = m.group(1)
        rhs = m.group(2)
        if not looks_like_bus_net(lhs):
            continue
        # Must contain a ternary AND a high-impedance literal.
        if "?" not in rhs or ":" not in rhs:
            continue
        if not re.search(r"1'b\s*z|1'bz|1'hz", rhs, re.IGNORECASE):
            continue
        bus_consumers.append(lhs)
    if len(bus_consumers) != 1:
        return False
    bus_name = bus_consumers[0]
    # Confirm only ONE assign drives that bus net at all.
    n_assigns = 0
    for m in re.finditer(r"assign\s+(\w+)\s*=", src):
        if m.group(1) == bus_name:
            n_assigns += 1
    return n_assigns == 1


def waived(project_dir: Path) -> bool:
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return False
    try:
        d = json.loads(waivers.read_text())
        return bool(d.get("single_bus_driver_alternative"))
    except Exception:
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: single_bus_driver_check.py <project_dir>")
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
        print("PASS — no rtl/ directory yet")
        sys.exit(0)

    failures = []
    notes: list[str] = []

    # Aggregate sources across all RTL files (concatenated text-level
    # analysis). Splitting per-file would miss the bus tristate when
    # OE is OR-ed in one file and the tristate lives in another.
    all_src = ""
    file_for_oe: dict[str, str] = {}
    for rtl in sorted(list(rtl_dir.glob("*.sv")) + list(rtl_dir.glob("*.v"))):
        try:
            src = strip_comments(rtl.read_text())
        except Exception:
            continue
        rel = str(rtl.relative_to(project_dir))
        all_src += "\n// === " + rel + " ===\n" + src
        for oe_name, _ in find_oe_assignments(src):
            file_for_oe.setdefault(oe_name, rel)

    # ----- Rule 1: physical bus net must have exactly one driver. -----
    # Count `assign <bus> = ...` and `<bus> <=` writers per bus net.
    bus_assigns: dict[str, list[str]] = {}
    for bus_name, rhs in find_bus_net_assigns(all_src):
        bus_assigns.setdefault(bus_name, []).append(rhs)
    for bus_name, rhss in bus_assigns.items():
        if len(rhss) >= 2:
            failures.append({
                "kind": "multiple_continuous_assigns",
                "file": "(aggregate)",
                "bus": bus_name,
                "drivers": rhss,
            })

    seq_writes = find_always_drivers(all_src)
    for bus_name, n in seq_writes.items():
        # Two distinct always blocks writing the same bus net is a
        # clear multi-driver violation.
        if n >= 2:
            failures.append({
                "kind": "multiple_always_blocks",
                "file": "(aggregate)",
                "bus": bus_name,
                "drivers": [f"{n} always blocks writing {bus_name}"],
            })
        # Continuous-assign + sequential-write to the same bus net
        # is also a violation.
        if n >= 1 and bus_name in bus_assigns:
            failures.append({
                "kind": "always_plus_assign",
                "file": "(aggregate)",
                "bus": bus_name,
                "drivers": [
                    f"{n} always block(s) + "
                    f"{len(bus_assigns[bus_name])} continuous assign(s)",
                ],
            })

    # ----- Rule 2: OR-of-enables only OK when consumed by single tristate. -----
    # Walk OE OR-of-N patterns; for each, if the OE is consumed by
    # exactly ONE tristate `assign <bus> = oe ? 1'b0/1'bz : ...;`
    # and no other `assign <bus>` exists, treat as PASS (Wave 10).
    for oe_name, rhs in find_oe_assignments(all_src):
        n, srcs = count_or_drivers(rhs)
        if n < 2:
            continue
        if is_oe_consumed_by_single_tristate(oe_name, all_src):
            notes.append(
                f"OK pattern: {oe_name} = {rhs}  "
                f"→ consumed by single tristate driving bus net "
                "(open-drain OR-of-LOW-enables)."
            )
            continue
        failures.append({
            "kind": "or_enables_no_single_tristate",
            "file": file_for_oe.get(oe_name, "(aggregate)"),
            "oe": oe_name,
            "rhs": rhs,
            "drivers": srcs,
        })

    if not failures:
        print("PASS — bus net has a single physical driver")
        for note in notes:
            print(f"  note: {note}")
        sys.exit(0)

    if waived(project_dir):
        print(f"PASS_WITH_WAIVER — {len(failures)} multi-driver "
              "violation(s) but waiver set")
        for f in failures:
            print(f"  • {f.get('file', '?')}: {f}")
        sys.exit(0)

    print(f"FAIL — {len(failures)} bus-driver violation(s):")
    for f in failures:
        kind = f.get("kind", "?")
        if kind == "multiple_continuous_assigns":
            print(f"  • {f['file']}: bus net `{f['bus']}` driven by "
                  f"{len(f['drivers'])} `assign` statements:")
            for rhs in f["drivers"]:
                print(f"      assign {f['bus']} = {rhs};")
        elif kind == "multiple_always_blocks":
            print(f"  • {f['file']}: bus net `{f['bus']}` written by "
                  "multiple always blocks: "
                  f"{f['drivers'][0]}")
        elif kind == "always_plus_assign":
            print(f"  • {f['file']}: bus net `{f['bus']}` driven both "
                  f"sequentially AND continuously: {f['drivers'][0]}")
        elif kind == "or_enables_no_single_tristate":
            print(f"  • {f['file']}: assign {f['oe']} = {f['rhs']}")
            print(f"    drivers OR-ed: {f['drivers']}")
            print(f"    but {f['oe']} is NOT consumed by a single "
                  "tristate `assign <bus> = oe ? 1'b0 : 1'bz;` —")
            print( "    so the OR-ed enables fan out to multiple "
                  "physical drivers.")
    print()
    print("Why this matters:")
    print("  Half-duplex single-wire protocols require a single physical")
    print("  driver on the bus net. Multiple parallel drivers cause:")
    print("    1. RX self-mask logic (`!tx_active`) to mis-track the")
    print("       active driver, so the chip processes its own pulse.")
    print("    2. Different routing paths in the FPGA / fabric, producing")
    print("       sub-microsecond edge-shape differences a host-side")
    print("       hardware bit-receiver may classify as separate symbols.")
    print("    3. Independent timing drift between drivers.")
    print()
    print("Acceptable open-drain pattern (Wave 10 / v0.119.42):")
    print("    assign bus_oe = drv_a | drv_b | drv_c;     // OR of LOW enables")
    print("    assign id_bus = bus_oe ? 1'b0 : 1'bz;       // single tristate")
    print("    `id_bus` has exactly one driver; the OR of enables is the")
    print("    standard open-drain control input, not a parallel driver.")
    print()
    print("Fix: route every drive request through a single tristate")
    print("driving the bus net, OR consolidate the FSMs through a single")
    print("tx_phy state machine.")
    print()
    print("Or document an alternative in waivers.json:")
    print('    {"single_bus_driver_alternative": "<reason>"}')
    sys.exit(1)


if __name__ == "__main__":
    main()
