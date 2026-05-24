#!/usr/bin/env python3
"""
Golden Model Generator — Python behavioral model from RTL specification
========================================================================
Generates a Python golden model function from an IC's port list and
behavior rules (extracted from datasheet). The golden model computes
expected outputs for any input combination, enabling:

    1. Pre-FPGA vector validation (before BIST)
    2. Cross-verification of BIST expected values
    3. Exhaustive input space exploration
    4. Stress loop comparison

Usage:
    # CLI: Generate golden model for a known IC
    python3 golden_model_gen.py --ic CD4013B --output cd4013b_golden.py

    # CLI: Generate from a spec JSON file
    python3 golden_model_gen.py --spec my_ic_spec.json --output my_ic_golden.py

    # Programmatic
    from golden_model_gen import generate_golden_model, GoldenModelSpec
    spec = GoldenModelSpec(name="CD4013B", ...)
    code = generate_golden_model(spec)
"""

import sys
import os
import json
import argparse
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class PortDef:
    """Single port definition."""
    name: str
    direction: str   # "input", "output"
    width: int = 1
    description: str = ""
    active_low: bool = False


@dataclass
class BehaviorRule:
    """Single behavior rule (priority-ordered)."""
    priority: int
    condition: str           # Python expression
    assignments: Dict[str, str]  # output_name -> Python expression
    description: str = ""


@dataclass
class GoldenModelSpec:
    """Complete specification for generating a golden model."""
    name: str
    description: str = ""
    ports: List[PortDef] = field(default_factory=list)
    state_vars: List[str] = field(default_factory=list)
    behavior_rules: List[BehaviorRule] = field(default_factory=list)
    initial_state: Dict[str, int] = field(default_factory=dict)
    is_sequential: bool = False
    clock_ports: List[str] = field(default_factory=list)
    reset_behavior: str = ""


# ============================================================================
# Known IC Library
# ============================================================================

KNOWN_ICS = {
    "CD4013B": GoldenModelSpec(
        name="CD4013B",
        description="CMOS Dual D-Type Flip-Flop with Set and Reset",
        ports=[
            PortDef("d1", "input", 1, "Data input, FF1"),
            PortDef("clk1", "input", 1, "Clock input, FF1 (posedge)"),
            PortDef("s1", "input", 1, "Async Set, FF1 (active high)"),
            PortDef("r1", "input", 1, "Async Reset, FF1 (active high)"),
            PortDef("d2", "input", 1, "Data input, FF2"),
            PortDef("clk2", "input", 1, "Clock input, FF2 (posedge)"),
            PortDef("s2", "input", 1, "Async Set, FF2 (active high)"),
            PortDef("r2", "input", 1, "Async Reset, FF2 (active high)"),
            PortDef("q1", "output", 1, "Q output, FF1"),
            PortDef("q1b", "output", 1, "Q-bar output, FF1"),
            PortDef("q2", "output", 1, "Q output, FF2"),
            PortDef("q2b", "output", 1, "Q-bar output, FF2"),
        ],
        state_vars=["q1", "q1b", "q2", "q2b"],
        is_sequential=True,
        clock_ports=["clk1", "clk2"],
        initial_state={"q1": 0, "q1b": 1, "q2": 0, "q2b": 1},
    ),
    "SN74HC163": GoldenModelSpec(
        name="SN74HC163",
        description="4-Bit Synchronous Binary Counter with Synchronous Clear",
        ports=[
            PortDef("clk", "input", 1, "Clock (posedge)"),
            PortDef("clr_n", "input", 1, "Synchronous Clear (active low)"),
            PortDef("load_n", "input", 1, "Synchronous Load (active low)"),
            PortDef("enp", "input", 1, "Count Enable P"),
            PortDef("ent", "input", 1, "Count Enable T"),
            PortDef("a", "input", 1, "Data input A"),
            PortDef("b", "input", 1, "Data input B"),
            PortDef("c", "input", 1, "Data input C"),
            PortDef("d", "input", 1, "Data input D"),
            PortDef("qa", "output", 1, "Count output A (LSB)"),
            PortDef("qb", "output", 1, "Count output B"),
            PortDef("qc", "output", 1, "Count output C"),
            PortDef("qd", "output", 1, "Count output D (MSB)"),
            PortDef("rco", "output", 1, "Ripple Carry Output"),
        ],
        state_vars=["qa", "qb", "qc", "qd"],
        is_sequential=True,
        clock_ports=["clk"],
        initial_state={"qa": 0, "qb": 0, "qc": 0, "qd": 0},
    ),
    "LM75": GoldenModelSpec(
        name="LM75",
        description="Digital Temperature Sensor with I2C Interface",
        ports=[
            PortDef("sda", "input", 1, "I2C data"),
            PortDef("scl", "input", 1, "I2C clock"),
            PortDef("os", "output", 1, "Over-temperature Shutdown"),
            PortDef("addr", "input", 3, "I2C address bits A2:A0"),
        ],
        state_vars=["temp_reg", "config_reg", "tos_reg", "thyst_reg", "pointer_reg"],
        is_sequential=True,
        clock_ports=["scl"],
        initial_state={"temp_reg": 0, "config_reg": 0, "tos_reg": 80,
                       "thyst_reg": 75, "pointer_reg": 0},
    ),
}


