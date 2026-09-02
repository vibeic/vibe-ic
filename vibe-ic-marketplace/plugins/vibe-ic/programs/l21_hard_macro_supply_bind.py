#!/usr/bin/env python3
"""Bind each analog/hard-macro supply PIN to the rail the design's own
documents say feeds it — the Phase-1 PRODUCER of `L21.fields.hard_macro_supplies`.

WHY (the measured defect, chip-AGNOSTIC)
----------------------------------------
`L21.fields.hard_macro_supplies` had THREE consumers and NO producer:
`hardmacro_supply_intent`, `ip_integration_check` and
`nvm_program_supply_intent` all read it; nothing in the tree wrote it before
the macro abstracts exist (Phase 3, step A8). Rounds 13-14 of the u_hawaii_adc
acceptance declared it BY HAND from the design's own sentences so the pre-route
gate could classify the macro supplies — the same emitter/checker split that
`spec.json:interface.pins[]` had before its interface declaration landed.
A key with consumers and no producer is a gate that a run can only pass by a
human's hand-edit, which is not a flow.

WHAT IT READS, AND WHAT IT BINDS
--------------------------------
* the design's INTERFACE DECLARATION — every `.subckt <block> <pins…>` under
  `input/` (the SPICE form the Phase-1 metadata reader already ingests): which
  blocks exist, and which pins each has. No pin is invented.
* the design's RAILS — `L21.fields.power_domains[]` as the two rail producers
  already declared them (name, voltage, POWER/GROUND polarity). No rail is
  invented; a pin binds only to a rail the design independently declares.
* the design's per-block SPEC TABLES — the markdown tables under the heading
  that names the block. A row whose leading identifier is the pin's name is
  that pin's declaration.

A pin BINDS to rail R when its declaration names R and nothing else that is
a declared rail, in one of the two places a row states what a pin IS rather
than what it relates to: the SPEC cell itself (`Vdd (core)` -> CORE) or the
HEAD of the note (`IOVDD (confirmed top pin)` -> IOVDD). A rail named only in
the BODY of the note is a relation, not a binding (`regulated CORE for the
LDO-fed modulator copy` is what an LDO OUTPUT does to CORE, not what feeds
the pin), and is recorded as a CITATION, unbound, with the sentence, so a
reader can promote it. A stated target voltage that contradicts the rail's
declared voltage refuses the binding and says so.

A GROUND-named pin (`vss`, `gnd`, …, the same vocabulary
`l21_doc_supply_rail_synth` uses) binds to the design's declared GROUND rail
when exactly one exists, and is otherwise recorded as a DECLARED INTEGRATION
GAP: the documents name the supplies and no return, which is a real gap in
them, owned here rather than papered over with an invented rail.

WHAT IT REFUSES TO DO
---------------------
* never overwrite an existing `(master, pin)` entry — a declaration already
  present (by hand, or by an earlier run) is left byte-identical;
* never bind a pin whose declaration names two declared rails, or none;
* never guess a pin's direction. The interface declaration carries none, so
  an OUTPUT that GENERATES a supply is not bound here; Phase 3 discovers it
  from the netlist (a net driven by a macro pin that lands on a POWER-typed
  terminal) and builds it as a secondary supply.

rc 0 = ran (bindings and/or gaps written, or nothing new to add)
rc 2 = NOT_APPLICABLE (no L21, no interface declaration, or no rail declared)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROGRAM = "l21_hard_macro_supply_bind"
VERSION = "1.0.0"

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:
    import _path_layout as _pl  # type: ignore
except Exception:  # noqa: BLE001
    _pl = None  # type: ignore

# vibe-ic#1082 — the declared report appears under its final name only once it
# is complete. `Path.write_text` truncates first and fills second, so a writer
# killed in between leaves a short file that `required_outputs` reads as "the
# step produced this". Not optional here: `--json` names the artefact the flow
# resolves, and `atomic_artifact_write_check` blocks on a NEW non-atomic writer.
import _atomic_artefact as _aa  # noqa: E402

try:  # ONE table grammar for every L21 producer
    from l21_doc_supply_rail_synth import (  # type: ignore
        _GROUND_NAME_RE, _IDENT_RE, _tables, _volts, doc_sources)
except Exception:  # noqa: BLE001 — a missing sibling is a real defect
    raise

_SUBCKT_RE = re.compile(r"^\s*\.subckt\s+(\S+)\s+([^\n]*?)\s*$", re.I | re.M)
_TOKEN_SPLIT_RE = re.compile(r"[\s/,;()\[\]|:]+")
_SP_EXTS = (".sp", ".spice", ".cir", ".cdl", ".ckt", ".net")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


# ── interface declaration ────────────────────────────────────────────────────
def interface_blocks(project: Path) -> List[Dict[str, Any]]:
    """``[{master, pins, file, line}]`` for every `.subckt` under `input/`."""
    out: List[Dict[str, Any]] = []
    root = project / "input"
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in _SP_EXTS:
            continue
        try:
            txt = p.read_text(errors="replace")
        except OSError:
            continue
        for m in _SUBCKT_RE.finditer(txt):
            pins = [t for t in m.group(2).split() if "=" not in t]
            out.append({"master": m.group(1), "pins": pins,
                        "file": str(p.relative_to(project)),
                        "line": txt[:m.start()].count("\n") + 1})
    return out


# ── rails ───────────────────────────────────────────────────────────────────
def declared_rails(l21: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """name -> {voltage_v, use} for every rail L21 declares. A ``power_domains``
    entry stamped ``is_power_domain: False`` is a GROUND rail declaration (the
    marker the rail producers use); everything else is POWER."""
    f = (l21 or {}).get("fields") or {}
    out: Dict[str, Dict[str, Any]] = {}
    for d in (f.get("power_domains") or []):
        if not isinstance(d, dict):
            continue
        name = str(d.get("name") or d.get("power_net") or "").strip()
        if not name:
            continue
        use = "GROUND" if d.get("is_power_domain") is False else "POWER"
        v = d.get("voltage_v")
        try:
            v = float(v) if v is not None else None
        except (TypeError, ValueError):
            v = None
        out.setdefault(name, {"voltage_v": v, "use": use})
    return out


def _rail_tokens(text: str, rails: Dict[str, Dict[str, Any]],
                 exclude_first: bool = False) -> List[str]:
    """Declared rail names whose token appears in `text` (case-insensitive,
    identifier-normalised, whole token)."""
    toks = [t for t in _TOKEN_SPLIT_RE.split(text or "") if t]
    if exclude_first and toks:
        toks = toks[1:]
    hits: List[str] = []
    by_norm = {_norm(r): r for r in rails}
    for t in toks:
        r = by_norm.get(_norm(t))
        if r and r not in hits:
            hits.append(r)
    return hits


# ── the declaration of one pin ──────────────────────────────────────────────
def _block_tables(project: Path, master: str) -> List[Tuple[str, Dict[str, Any]]]:
    """(project-relative file, table) for every table under a heading that
    names `master`, across the design's documents."""
    out = []
    for _p, rel, text in doc_sources(project):
        for tb in _tables(text):
            head = tb.get("heading") or ""
            if re.search(r"(?<![A-Za-z0-9_])" + re.escape(master)
                         + r"(?![A-Za-z0-9_])", head):
                out.append((rel, tb))
    return out


