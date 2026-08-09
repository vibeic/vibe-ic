#!/usr/bin/env python3
"""crc_oracle_vector_check.py — BACKLOG-v11 P0.5.

Verify CRC modules' poly + init constants match the L3 / L8 spec
declaration, and (optionally) check the implementation against
spec-derived test vectors via a Python software CRC oracle.

Motivation
==========

v0.116 <benchmark> generated `crc8.sv` with `poly=0x07, init=0x00, no
reflection`, while the <chip-class> spec requires `poly=0x31 forward,
init=0xFF, refin=true, refout=true` (equivalent reflected form:
`poly=0x8C, init=0xFF`). Every received frame silently failed the CRC
check and was dropped. Caught only by hand-decoding the host's CRC byte
off scope and comparing to module output — multiple expensive
iterations.

Two ways this gate could not report that bug
============================================

1. IT NEVER SAW A SPEC. The reader looked for `crc.poly` / `crc.init` /
   `crc_poly` / `crc_init`. No producer in this tree writes any of those
   spellings: the doc-extraction producers write `crc.poly_hex` and
   `crc_parameters.polynomial_hex` / `init_hex` / `reflect_input` /
   `reflect_output` / `xorout_hex` / `width_bits` (the same key skew
   adjudicated for `phase1_quality_parity_check.extract_crc_poly` in
   re #495, whose repair landed in `_spec_floor_keys.py` — this gate was
   never migrated onto it). Against a real project the spec dict came
   back empty and the gate printed `[skipped] no CRC parameters declared
   in L3/L8` and exited 2 — every verdict, PASS and FAIL alike,
   unreachable.

2. ITS OWN BUG CLASS COULD NOT REACH FAIL. `CRC_LITERAL_MISMATCH` — the
   finding for the v0.116 defect — was emitted at severity WARNING, and
   `main()` returns 0 for warning-only findings. The only ERROR-severity
   rule was `CRC_ORACLE_VECTOR_MISMATCH`, which fires only when L3
   carries `crc_test_vectors`; no producer emits those either. So exit 1
   was reachable from a hand-written fixture and from nothing else.

Both are repaired here, and the severity repair is deliberately narrow —
see "Severity" below.

Gate behaviour
==============

1. Parse L3 / L8 for declared CRC parameters under BOTH the incumbent
   and the producer spellings: polynomial (forward or reflected), init,
   refin, refout, xorout, width, and optionally
   `test_vectors: [{input: [bytes], expected: <value>}, …]`.

2. For every RTL module whose name matches `crc[0-9]+`, check that:
     a. The RTL carries the spec init value as a literal of any base
        (`8'hFF`, `8'hff`, `8'd255`, `8'b1111_1111` all count).
     b. The RTL carries the spec polynomial in either orientation
        (forward or bit-reversed — mathematically equivalent).
   Comparison is NUMERIC, not textual, so `_` separators and
   zero-padding do not mint a false mismatch.

3. If test vectors are declared, run a software CRC oracle over every
   reading of the declared parameters that a standards-compliant
   implementation could take, and report a mismatch only when NO
   reading reproduces the declared expectation. That is the claim the
   gate can actually support: the spec contradicts itself.

Severity
========

A missing literal is ERROR only when the CRC module hard-codes its
constants and they contradict the spec: the module body carries at
least one width-matched literal, declares no `parameter` / `localparam`
/ `` `define `` / package import, and takes no poly/init/seed port. In
that shape the constants in the file ARE the implementation's constants
and they are not the spec's — the v0.116 defect exactly, and no further
evidence can change the answer.

When any indirection exists the value may arrive from a package, a
parameter override or a port, and absence from this file proves
nothing — WARNING, as before. So the escalation only ever applies to
cases that already emitted a warning; a module that is silent today
cannot be made loud by it.

False-alert guards
==================

  - Silent if no CRC module exists in RTL (skip exit-2).
  - Silent if no L3/L8 CRC declaration exists, or the doc explicitly
    declares `no_crc_parameters_in_input: true`.
  - Silent if the RTL carries the spec values anywhere — even outside
    the always_ff block, even in a comment. We catch literal absence,
    not algorithmic correctness (formal proof needs Verilator).
  - The oracle runs only for widths it implements (>= 8, multiple-of-4
    nibbles) and only when the declared parameters are complete;
    otherwise it is disclosed as skipped in the JSON rather than
    guessed at.

chip-AGNOSTIC: polynomial/width arithmetic and schema key spellings
only. No design, PDK or vendor literal.

Exit codes: 0 PASS / 1 FAIL / 2 skip
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import _spec_floor_keys as _sfk
from gate_utils import find_modules as _find_modules
from gate_utils import find_rtl_files as _rtl_files
from gate_utils import read_text as _read


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""


# ---------------------------------------------------------------------------
# Spec extraction from L3 / L8
# ---------------------------------------------------------------------------
#
# Every tuple below carries the INCUMBENT spellings first and the spellings the
# producers in this tree actually write after them. Reading order is
# irrelevant (each field is taken from the first alias present), but keeping
# the incumbent first documents that no previously-readable doc changes
# meaning.

#: Containers that hold a CRC parameter block. `_sfk.L3_CRC_CONTAINER_KEYS` is
#: the adjudicated list (re #495); the rest are spellings this gate already
#: accepted plus the two `*_polynomial` blocks the fieldbus/ethernet synths
#: write.
_CRC_CONTAINERS: tuple[str, ...] = tuple(dict.fromkeys(
    _sfk.L3_CRC_CONTAINER_KEYS
    + ("crc_spec", "crc16", "crc32", "crc_engine",
       "fcs_polynomial", "crc_polynomial", "frame_check_sequence")
))

#: Forward-or-unspecified polynomial. `_sfk.L3_CRC_POLY_FIELD_KEYS` supplies
#: poly / polynomial / poly_hex / polynomial_hex.
_POLY_KEYS: tuple[str, ...] = tuple(dict.fromkeys(
    _sfk.L3_CRC_POLY_FIELD_KEYS
    + ("poly_forward", "polynomial_forward", "poly_normal",
       "polynomial_hex_msb_first", "generator_polynomial_hex")
))
_POLY_REFLECTED_KEYS: tuple[str, ...] = (
    "poly_reflected", "poly_refl", "polynomial_reflected",
    "reflected_representation_hex", "poly_reflected_hex",
    "polynomial_hex_lsb_first_shift_form", "polynomial_reversed_hex",
)
_INIT_KEYS: tuple[str, ...] = (
    "init", "init_hex", "initial_value", "initial_value_hex",
    "seed", "seed_hex", "preset", "preset_hex",
)
_XOROUT_KEYS: tuple[str, ...] = (
    "xorout", "xorout_hex", "final_xor", "final_xor_hex", "xor_out_hex",
)
_WIDTH_KEYS: tuple[str, ...] = ("width", "bits", "width_bits", "crc_width_bits")
_REFIN_KEYS: tuple[str, ...] = ("refin", "reflect_in", "reflect_input",
                                "input_reflected")
_REFOUT_KEYS: tuple[str, ...] = ("refout", "reflect_out", "reflect_output",
                                 "output_reflected")
_VECTOR_KEYS: tuple[str, ...] = ("test_vectors", "vectors", "golden_vectors",
                                 "known_answer_tests", "kat_vectors")

#: Flat (un-nested) spellings, matched on the walk. `crc_` prefix + the field
#: name under any of its aliases.
_FLAT_PREFIXES = ("crc_", "crc8_", "crc16_", "crc32_")


def _flat_aliases(keys: tuple[str, ...]) -> set[str]:
    return {p + k for p in _FLAT_PREFIXES for k in keys}


_FLAT_POLY = _flat_aliases(_POLY_KEYS)
_FLAT_POLY_REFL = _flat_aliases(_POLY_REFLECTED_KEYS)
_FLAT_INIT = _flat_aliases(_INIT_KEYS)
_FLAT_XOROUT = _flat_aliases(_XOROUT_KEYS)
_FLAT_WIDTH = _flat_aliases(_WIDTH_KEYS)
_FLAT_REFIN = _flat_aliases(_REFIN_KEYS)
_FLAT_REFOUT = _flat_aliases(_REFOUT_KEYS)
_FLAT_VECTORS = _flat_aliases(_VECTOR_KEYS)


def _declares_no_crc(d: dict) -> bool:
    """The doc's OWN explicit "this design carries no CRC" declaration."""
    for k, v in d.items():
        kl = k.lower()
        if kl.startswith("no_crc") and v is True:
            return True
    return False