# ============================================================================
# Code Generation
# ============================================================================

def _generate_cd4013b_code() -> str:
    """Generate complete CD4013B golden model code."""
    return '''#!/usr/bin/env python3
"""
CD4013B Golden Model — CMOS Dual D-Type Flip-Flop with Set/Reset
================================================================
Behavioral Python model matching the TI CD4013B datasheet.
Used for FPGA BIST cross-verification.

Truth Table (per flip-flop):
    S  R  CLK  D  | Q    Q_bar
    0  0   ^   0  | 0    1      (D capture on posedge)
    0  0   ^   1  | 1    0      (D capture on posedge)
    0  0   X   X  | Q_n  Q_bar_n (hold)
    1  0   X   X  | 1    0      (async set)
    0  1   X   X  | 0    1      (async reset)
    1  1   X   X  | 1    1      (both high — illegal, datasheet-defined)

Usage:
    state = cd4013b_initial_state()
    # Apply test vector: {d1,clk1,s1,r1, d2,clk2,s2,r2}
    state = cd4013b_golden(d1, clk1, s1, r1, d2, clk2, s2, r2, state)
    q1, q1b, q2, q2b = state
"""

from typing import Tuple


State = Tuple[int, int, int, int]  # (q1, q1b, q2, q2b)


def cd4013b_initial_state() -> State:
    """Return default power-on state (after reset)."""
    return (0, 1, 0, 1)


def _ff_logic(d: int, clk: int, s: int, r: int,
              q_prev: int, qb_prev: int,
              was_illegal: bool = False) -> Tuple[int, int]:
    """
    Single flip-flop logic with async SET/RESET priority.

    Priority (highest first):
        1. S=1, R=1 -> Q=1, Q_bar=1 (illegal but deterministic)
        2. S=1, R=0 -> Q=1, Q_bar=0 (async set)
        3. S=0, R=1 -> Q=0, Q_bar=1 (async reset)
        4. CLK posedge (clk=1) -> Q=D, Q_bar=~D (data capture)
        5. Otherwise -> hold previous state

    When transitioning from S=R=1 illegal state to S=R=0,
    SET path wins: Q=1, Q_bar=0.

    Args:
        d: Data input (0 or 1)
        clk: Clock input -- 1 means posedge happened this cycle
        s: Set input (active high)
        r: Reset input (active high)
        q_prev: Previous Q state
        qb_prev: Previous Q_bar state
        was_illegal: True if previous state was S=R=1

    Returns:
        (q_new, qb_new)
    """
    if s and r: return (1, 1)
    elif s: return (1, 0)
    elif r: return (0, 1)
    elif clk: return (d, 1 - d)
    else:
        if was_illegal: return (1, 0)
        return (q_prev, qb_prev)


def cd4013b_golden(d1: int, clk1: int, s1: int, r1: int,
                   d2: int, clk2: int, s2: int, r2: int,
                   state: State) -> State:
    """
    Compute next state for CD4013B dual flip-flop.

    Args:
        d1, clk1, s1, r1: FF1 inputs
        d2, clk2, s2, r2: FF2 inputs
        state: Current (q1, q1b, q2, q2b)

    Returns:
        New (q1, q1b, q2, q2b)
    """
    q1_prev, q1b_prev, q2_prev, q2b_prev = state
    ff1_was_illegal = (q1_prev == 1 and q1b_prev == 1)
    ff2_was_illegal = (q2_prev == 1 and q2b_prev == 1)

    q1_new, q1b_new = _ff_logic(d1, clk1, s1, r1, q1_prev, q1b_prev, ff1_was_illegal)
    q2_new, q2b_new = _ff_logic(d2, clk2, s2, r2, q2_prev, q2b_prev, ff2_was_illegal)

    return (q1_new, q1b_new, q2_new, q2b_new)


def cd4013b_from_vector(vec_in: int, state: State) -> State:
    """
    Convenience: apply an 8-bit BIST test vector.

    Vector format (matching BIST):
        bit7: d1
        bit6: s1
        bit5: r1
        bit4: clk1
        bit3: d2
        bit2: s2
        bit1: r2
        bit0: clk2
    """
    d1   = (vec_in >> 7) & 1
    s1   = (vec_in >> 6) & 1
    r1   = (vec_in >> 5) & 1
    clk1 = (vec_in >> 4) & 1
    d2   = (vec_in >> 3) & 1
    s2   = (vec_in >> 2) & 1
    r2   = (vec_in >> 1) & 1
    clk2 = (vec_in >> 0) & 1

    return cd4013b_golden(d1, clk1, s1, r1, d2, clk2, s2, r2, state)


def cd4013b_state_to_4bit(state: State) -> int:
    """Convert state tuple to 4-bit integer {q1,q1b,q2,q2b}."""
    q1, q1b, q2, q2b = state
    return (q1 << 3) | (q1b << 2) | (q2 << 1) | q2b


# ============================================================================
# Built-in Test Vectors (matching BIST v4/v5)
# ============================================================================

BIST_VECTORS = [
    # (input_8bit, expected_4bit, group, description)
    (0b0_0_1_0__0_0_1_0, 0b0101, 0, "A0: Reset both"),
    (0b0_1_0_0__0_0_0_0, 0b1001, 0, "A1: Set FF1"),
    (0b0_0_1_0__0_0_0_0, 0b0101, 0, "A2: Reset FF1"),
    (0b0_1_1_0__0_0_0_0, 0b1101, 0, "A3: S=R=1 FF1 illegal"),
    (0b0_0_0_0__0_0_0_0, 0b1001, 0, "A4: Release, hold"),
    (0b0_0_1_0__0_0_1_0, 0b0101, 0, "A5: Reset both"),
    (0b0_0_0_0__0_1_0_0, 0b0110, 0, "A6: Set FF2"),
    (0b0_0_0_0__0_0_1_0, 0b0101, 0, "A7: Reset FF2"),
    (0b0_0_1_0__0_0_1_0, 0b0101, 1, "B0: Reset"),
    (0b1_0_0_1__0_0_0_0, 0b1001, 1, "B1: Clock D=1 FF1"),
    (0b0_0_0_1__0_0_0_0, 0b0101, 1, "B2: Clock D=0 FF1"),
    (0b1_0_0_1__0_0_0_0, 0b1001, 1, "B3: Clock D=1 FF1"),
    (0b0_1_0_1__0_0_0_0, 0b1001, 2, "C0: S+CLK FF1"),
    (0b1_0_1_1__0_0_0_0, 0b0101, 2, "C1: R+CLK FF1"),
    (0b0_0_0_0__0_1_0_1, 0b0110, 2, "C2: S+CLK FF2"),
    (0b0_0_0_0__1_0_1_1, 0b0101, 2, "C3: R+CLK FF2"),
    (0b0_0_1_0__0_0_1_0, 0b0101, 3, "D0: Reset both"),
    (0b0_1_0_0__0_1_0_0, 0b1010, 3, "D1: Set both"),
    (0b0_0_1_0__0_0_1_0, 0b0101, 3, "D2: Reset both"),
    (0b1_0_0_1__1_0_0_1, 0b1010, 3, "D3: Clock both D=1"),
    (0b0_0_1_0__0_0_1_0, 0b0101, 4, "E0: Reset both"),
    (0b0_1_0_0__0_0_0_0, 0b1001, 4, "E1: Set FF1 only"),
    (0b0_0_0_0__1_0_0_1, 0b1010, 4, "E2: Clock FF2 D=1"),
    (0b0_0_1_0__0_0_0_0, 0b0110, 4, "E3: Reset FF1"),
    (0b0_0_1_0__0_0_1_0, 0b0101, 5, "F0: Reset both"),
    (0b1_0_0_1__1_0_0_1, 0b1010, 5, "F1: Toggle both"),
    (0b0_0_0_1__0_0_0_1, 0b0101, 5, "F2: Toggle back"),
    (0b1_0_0_1__1_0_0_1, 0b1010, 5, "F3: Toggle again"),
    (0b0_0_1_0__0_0_1_0, 0b0101, 6, "G0: Reset both"),
    (0b1_0_0_1__0_0_0_0, 0b1001, 6, "G1: Clock1"),
    (0b0_0_0_1__0_0_0_0, 0b0101, 6, "G2: Clock2"),
    (0b1_0_0_1__0_0_0_0, 0b1001, 6, "G3: Clock3"),
    (0b0_0_1_0__0_0_1_0, 0b0101, 7, "H0: Reset both"),
    (0b1_0_0_1__1_0_0_1, 0b1010, 7, "H1: Clock both"),
    (0b0_1_0_0__0_0_1_0, 0b1001, 7, "H2: Set FF1, Reset FF2"),
    (0b0_0_1_0__0_1_0_0, 0b0110, 7, "H3: Reset FF1, Set FF2"),
    (0b0_0_1_0__0_0_1_0, 0b0101, 8, "I0: Reset both"),
    (0b1_0_0_1__0_0_0_0, 0b1001, 8, "I1: Clock D=1 FF1"),
    (0b0_1_0_0__0_0_0_0, 0b1001, 8, "I2: Set FF1 (already Q=1)"),
    (0b0_0_0_0__0_0_0_0, 0b1001, 8, "I3: Hold"),
    (0b0_0_0_0__0_1_1_0, 0b1011, 9, "J0: FF2 S=R=1 illegal"),
    (0b0_0_0_0__0_0_0_0, 0b1010, 9, "J1: Release, hold"),
    (0b0_0_1_0__0_0_1_0, 0b0101, 10, "K0: Reset both"),
    (0b1_0_0_1__1_0_0_1, 0b1010, 10, "K1: Clock both"),
    (0b0_0_0_1__0_0_0_1, 0b0101, 10, "K2: Clock both D=0"),
    (0b0_1_0_0__0_1_0_0, 0b1010, 10, "K3: Set both"),
    (0b0_0_1_0__0_0_1_0, 0b0101, 10, "K4: Reset both"),
    (0b0_0_0_0__0_0_0_0, 0b0101, 10, "K5: Hold final"),
]


def validate_vectors() -> Tuple[int, int, list]:
    """
    Run all BIST vectors through golden model and verify expected values.

    Returns:
        (pass_count, fail_count, failures_list)
        Each failure: {'index': i, 'input': hex, 'expected': hex,
                       'golden': hex, 'description': str}
    """
    state = cd4013b_initial_state()
    passes = 0
    fails = 0
    failures = []

    for i, (vec_in, exp_4bit, group, desc) in enumerate(BIST_VECTORS):
        state = cd4013b_from_vector(vec_in, state)
        golden_4bit = cd4013b_state_to_4bit(state)

        if golden_4bit == exp_4bit:
            passes += 1
        else:
            fails += 1
            failures.append({
                'index': i,
                'input': f"0x{vec_in:02X}",
                'expected': f"0x{exp_4bit:X}",
                'golden': f"0x{golden_4bit:X}",
                'state': state,
                'description': desc,
            })

    return passes, fails, failures


# ============================================================================
# Self-Test
# ============================================================================

if __name__ == "__main__":
    print("CD4013B Golden Model — Self-Verification")
    print("=" * 50)

    passes, fails, failures = validate_vectors()

    print(f"\\nResults: {passes} PASS, {fails} FAIL out of {len(BIST_VECTORS)} vectors")

    if failures:
        print(f"\\nFailures:")
        for f in failures:
            print(f"  [{f['index']:2d}] {f['description']}")
            print(f"       Input={f['input']} Expected={f['expected']} "
                  f"Golden={f['golden']} State={f['state']}")

    if fails == 0:
        print("\\nAll vectors match golden model.")
    else:
        print(f"\\n!! {fails} vector(s) have mismatched expectations !!")
        print("These are likely test vector bugs, not RTL bugs.")

    sys.exit(0 if fails == 0 else 1)
'''


