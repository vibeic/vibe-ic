#!/usr/bin/env python3
"""l4_regmap_phase2_emitter_contract_check.py — SEMANTIC layer gate for L4.

THE CONSUMER MODEL (#509)
=========================
``phase2_scaffold_gen`` is an ORACLE, not a flow step: no runner and no
step of ``flow/phase1_phase2_phase3.yaml`` calls it, at any version. It
is the EXECUTABLE SPECIFICATION of what a conforming Phase 2 must be
able to build from L4, and this gate drives it as such. Every sentence
below is accordingly counterfactual — what a conforming phase 2 WOULD
emit, never what phase 2 does emit. The requirement is unaffected: an L4
that cannot yield a buildable register file is underspecified whether or
not any program consumes it.

BLOCKS (exit 1). Rationale for blocking rather than advising
=============================================================
What this gate protects against is an UNCOMPILABLE register file — a
defect that, in any phase 2 conforming to the contract, surfaces several
steps downstream behind an opaque tool error. ``emit_regs_v()`` writes
one ``reg`` declaration per L4 register using a sanitized identifier;
when two L4 registers sanitize to the same identifier the emitted
``<top>_regs.v`` would declare the same signal twice, and every later
step — lint, synth, simulation, LEC — would fail with a message naming
the *identifier*, not the L4 record that produced it. The layer that
caused it is five steps upstream. An advisory verdict here buys
nothing: the flow cannot proceed either way, and the only difference is
how long it takes to find out why. So: FAIL blocks.

The contract this gate enforces
===============================
    A layer is complete when the requirement is present IN THE LAYER
    THAT CONSUMES IT, in an ACTIONABLE FORM — not when a token appears
    somewhere.

This is the L4 check that DIFFS the layer against the register block
``phase2_scaffold_gen`` — the contract oracle — would emit from it. It
does not restate the emitter's rules: it imports ``derive_registers()``
and ``emit_regs_v()`` and inspects their real output, so it stays
correct when the specification changes. It is deliberately disjoint from
``l4_regmap_enumerated_values_typed_check`` (field-level enum typing) —
this one is about whether the register FILE can be built at all.

Requirements
------------
  R1  every register ``derive_registers()`` returns must carry a
      non-empty, UNIQUE Verilog identifier. Measured on a real Phase-1
      output: two L4 entries with ``name: ""`` both sanitized to the
      same fallback identifier, and nine counter registers collided
      pairwise — ``emit_regs_v()`` duly produced ten duplicated ``reg``
      declarations when driven on it. The names were "present" in L4;
      they were not present in a form the emitter could turn into
      distinct signals.

  R2  a register whose OWN record states an address must state it under
      a key ``derive_registers()`` reads (``offset`` / ``address``).
      This is the load-bearing check and it is derived, not hardcoded:
      the gate scans each register record for an address-shaped VALUE
      under any key, then asks the emitter what it actually extracted.
      A record that carries ``0x1a110000`` under some other key while
      the emitter sees an empty offset is the exact defect this whole
      family of gates exists for — the address is in the layer, and the
      contract's reader cannot see it, so ``emit_regs_v()`` writes
      ``// TODO — address decode (per L4 offsets)`` and no conforming
      phase 2 could generate the decode. Measured on a real Phase-1
      output: 32 of 80 registers carried their address under
      ``addr_hex``.

  R3  two registers must not claim the same decoded address — an
      ambiguous decode. Derived from L4's own contents.

  HONEST SILENCE is preserved throughout: a register whose record
  contains NO address-shaped value anywhere is reported as a WARN, not
  a FAIL. The input may genuinely not assign one, and inventing an
  address would be far worse than omitting it.

Fail-safe / no-false-positive design
====================================
* No L4 file, no ``registers[]``, or L4 positively records
  ``no_registers_in_input`` / ``register_map_present: false`` → SKIP(2).
* ``ic_class`` in {pure_analog, bare_fpga} → SKIP (no fab-side regmap).
* ``phase2_scaffold_gen`` not importable → SKIP rather than guess at
  the emitter's contract.

Waiver: ``l4_regmap_emitter_contract_intentional`` (>=40 chars) in
``<project>/waivers.json``.

Usage:
    python3 l4_regmap_phase2_emitter_contract_check.py <project_dir> \
        [--json <out.json>]

Exit codes:
    0 = PASS / SKIP-by-class / PASS_WITH_WAIVER
    1 = FAIL (blocks)
    2 = input-missing / not-applicable (skip)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _path_layout as _pl  # noqa: E402

WAIVER_KEY = "l4_regmap_emitter_contract_intentional"
WAIVER_MIN_LEN = 40

_SKIP_CLASSES = ("pure_analog", "bare_fpga")

# An address-shaped VALUE. Deliberately value-shaped, not key-named:
# the point of R2 is to find addresses hiding under keys nobody
# anticipated, so keying on a name list would defeat it.
_ADDR_VALUE_RE = re.compile(
    r"^\s*(?:0[xX][0-9a-fA-F]{1,16}"        # 0x300, 0x1a110000
    r"|0[bB][01_]{2,64}"                     # 0b0011
    r"|\d+'[hHbBdDoO][0-9a-fA-FxXzZ_]+"      # 12'h300
    r"|\d{1,10})\s*$"                        # bare decimal offset
)

# Keys that are certainly NOT an address even when their value looks
# like a number — checked so R2 does not mistake a width or a reset
# value for a hidden address.
_NON_ADDR_KEY_RE = re.compile(
    r"(?i)(width|size|bits?|lsb|msb|reset|default|value|count|len|"
    r"index|line|mask|version|schema|confidence|multiplicity)")


def _find_l4(project: Path) -> Optional[Path]:
    cand = _pl.generated_docs_dir(project) / "L4_REGMAP.json"
    if cand.is_file():
        return cand
    for pat in ("phase1/generated_docs/L4_REGMAP.json",
                "phase1/generated_docs/L4*.json",
                "**/L4_REGMAP.json"):
        for hit in project.glob(pat):
            if hit.is_file():
                return hit
    return None


def _load_scaffold_gen():
    try:
        import phase2_scaffold_gen as psg  # type: ignore
        return psg
    except Exception:
        return None


def _declares_no_registers(l4: dict) -> bool:
    """L4's own positive assertion that the input carries no register map."""
    if l4.get("no_registers_in_input") is True:
        return True
    if l4.get("register_map_present") is False:
        return True
    return False