def _l3_l8_crc_spec(project: Path) -> dict:
    """Return {width, poly, poly_reflected, init, refin, refout, xorout,
    vectors} or {} if no CRC declaration found."""
    out: dict = {}

    def _set(name: str, value):
        if value is not None and name not in out:
            out[name] = value

    def _absorb(d: dict):
        if _declares_no_crc(d):
            return
        low = {k.lower(): v for k, v in d.items()}
        for k in _POLY_KEYS:
            if low.get(k) is not None:
                _set("poly", _to_int(low[k]))
                break
        for k in _POLY_REFLECTED_KEYS:
            if low.get(k) is not None:
                _set("poly_reflected", _to_int(low[k]))
                break
        for k in _INIT_KEYS:
            if low.get(k) is not None:
                _set("init", _to_int(low[k]))
                break
        for k in _XOROUT_KEYS:
            if low.get(k) is not None:
                _set("xorout", _to_int(low[k]))
                break
        for k in _WIDTH_KEYS:
            if low.get(k) is not None:
                _set("width", _to_int(low[k]))
                break
        for k in _REFIN_KEYS:
            if isinstance(low.get(k), bool):
                _set("refin", low[k])
                break
        for k in _REFOUT_KEYS:
            if isinstance(low.get(k), bool):
                _set("refout", low[k])
                break
        for k in _VECTOR_KEYS:
            if isinstance(low.get(k), list) and low[k]:
                _set("vectors", low[k])
                break

    def _walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                klow = k.lower()
                if klow in _CRC_CONTAINERS and isinstance(v, dict):
                    _absorb(v)
                elif klow in _FLAT_POLY_REFL:
                    _set("poly_reflected", _to_int(v))
                elif klow in _FLAT_POLY:
                    _set("poly", _to_int(v))
                elif klow in _FLAT_INIT:
                    _set("init", _to_int(v))
                elif klow in _FLAT_XOROUT:
                    _set("xorout", _to_int(v))
                elif klow in _FLAT_WIDTH:
                    _set("width", _to_int(v))
                elif klow in _FLAT_REFIN and isinstance(v, bool):
                    _set("refin", v)
                elif klow in _FLAT_REFOUT and isinstance(v, bool):
                    _set("refout", v)
                elif klow in _FLAT_VECTORS and isinstance(v, list) and v:
                    _set("vectors", v)
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    for cand in (
        list(project.glob("phase1/generated_docs/L3*.json"))
        + list(project.glob("phase1/generated_docs/L8*.json"))
        + list(project.glob("phase1/generated_docs/L8R*.json"))
        + list(project.glob("L3*.json"))
        + list(project.glob("L8*.json"))
        + list(project.glob("input/docs/L3*.json"))
        + list(project.glob("input/docs/L8*.json"))
    ):
        try:
            data = json.loads(_read(cand) or "{}")
        except json.JSONDecodeError:
            continue
        _walk(data)
    return out