def _generate_sn74hc163_code() -> str:
    """Generate SN74HC163 golden model code."""
    return '''#!/usr/bin/env python3
"""
SN74HC163 Golden Model — 4-Bit Synchronous Binary Counter
==========================================================
"""

from typing import Tuple

State = Tuple[int, int, int, int]  # (qa, qb, qc, qd)


def sn74hc163_initial_state() -> State:
    return (0, 0, 0, 0)


def sn74hc163_golden(clk: int, clr_n: int, load_n: int,
                     enp: int, ent: int,
                     a: int, b: int, c: int, d: int,
                     state: State) -> Tuple[State, int]:
    """
    Returns: (new_state, rco)
    """
    qa, qb, qc, qd = state
    count = (qd << 3) | (qc << 2) | (qb << 1) | qa

    if clk:  # posedge
        if not clr_n:
            count = 0
        elif not load_n:
            count = (d << 3) | (c << 2) | (b << 1) | a
        elif enp and ent:
            count = (count + 1) & 0xF

    rco = 1 if (ent and count == 0xF) else 0
    qa = (count >> 0) & 1
    qb = (count >> 1) & 1
    qc = (count >> 2) & 1
    qd = (count >> 3) & 1

    return (qa, qb, qc, qd), rco


if __name__ == "__main__":
    print("SN74HC163 Golden Model — Self-Test")
    state = sn74hc163_initial_state()
    # Count 0 to 15
    for i in range(16):
        state, rco = sn74hc163_golden(1, 1, 1, 1, 1, 0, 0, 0, 0, state)
        qa, qb, qc, qd = state
        val = (qd << 3) | (qc << 2) | (qb << 1) | qa
        expected = (i + 1) & 0xF
        status = "PASS" if val == expected else "FAIL"
        print(f"  Cycle {i+1:2d}: count={val:2d} expected={expected:2d} rco={rco} [{status}]")
    print("Done.")
'''