def _hidden_address(reg: dict) -> Tuple[str, str]:
    """Return (key, value) of an address-shaped value in this register's
    own record, or ("", ""). Scans values, not key names."""
    for k, v in reg.items():
        if k in ("offset", "address"):
            continue
        if not isinstance(v, (str, int)) or isinstance(v, bool):
            continue
        if _NON_ADDR_KEY_RE.search(str(k)):
            continue
        s = str(v).strip()
        if not s:
            continue
        # A bare small decimal is too weak a signal on its own; require
        # an explicit radix prefix unless the key itself says address.
        if _ADDR_VALUE_RE.match(s):
            if re.match(r"^\s*\d+\s*$", s) and not re.search(
                    r"(?i)(addr|offset|base)", str(k)):
                continue
            return str(k), s
    return "", ""


def _norm_addr(s: str) -> str:
    """Normalise an address literal for collision comparison."""
    t = str(s).strip().lower().replace("_", "")
    try:
        if t.startswith("0x"):
            return hex(int(t, 16))
        if t.startswith("0b"):
            return hex(int(t, 2))
        m = re.match(r"^(\d+)'([hbdo])(.+)$", t)
        if m:
            base = {"h": 16, "b": 2, "d": 10, "o": 8}[m.group(2)]
            return hex(int(m.group(3).replace("_", ""), base))
        if t.isdigit():
            return hex(int(t))
    except ValueError:
        pass
    return t


def _waived(project: Path) -> Tuple[bool, str]:
    p = project / "waivers.json"
    if not p.is_file():
        return False, ""
    try:
        d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return False, ""
    raw = d.get(WAIVER_KEY)
    if isinstance(raw, str) and len(raw.strip()) >= WAIVER_MIN_LEN:
        return True, raw.strip()
    if isinstance(raw, dict):
        r = raw.get("rationale") or raw.get("reason") or ""
        if isinstance(r, str) and len(r.strip()) >= WAIVER_MIN_LEN:
            return True, r.strip()
    return False, ""


