#!/usr/bin/env python3
"""analog_a1_spec_emit.py — the A1 spec PRODUCER that was missing.

WHAT WAS BROKEN
===============
Flow step A1 ("Analog Spec Extraction") declares
`phase{1,3}/analog/<block>/spec.json` as its `required_output`, and
`analog_a1_spec_extract_check` is the gate of record for it. There is no
deterministic PRODUCER: A1 is a skill-only step, so
`analog_one_shot_runner.step_for_block` runs the gate, gets rc=2, and reports
WAIVED. Across a whole run `find -name spec.json` returns 0 files while the
downstream consumers that read spec.json — `ams_analysis_select`,
`analog_meas_from_spec_gen`, `analog_adc_enob_corner_check`,
`analog_hardmacro_pinname_consistency_check`,
`analog_digital_interface_check`, `analog_block_coverage_check`,
`analog_per_block_pv_completeness_check` — validate a file nothing writes.

WHAT THIS PROGRAM DOES
======================
For every declared analog block it binds the STRUCTURED Phase-1 spec that
Phase 1 already attributed to that block, and only that:

    phase1/generated_docs/L5_ADI_SPEC.json # analog_blocks[].spec.specs[]
        -> phase3/analog/<block>/spec.json      (layout (a): `specs: [...]`)

The binding runs through the consumer's OWN vocabulary —
`analog_real_corner_sweep.l5_block_specs()` / `normalize_spec_label()`, whose
docstring says it is "Exported so the Phase-1 PRODUCER can emit spec names in
the vocabulary the consumer actually reads, instead of maintaining a second
copy of it that drifts". This program is that producer.

WHAT IT DELIBERATELY DOES **NOT** DO — the whole point
======================================================
It never invents a number, and it never writes an artefact that LOOKS like an
extraction when no extraction happened.

  * The un-attributed electrical tables (`L5.electrical_specs`,
    `L1_DATASHEET.electrical_specs`) carry NO block key. Deciding which row of
    a prose datasheet is *this* block's typ Vout is judgment, and
    `analog-spec-extract/SKILL.md` marks it KEEP-JUDGMENT. This program does
    not guess: it binds only what Phase 1 already attributed to the block.
  * A block whose structured spec yields nothing gets **NO spec.json at all**.
    It gets `spec_gap.json` — an artefact whose `status` is
    `NO_SPEC_IN_DOCS`, which names the evidence, says in `ai_handoff` which
    skill must take over, and states `spec_json_written: false` — and the
    program returns rc 2, so the runner keeps reporting WAIVED.

    This is forced by measurement, not taste. `analog_a1_spec_extract_check`
    has no encoding for an honest absence: a body carrying `"specs": []` plus
    `"extraction_status": "NO_SPEC_IN_DOCS"` is rc=1 A1_SPEC_NO_FIELDS, which
    the runner reports as **FAIL**. Writing spec.json for a block with no spec
    would therefore convert an honest WAIVE into a fabricated FAIL — and, far
    worse, a spec.json filled with per-type defaults would convert it into a
    fabricated PASS. `analog_real_corner_sweep`'s static `TARGETS` table is
    exactly that failure mode one step later: it is why a bandgap whose target
    the documents never stated is graded against 1.205 V.

PROVENANCE IS STAMPED INTO THE ARTEFACT
=======================================
Every emitted spec.json carries `_provenance`: the producer, the input file
and the digest it was read at, how the block was matched (by name or by
type), the vocabulary used to bind each field, the list of fields bound,
`fields_defaulted` (**always empty** — this producer has no defaults; the key
is present so a reader never has to infer its absence), and `ai_handoff`.
`corner_results.json`'s `_provenance: "real_ngspice"` is true of the
simulator and silent about the subject; that silence is what let the analog
section read stronger than it was. A reader of this artefact can always tell
what produced it, from which input, and whether anything was assumed.

RC CONTRACT — a deferral is never a success and never a failure
===============================================================
    rc 0  at least one selected block bound a real spec and got a spec.json
          (or already carried a spec.json this producer must not overwrite).
    rc 1  the inputs themselves are unusable (no project dir / no block list).
          NOT used for "nothing bound" — that is not an error, it is a
          measurement.
    rc 2  no selected block bound anything. `spec_gap.json` written per block;
          hand off to skill `analog-spec-extract`.

chip-AGNOSTIC: block names, types and evidence all come from the Phase-1
artefacts. No chip, PDK SKU, vendor or part number appears below.

Usage:
    python3 analog_a1_spec_emit.py <project> [--block NAME] [--json OUT]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _analog_producer_common as _pc  # noqa: E402

PRODUCER = "analog_a1_spec_emit"


def producer_fingerprint() -> str:
    """A digest of THIS producer's own source, stamped into the provenance.

    The last instance of the shape round 23 measured: an artefact that names
    its producer but not WHICH producer cannot be told apart from a stale one,
    so the runner skipped the producer and the flow inherited the old file.
    Same mechanism as `analog_a2_topology_emit.producer_fingerprint`, derived
    from the producer's own bytes -- not mtime, not a file name.
    """
    import hashlib
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]
    except OSError:                                     # pragma: no cover
        return ""
PROVENANCE_SCHEMA = 1
SKILL = "analog-spec-extract"

# The canonical analog root the runner writes and every A-gate probes first.
_CANONICAL_ANALOG = "phase3/analog"
_DECLARED_ANALOG = "phase1/analog"
_L5_REL = "phase1/generated_docs/L5_ADI_SPEC.json"


# ── inputs ────────────────────────────────────────────────────────────────
def _sha256(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None


def block_entries(project: Path) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Full per-block ENTRIES (not just names) plus the relative path they came
    from. `_analog_a_check_common.load_block_list` flattens to names; A1 needs
    the `type` / `evidence` / `low_confidence` fields the list carries."""
    for rel in (f"{_CANONICAL_ANALOG}/analog_block_list.json",
                f"{_DECLARED_ANALOG}/analog_block_list.json"):
        data = _read_json(project / rel)
        if data is None:
            continue
        blocks = data.get("blocks") if isinstance(data, dict) else data
        if isinstance(blocks, list):
            return ([b for b in blocks if isinstance(b, dict)], rel)
    data = _read_json(project / _L5_REL)
    if isinstance(data, dict):
        blocks = data.get("analog_blocks")
        if isinstance(blocks, list):
            return ([b for b in blocks if isinstance(b, dict)], _L5_REL)
    return ([], None)


