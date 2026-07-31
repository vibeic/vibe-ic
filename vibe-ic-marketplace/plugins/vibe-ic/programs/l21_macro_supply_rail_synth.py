#!/usr/bin/env python3
"""Derive the power-intent rail set from the design's OWN hard-macro LEFs.

WHY (the measured defect, chip-AGNOSTIC)
----------------------------------------
`l21_macro_supply_rail_declared_check` asserts the load-bearing clause:

    every supply/ground pin that ANY instantiated hard macro types USE POWER /
    USE GROUND in that design's OWN macro LEF must appear as a declared rail of
    the SAME use in L21.power_domains[].

When that clause fails, the consequence chain is deterministic and expensive::

    no rail declared for the macro's supply pin
      -> the PDN carries no such rail
      -> synthesis constant-ties the macro's POWER-typed terminal
      -> a SIGNAL net lands on a POWER-typed terminal
      -> detailed routing refuses that net and aborts the WHOLE route
      -> every sign-off step needing a routed database becomes unreachable

The gate that detects this is deliberately ADVISORY: promoting it to blocking
would red already-published cells whose rails are undeclared, which is a
flow-owner decision. This program attacks the other end -- it removes the CAUSE,
so the clause is satisfied without anyone flipping enforcement, and a blind run
recovers with no agent involved.

WHAT IT DERIVES, AND FROM WHAT
------------------------------
Everything comes from the design's own machine-readable inputs:

* the macro's own LEF ``MACRO`` / ``PIN`` / ``USE`` / ``CLASS`` records -- which
  pins are POWER, which are GROUND, and which masters are hard macros;
* optionally a netlist or RTL directory, to scope the derivation to macros the
  design actually instantiates.

It emits one ``power_domains[]`` entry per distinct POWER net, each paired with
the design's GROUND net, in the shape the consumer name-matches against.

WHAT IT REFUSES TO DO
---------------------
* It never invents a rail name. Names come from the macro's own LEF pins.
* It never folds one supply onto another. A dedicated supply (a programming
  voltage, a separate analog rail) gets its OWN domain. Folding a programming
  supply onto the core rail is both functionally wrong and a reliability
  hazard, and is exactly what a checker must not guess.
* It never invents a voltage. A voltage is recorded only when a literal in the
  design's own documents states it, together with the file, line and matched
  text. Otherwise the field is null and marked unstated.
* It never overwrites an existing declaration. Anything already declared is
  left byte-identical; this only ADDS what is missing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

PROGRAM = "l21_macro_supply_rail_synth"
VERSION = "1.0.0"

# Key spellings the consumer gate accepts, so what is emitted is what is read.
_POWER_KEY = "power_net"
_GROUND_KEY = "ground_net"
_NAME_KEY = "name"


# ── LEF ──────────────────────────────────────────────────────────────────────
def _parse_lef(text: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    macro: Optional[str] = None
    pin: Optional[str] = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        tok = line.split()
        if tok[0] == "MACRO" and len(tok) > 1:
            macro, pin = tok[1], None
            out.setdefault(macro, {"pins": {}, "class": None})
            continue
        if macro is None:
            continue
        if tok[0] == "CLASS" and len(tok) > 1:
            out[macro]["class"] = tok[1].rstrip(";").upper()
        elif tok[0] == "PIN" and len(tok) > 1:
            pin = tok[1]
            out[macro]["pins"].setdefault(pin, None)
        elif tok[0] == "END" and len(tok) > 1:
            if pin is not None and tok[1] == pin:
                pin = None
            elif tok[1] == macro:
                macro, pin = None, None
        elif pin is not None and tok[0] == "USE" and len(tok) > 1:
            out[macro]["pins"][pin] = tok[1].rstrip(";").upper()
    return out


def _collect_macros(lef_paths: List[Path]) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    masters: Dict[str, Dict[str, Any]] = {}
    read: List[str] = []
    files: List[Path] = []
    for p in lef_paths:
        if p.is_dir():
            files.extend(sorted(p.rglob("*.lef")))
        elif p.is_file():
            files.append(p)
    for f in files:
        try:
            parsed = _parse_lef(f.read_text(errors="replace"))
        except Exception:
            continue
        if parsed:
            read.append(str(f))
            for m, d in parsed.items():
                if m not in masters or not masters[m]["pins"]:
                    masters[m] = d
    return masters, read


def _hard_macros_with_pg(masters: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """{master: {pin: USE}} for BLOCK-class masters that declare PG pins."""
    out: Dict[str, Dict[str, str]] = {}
    for m, d in masters.items():
        if (d.get("class") or "") not in ("BLOCK", "RING", "PAD"):
            continue
        pg = {p: u for p, u in d["pins"].items() if u in ("POWER", "GROUND")}
        if pg:
            out[m] = pg
    return out


def _instantiated(masters: Set[str], netlist: Optional[Path],
                  rtl_dir: Optional[Path]) -> Optional[Set[str]]:
    """Masters actually instantiated, or None when that cannot be determined."""
    texts: List[str] = []
    if netlist and netlist.is_file():
        texts.append(netlist.read_text(errors="replace"))
    if rtl_dir and rtl_dir.is_dir():
        for ext in ("*.v", "*.sv"):
            for f in sorted(rtl_dir.rglob(ext)):
                texts.append(f.read_text(errors="replace"))
    if not texts:
        return None
    blob = "\n".join(texts)
    blob = re.sub(r"//[^\n]*", "", blob)
    blob = re.sub(r"/\*.*?\*/", "", blob, flags=re.S)
    return {m for m in masters
            if re.search(r"(?<![\w.])" + re.escape(m) + r"(?![\w])", blob)}


# ── voltage evidence (never invented) ────────────────────────────────────────
def _voltage_evidence(pin: str, doc_dir: Optional[Path],
                      project: Optional[Path] = None
                      ) -> Optional[Dict[str, Any]]:
    """A stated voltage for ``pin``, with file/line/text, or None.

    Only accepts a literal that names the pin and a voltage in the SAME
    fragment, e.g. "<PIN>=7.5V", "7.5V <PIN>", "<PIN> is 1.8 V". Anything less
    direct is left unstated rather than guessed.

    ``evidence.file`` is emitted PROJECT-RELATIVE. An absolute path in an L doc
    is a portability defect the flow enforces (`l_doc_path_portability_check`
    FAILs on it, which returns exit 1 from Phase 1) and it also records the
    account the run happened under. This only became visible once the synth was
    wired into the Phase-1 post-emit sequence — invoked by hand AFTER the run,
    it wrote the same absolute path but no gate was left to see it.
    """
    if not doc_dir or not doc_dir.is_dir():
        return None
    p = re.escape(pin)
    pats = [
        re.compile(rf"{p}\s*[=:]\s*([0-9]+(?:\.[0-9]+)?)\s*V\b", re.I),
        re.compile(rf"([0-9]+(?:\.[0-9]+)?)\s*V\s+{p}\b", re.I),
        re.compile(rf"{p}\b[^.\n]{{0,24}}?\bis\s+([0-9]+(?:\.[0-9]+)?)\s*V\b", re.I),
    ]
    for f in sorted(doc_dir.rglob("*.txt")):
        try:
            lines = f.read_text(errors="replace").splitlines()
        except Exception:
            continue
        for ln, line in enumerate(lines, 1):
            for rx in pats:
                m = rx.search(line)
                if m:
                    rel = str(f)
                    if project:
                        try:
                            rel = str(f.resolve().relative_to(project.resolve()))
                        except ValueError:
                            # Evidence genuinely outside the project tree: keep
                            # the path but do not fabricate a relative one.
                            rel = str(f)
                    return {
                        "voltage_v": float(m.group(1)),
                        "evidence": {
                            "file": rel, "line": ln,
                            "matched_text": m.group(0).strip(),
                        },
                    }
    return None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Derive power_domains[] from the design's own macro LEFs.")
    ap.add_argument("project")
    ap.add_argument("--l21", help="power-intent layer JSON (default: "
                                  "phase1/generated_docs/L21_POWER_INTENT.json)")
    ap.add_argument("--lef", nargs="*", help="LEF file(s)/dir(s) "
                                             "(default: input/pdk, input/pdk_local)")
    ap.add_argument("--netlist", help="gate netlist, to scope to instantiated macros")
    ap.add_argument("--rtl-dir", help="RTL dir, to scope to instantiated macros")
    ap.add_argument("--doc-dir", help="converted input docs, for voltage evidence "
                                      "(default: phase1/input_doc)")
    ap.add_argument("--apply", action="store_true",
                    help="write the derived rails into the layer (default: dry run)")
    ap.add_argument("--json", help="write the result JSON here")
    args = ap.parse_args(argv)

    proj = Path(args.project).resolve()
    l21 = Path(args.l21) if args.l21 else \
        proj / "phase1" / "generated_docs" / "L21_POWER_INTENT.json"
    lefs = [Path(p) for p in args.lef] if args.lef else \
        [proj / "input" / "pdk", proj / "input" / "pdk_local"]
    doc_dir = Path(args.doc_dir) if args.doc_dir else proj / "phase1" / "input_doc"

    if not l21.is_file():
        print(f"[FAIL] {PROGRAM}: power-intent layer not found: {l21}",
              file=sys.stderr)
        return 2

    masters, lefs_read = _collect_macros(lefs)
    hard = _hard_macros_with_pg(masters)
    if not hard:
        print(f"=== {PROGRAM} ===")
        print("  verdict: NOT_APPLICABLE")
        print(f"  count: 0 hard macro(s) with PG pins across "
              f"{len(lefs_read)} LEF file(s), {len(masters)} master(s)")
        return 0

    inst = _instantiated(set(hard), Path(args.netlist) if args.netlist else None,
                         Path(args.rtl_dir) if args.rtl_dir else None)
    scoped = {m: pg for m, pg in hard.items() if inst is None or m in inst}
    scope_note = ("all design-local hard macros (instantiation not determinable "
                  "at this stage)" if inst is None
                  else f"{len(scoped)} instantiated of {len(hard)} hard macro(s)")

    power_pins: Dict[str, List[str]] = {}
    ground_pins: Dict[str, List[str]] = {}
    for m, pg in sorted(scoped.items()):
        for pin, use in sorted(pg.items()):
            (power_pins if use == "POWER" else ground_pins).setdefault(pin, []).append(m)

    doc = json.loads(l21.read_text())
    container = doc.get("fields") if isinstance(doc.get("fields"), dict) else doc
    existing = container.get("power_domains")
    if not isinstance(existing, list):
        existing = []

    def _declared_nets(entries: List[Any], keys: Tuple[str, ...]) -> Set[str]:
        out: Set[str] = set()
        for e in entries:
            if isinstance(e, str):
                out.add(e)
            elif isinstance(e, dict):
                for k in keys:
                    v = e.get(k)
                    if isinstance(v, str) and v:
                        out.add(v)
        return out

    # "Already declared" must mean declared where BOTH readers can see it.
    # A rail mentioned only as some other domain's `power_net`/`ground_net` is
    # visible to the Phase-1 completeness gate but invisible to the Phase-3
    # pre-route consumer, which harvests `name` / `rail` / `supply` only. Testing
    # against the narrower (consumer) key set is what makes this program
    # idempotent AND sufficient: it re-adds a named entry for any rail that is
    # currently only half-declared, and adds nothing once both readers agree.
    consumer_visible = _declared_nets(existing, ("name", "rail", "supply"))
    have_pwr = consumer_visible
    have_gnd = consumer_visible

    # One ground net serves as the domains' reference. If the design declares
    # several, the first by name is used and the rest are declared too.
    gnd_list = sorted(ground_pins) or sorted(have_gnd)
    ref_gnd = gnd_list[0] if gnd_list else None

    added: List[Dict[str, Any]] = []
    for pin in sorted(power_pins):
        if pin in have_pwr:
            continue
        if ref_gnd is None:
            continue
        entry: Dict[str, Any] = {
            _NAME_KEY: pin,
            _POWER_KEY: pin,
            _GROUND_KEY: ref_gnd,
            "derived_by": PROGRAM,
            "derived_from": {
                "macro_lef_pin_use": "POWER",
                "declared_by_macros": sorted(power_pins[pin]),
            },
            "voltage_v": None,
            "voltage_status": "not stated in the design's own documents",
        }
        ev = _voltage_evidence(pin, doc_dir, proj)
        if ev:
            entry["voltage_v"] = ev["voltage_v"]
            entry["voltage_status"] = "stated in the design's own documents"
            entry["voltage_evidence"] = ev["evidence"]
        added.append(entry)

    # Every distinct GROUND rail also gets its OWN named entry, even when it is
    # already referenced as some power domain's `ground_net`.
    #
    # Two readers disagree about where a rail name lives, and a declaration has
    # to satisfy BOTH or it is only half-declared:
    #   * the Phase-1 completeness gate reads `ground_net` (among others), so a
    #     ground rail named only there makes that gate report PASS;
    #   * the Phase-3 pre-route consumer harvests `rail` / `supply` / `name`
    #     ONLY, so the same rail is invisible to it and the macro's ground pin
    #     is still reported as having no bindable rail.
    # A design could therefore pass the producer gate and be blocked by the
    # consumer for the identical pin. Setting `name` on a dedicated entry is the
    # intersection of both key sets, so the declaration means the same thing to
    # whichever reader looks at it.
    # L21-2 COMPATIBILITY, measured rather than assumed: the consumer gate
    # requires EVERY declared entry to carry a primary power net, so an entry
    # with `power_net: None` trades the L21-1 failure this program exists to
    # fix for an L21-2 failure. Verified end-to-end on a synthetic macro LEF:
    # before the synth the gate reported L21-1 (rc=1); with a null-power ground
    # entry it reported L21-2 (rc=1) — a different failure, not a fix.
    #
    # So the ground entry carries the design's own primary power net alongside
    # its ground name. That satisfies BOTH readers with ONE entry: the Phase-3
    # consumer finds the ground rail under `name`, and the completeness gate
    # finds a primary power net. It invents nothing — the power net is one the
    # design already declares; only its pairing is new.
    _primary_power = None
    for _e in list(existing) + added:
        if isinstance(_e, dict) and _e.get(_POWER_KEY):
            _primary_power = _e[_POWER_KEY]
            break
    for pin in sorted(ground_pins):
        if pin in have_gnd:
            continue
        added.append({
            _NAME_KEY: pin, _POWER_KEY: _primary_power, _GROUND_KEY: pin,
            "derived_by": PROGRAM,
            "derived_from": {"macro_lef_pin_use": "GROUND",
                             "declared_by_macros": sorted(ground_pins[pin])},
            "voltage_v": 0.0,
            "voltage_status": "ground reference",
        })

    # An EXPLICIT (master, pin) -> rail binding map, in addition to the rails.
    #
    # Declaring the rail is necessary but NOT sufficient. The pre-route gate
    # accepts a pin as accounted for once a same-use rail is declared, but the
    # emitter that physically binds pins name-matches against the PDK's own
    # supply nets. A dedicated supply the PDK knows nothing about (a programming
    # voltage, a separate analog rail) therefore passes the gate and still
    # arrives at routing constant-tied -- the exact abort the gate exists to
    # prevent. The explicit map is what the emitter consumes, so what the gate
    # accepts is what actually gets bound.
    #
    # The map only ever points at a rail declared above, so it cannot fabricate
    # a rail; a mapping to an unestablished rail is dropped by the consumer.
    bind_map: List[Dict[str, Any]] = []
    all_rails = {e[_NAME_KEY] for e in added} | consumer_visible
    existing_map = container.get("hard_macro_supplies")
    if not isinstance(existing_map, list):
        existing_map = []
    have_bind = {(str(m.get("master", "")), str(m.get("pin", "")))
                 for m in existing_map if isinstance(m, dict)}
    for m, pg in sorted(scoped.items()):
        for pin, use in sorted(pg.items()):
            if (m, pin) in have_bind or pin not in all_rails:
                continue
            bind_map.append({
                "master": m, "pin": pin, "rail": pin, "use": use,
                "derived_by": PROGRAM,
                "rationale": ("LEF types this pin USE " + use +
                              "; bound to the same-named rail declared in "
                              "power_domains[] by this program"),
            })

    if args.apply and bind_map:
        container["hard_macro_supplies"] = list(existing_map) + bind_map

    result = {
        "program": PROGRAM, "version": VERSION,
        "power_intent_layer": str(l21),
        "bindings_added": bind_map,
        "lef_files_read": len(lefs_read),
        "scope": scope_note,
        "counts": {
            "hard_macros_with_pg_pins": len(hard),
            "hard_macros_in_scope": len(scoped),
            "distinct_power_pins": len(power_pins),
            "distinct_ground_pins": len(ground_pins),
            "already_declared_power_nets": len(have_pwr),
            "rails_added": len(added),
        },
        "power_pins": {p: v for p, v in sorted(power_pins.items())},
        "ground_pins": {p: v for p, v in sorted(ground_pins.items())},
        "rails_added": added,
        "applied": False,
    }

    result["counts"]["bindings_added"] = len(bind_map)
    if args.apply and (added or bind_map):
        if added:
            container["power_domains"] = list(existing) + added
            if "power_intent_present" in container:
                container["power_intent_present"] = True
        l21.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
        result["applied"] = True

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(result, indent=2, ensure_ascii=False))

    c = result["counts"]
    print(f"=== {PROGRAM} ===")
    print(f"  scope: {scope_note}")
    print(f"  count: {c['hard_macros_in_scope']} macro(s) in scope, "
          f"{c['distinct_power_pins']} power pin(s), "
          f"{c['distinct_ground_pins']} ground pin(s), "
          f"{c['rails_added']} rail(s) {'ADDED' if result['applied'] else 'derivable'}")
    for e in added:
        v = e["voltage_v"]
        print(f"  + rail {e[_NAME_KEY]}: power={e[_POWER_KEY]} ground={e[_GROUND_KEY]} "
              f"voltage={v if v is not None else 'unstated'} "
              f"({e['voltage_status']})")
    if not result["applied"] and added:
        print("  (dry run — re-run with --apply to write these into the layer)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
