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
try:  # ONE LEF walk for the producer and its consumer (#785)
    from hardmacro_supply_intent import (  # type: ignore
        lef_all_pins as _shared_lef_all_pins,
        lef_macro_classes as _shared_lef_macro_classes,
        project_liberty_pg_pins as _shared_project_liberty_pg_pins,
    )
except Exception:                                           # noqa: BLE001
    _shared_lef_all_pins = None                             # type: ignore
    _shared_lef_macro_classes = None                        # type: ignore
    _shared_project_liberty_pg_pins = None                  # type: ignore


def _parse_lef(text: str) -> Dict[str, Dict[str, Any]]:
    """``{MACRO: {"pins": {pin: USE|None}, "class": CLASS|None}}``.

    A PRODUCER AND ITS CONSUMER MUST NOT KEEP SEPARATE PARSERS (#785)
    ----------------------------------------------------------------
    The body below is a LINE-ORIENTED walk, and it never got the one-line-pin
    fix #316/#329 landed on the shared block parser. LEF is newline-tolerant, so
    a whole PIN block is legal on ONE line::

        PIN <name> DIRECTION INOUT ; USE POWER ; PORT ... END END <name>

    The walk consumes that line at its ``PIN`` token and moves on, so the
    same-line ``USE`` is never read and the pin comes out ``{'<name>': None}``.

    MEASURED on published data — `benchmark-data/ic/u_hawaii_adc` stages two
    hard macros in exactly this form (``ldo`` IOVDD/VSS, ``delta_sigma``
    VDD/VSS) — this program printed

        verdict: NOT_APPLICABLE
        0 hard macro(s) with PG pins across 2 LEF file(s), 2 master(s)

    while its own consumer, `l21_macro_supply_rail_declared_check`, FAILED on
    those four pins reading the same two files. A producer and its consumer
    disagreeing about the same file, because the producer kept a private parser.
    `phase3_one_shot_runner._parse_macro_supply_pins` had already been converted
    to the shared walk for this exact reason; this was the copy left behind.

    So the block walk and the CLASS walk are both DELEGATED, and the line walk
    below survives only as a stand-alone fallback — a subset, never a superset.
    """
    if _shared_lef_all_pins is not None:
        out: Dict[str, Dict[str, Any]] = {}
        classes = (_shared_lef_macro_classes(text)
                   if _shared_lef_macro_classes is not None else {})
        for rec in _shared_lef_all_pins(text):
            master = str(rec.get("master") or "")
            if not master:
                continue
            d = out.setdefault(master, {"pins": {}, "class": None})
            uses = [u for u in (rec.get("uses") or [])]
            pin_name = str(rec.get("pin") or "")
            if pin_name:
                d["pins"].setdefault(pin_name, uses[0] if uses else None)
        for master, cls in classes.items():
            out.setdefault(master, {"pins": {}, "class": None})["class"] = cls
        return out
    return _parse_lef_line_walk(text)


def _parse_lef_line_walk(text: str) -> Dict[str, Dict[str, Any]]:
    """Stand-alone fallback for `_parse_lef`. Carries the one-line-pin blind
    spot documented there; used only when the shared walk cannot be imported."""
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


def _is_hard_macro(cls: Optional[str]) -> bool:
    """Does this LEF ``CLASS`` denote a hard macro?

    The CONSUMER's policy, imported rather than restated (#785): its
    `_HARD_MACRO_CLASSES` includes ``COVER``, and it treats a master with NO
    CLASS record as a hard macro because many vendor macro LEFs omit it. This
    program used a narrower private tuple and required the record to be present,
    so a COVER-class or class-less macro was invisible here and in scope there —
    the same producer/consumer disagreement `_parse_lef` documents, one field
    over. An explicit ``CORE`` (std cell / filler / tap) is still excluded.
    """
    c = (cls or "").upper()
    if not c:
        return True
    try:
        from l21_macro_supply_rail_declared_check import (  # type: ignore
            _HARD_MACRO_CLASSES as _classes)
    except Exception:                                       # noqa: BLE001
        _classes = ("BLOCK", "RING", "PAD", "COVER")
    return any(c.startswith(x) for x in _classes)