def _canonical_type(btype: Optional[str]) -> str:
    """Block-type spelling the downstream consumers deck. Falls back to the
    raw lowercased token when `analog_real_corner_sweep` is unavailable."""
    try:
        import analog_real_corner_sweep as _arcs
        return _arcs.canonical_block_type(btype)
    except Exception:
        return str(btype or "").strip().lower()


def _bind_l5(project: Path, name: str, btype: str) -> Dict[str, Any]:
    """The consumer's own binder. Returns {} when nothing binds — never a
    default. Any import failure is reported as an unusable input rather than
    silently degrading to a second, drifting copy of the vocabulary."""
    import analog_real_corner_sweep as _arcs
    return _arcs.l5_block_specs(project, name, btype) or {}


# ── artefact bodies ───────────────────────────────────────────────────────
def _spec_entry(canon: str, bound: Dict[str, Any],
                entry: Dict[str, Any]) -> Dict[str, Any]:
    """One `specs[]` element in the layout `analog_a1_spec_extract_check`
    accepts: a `name` plus one of min/typ/max/value/target."""
    raw = bound.get("raw") if isinstance(bound.get("raw"), dict) else {}
    out: Dict[str, Any] = {
        "name": canon,
        bound.get("bound") or "target": bound.get("value"),
        "unit": bound.get("unit"),
        "source": "L5",
        "source_field": f"analog_blocks[].spec.specs[].{bound.get('bound')}",
        "l5_name": raw.get("name"),
        "bound_via": "analog_real_corner_sweep.normalize_spec_label",
    }
    # Carry the sentence Phase 1 attributed the number to, when it has one.
    for k in ("evidence_text", "label", "attribution"):
        if raw.get(k) is not None:
            out[k] = raw.get(k)
    # A range, when Phase 1 recorded one, is spec content — not a default.
    for k in ("min", "max"):
        v = raw.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) \
                and k not in out:
            out[k] = float(v)
    return out


