#!/usr/bin/env python3
"""Opcode field-width bound + L3<->L15 hex-consistency check (v0.2.13).

Closes the gap that let the usb_pd benchmark ship FABRICATED data-message
opcodes 0x11-0x1F: USB-PD's Message Type is a 4-bit field (max 0xF), and the
SAME design's L15 encoding table already said 0x01/0x03/0x0F — but gated parity
was blind because the gold copied the identical wrong hexes (v0.1.89 lesson).

Two deterministic, chip-AGNOSTIC checks over a project's generated L-docs:

  (1) FIELD-WIDTH bound — if L4/L8 declare an opcode / command-type / message-type
      field of width W bits, every L3.opcodes[].hex must satisfy
      int(hex) <= 2**W - 1. A hex that overflows the declared field is
      structurally impossible (never a judgment call) -> FAIL.

  (2) L3<->L15 CONSISTENCY — for any mnemonic that appears in BOTH L3.opcodes
      and an L15 encoding table, the hex must match. A mismatch is an
      intra-design contradiction -> FAIL.

Both are conservative: when no field width can be extracted, the width check is
skipped (reported, not failed); only hex-bearing, name-matched rows are compared.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROGRAMS_DIR = Path(__file__).resolve().parent
# flow #486: parents[3] = repo root on the source monorepo. On the flattened
# install cache programs/ sits directly under the plugin root with no
# monorepo ancestors, so guard against IndexError at import (REPO_ROOT is
# only used to derive default paths, never as detection logic).
try:
    REPO_ROOT = PROGRAMS_DIR.parents[3]
except IndexError:
    REPO_ROOT = PROGRAMS_DIR.parent  # plugin root (cache tree)

_HEX_RE = re.compile(r"^0x[0-9a-fA-F]+$")
_BITRANGE_RE = re.compile(r"\[(\d+)\s*:\s*0\]")
# Field names that denote the opcode / command-type / message-type selector.
_TYPE_FIELD_RE = re.compile(
    r"(?:message[\s_]*type|command[\s_]*type|cmd[\s_]*type|op[\s_]*code|"
    r"opcode|cmd[\s_]*opcode)", re.I)


#: Nothing was examined. Deliberately NOT 0 and NOT 1: a caller must be able to
#: tell "I looked and it is clean" from "I could not look", and must not read a
#: path typo as a finding either.
RC_NOTHING_EXAMINED = 2


def _load(gd: Path, name: str):
    p = gd / f"{name}.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _hexval(s):
    if isinstance(s, str) and _HEX_RE.match(s.strip()):
        try:
            return int(s, 16)
        except Exception:
            return None
    return None


def _l3_name_hex(l3: dict):
    """{mnemonic_lower: (hexval, hexstr)} from L3.opcodes (real hexes only)."""
    out = {}
    for op in (l3.get("opcodes") or []):
        if not isinstance(op, dict):
            continue
        name = op.get("name")
        v = _hexval(op.get("hex"))
        if isinstance(name, str) and v is not None:
            out.setdefault(name.strip().lower(), (v, op.get("hex")))
    return out


def _iter_l15_name_hex(obj):
    """Yield (name_lower, hexval, hexstr) from any L15 table-like structure:
    rows of [hex, name] / [name, hex] / [name, ..., hex], or dict rows."""
    if isinstance(obj, dict):
        rows = obj.get("rows")
        if isinstance(rows, list):
            for r in rows:
                cells = list(r.values()) if isinstance(r, dict) else (
                    r if isinstance(r, list) else [])
                hexes = [(c, _hexval(c)) for c in cells if _hexval(c) is not None]
                names = [c for c in cells
                         if isinstance(c, str) and _hexval(c) is None
                         and re.search(r"[A-Za-z]", c)]
                if len(hexes) == 1 and names:
                    # the longest alpha cell is the mnemonic
                    nm = max(names, key=len)
                    yield nm.strip().lower(), hexes[0][1], hexes[0][0]
        for v in obj.values():
            yield from _iter_l15_name_hex(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_l15_name_hex(v)


def _declared_type_width(l4, l8):
    """Best-effort: width W of the opcode/type field, or None."""
    blobs = []
    for d in (l4, l8):
        if isinstance(d, dict):
            blobs.append(json.dumps(d))
    # Pattern A: a register/field whose name matches a type-field and a [W-1:0].
    for blob in blobs:
        # find "...message type...[3:0]..." within a small window
        for m in _TYPE_FIELD_RE.finditer(blob):
            window = blob[m.start(): m.start() + 120]
            br = _BITRANGE_RE.search(window)
            if br:
                return int(br.group(1)) + 1
    # Pattern B: an explicit width parameter like CMD_OPCODE_BITS / *TYPE_BITS.
    for d in (l8,):
        if not isinstance(d, dict):
            continue
        for container in ("width_parameters", "key_constants", "named_parameters"):
            wp = d.get(container)
            if isinstance(wp, dict):
                for k, v in wp.items():
                    if _TYPE_FIELD_RE.search(k) and ("bit" in k.lower()
                                                     or "width" in k.lower()):
                        w = v.get("width_bits") if isinstance(v, dict) else v
                        if isinstance(w, int):
                            return w
    return None


def check_project(project_dir: Path):
    gd = project_dir / "phase1" / "generated_docs"
    if not gd.is_dir():
        gd = project_dir  # allow pointing directly at a generated_docs dir
    l3 = _load(gd, "L3_CMD_PROTOCOL")
    l4 = _load(gd, "L4_REGMAP")
    l8 = _load(gd, "L8_RTL_CONSTANTS")
    l15 = _load(gd, "L15_ENCODING_TABLES")
    findings = []
    if not isinstance(l3, dict) or not (l3.get("opcodes")):
        return findings  # no command protocol -> nothing to check
    l3map = _l3_name_hex(l3)

    # (1) field-width bound
    w = _declared_type_width(l4, l8)
    if w is not None:
        ceil = (1 << w) - 1
        for op in l3.get("opcodes"):
            if not isinstance(op, dict):
                continue
            v = _hexval(op.get("hex"))
            if v is not None and v > ceil:
                findings.append({
                    "kind": "FIELD_WIDTH_OVERFLOW",
                    "opcode": op.get("name"), "hex": op.get("hex"),
                    "declared_width_bits": w, "max_hex": hex(ceil),
                    "detail": f"opcode {op.get('name')}={op.get('hex')} exceeds "
                              f"the declared {w}-bit type field (max {hex(ceil)})"})

    # (2) L3<->L15 consistency
    if isinstance(l15, dict):
        seen = {}
        for nm, v, hx in _iter_l15_name_hex(l15.get("fields", l15)):
            seen.setdefault(nm, (v, hx))
        for nm, (v3, h3) in l3map.items():
            if nm in seen and seen[nm][0] != v3:
                findings.append({
                    "kind": "L3_L15_HEX_MISMATCH",
                    "mnemonic": nm, "l3_hex": h3, "l15_hex": seen[nm][1],
                    "detail": f"mnemonic '{nm}' is {h3} in L3 but "
                              f"{seen[nm][1]} in L15"})
    return findings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path, nargs="?")
    ap.add_argument("--benchmark-dir", type=Path, default=None,
                    help="check every <bench>/ under this dir")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    targets = []
    if args.benchmark_dir:
        if not args.benchmark_dir.is_dir():
            print(f"[NOT CHECKED] --benchmark-dir does not exist: "
                  f"{args.benchmark_dir}", file=sys.stderr)
            return RC_NOTHING_EXAMINED
        for d in sorted(args.benchmark_dir.iterdir()):
            # A subdirectory this process cannot stat is not a subdirectory
            # without a phase1/ tree. Measured: one unreadable entry under the
            # sweep root (/tmp/snap-private-tmp) took the whole survey down
            # with a PermissionError traceback, so the other benchmarks were
            # never examined and the operator saw a crash rather than a
            # verdict. Skipped loudly, and the sweep continues.
            try:
                if d.is_dir() and (d / "phase1").is_dir():
                    targets.append(d)
            except OSError as exc:
                print(f"[SKIPPED] {d}: {exc.__class__.__name__} — not "
                      f"examined", file=sys.stderr)
    elif args.project_dir:
        if not args.project_dir.is_dir():
            # THE SHAPE THIS GATE EXISTS INSIDE: a project that is not there
            # produced zero findings, and zero findings printed
            # "checked 1 project(s) — ALL_PASS" and exited 0. A typo in a path
            # was therefore indistinguishable from a clean chip, and the clean
            # answer was the one a caller acted on.
            print(f"[NOT CHECKED] no such project: {args.project_dir} — "
                  f"nothing was examined, which is not a pass", file=sys.stderr)
            return RC_NOTHING_EXAMINED
        targets = [args.project_dir]
    else:
        ap.error("give a project_dir or --benchmark-dir")

    if not targets:
        # The third exit from the same room. Every entry under the sweep root
        # was unreadable, or none carried a phase1/ tree — either way nothing
        # was opened, and "checked 0 project(s) — ALL_PASS" is the sentence a
        # caller would act on.
        print(f"[NOT CHECKED] no project with a phase1/ tree was found — "
              f"nothing was examined, which is not a pass", file=sys.stderr)
        return RC_NOTHING_EXAMINED

    all_findings = {}
    for t in targets:
        f = check_project(t)
        if f:
            all_findings[t.name] = f
            for x in f:
                print(f"  [{x['kind']}] {t.name}: {x['detail']}")
    if args.json:
        args.json.write_text(json.dumps(all_findings, indent=2))
    if all_findings:
        n = sum(len(v) for v in all_findings.values())
        print(f"\n{n} opcode-consistency finding(s) in "
              f"{len(all_findings)} benchmark(s)")
        return 1
    print(f"checked {len(targets)} project(s) — ALL_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