def generate_golden_model(spec: GoldenModelSpec) -> str:
    """
    Generate a golden model Python file from spec.

    For known ICs, returns hand-crafted models.
    For unknown ICs, generates a template.
    """
    name_upper = spec.name.upper().replace("-", "")

    # Check for known ICs
    if name_upper == "CD4013B":
        return _generate_cd4013b_code()
    elif name_upper in ("SN74HC163", "74HC163"):
        return _generate_sn74hc163_code()

    # Generic template generation
    return _generate_generic_code(spec)


def _generate_generic_code(spec: GoldenModelSpec) -> str:
    """Generate a template golden model for an unknown IC."""
    name_lower = spec.name.lower().replace("-", "_")
    inputs = [p for p in spec.ports if p.direction == "input"]
    outputs = [p for p in spec.ports if p.direction == "output"]

    input_params = ", ".join(f"{p.name}: int" for p in inputs)
    state_type = "Tuple[" + ", ".join("int" for _ in spec.state_vars) + "]" if spec.state_vars else "None"
    output_names = [p.name for p in outputs]

    code = f'''#!/usr/bin/env python3
"""
{spec.name} Golden Model — {spec.description}
{'=' * (len(spec.name) + 17 + len(spec.description))}
Auto-generated template. Fill in behavior rules.

Ports:
'''
    for p in spec.ports:
        code += f"    {p.direction:6s} {p.name}: {p.description}\n"

    code += f'''
"""

from typing import Tuple

'''

    if spec.state_vars:
        code += f"State = Tuple[{', '.join('int' for _ in spec.state_vars)}]"
        code += f"  # ({', '.join(spec.state_vars)})\n\n"
        code += f"def {name_lower}_initial_state() -> State:\n"
        init_vals = ", ".join(str(spec.initial_state.get(v, 0))
                              for v in spec.state_vars)
        code += f"    return ({init_vals})\n\n"

    code += f"def {name_lower}_golden({input_params}"
    if spec.state_vars:
        code += f", state: State"
    code += f") -> "
    if spec.state_vars:
        code += "State"
    else:
        code += f"Tuple[{', '.join('int' for _ in outputs)}]"
    code += ":\n"
    code += f'    """\n'
    code += f"    Compute outputs for {spec.name}.\n"
    code += f"    TODO: Implement behavior rules from datasheet.\n"
    code += f'    """\n'

    if spec.state_vars:
        unpack = ", ".join(spec.state_vars)
        code += f"    {unpack} = state\n\n"

    code += f"    # TODO: Implement behavior rules\n"
    code += f"    # Priority-ordered conditions:\n"
    for rule in spec.behavior_rules:
        code += f"    # P{rule.priority}: if {rule.condition}: {rule.description}\n"
        for out_name, expr in rule.assignments.items():
            code += f"    #     {out_name} = {expr}\n"

    if not spec.behavior_rules:
        code += f"    # (No behavior rules defined — fill from datasheet)\n"
        code += f"    pass\n"

    if spec.state_vars:
        code += f"\n    return ({', '.join(spec.state_vars)})\n"
    else:
        code += f"\n    return ({', '.join(p.name for p in outputs)})\n"

    code += f'\n\nif __name__ == "__main__":\n'
    code += f'    print("{spec.name} Golden Model — Template")\n'
    code += f'    print("TODO: Add test vectors and self-verification")\n'

    return code


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Generate Python golden model from IC specification")
    parser.add_argument("--ic", default=None,
                        help="Known IC name (e.g., CD4013B, SN74HC163)")
    parser.add_argument("--spec", default=None,
                        help="Path to spec JSON file")
    parser.add_argument("--output", "-o", default=None,
                        help="Output file path (default: <ic>_golden.py)")
    parser.add_argument("--validate", action="store_true",
                        help="Run self-validation after generation")
    parser.add_argument("--list", action="store_true",
                        help="List known ICs")
    args = parser.parse_args()

    if args.list:
        print("Known ICs with built-in golden models:")
        for name, spec in KNOWN_ICS.items():
            print(f"  {name}: {spec.description}")
        sys.exit(0)

    if args.spec:
        with open(args.spec) as f:
            data = json.load(f)
        spec = GoldenModelSpec(
            name=data.get("name", "UNKNOWN"),
            description=data.get("description", ""),
            ports=[PortDef(**p) for p in data.get("ports", [])],
            state_vars=data.get("state_vars", []),
            behavior_rules=[BehaviorRule(**r) for r in data.get("behavior_rules", [])],
            initial_state=data.get("initial_state", {}),
            is_sequential=data.get("is_sequential", False),
            clock_ports=data.get("clock_ports", []),
        )
    elif args.ic:
        ic_upper = args.ic.upper().replace("-", "")
        if ic_upper in KNOWN_ICS:
            spec = KNOWN_ICS[ic_upper]
        else:
            print(f"Warning: {args.ic} not in known IC library. Generating template.")
            spec = GoldenModelSpec(name=args.ic, description=f"{args.ic} (template)")
    else:
        parser.print_help()
        sys.exit(1)

    code = generate_golden_model(spec)

    output_path = args.output
    if not output_path:
        output_path = f"{spec.name.lower().replace('-', '_')}_golden.py"

    with open(output_path, "w") as f:
        f.write(code)
    print(f"Golden model generated: {output_path}")

    if args.validate and spec.name.upper() == "CD4013B":
        print("\nRunning self-validation...")
        # Execute the generated file
        import subprocess
        result = subprocess.run([sys.executable, output_path],
                                capture_output=True, text=True)
        print(result.stdout)
        if result.returncode != 0:
            print(result.stderr)
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