def _staged_interface_ports(project: Path, name: str,
                            btype: str) -> Optional[List[str]]:
    """Port list for this block from a DESIGN-STAGED interface declaration.

    MEASURED, and it is why this exists: `spec.json:interface.pins[]` is the
    "golden source" `analog_hardmacro_pinname_consistency_check` names in its
    own docstring — and NOTHING emitted it. The L5 block record carries the
    block's PERFORMANCE and no pins, so `_interface` below correctly declined
    to invent one, the gate self-skipped, and two producers derived the
    interface independently: the Phase-2 RTL blackbox from the doc prose, the
    A2 topology emitter from its topology library. They disagreed about every
    block, and the disagreement first surfaced at PnR as OpenROAD `STA-0201
    port not found` — after A8 had cleared ORD-2013 and not before.

    So the missing link is not a guess, it is a DECLARATION: when the design
    stages one (any SPICE `.subckt <block> …` under `input/`, which Phase 1
    already ingests into `L9.submodules`), its ports are this block's declared
    interface. Read, never derived — a design that stages nothing still gets
    no `interface` key and the gate still self-skips, exactly as before.
    """
    l9 = _read_json(project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json")
    subs = (l9 or {}).get("submodules")
    if not isinstance(subs, list):
        return None
    # A block can appear in `submodules` more than once — an entry
    # contributed by the multiplicity pass carries the NAME and no ports, and
    # the staged declaration carries the ports. Take the first entry that
    # actually declares a port list, never the first entry by name (measured:
    # one block resolved to a port-less multiplicity record and lost its
    # declaration while its sibling, which had no such record, resolved fine).
    for sc in subs:
        if not isinstance(sc, dict):
            continue
        nm = str(sc.get("name") or "")
        if nm.lower() not in (str(name).lower(), str(btype).lower()):
            continue
        ports = sc.get("ports_normalized") or sc.get("ports")
        if isinstance(ports, list) and ports:
            out = []
            for p in ports:
                if isinstance(p, str) and p:
                    out.append(p)
                elif isinstance(p, dict) and p.get("name"):
                    out.append(str(p["name"]))
            if out:
                return out
    return None


def _interface(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """`interface.pins[]` ONLY when the block list actually names pins.
    `analog_hardmacro_pinname_consistency_check` self-skips when the key is
    absent and hard-compares when it is present, so inventing a pin list would
    manufacture a mismatch out of nothing."""
    pins = entry.get("pins") or entry.get("ports")
    if not isinstance(pins, list) or not pins:
        return None
    out = []
    for p in pins:
        if isinstance(p, dict) and p.get("name"):
            out.append({k: v for k, v in p.items() if k in
                        ("name", "direction", "type", "description")})
        elif isinstance(p, str) and p:
            out.append({"name": p})
    return {"pins": out} if out else None


def _unattributed_row_count(project: Path) -> int:
    """How many electrical rows exist that carry NO block key. These are the
    rows the deterministic track refuses to bind — and their COUNT is what
    tells a reader whether the emitted spec is the whole story for this block
    or only the attributed part of it."""
    n = 0
    for rel, key in ((_L5_REL, "electrical_specs"),
                     ("phase1/generated_docs/L1_DATASHEET.json",
                      "electrical_specs")):
        d = _read_json(project / rel)
        if isinstance(d, dict) and isinstance(d.get(key), list):
            n += len(d[key])
    return n


def _provenance(project: Path, entry: Dict[str, Any], btype: str,
                bound_fields: List[str], match: str) -> Dict[str, Any]:
    l5 = project / _L5_REL
    unattributed = _unattributed_row_count(project)
    handoff = None
    if unattributed:
        # A PARTIAL bind is still a handoff. The emitted artefact has to say
        # so, or a consumer reads a spec.json carrying one field as this
        # block's complete spec.
        handoff = {
            "track": "skill",
            "skill": SKILL,
            "reason": (
                f"{unattributed} electrical row(s) exist in the Phase-1 "
                f"documents with NO block attribution. Deciding which of "
                f"them belongs to this block is judgment (the skill's "
                f"KEEP-JUDGMENT boundary); the deterministic track bound "
                f"only the rows Phase 1 had already attributed."),
            "scope": "additional_specs_for_this_block",
        }
    return {
        "schema": PROVENANCE_SCHEMA,
        "producer": PRODUCER,
        "produced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "input": {
            "path": _L5_REL,
            "sha256": _sha256(l5),
            "block_matched_by": match,
            "block_list_declares_low_confidence":
                bool(entry.get("low_confidence")),
            "evidence": entry.get("evidence"),
        },
        "binding_vocabulary":
            "analog_real_corner_sweep.normalize_spec_label",
        "fields_bound": sorted(bound_fields),
        # Present and empty BY CONSTRUCTION. This producer has no per-type
        # default table; a reader must never have to infer that from silence.
        "fields_defaulted": [],
        "defaults_used": False,
        "unattributed_electrical_rows_not_bound": unattributed,
        "ai_handoff": handoff,
        "limits": (
            "binds ONLY the structured per-block spec Phase 1 already "
            "attributed to this block. The un-attributed electrical tables "
            "(L5.electrical_specs / L1_DATASHEET.electrical_specs) carry no "
            "block key; binding a row of those to a block is judgment and is "
            "left to skill `analog-spec-extract`."),
    }


def _gap_body(project: Path, entry: Dict[str, Any], name: str, btype: str,
              seen: List[str]) -> Dict[str, Any]:
    return {
        "block": name,
        "block_type": btype,
        "_provenance": {
            "producer_fingerprint": producer_fingerprint(),
            "schema": PROVENANCE_SCHEMA,
            "producer": PRODUCER,
            "produced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "input": {"path": _L5_REL, "sha256": _sha256(project / _L5_REL)},
            "fields_bound": [],
            "fields_defaulted": [],
            "defaults_used": False,
        },
        "status": "NO_SPEC_IN_DOCS",
        "spec_json_written": False,
        "reason": (
            "no numerically-bounded spec is attributed to this block in the "
            "Phase-1 structured extraction, so this producer emitted NOTHING "
            "for it. An empty or default-filled spec.json would be read by "
            "every downstream consumer as an extraction that happened."),
        "evidence": entry.get("evidence"),
        "evidence_paragraph": entry.get("evidence_paragraph"),
        "low_confidence": bool(entry.get("low_confidence")),
        "l5_spec_field_present": entry.get("spec") is not None,
        "spec_names_seen_but_unbindable": seen,
        "ai_handoff": {
            "track": "skill",
            "skill": SKILL,
            "required_output": f"{_CANONICAL_ANALOG}/{name}/spec.json",
            "reason": (
                "binding an un-attributed electrical row to this block is "
                "judgment (see the skill's KEEP-JUDGMENT section); the "
                "deterministic track cannot decide it and must not guess."),
        },
    }


# ── per-block driver ──────────────────────────────────────────────────────
def emit_for_block(project: Path, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Emit spec.json OR spec_gap.json for one block. Returns a record."""
    name = entry.get("name") or entry.get("block") or entry.get("type")
    btype = _canonical_type(entry.get("type") or entry.get("block_type"))
    bdir = project / _CANONICAL_ANALOG / str(name)
    spec_path = bdir / "spec.json"
    rec: Dict[str, Any] = {"block": name, "block_type": btype}

    existing = _read_json(spec_path) if spec_path.is_file() else None
    if isinstance(existing, dict):
        prod = (existing.get("_provenance") or {}).get("producer") \
            if isinstance(existing.get("_provenance"), dict) else None
        if prod != PRODUCER:
            # Someone else's artefact — the AI track's, or a human's. A
            # producer that silently overwrote it would destroy the very
            # judgment it is supposed to defer to.
            rec.update(action="kept_preexisting", emitted=False,
                       spec_path=str(spec_path.relative_to(project)))
            return rec

    bound = _bind_l5(project, str(name), btype)
    if not bound:
        seen = []
        raw_spec = entry.get("spec")
        if isinstance(raw_spec, dict) and isinstance(raw_spec.get("specs"),
                                                     list):
            seen = [str(s.get("name")) for s in raw_spec["specs"]
                    if isinstance(s, dict) and s.get("name")]
        bdir.mkdir(parents=True, exist_ok=True)
        gap = _gap_body(project, entry, str(name), btype, seen)
        (bdir / "spec_gap.json").write_text(
            json.dumps(gap, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        # An earlier run of THIS producer may have written a spec.json that
        # the inputs no longer support. Leaving it would make a stale artefact
        # outlive its evidence.
        if spec_path.is_file() and isinstance(existing, dict) and \
                (existing.get("_provenance") or {}).get("producer") == PRODUCER:
            spec_path.unlink()
            rec["stale_spec_removed"] = True
        rec.update(action="gap", emitted=False,
                   gap_path=str((bdir / "spec_gap.json").relative_to(project)),
                   status="NO_SPEC_IN_DOCS")
        return rec

    # Which way the block was matched inside l5_block_specs (name first,
    # then type) — reported so a type-matched bind is never mistaken for a
    # per-block attribution.
    l5 = _read_json(project / _L5_REL) or {}
    names = {b.get("name") for b in (l5.get("analog_blocks") or [])
             if isinstance(b, dict)}
    match = "name" if name in names else "type"

    specs = [_spec_entry(canon, b, entry) for canon, b in sorted(bound.items())]
    body: Dict[str, Any] = {
        "block": name,
        "block_type": btype,
        "specs": specs,
        "extraction_strategy": "l5_structured_bind",
        "low_confidence": bool(entry.get("low_confidence")),
        "_provenance": _provenance(project, entry, btype,
                                   sorted(bound.keys()), match),
    }
    iface = _interface(entry)
    if not iface:
        staged = _staged_interface_ports(project, name, btype)
        if staged:
            iface = {"pins": [{"name": p} for p in staged],
                     "source": "design-staged interface declaration "
                               "(L9.submodules)"}
    if iface:
        body["interface"] = iface
    bdir.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    gap_path = bdir / "spec_gap.json"
    if gap_path.is_file():
        gap_path.unlink()          # the gap is resolved; do not leave both
    rec.update(action="emitted", emitted=True,
               spec_path=str(spec_path.relative_to(project)),
               fields=sorted(bound.keys()))
    return rec


def run(project: Path, only: Optional[str] = None) -> Tuple[int, Dict[str, Any]]:
    entries, src = block_entries(project)
    if not entries:
        return 1, {
            "producer": PRODUCER, "verdict": "NO_INPUT",
            "reason": ("no analog_block_list.json under "
                       f"{_CANONICAL_ANALOG}/ or {_DECLARED_ANALOG}/ and no "
                       f"analog_blocks[] in {_L5_REL}"),
            "records": [],
        }
    if only:
        entries = [e for e in entries
                   if (e.get("name") or e.get("block") or e.get("type"))
                   == only]
        if not entries:
            return 1, {"producer": PRODUCER, "verdict": "NO_SUCH_BLOCK",
                       "reason": f"block `{only}` is not declared in {src}",
                       "records": []}
    try:
        records = [emit_for_block(project, e) for e in entries]
    except ImportError as exc:
        return 1, {"producer": PRODUCER, "verdict": "NO_BINDER",
                   "reason": (f"the consumer's spec vocabulary is "
                              f"unavailable ({exc}); refusing to bind with a "
                              f"second, drifting copy of it"),
                   "records": []}
    emitted = [r for r in records if r.get("emitted")]
    kept = [r for r in records if r.get("action") == "kept_preexisting"]
    gaps = [r for r in records if r.get("action") == "gap"]
    report = {
        "producer": PRODUCER,
        "block_list_source": src,
        "verdict": "EMITTED" if (emitted or kept) else "ALL_GAP",
        "blocks_total": len(records),
        "blocks_emitted": len(emitted),
        "blocks_kept_preexisting": len(kept),
        "blocks_gap": len(gaps),
        "ai_handoff_blocks": [r["block"] for r in gaps],
        "suggested_skill": SKILL if gaps else None,
        "records": records,
    }
    return (0 if (emitted or kept) else 2), report


def main(argv: Optional[List[str]] = None) -> int:
    # A usage error exits `_pc.EX_USAGE`, never the honest-gap tier — see
    # `_analog_producer_common` for the measurement that forced the split.
    ap = _pc.ProducerArgumentParser(prog=PRODUCER, description=__doc__,
                                    formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--block", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    project = args.project.resolve()
    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        return 1
    rc, report = run(project, args.block)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    if rc == 0:
        print(f"{PRODUCER}: {report['blocks_emitted']} spec.json emitted, "
              f"{report['blocks_gap']} honest gap(s) "
              f"(hand off to `{SKILL}`)")
    elif rc == _pc.RC_HONEST_GAP:
        print(_pc.honest_gap_line(
            PRODUCER,
            f"NO block bound a spec — {report['blocks_gap']} spec_gap.json "
            f"written, no spec.json; invoke skill `{SKILL}`"),
            file=sys.stderr)
    else:
        print(f"{PRODUCER}: {report.get('verdict')} — "
              f"{report.get('reason')}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