def _pin_row(tables, pin: str):
    """The row whose leading identifier IS the pin name, or None."""
    for rel, tb in tables:
        for line_no, cells in tb.get("rows") or []:
            if not cells:
                continue
            m = _IDENT_RE.match(cells[0] or "")
            if m and _norm(m.group(1)) == _norm(pin):
                return rel, line_no, cells
    return None


def bind_pin(master: str, pin: str, tables,
             rails: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Classify ONE interface pin against its documented row and the rails."""
    base = {"master": master, "pin": pin}
    row = _pin_row(tables, pin)
    ground_named = bool(_GROUND_NAME_RE.match(pin or ""))
    gnd_rails = [r for r, d in rails.items() if d["use"] == "GROUND"]
    if row is None:
        if ground_named:
            if len(gnd_rails) == 1:
                return {**base, "status": "bound", "rail": gnd_rails[0],
                        "use": "GROUND",
                        "why": "ground-named pin; the design declares exactly "
                               "one GROUND rail"}
            return {**base, "status": "gap", "use": "GROUND",
                    "why": ("ground-named pin with no document row and "
                            + ("no declared GROUND rail" if not gnd_rails else
                               f"{len(gnd_rails)} declared GROUND rails"))}
        return {**base, "status": "no_row",
                "why": "no document row declares this pin"}
    rel, line_no, cells = row
    spec = cells[0] or ""
    note = cells[-1] if len(cells) > 1 else ""
    ev = {"file": rel, "line": line_no,
          "matched_text": " | ".join(cells)[:200]}
    in_spec = _rail_tokens(spec, rails, exclude_first=True)
    note_toks = [t for t in _TOKEN_SPLIT_RE.split(note) if t]
    head = _rail_tokens(note_toks[0], rails) if note_toks else []
    everywhere = _rail_tokens(" ".join(cells), rails, exclude_first=True)
    binding = []
    for r in in_spec + head:
        if r not in binding:
            binding.append(r)
    if not everywhere:
        return {**base, "status": "no_rail_named", "evidence": ev,
                "why": "the pin's row names no declared rail"}
    if len(everywhere) > 1:
        return {**base, "status": "ambiguous", "evidence": ev,
                "cited_rails": everywhere,
                "why": f"the row names {len(everywhere)} declared rails"}
    rail = everywhere[0]
    if rail not in binding:
        return {**base, "status": "cited", "evidence": ev,
                "cited_rails": [rail],
                "why": (f"rail {rail!r} appears in the body of the note, "
                        "not in the spec cell or at the head of the note — "
                        "a relation, not a binding")}
    # voltage cross-check: the row's target vs the rail's declared level
    target = None
    for c in cells[1:-1] if len(cells) > 2 else cells[1:]:
        got = _volts(c) if _volts(c) else None
        if got:
            target = got[0]
            break
    if target is None and len(cells) > 2:
        try:
            target = float(cells[1])
        except (TypeError, ValueError):
            target = None
    rv = rails[rail]["voltage_v"]
    if target is not None and rv is not None and \
            abs(target - rv) > 0.05 * max(abs(rv), 1e-9):
        return {**base, "status": "voltage_mismatch", "evidence": ev,
                "cited_rails": [rail],
                "why": (f"the row states {target} V but rail {rail!r} is "
                        f"declared at {rv} V")}
    return {**base, "status": "bound", "rail": rail,
            "use": rails[rail]["use"], "evidence": ev,
            "why": ("the spec cell names the rail" if rail in in_spec
                    else "the note's head names the rail")
                   + (f"; {target} V agrees with the rail's {rv} V"
                      if target is not None and rv is not None else "")}


# ── derive ──────────────────────────────────────────────────────────────────
def derive(project: Path, l21: Dict[str, Any]) -> Dict[str, Any]:
    blocks = interface_blocks(project)
    rails = declared_rails(l21)
    results: List[Dict[str, Any]] = []
    for b in blocks:
        tables = _block_tables(project, b["master"])
        for pin in b["pins"]:
            r = bind_pin(b["master"], pin, tables, rails)
            r["interface"] = {"file": b["file"], "line": b["line"]}
            results.append(r)
    return {"blocks": blocks, "rails": rails, "pins": results}


def _entries_from(results: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]],
                                                          List[Dict[str, Any]]]:
    """(hard_macro_supplies entries, citation records) from the classified pins."""
    entries: List[Dict[str, Any]] = []
    cites: List[Dict[str, Any]] = []
    for r in results:
        if r["status"] == "bound":
            e = {"master": r["master"], "pin": r["pin"], "rail": r["rail"],
                 "use": r.get("use", ""), "derived_by": PROGRAM,
                 "rationale": r["why"]}
            if r.get("evidence"):
                e["evidence"] = r["evidence"]
            entries.append(e)
        elif r["status"] == "gap":
            entries.append({
                "master": r["master"], "pin": r["pin"],
                "integration_gap": True, "derived_by": PROGRAM,
                "detail": (r["why"] + "; the input documents name the "
                           "supplies and no return. Declared as a KNOWN, "
                           "OWNED gap rather than mapped to a rail the "
                           "design never stated.")})
        elif r["status"] in ("cited", "ambiguous", "voltage_mismatch"):
            cites.append({k: r[k] for k in ("master", "pin", "status",
                                            "cited_rails", "why", "evidence")
                          if k in r})
    return entries, cites


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Bind hard-macro supply pins to the rails the design's "
                    "own documents name (L21.hard_macro_supplies producer).")
    ap.add_argument("project")
    ap.add_argument("--l21", help="power-intent layer JSON (default: "
                                  "phase1/generated_docs/L21_POWER_INTENT.json)")
    ap.add_argument("--apply", action="store_true",
                    help="write the bindings into the layer (default: dry run)")
    ap.add_argument("--json", help="write the result JSON here")
    args = ap.parse_args(argv)

    proj = Path(args.project).resolve()
    l21_path = Path(args.l21) if args.l21 else \
        proj / "phase1" / "generated_docs" / "L21_POWER_INTENT.json"
    if not l21_path.is_file():
        print(f"[NOT_APPLICABLE] {PROGRAM}: power-intent layer not found: "
              f"{l21_path}", file=sys.stderr)
        return 2
    try:
        doc = json.loads(l21_path.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        print(f"[FAIL] {PROGRAM}: unreadable L21: {exc}", file=sys.stderr)
        return 1
    container = doc.get("fields") if isinstance(doc.get("fields"), dict) else doc
    res = derive(proj, doc)
    verdict = "DERIVED"
    if not res["blocks"]:
        verdict = "NOT_APPLICABLE_NO_INTERFACE_DECLARATION"
    elif not res["rails"]:
        verdict = "NOT_APPLICABLE_NO_DECLARED_RAIL"
    entries, cites = _entries_from(res["pins"])
    existing = container.get("hard_macro_supplies")
    if not isinstance(existing, list):
        existing = []
    # A PLACEHOLDER is not a declaration. `l21_macro_supply_rail_synth`
    # binds a pin to a rail named after the pin itself (`vdd` -> `vdd`)
    # when the abstracts already exist at Phase-1 time: it records that the
    # pin IS a supply, not which of the design's rails feeds it. A binding
    # the DOCUMENTS state supersedes such a placeholder for the same pin
    # (recorded on the entry); every other existing entry is left as is.
    def _is_placeholder(m: Dict[str, Any]) -> bool:
        return (str(m.get("derived_by", "")) == "l21_macro_supply_rail_synth"
                and str(m.get("rail", "")).strip() == str(m.get("pin", "")).strip()
                and m.get("integration_gap") is not True)
    doc_bound = {(e["master"], e["pin"]): e for e in entries
                 if "rail" in e and not e.get("integration_gap")}
    superseded: List[Dict[str, Any]] = []
    kept_existing: List[Dict[str, Any]] = []
    for m in existing:
        if isinstance(m, dict) and _is_placeholder(m) and \
                (str(m.get("master", "")), str(m.get("pin", ""))) in doc_bound:
            e = doc_bound[(str(m.get("master", "")), str(m.get("pin", "")))]
            e["superseded_placeholder"] = {
                "rail": m.get("rail"), "derived_by": m.get("derived_by"),
                "why": "a rail named after the pin itself records that the "
                       "pin is a supply, not which rail feeds it; the "
                       "documents state the rail"}
            superseded.append(m)
        else:
            kept_existing.append(m)
    existing = kept_existing
    have = {(str(m.get("master", "")), str(m.get("pin", "")))
            for m in existing if isinstance(m, dict)}
    added = [e for e in entries if (e["master"], e["pin"]) not in have]
    result = {
        "program": PROGRAM, "version": VERSION, "verdict": verdict,
        "power_intent_layer": str(l21_path),
        "interface_blocks": res["blocks"],
        "declared_rails": res["rails"],
        "pins": res["pins"],
        "bindings_added": added,
        "already_declared": [e for e in entries
                             if (e["master"], e["pin"]) in have],
        "citations_unbound": cites,
        "placeholders_superseded": superseded,
        "counts": {
            "blocks": len(res["blocks"]),
            "pins": len(res["pins"]),
            "bound": len([r for r in res["pins"] if r["status"] == "bound"]),
            "gaps": len([r for r in res["pins"] if r["status"] == "gap"]),
            "cited_unbound": len(cites),
            "added": len(added),
        },
        "applied": bool(args.apply and (added or superseded)),
    }
    if args.apply and (added or superseded):
        container["hard_macro_supplies"] = list(existing) + added
        if cites:
            container["hard_macro_supply_citations"] = cites
        l21_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    out_json = Path(args.json) if args.json else (
        _pl.report_path(proj, f"phase1/{PROGRAM}.json") if _pl else None)
    if out_json is not None:
        try:
            out_json.parent.mkdir(parents=True, exist_ok=True)
            _aa.write_json(out_json, result)
        except OSError as exc:
            print(f"[WARN] {PROGRAM}: could not write {out_json}: {exc}",
                  file=sys.stderr)
    c = result["counts"]
    print(f"[{'PASS' if verdict == 'DERIVED' else 'SKIP'}] {PROGRAM}: "
          f"{verdict} — {c['blocks']} block(s), {c['pins']} pin(s): "
          f"{c['bound']} bound, {c['gaps']} declared gap(s), "
          f"{c['cited_unbound']} cited-unbound; {c['added']} added"
          + (" (applied)" if result["applied"] else " (dry run)"
             if not args.apply else ""))
    return 0 if verdict == "DERIVED" else 2


if __name__ == "__main__":
    sys.exit(main())