_VERILOG_LIT_RE = re.compile(
    r"(?:(\d+)\s*)?'\s*[sS]?\s*([hHdDbBoO])\s*([0-9a-fA-FxXzZ?_]+)"
)
_BASES = {"h": 16, "d": 10, "b": 2, "o": 8}


def _to_int(v):
    """Accept int, `0x31`, `49`, and the Verilog literal spellings the RTL
    generators round-trip through L3 (`8'hFF`, `8'h ff`, `32'hFFFF_FFFF`)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if not isinstance(v, str):
        return None
    s = v.strip().replace(" ", "")
    if not s:
        return None
    m = _VERILOG_LIT_RE.fullmatch(s)
    if m and not re.search(r"[xXzZ?]", m.group(3)):
        try:
            return int(m.group(3).replace("_", ""), _BASES[m.group(2).lower()])
        except ValueError:
            return None
    s = s.replace("_", "")
    try:
        if s.lower().startswith("0x"):
            return int(s, 16)
        return int(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Software CRC oracle
# ---------------------------------------------------------------------------

def _reflect(value: int, width: int) -> int:
    mask = (1 << width) - 1
    return int(format(value & mask, "0{}b".format(width))[::-1], 2)


def _crc_reflected(data_bytes: list[int], poly_reflected: int, init: int,
                   width: int, xorout: int) -> int:
    mask = (1 << width) - 1
    crc = init & mask
    for byte in data_bytes:
        crc ^= byte & 0xFF
        for _ in range(8):
            crc = ((crc >> 1) ^ poly_reflected) if (crc & 1) else (crc >> 1)
            crc &= mask
    return (crc ^ xorout) & mask


def _crc_forward(data_bytes: list[int], poly_forward: int, init: int,
                 width: int, xorout: int) -> int:
    mask = (1 << width) - 1
    top = 1 << (width - 1)
    crc = init & mask
    for byte in data_bytes:
        crc = (crc ^ ((byte & 0xFF) << (width - 8))) & mask
        for _ in range(8):
            crc = (((crc << 1) ^ poly_forward) & mask) if (crc & top) \
                else ((crc << 1) & mask)
    return (crc ^ xorout) & mask


def _oracle_candidates(spec_polys: set[int], width: int,
                       refin, refout) -> list[tuple[str, int]]:
    """Every reading of the declared parameters a standards-compliant
    implementation could take.

    A declared polynomial is orientation-AMBIGUOUS in this tree: producers
    write `poly_hex` for both the normal form (0x31) and the reflected form
    (0x8C) of the same polynomial. So each declared constant is tried as
    given AND bit-reversed. When refin/refout are declared and agree, the
    algorithm family is pinned to what they say; otherwise both families are
    admissible. A mismatch is only reported when NONE of these reproduces the
    declared expectation — the one claim the parameters can support.
    """
    constants = set()
    for p in spec_polys:
        if p is None:
            continue
        constants.add(p & ((1 << width) - 1))
        constants.add(_reflect(p, width))
    families: list[str] = []
    if refin is True and refout is True:
        families = ["reflected"]
    elif refin is False and refout is False:
        families = ["forward"]
    else:
        families = ["reflected", "forward"]
    return [(f, c) for f in families for c in sorted(constants)]


# ---------------------------------------------------------------------------
# RTL reading
# ---------------------------------------------------------------------------

_CRC_MODULE_RE = re.compile(r"\bmodule\s+(crc\d+)\b", re.IGNORECASE)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
#: Any of these means a constant can arrive from outside this file.
_INDIRECTION_RE = re.compile(r"\b(?:parameter|localparam|import)\b|`define")
#: A port or parameter that carries the polynomial / seed from the caller.
_CONST_PORT_RE = re.compile(r"\b\w*(?:poly|init|seed)\w*\b", re.IGNORECASE)


def _strip_hdl_comments(text: str) -> str:
    """vibe-ic#731 — a declaration regex must not read a comment. `// module
    controls the round counter` otherwise mints a module named `controls`."""
    return _LINE_COMMENT_RE.sub(" ", _BLOCK_COMMENT_RE.sub(" ", text))


def _literals(text: str) -> list[tuple[int | None, int]]:
    """(declared_width, value) for every sized/unsized Verilog literal."""
    out: list[tuple[int | None, int]] = []
    for m in _VERILOG_LIT_RE.finditer(text):
        digits = m.group(3)
        if re.search(r"[xXzZ?]", digits):
            continue
        try:
            value = int(digits.replace("_", ""), _BASES[m.group(2).lower()])
        except ValueError:
            continue
        w = int(m.group(1)) if m.group(1) else None
        out.append((w, value))
    return out


def _module_width(spec_width, module_name: str) -> int:
    if isinstance(spec_width, int) and 4 <= spec_width <= 128:
        return spec_width
    m = re.search(r"(\d+)$", module_name)
    if m:
        n = int(m.group(1))
        if 4 <= n <= 128:
            return n
    return 8


def _fmt(value: int, width: int) -> str:
    return f"{width}'h{value:0{max(1, (width + 3) // 4)}X}"


def _hardcodes_constants(rtl: str, module_name: str, width: int) -> list[int]:
    """Width-matched literals in the module body when NOTHING can carry a
    constant in from elsewhere; empty list when the module is indirect.

    Returning the literals rather than a bool lets the finding name them,
    which is what makes the ERROR verdict auditable instead of assertive.
    """
    span = None
    for s in _find_modules(_strip_hdl_comments(rtl)):
        if s.name.lower() == module_name.lower():
            span = s
            break
    if span is None:
        return []
    if _INDIRECTION_RE.search(span.body):
        return []
    if _CONST_PORT_RE.search(span.header):
        return []
    return sorted({v for (w, v) in _literals(span.body) if w == width})


def _present(rtl: str, value: int) -> bool:
    """Is `value` carried by ANY literal in the file?

    Numeric, so `8'hFF` / `8'hff` / `8'd255` / `8'b1111_1111` all count. The
    raw text is used on purpose: a value that appears only in a comment still
    counts as declared-somewhere, which keeps this guard exactly as permissive
    as the substring test it replaces.
    """
    return any(v == value for (_w, v) in _literals(rtl))


# ---------------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------------

def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "spec": {},
        "crc_modules": [],
        "vectors_run": 0,
        "vectors_pass": 0,
        "skipped_reason": "",
        "oracle_skipped_reason": "",
        "hardcoded_literals": {},
    }
    spec = _l3_l8_crc_spec(project)
    summary["spec"] = spec

    rtl_files = _rtl_files(project)
    crc_files: list[tuple[Path, str, str]] = []
    for f in rtl_files:
        rtl = _read(f)
        code = _strip_hdl_comments(rtl)
        m = _CRC_MODULE_RE.search(code)
        if m:
            crc_files.append((f, rtl, m.group(1)))
            summary["crc_modules"].append(
                f"{m.group(1)}@{f.relative_to(project)}"
            )

    if not crc_files:
        summary["skipped_reason"] = "no CRC module found in RTL"
        return findings, summary
    if not spec:
        summary["skipped_reason"] = "no CRC parameters declared in L3/L8"
        return findings, summary

    init = spec.get("init")
    poly_fwd = spec.get("poly")
    poly_refl = spec.get("poly_reflected")
    xorout = spec.get("xorout") or 0
    spec_width = spec.get("width")

    # Literal presence check, per CRC module, at that module's width.
    for path, rtl, mod_name in crc_files:
        rel = str(path.relative_to(project))
        width = _module_width(spec_width, mod_name)
        hard = _hardcodes_constants(rtl, mod_name, width)
        if hard:
            summary["hardcoded_literals"][rel] = [_fmt(v, width) for v in hard]

        def _emit(rule_values: list[int], label: str):
            """One finding for a spec constant no literal in the file carries."""
            if any(_present(rtl, v) for v in rule_values):
                return
            shown = " / ".join(_fmt(v, width) for v in rule_values)
            if hard:
                findings.append(Finding(
                    severity="ERROR",
                    rule="CRC_LITERAL_MISMATCH",
                    message=(
                        f"L3/L8 declares CRC {label}={shown}; module "
                        f"`{mod_name}` hard-codes its constants "
                        f"({', '.join(_fmt(v, width) for v in hard)}) and "
                        f"none of them is the declared value. The module "
                        f"takes no poly/init/seed port and declares no "
                        f"parameter, localparam or `define, so no value can "
                        f"reach it from elsewhere: this implementation "
                        f"computes a different CRC than the spec declares, "
                        f"and every frame checked against it will be "
                        f"rejected."
                    ),
                    file=rel,
                ))
            else:
                findings.append(Finding(
                    severity="WARNING",
                    rule="CRC_LITERAL_MISMATCH",
                    message=(
                        f"L3/L8 declares CRC {label}={shown}, but no literal "
                        f"in {rel} carries that value. Module `{mod_name}` "
                        f"parameterises or imports its constants, so the "
                        f"value may legitimately arrive from elsewhere — "
                        f"confirm it by hand."
                    ),
                    file=rel,
                ))

        if init is not None:
            _emit([init & ((1 << width) - 1)], "init")
        if poly_fwd is not None or poly_refl is not None:
            poly_cands: list[int] = []
            for p in (poly_fwd, poly_refl):
                if p is None:
                    continue
                poly_cands.append(p & ((1 << width) - 1))
                poly_cands.append(_reflect(p, width))
            _emit(sorted(set(poly_cands)), "polynomial (either orientation)")

    # Software oracle vector check — a spec self-consistency test.
    vectors = spec.get("vectors") or []
    oracle_width = _module_width(spec_width, crc_files[0][2])
    if not vectors:
        summary["oracle_skipped_reason"] = "no test vectors declared in L3/L8"
    elif init is None or (poly_fwd is None and poly_refl is None):
        summary["oracle_skipped_reason"] = (
            "declared parameters incomplete (need init and a polynomial)")
    elif oracle_width < 8 or oracle_width % 8:
        summary["oracle_skipped_reason"] = (
            f"width {oracle_width} outside the implemented oracle "
            f"(byte-fed widths that are a multiple of 8)")
    else:
        cands = _oracle_candidates({poly_fwd, poly_refl}, oracle_width,
                                   spec.get("refin"), spec.get("refout"))
        for v in vectors:
            if not isinstance(v, dict):
                continue
            inputs, expected = _vector_fields(v)
            if inputs is None or expected is None:
                continue
            ints = _byte_list(inputs)
            exp = _to_int(expected) if not isinstance(expected, int) else expected
            if ints is None or exp is None:
                continue
            exp &= (1 << oracle_width) - 1
            got: list[str] = []
            matched = False
            for family, poly in cands:
                fn = _crc_reflected if family == "reflected" else _crc_forward
                calc = fn(ints, poly, init, oracle_width, xorout)
                got.append(f"{family}/{_fmt(poly, oracle_width)}"
                           f"={_fmt(calc, oracle_width)}")
                if calc == exp:
                    matched = True
                    break
            summary["vectors_run"] += 1
            if matched:
                summary["vectors_pass"] += 1
            else:
                findings.append(Finding(
                    severity="ERROR",
                    rule="CRC_ORACLE_VECTOR_MISMATCH",
                    message=(
                        f"No reading of the declared CRC parameters "
                        f"(init={_fmt(init, oracle_width)}, xorout="
                        f"{_fmt(xorout, oracle_width)}, width={oracle_width}) "
                        f"reproduces the declared expectation "
                        f"{_fmt(exp, oracle_width)} for input bytes "
                        f"{inputs}. Tried: {'; '.join(got)}. The spec "
                        f"contradicts itself — fix the declaration before "
                        f"generating RTL."
                    ),
                ))
    return findings, summary