def _hard_macros_with_pg(masters: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """{master: {pin: USE}} for hard-macro masters that declare PG pins."""
    out: Dict[str, Dict[str, str]] = {}
    for m, d in masters.items():
        if not _is_hard_macro(d.get("class")):
            continue
        pg = {p: u for p, u in d["pins"].items() if u in ("POWER", "GROUND")}
        if pg:
            out[m] = pg
    return out


def _hard_macros_untyped(masters: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    """``{master: [pin, ...]}`` for every hard macro that declares PINs and
    types NONE of them with a ``USE`` record.

    ABSENCE OF EVIDENCE IS NOT NON-APPLICABILITY (#785). `_hard_macros_with_pg`
    returning ``{}`` used to be the ONLY answer this program had for three
    different files, and it printed the same ``NOT_APPLICABLE`` for all three:
    no LEF at all; an abstract that types its pins and declares no supply
    terminal (an AFFIRMATIVE statement, and genuinely nothing to derive); and an
    abstract that types NOTHING — which is what `magic`'s ``lef write`` emits,
    and where the rails this program exists to derive are simply MISSING from an
    artefact that exists.
    """
    out: Dict[str, List[str]] = {}
    for m, d in masters.items():
        if not _is_hard_macro(d.get("class")):
            continue
        pins = d.get("pins") or {}
        if not pins or any(u for u in pins.values()):
            continue
        out[m] = sorted(pins)
    return out


def _recover_untyped_pg(untyped: Dict[str, List[str]],
                        proj: Path) -> Dict[str, Dict[str, str]]:
    """``{master: {pin: USE}}`` recovered from the macro's OWN Liberty view.

    `pg_pin`/`pg_type` survive a ``lef write`` that drops the LEF ``USE``
    records, so this is the design's own independent statement about the same
    macro — not a name pattern, not a keyword list, and never a rail this
    program invents. Only POWER/GROUND-resolved pins are returned: a `pg_pin`
    with no `pg_type` states a supply terminal without its polarity, and a rail
    whose polarity is unknown is exactly what this program refuses to guess.
    """
    if not untyped or _shared_project_liberty_pg_pins is None:
        return {}
    try:
        lib = _shared_project_liberty_pg_pins(proj)
    except Exception:                                       # noqa: BLE001
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for master, pins in untyped.items():
        cell = lib.get(master) or {}
        got = {p: cell[p] for p in pins
               if cell.get(p) in ("POWER", "GROUND")}
        if got:
            out[master] = got
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
    found: List[Dict[str, Any]] = []
    p = re.escape(pin)
    pats = [
        re.compile(rf"{p}\s*[=:]\s*([0-9]+(?:\.[0-9]+)?)\s*V\b", re.I),
        re.compile(rf"([0-9]+(?:\.[0-9]+)?)\s*V\s+{p}\b", re.I),
        re.compile(rf"{p}\b[^.\n]{{0,24}}?\bis\s+([0-9]+(?:\.[0-9]+)?)\s*V\b", re.I),
        # #689 — "<PIN> same as <n>V <OTHER>". A real form the three patterns
        # above do not cover, and the one that carries the SECOND operating
        # voltage of a mode-dependent supply: the NVM datasheet states
        # "VPP same as 1.8V VDD for Read" on one line and "7.5V VPP … for
        # Program" four lines later. Without this the extractor sees only the
        # 7.5 and the rail looks single-voltage.
        #
        # The number belongs to the OTHER rail by grammar — "same as 1.8V VDD"
        # is a statement about VDD — but the sentence asserts THIS pin takes
        # that value in that mode, which is exactly the fact being lost. Matched
        # deliberately, and the matched_text keeps the whole clause so a reader
        # sees the attribution rather than a bare number.
        re.compile(rf"{p}\b[^.\n]{{0,16}}?\bsame\s+as\s+"
                   rf"([0-9]+(?:\.[0-9]+)?)\s*V\b[^.\n]{{0,24}}", re.I),
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
                    found.append({
                        "voltage_v": float(m.group(1)),
                        "evidence": {
                            "file": rel, "line": ln,
                            "matched_text": m.group(0).strip(),
                        },
                    })
                    break            # one hit per line; the patterns overlap
    if not found:
        return None
    # ORGANIC #689 — COLLECT, then decide. This used to `return` on the first
    # match, so a rail with more than one operating voltage had one of them
    # recorded and the rest dropped, under a `voltage_status` reading "stated in
    # the design's own documents". A true quotation of a false summary.
    #
    # The standard case is a programmable NVM's programming supply: its own
    # datasheet gives the elevated voltage FOR PROGRAMMING and the core voltage
    # FOR READING, on the same pin, four lines apart —
    #
    #     line 103:  <rail> same as 1.8V VDD for Read
    #     line 107:  7.5V <rail>, 1.8V VDD for Program
    #
    # Recording only 7.5 makes every consumer assert the wrong voltage in read
    # mode: a crossing check keyed on `7.5 != 1.8` demands level shifters on
    # paths that sit at the same potential, and an IR budget at 7.5 V is wrong
    # for the mode the part spends its life in. It also mis-scores the
    # CONSEQUENCE of leaving the rail unrealised — "we cannot burn the array"
    # instead of "the device does not read".
    #
    # `voltage_v` stays the MAXIMUM so every existing consumer keeps working
    # unchanged; the list is what stops the information being lost.
    by_v: Dict[float, Dict[str, Any]] = {}
    for f_ in found:
        by_v.setdefault(f_["voltage_v"], f_)
    distinct = sorted(by_v)
    top = by_v[distinct[-1]]
    return {
        "voltage_v": top["voltage_v"],
        "evidence": top["evidence"],
        "voltage_by_mode": [
            {"voltage_v": v, "evidence": by_v[v]["evidence"]}
            for v in distinct
        ],
        "voltage_complete": len(distinct) <= 1,
    }


def _default_lef_roots(proj: Path) -> List[Path]:
    """Where to look for macro LEFs when the caller names no `--lef`.

    This MUST cover every root the CONSUMER searches. The default used to be
    just `input/pdk` + `input/pdk_local`, while
    `l21_macro_supply_rail_declared_check` harvests macros from FIVE roots
    (`input/pdk_local`, `input/macros`, `input/hardmacro`, and the analog
    `phase2/phase3 .../hardmacro` trees). On any design whose hard macros live
    in one of the four roots the producer did not search, the gate saw a macro
    with unmatched PG pins and failed, while this program looked in the wrong
    places and reported NOT_APPLICABLE — a producer measuring something
    ADJACENT to what its consumer measures, which is the same defect shape as
    running with no call site at all.

    So the consumer's own glob list is the single source of truth, imported
    rather than copied: a root added there can never silently go unsearched
    here. `input/pdk` is retained on top of it — the full PDK is a legitimate
    place to find a hard macro, and `_hard_macros_with_pg` already filters
    std cells out by CLASS, not by path.
    """
    roots: List[Path] = [proj / "input" / "pdk"]
    try:
        from l21_macro_supply_rail_declared_check import (
            _MACRO_LEF_GLOBS as _consumer_globs)
    except Exception:                                       # noqa: BLE001
        # Never let the producer die because the consumer moved; fall back to
        # the historical default rather than searching nothing.
        return roots + [proj / "input" / "pdk_local"]
    for pat in _consumer_globs:
        # "input/macros/**/*.lef" -> the "input/macros" root; rglob in
        # _collect_macros already supplies the recursion.
        head = pat.split("/**", 1)[0]
        root = proj / head
        if root not in roots:
            roots.append(root)
    return roots


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
    lefs = [Path(p) for p in args.lef] if args.lef else _default_lef_roots(proj)
    doc_dir = Path(args.doc_dir) if args.doc_dir else proj / "phase1" / "input_doc"

    if not l21.is_file():
        print(f"[FAIL] {PROGRAM}: power-intent layer not found: {l21}",
              file=sys.stderr)
        return 2

    masters, lefs_read = _collect_macros(lefs)
    hard = _hard_macros_with_pg(masters)

    # ---- THE THREE-WAY SPLIT (#785) -------------------------------------- #
    # An abstract that types NOTHING is not an abstract with nothing to declare.
    # The typing is recovered from the macro's OWN Liberty view where one is
    # staged, and those pins then flow through the SAME derivation as a
    # LEF-typed pin — so a tool-written abstract still yields its rails instead
    # of a silent NOT_APPLICABLE. What cannot be recovered is REPORTED, not
    # printed as non-applicability.
    untyped = {m: p for m, p in _hard_macros_untyped(masters).items()
               if m not in hard}
    recovered = _recover_untyped_pg(untyped, proj)
    for m, pg in recovered.items():
        hard[m] = dict(pg)
    unresolved = sorted(m for m in untyped if m not in recovered)

    if not hard:
        print(f"=== {PROGRAM} ===")
        if unresolved:
            # NOT the same answer as "nothing to derive". Named, printed, and
            # given its own verdict token so a reader (and a grep) can tell the
            # two apart.
            print("  verdict: UNTYPED_ABSTRACT")
            print(f"  count: 0 hard macro(s) with PG pins across "
                  f"{len(lefs_read)} LEF file(s), {len(masters)} master(s) — "
                  f"but {len(unresolved)} staged hard macro(s) type NO pin at "
                  f"all, so there is no `USE POWER`/`USE GROUND` record to "
                  f"derive a rail FROM, and no Liberty `pg_pin` beside the "
                  f"abstract to recover one from either")
            for m in unresolved:
                print(f"  ! {m}: {len(untyped[m])} PIN(s), none typed "
                      f"({', '.join(untyped[m][:8])}) — `magic`'s `lef write` "
                      f"emits neither `DIRECTION` nor `USE`, so re-attach the "
                      f"typing to the abstract or stage the macro's Liberty "
                      f"view beside it; until then this design's rails are "
                      f"UNDERIVABLE, not absent")
            return 0
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

    def _provenance(pin: str, use: str, by_macros: List[str]) -> Dict[str, Any]:
        """WHERE this rail's polarity actually came from.

        A rail recovered from a Liberty `pg_pin` must NOT claim
        ``macro_lef_pin_use: POWER`` — the LEF said nothing at all, and a
        provenance field that quotes a record the file does not contain is the
        same defect one layer down. `hardmacro_supply_intent`'s anti-cheat reads
        `derived_by` too, so a recovered rail is still correctly excluded from
        the independent declarations it would otherwise be checked against.
        """
        src: Dict[str, Any] = {"declared_by_macros": sorted(by_macros)}
        rec = [m for m in by_macros if m in recovered]
        if rec and all(m in recovered for m in by_macros):
            src["macro_lef_pin_use"] = None
            src["recovered_from"] = (
                f"the macro's OWN Liberty `pg_pin ({pin})` declares a "
                f"pg_type resolving to {use}; its abstract types NO pin at all "
                f"(a `lef write` emits neither `DIRECTION` nor `USE`)")
        else:
            src["macro_lef_pin_use"] = use
            if rec:
                src["also_recovered_from_liberty_for"] = sorted(rec)
        return src

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
            "derived_from": _provenance(pin, "POWER", power_pins[pin]),
            "voltage_v": None,
            "voltage_status": "not stated in the design's own documents",
        }
        ev = _voltage_evidence(pin, doc_dir, proj)
        if ev:
            entry["voltage_v"] = ev["voltage_v"]
            entry["voltage_evidence"] = ev["evidence"]
            # #689 — carry EVERY stated voltage, and say when there is more than
            # one. `voltage_status` used to encode only PROVENANCE (stated vs
            # inferred) and had no representable value meaning "this rail has
            # more than one operating voltage and I captured one". That is the
            # value the schema was missing, so the extractor could be truthful
            # about where it read and silent about what it dropped.
            entry["voltage_by_mode"] = ev.get("voltage_by_mode") or [
                {"voltage_v": ev["voltage_v"], "evidence": ev["evidence"]}]
            if ev.get("voltage_complete", True):
                entry["voltage_status"] = "stated in the design's own documents"
            else:
                _vs = ", ".join(f"{d['voltage_v']}V"
                                for d in entry["voltage_by_mode"])
                entry["voltage_status"] = (
                    f"MODE-DEPENDENT — {len(entry['voltage_by_mode'])} distinct "
                    f"voltages stated for this rail ({_vs}); `voltage_v` is the "
                    f"maximum and is NOT the whole answer. A consumer that "
                    f"reasons about one mode must read `voltage_by_mode`.")
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
        # #598: this entry is a RAIL DECLARATION, not a power domain, and it
        # must say so. `power_net` is here because both readers need it (see
        # the measured L21-1/L21-2 trade above) — it is the design's primary
        # rail, NOT this entry's operating voltage. Without the marker a
        # consumer reads a domain named after a GROUND pin carrying the 1.2 V
        # core rail at 0.0 V, and `power_domain_signal_crossing_check` built
        # exactly that phantom domain.
        added.append({
            _NAME_KEY: pin, _POWER_KEY: _primary_power, _GROUND_KEY: pin,
            "derived_by": PROGRAM,
            "derived_from": _provenance(pin, "GROUND", ground_pins[pin]),
            "is_power_domain": False,
            "voltage_v": 0.0,
            "voltage_status": (
                "ground reference; `power_net` names the design's primary rail "
                "so both the completeness gate and the Phase-3 consumer "
                "resolve this pin, and is NOT this entry's operating voltage"),
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
                "rationale": (
                    ("the macro's OWN Liberty `pg_pin` types this pin " + use +
                     " (its abstract types no pin at all)"
                     if m in recovered else
                     "LEF types this pin USE " + use) +
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
            "untyped_abstracts": len(untyped),
            "untyped_abstracts_recovered": len(recovered),
            "untyped_abstracts_unresolved": len(unresolved),
        },
        # #785 — carried whether or not the derivation succeeded. A run that
        # derived rails for macro A while macro B's abstract types nothing must
        # not read as a run with nothing left to say about B.
        "untyped_abstracts": {m: untyped[m] for m in sorted(untyped)},
        "untyped_abstracts_recovered": {m: recovered[m]
                                        for m in sorted(recovered)},
        "untyped_abstracts_unresolved": unresolved,
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
    for m in sorted(recovered):
        print(f"  ~ {m}: abstract types NO pin; supply role RECOVERED from the "
              f"macro's OWN Liberty `pg_pin` — "
              + ", ".join(f"{p}={u}" for p, u in sorted(recovered[m].items())))
    for m in unresolved:
        print(f"  ! {m}: {len(untyped[m])} PIN(s), none typed "
              f"({', '.join(untyped[m][:8])}) and no Liberty `pg_pin` beside "
              f"the abstract — this macro's rails are UNDERIVABLE, not absent")
    if not result["applied"] and added:
        print("  (dry run — re-run with --apply to write these into the layer)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
