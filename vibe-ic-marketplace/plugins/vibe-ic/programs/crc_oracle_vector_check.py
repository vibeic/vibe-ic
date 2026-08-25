#!/usr/bin/env python3
"""crc_oracle_vector_check.py — BACKLOG-v11 P0.5.

Verify CRC modules' poly + init constants match the L3 / L8 spec
declaration, and (optionally) check the implementation against
spec-derived test vectors via a Python software CRC oracle.

Motivation
==========

v0.116 <benchmark> generated `crc8.sv` with `poly=0x07, init=0x00, no
reflection`, while the <chip-class> / Apple-MFi spec requires
`poly=0x31 forward, init=0xFF, refin=true, refout=true` (equivalent
reflected form: `poly=0x8C, init=0xFF`). Every received frame silently
failed the CRC check and was dropped. Caught only by hand-decoding
the host's CRC byte off scope and comparing to module output —
multiple expensive iterations.

Gate behaviour
==============

1. Parse L3 / L8 for declared CRC parameters: poly_forward,
   poly_reflected, init, refin, refout, xorout, and optionally
   `crc_test_vectors: [{input: [bytes], expected: <byte>}, …]`.

2. For every RTL module whose name matches `crc[0-9]+` (CRC-8 / CRC-16
   / CRC-32 / etc.), check that:
     a. The RTL contains the spec init value as a hex literal
        (e.g. `8'hFF` if init=0xFF).
     b. The RTL contains the spec poly value (forward OR reflected
        form, since either is mathematically equivalent).
   If either is missing, emit `CRC_LITERAL_MISMATCH` error.

3. If `crc_test_vectors` is provided in L3, run a software CRC8
   oracle (poly_reflected + init from spec) on each vector and verify
   the expected match. This catches ambiguity in the spec's own
   parameters.

False-alert guards
==================

  - Silent if no CRC module exists in RTL (skip exit-2).
  - Silent if no L3/L8 CRC declaration exists.
  - Silent if RTL contains the spec values somewhere — even outside
    the always_ff block. We only catch literal absence, not algorithmic
    correctness (formal proof needs Verilator). Algorithmic correctness
    is enforced via the test_vectors path when L3 supplies them.

Exit codes: 0 PASS / 1 FAIL / 2 skip
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from gate_utils import find_rtl_files as _rtl_files
from gate_utils import read_text as _read

# ---------------------------------------------------------------------------
# The two CRC programs this gate COMPOSES rather than re-implements.
#
# `crc_vector_gen` owns the ONE parametric byte-mode CRC reference in the tree
# (widths 4..32, refin/refout/xorout). This file used to carry a second,
# CRC-8-reflected-only copy of that arithmetic, and a second copy of a CRC is
# precisely the defect `crc_vector_gen`'s own header records: the hand-written
# CRC8 that silently implemented the bit-reversed polynomial form while the
# reference did not. `_crc8_reflected` below now DELEGATES; its signature and
# its results are unchanged (proved by equality over the reflected identity
# poly_msb = reflect8(poly_reflected), init_msb = reflect8(init)).
#
# `cmd_protocol_crc_verify` owns the INVERSE question. When the oracle
# disagrees with a declared parameter set this gate could only ever say "these
# parameters are inconsistent" — it named the defect and not the repair, and
# the 2026-04-22 audit that motivated that program recorded exactly this gap:
# sixteen golden command/payload/CRC triples sat in the spec and nothing ever
# asked which parameters actually reproduce them. On a mismatch this gate now
# asks, and puts the answer in the finding.
#
# Both are imported DEFENSIVELY: a packaging that ships this checker without
# its neighbours degrades to the previous behaviour instead of crashing a gate
# the P0 umbrella runs.
try:
    import crc_vector_gen as _crcgen            # type: ignore
except Exception:                               # pragma: no cover - defensive
    _crcgen = None
try:
    import cmd_protocol_crc_verify as _crcderive  # type: ignore
except Exception:                               # pragma: no cover - defensive
    _crcderive = None


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""


# ---------------------------------------------------------------------------
# Spec extraction from L3 / L8
# ---------------------------------------------------------------------------

def _l3_l8_crc_spec(project: Path) -> dict:
    """Return {width: int, poly: int, poly_reflected: int, init: int,
                refin: bool, refout: bool, xorout: int, vectors: [...]}
    or {} if no CRC declaration found."""
    out: dict = {}
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

        def _walk(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    klow = k.lower()
                    if klow in ("crc", "crc_spec", "crc8", "crc16",
                                "crc_engine", "crc_parameters"):
                        if isinstance(v, dict):
                            _absorb(v)
                    elif klow == "crc_poly" or klow == "crc_polynomial":
                        if isinstance(v, (int, str)):
                            out.setdefault("poly", _to_int(v))
                    elif klow == "crc_poly_reflected":
                        out.setdefault("poly_reflected", _to_int(v))
                    elif klow == "crc_init":
                        out.setdefault("init", _to_int(v))
                    elif klow == "crc_refin":
                        out.setdefault("refin", bool(v))
                    elif klow == "crc_refout":
                        out.setdefault("refout", bool(v))
                    elif klow == "crc_xorout":
                        out.setdefault("xorout", _to_int(v))
                    elif klow == "crc_width" or klow == "crc_bits":
                        out.setdefault("width", _to_int(v))
                    elif klow in ("crc_test_vectors", "crc_vectors"):
                        if isinstance(v, list):
                            out.setdefault("vectors", v)
                    _walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item)

        def _absorb(d: dict):
            for k, v in d.items():
                klow = k.lower()
                if klow in ("poly", "polynomial"):
                    out.setdefault("poly", _to_int(v))
                elif klow in ("poly_reflected", "poly_refl", "polynomial_reflected"):
                    out.setdefault("poly_reflected", _to_int(v))
                elif klow == "init":
                    out.setdefault("init", _to_int(v))
                elif klow in ("refin", "reflect_in"):
                    out.setdefault("refin", bool(v))
                elif klow in ("refout", "reflect_out"):
                    out.setdefault("refout", bool(v))
                elif klow == "xorout":
                    out.setdefault("xorout", _to_int(v))
                elif klow in ("width", "bits"):
                    out.setdefault("width", _to_int(v))
                elif klow in ("test_vectors", "vectors"):
                    if isinstance(v, list):
                        out.setdefault("vectors", v)

        _walk(data)
    return out


def _to_int(v):
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip()
        try:
            if s.lower().startswith("0x"):
                return int(s, 16)
            return int(s)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Software CRC8 oracle (reflected, LSB-first)
# ---------------------------------------------------------------------------

def _reflect8(v: int) -> int:
    return int("{:08b}".format(v & 0xFF)[::-1], 2)


def _crc8_reflected(data_bytes: list[int], poly_reflected: int, init: int) -> int:
    """LSB-first (reflected) CRC-8 over `data_bytes`.

    DELEGATES to `crc_vector_gen.crc_byte_mode`, the tree's single parametric
    CRC reference. The reflected engine `(crc>>1) ^ poly_reflected` is exactly
    the MSB-first engine driven with the reflected polynomial and the reflected
    register seed, with refin/refout set and no final XOR — so the spec below
    is a restatement of this function's contract, not a new convention.

    The literal fallback is kept for a checkout that ships this gate without
    `crc_vector_gen`; it is the previous body, byte for byte.
    """
    if _crcgen is not None:
        spec = _crcgen.CrcSpec(
            width=8, poly=_reflect8(poly_reflected), init=_reflect8(init),
            refin=True, refout=True, xorout=0, name="l3_declared_crc8")
        return _crcgen.crc_byte_mode(bytes(b & 0xFF for b in data_bytes), spec)
    crc = init & 0xFF
    for byte in data_bytes:
        crc ^= byte & 0xFF
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ poly_reflected
            else:
                crc >>= 1
    return crc & 0xFF


def _params_the_vectors_imply(pairs: list) -> str:
    """Name the CRC-8 parameter set that reproduces EVERY supplied vector.

    `pairs` is [(data_bytes, expected_int), ...]. Returns a sentence to append
    to a mismatch finding, or "" when nothing can be said. Never raises: a
    diagnostic that can fail the gate it is explaining is worse than no
    diagnostic.
    """
    if _crcderive is None or not pairs:
        return ""
    try:
        vectors = [{"data_hex": " ".join(f"{b & 0xFF:02X}" for b in data),
                    "crc_hex": f"{exp & 0xFF:02X}"} for data, exp in pairs]
        res = _crcderive.verify(vectors, 8)
        if not isinstance(res, dict) or res.get("error"):
            return ""
        best = res.get("best_match")
        if best:
            return (" cmd_protocol_crc_verify: these {n} vector(s) ARE "
                    "reproduced by poly={p} init={i} refin={ri} refout={ro} "
                    "xorout={x} ({name}) — declare that instead."
                    .format(n=res.get("vectors_total"), p=best.get("poly"),
                            i=best.get("init"), ri=best.get("refin"),
                            ro=best.get("refout"), x=best.get("xorout"),
                            name=best.get("preset")))
        return (" cmd_protocol_crc_verify: NO CRC-8 parameter set reproduces "
                "all {n} declared vector(s) — the vectors themselves, not only "
                "the parameters, need review.".format(
                    n=res.get("vectors_total")))
    except Exception:                           # pragma: no cover - defensive
        return ""


# ---------------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------------

_CRC_MODULE_RE = re.compile(r"\bmodule\s+(crc\d+)\b", re.IGNORECASE)


def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "spec": {},
        "crc_modules": [],
        "vectors_run": 0,
        "vectors_pass": 0,
        "skipped_reason": "",
    }
    spec = _l3_l8_crc_spec(project)
    summary["spec"] = spec

    rtl_files = _rtl_files(project)
    crc_files: list[tuple[Path, str]] = []
    for f in rtl_files:
        rtl = _read(f)
        m = _CRC_MODULE_RE.search(rtl)
        if m:
            crc_files.append((f, rtl))
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

    # Compute reflected poly if only forward given, and vice versa
    if poly_fwd is not None and poly_refl is None:
        # Reflect 8 bits
        poly_refl = int("{:08b}".format(poly_fwd & 0xFF)[::-1], 2)
    if poly_refl is not None and poly_fwd is None:
        poly_fwd = int("{:08b}".format(poly_refl & 0xFF)[::-1], 2)

    # Literal presence check
    for path, rtl in crc_files:
        rel = str(path.relative_to(project))
        if init is not None:
            init_lit = f"8'h{init:02X}"
            init_lit_lc = f"8'h{init:02x}"
            if init_lit not in rtl and init_lit_lc not in rtl:
                findings.append(Finding(
                    severity="WARNING",
                    rule="CRC_LITERAL_MISMATCH",
                    message=(
                        f"L3/L8 declares CRC init={init_lit}, but RTL "
                        f"does not contain that literal anywhere. v0.116 "
                        f"<benchmark> lesson: a wrong init silently fails "
                        f"every CRC check."
                    ),
                    file=rel,
                ))
        if poly_fwd is not None and poly_refl is not None:
            poly_fwd_lit = f"8'h{poly_fwd:02X}"
            poly_fwd_lc = f"8'h{poly_fwd:02x}"
            poly_refl_lit = f"8'h{poly_refl:02X}"
            poly_refl_lc = f"8'h{poly_refl:02x}"
            has_any = any(
                lit in rtl for lit in (poly_fwd_lit, poly_fwd_lc,
                                       poly_refl_lit, poly_refl_lc)
            )
            if not has_any:
                findings.append(Finding(
                    severity="WARNING",
                    rule="CRC_LITERAL_MISMATCH",
                    message=(
                        f"L3/L8 declares poly_forward={poly_fwd_lit} / "
                        f"poly_reflected={poly_refl_lit}, but RTL "
                        f"contains neither value. RTL implementation "
                        f"likely uses a different polynomial."
                    ),
                    file=rel,
                ))

    # Software oracle vector check
    vectors = spec.get("vectors") or []
    # Every well-formed (bytes -> expected) pair, kept whether it matched or
    # not. The derivation below has to see the SAME population the oracle
    # judged: handing it only the failing rows would ask "what reproduces the
    # mismatches", which has an answer that reproduces nothing else.
    parsed_pairs: list = []
    mismatched: list = []
    if vectors and poly_refl is not None and init is not None:
        for v in vectors:
            if not isinstance(v, dict):
                continue
            inputs = v.get("input") or v.get("data") or v.get("bytes")
            expected = v.get("expected") or v.get("crc") or v.get("output")
            if inputs is None or expected is None:
                continue
            ints = [_to_int(b) if isinstance(b, str) else int(b) for b in inputs]
            ints = [b for b in ints if b is not None]
            exp = _to_int(expected) if isinstance(expected, str) else int(expected)
            calc = _crc8_reflected(ints, poly_refl, init)
            summary["vectors_run"] += 1
            parsed_pairs.append((ints, exp))
            if calc == exp:
                summary["vectors_pass"] += 1
            else:
                mismatched.append((inputs, calc, exp))
        # ONE derivation for the whole vector set, not one per failing row: the
        # answer is a property of the set, and asking 16 times would print the
        # same sentence 16 times.
        derived = _params_the_vectors_imply(parsed_pairs) if mismatched else ""
        if derived:
            summary["derived_parameters"] = derived.strip()
        for inputs, calc, exp in mismatched:
            findings.append(Finding(
                severity="ERROR",
                rule="CRC_ORACLE_VECTOR_MISMATCH",
                message=(
                    f"CRC software oracle (poly_reflected="
                    f"0x{poly_refl:02X}, init=0x{init:02X}) on "
                    f"input bytes {inputs} produces 0x{calc:02X}, "
                    f"but L3/L8 declares expected=0x{exp:02X}. "
                    f"Spec parameters are inconsistent — fix the "
                    f"declaration before generating RTL." + derived
                ),
            ))
    return findings, summary


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