def _vector_fields(v: dict):
    """(inputs, expected) under any declared spelling.

    Membership + `is not None`, never truthiness: an expected CRC of 0x00 and
    an empty-message input are both legitimate vectors, and an `or` chain
    silently drops them — a vector that can never fail is not a test.
    """
    low = {k.lower(): val for k, val in v.items()}
    inputs = None
    for k in ("input", "inputs", "data", "bytes", "message", "input_bytes",
              "payload"):
        if k in low and low[k] is not None:
            inputs = low[k]
            break
    expected = None
    for k in ("expected", "expected_crc", "expected_hex", "crc", "crc_hex",
              "output", "result"):
        if k in low and low[k] is not None:
            expected = low[k]
            break
    return inputs, expected


def _byte_list(inputs) -> list[int] | None:
    if isinstance(inputs, str):
        toks = [t for t in re.split(r"[\s,]+", inputs.strip()) if t]
        if len(toks) == 1 and not toks[0].lower().startswith("0x"):
            h = toks[0]
            if len(h) % 2 == 0 and re.fullmatch(r"[0-9a-fA-F]+", h):
                toks = [h[i:i + 2] for i in range(0, len(h), 2)]
                return [int(t, 16) for t in toks]
        vals = [_to_int(t if t.lower().startswith("0x") else "0x" + t)
                for t in toks]
        return None if any(x is None for x in vals) else [x & 0xFF for x in vals]
    if isinstance(inputs, list):
        vals = [b if isinstance(b, int) else _to_int(b) for b in inputs]
        return None if any(x is None for x in vals) else [x & 0xFF for x in vals]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(prog="crc_oracle_vector_check")
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
            "program": "crc_oracle_vector_check",
            "passed": not findings,
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2))

    print(f"=== crc_oracle_vector_check ({project.name}) ===")
    if summary["skipped_reason"]:
        print(f"  [skipped] {summary['skipped_reason']}")
        return 2
    if not findings:
        n = summary.get("vectors_pass", 0)
        print(f"  [PASS] {len(summary['crc_modules'])} CRC module(s); "
              f"{n} test vector(s) match")
        if summary.get("oracle_skipped_reason"):
            print(f"  [note] oracle not run: "
                  f"{summary['oracle_skipped_reason']}")
        return 0
    has_error = any(f.severity == "ERROR" for f in findings)
    for f in findings:
        loc = f" ({f.file})" if f.file else ""
        print(f"  [{f.severity.lower()}] {f.rule}{loc}: {f.message}")
    if has_error:
        print(f"\nOverall: FAIL ({len(findings)} issue(s))")
        return 1
    print(f"\nOverall: PASS (with {len(findings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