# ---------------------------------------------------------------------------
# Core evaluation (importable for tests)
# ---------------------------------------------------------------------------

def evaluate(project: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "gate": "l4_regmap_phase2_emitter_contract_check",
        "verdict": "SKIP",
        "reason": "",
        "registers_declared": 0,
        "registers_emitted": 0,
        "failures": [],
        "warnings": [],
    }

    l4p = _find_l4(project)
    if l4p is None:
        out["reason"] = "no L4_REGMAP.json"
        return out
    try:
        raw = json.loads(l4p.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        out["verdict"] = "FAIL"
        out["reason"] = f"L4 is not parseable JSON: {exc}"
        out["failures"] = [out["reason"]]
        return out
    if not isinstance(raw, dict):
        out["verdict"] = "FAIL"
        out["reason"] = "L4 top level is not an object"
        out["failures"] = [out["reason"]]
        return out

    psg = _load_scaffold_gen()
    if psg is None:
        out["reason"] = ("phase2_scaffold_gen not importable — cannot "
                         "state the emitter contract; skipped rather "
                         "than guessed")
        return out

    l4 = psg._unwrap_fields(raw)
    declared = [r for r in (l4.get("registers") or []) if isinstance(r, dict)]
    out["registers_declared"] = len(declared)

    if not declared:
        out["reason"] = (
            "L4 declares no registers[] "
            f"(no_registers_in_input={l4.get('no_registers_in_input')!r}, "
            f"register_map_present={l4.get('register_map_present')!r}) — "
            "nothing for the register-block emitter to build")
        return out
    if _declares_no_registers(l4) and not declared:
        out["reason"] = "L4 positively records no register map in the input"
        return out

    try:
        emitted = psg.derive_registers(l4, {})
    except Exception as exc:
        out["verdict"] = "FAIL"
        out["reason"] = (f"phase2_scaffold_gen.derive_registers() raised "
                         f"{type(exc).__name__}: {exc} on this L4")
        out["failures"] = [out["reason"]]
        return out
    out["registers_emitted"] = len(emitted)

    failures: List[str] = []
    warnings: List[str] = []

    # ---- R1: unique, non-empty Verilog identifiers ----
    ids = [str(r.get("name") or "") for r in emitted]
    blank = [i for i, n in enumerate(ids) if not n.strip()]
    if blank:
        failures.append(
            f"{len(blank)} register(s) sanitize to an EMPTY Verilog "
            "identifier — emit_regs_v() would declare a nameless reg")
    counts = Counter(n for n in ids if n.strip())
    dups = {n: c for n, c in counts.items() if c > 1}
    if dups:
        total_dup = sum(dups.values())
        # Show which L4 entries collided, so the fix is mechanical.
        by_id: Dict[str, List[str]] = defaultdict(list)
        for src, n in zip(declared, ids):
            if n in dups:
                by_id[n].append(repr(src.get("name", "")))
        detail = "; ".join(
            f"{n!r} <- L4 names {by_id[n]}" for n in list(dups)[:4])
        failures.append(
            f"{len(dups)} Verilog identifier(s) are claimed by "
            f"{total_dup} different L4 registers. emit_regs_v() emits one "
            "`reg` declaration per register, so <top>_regs.v would "
            "declare the same signal twice and NOT COMPILE — and the "
            f"error surfaces at lint/synth, not here. {detail}")

    # ---- R2: address present in the layer but invisible to the emitter ----
    hidden: List[str] = []
    silent: List[str] = []
    for src, em in zip(declared, emitted):
        if str(em.get("offset") or "").strip():
            continue
        key, val = _hidden_address(src)
        label = str(src.get("name") or em.get("name") or "?")
        if key:
            hidden.append(f"{label}: address {val} is under '{key}'")
        else:
            silent.append(label)
    if hidden:
        failures.append(
            f"{len(hidden)} register(s) DO carry an address in their own "
            "L4 record, but under a key derive_registers() never reads "
            "(it reads 'offset' then 'address'), so the emitter sees an "
            "empty offset and emit_regs_v() writes only "
            "'// TODO — address decode (per L4 offsets)'. The address is "
            "in the layer; it is not in the form the layer's consumer "
            f"reads. {'; '.join(hidden[:4])}")
    if silent:
        warnings.append(
            f"{len(silent)} register(s) carry no address anywhere in "
            "their record (honest extraction gap, not a typing defect): "
            f"{', '.join(silent[:6])}")

    # ---- R3: no ambiguous decode ----
    addr_map: Dict[str, List[str]] = defaultdict(list)
    for em in emitted:
        off = str(em.get("offset") or "").strip()
        if off:
            addr_map[_norm_addr(off)].append(str(em.get("name")))
    clashes = {a: ns for a, ns in addr_map.items() if len(ns) > 1}
    if clashes:
        detail = "; ".join(f"{a} <- {ns}" for a, ns in list(clashes.items())[:4])
        failures.append(
            f"{len(clashes)} address(es) are claimed by more than one "
            "register — the address decode emit_regs_v() would scaffold "
            f"is ambiguous. {detail}")

    out["failures"] = failures
    out["warnings"] = warnings
    if failures:
        out["verdict"] = "FAIL"
        out["reason"] = (
            f"L4 declares {len(declared)} register(s) but the register "
            f"block phase2_scaffold_gen would emit from them is not "
            f"buildable ({len(failures)} defect class(es))")
    else:
        out["verdict"] = "PASS"
        out["reason"] = (
            f"{len(emitted)} register(s) yield a unique identifier and an "
            "unambiguous decodable address through the emitter's own "
            "derive_registers()"
            + (f"; {len(warnings)} honest-silence warning(s)"
               if warnings else ""))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("project")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    project = Path(args.project).resolve()
    if not project.is_dir():
        print("[SKIP] l4_regmap_phase2_emitter_contract_check: "
              f"project dir not found: {project}")
        return 2

    try:
        from ic_class_profile import detect_ic_class  # noqa: E402
        ic_class = detect_ic_class(project).get("ic_class", "unknown")
    except Exception:
        ic_class = "unknown"
    if ic_class in _SKIP_CLASSES:
        print("[SKIP] l4_regmap_phase2_emitter_contract_check: "
              f"ic_class={ic_class} (no fab-side register map)")
        return 2

    res = evaluate(project)
    res["ic_class"] = ic_class

    if args.json_out:
        try:
            p = Path(args.json_out)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
        except OSError:
            pass

    for w in res.get("warnings", []):
        print(f"[WARN] l4_regmap_phase2_emitter_contract_check: {w}")

    if res["verdict"] == "SKIP":
        print("[SKIP] l4_regmap_phase2_emitter_contract_check: "
              f"{res['reason']}")
        return 2
    if res["verdict"] == "PASS":
        print("[PASS] l4_regmap_phase2_emitter_contract_check: "
              f"{res['reason']}")
        return 0

    waived, rationale = _waived(project)
    if waived:
        print("[PASS] l4_regmap_phase2_emitter_contract_check: waived by "
              f"waivers.{WAIVER_KEY} ({len(res['failures'])} suppressed): "
              f"{rationale[:70]}…")
        for f in res["failures"][:6]:
            print(f"  • {f}")
        return 0

    print("[FAIL] l4_regmap_phase2_emitter_contract_check: " + res["reason"])
    for f in res["failures"][:8]:
        print(f"  • {f}")
    print()
    print("  Fix in L4_REGMAP.json, using only what the input documents "
          "already state:")
    print("    - give every registers[] entry a distinct, non-empty name")
    print("    - put the address the record already holds under "
          "'offset' or 'address' (the keys the emitter reads)")
    print("  (Do NOT invent an address the input does not assign — leave "
          "it absent and it is reported as an honest gap, not a FAIL.)")
    print(f"  Or document the alternative in waivers.json under "
          f'"{WAIVER_KEY}" (>={WAIVER_MIN_LEN} chars).')
    return 1


if __name__ == "__main__":
    sys.exit(main())
