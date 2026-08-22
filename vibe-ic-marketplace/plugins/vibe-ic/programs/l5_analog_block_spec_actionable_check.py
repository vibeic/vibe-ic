#!/usr/bin/env python3
"""l5_analog_block_spec_actionable_check.py — SEMANTIC layer gate for L5.

BLOCKS (exit 1). Rationale for blocking rather than advising
=============================================================
The A-track's grading target is chosen ONCE, at sweep time, from L5.
When L5 fails this contract the A-track does not stop — it *silently
degrades*: ``analog_real_corner_sweep`` falls back to its generic
per-block-TYPE static default (or to ``target=None``, which makes
``_verdict()`` return ``PASS_INFORMATIONAL`` for every measurement).
The block is then reported as swept and non-failing while nothing was
ever graded against the design's own numbers. An advisory verdict on a
degradation that manufactures a PASS is worthless — the whole point of
this gate is that the run must not proceed on a spec the consumer
cannot read. So: FAIL blocks.

The contract this gate enforces
===============================
    A layer is complete when the requirement is present IN THE LAYER
    THAT CONSUMES IT, in an ACTIONABLE FORM — not when a token appears
    somewhere.

L5_ADI_SPEC.json is the ANALOG-DIGITAL INTERFACE layer (not the vendor
"Analog Devices"); a pure-digital design legitimately has it empty and
this gate SKIPs on it.  When L5 *does* declare ``analog_blocks[]``,
those entries are the A1-A9 track's entire work list, and three
different consumers dereference them:

  * ``analog_one_shot_runner``  — falls back to ``L5.analog_blocks[]``
    when ``analog/analog_block_list.json`` is absent; an empty list
    silently SKIPs the whole A1-A9 track.
  * ``analog_real_corner_sweep._pick_block_type(block)`` — reads
    ``entry["type"]`` to select the SPICE deck + the TARGETS row. With
    no ``type`` it falls back to ``name == type``; an unknown type has
    no deck, so the block is never actually simulated.
  * ``analog_real_corner_sweep.l5_block_specs(project, block)`` — the
    ONLY path by which the design's own electrical targets reach the
    sweep. It requires ``entry["spec"]`` to be a **dict** carrying a
    ``specs`` **list** whose entries hold a numeric ``target``/``min``/
    ``max``. It returns ``{}`` for anything else — including a perfectly
    informative *string* such as ``"1.8 V, 1.2 V, 125 °C"``.

That last one is the measured defect this gate exists for. On a real
Phase-1 output the ``ldo`` block carried a structured ``spec`` (the
sweep correctly graded its Vout against the design's 1.2 V) while the
sibling ``delta_sigma`` block carried its supplies as a bare STRING.
``l5_block_specs()`` returned ``{}`` for it, the sweep fell back to the
static ``TARGETS['delta_sigma']`` row whose ``target`` is ``None``, and
every measurement it produced was stamped ``PASS_INFORMATIONAL``. The
numbers were *in* L5. They were not in the form the consumer parses.

Requirements (each derived from the consumer, never hardcoded)
==============================================================
For every entry in ``L5.analog_blocks[]``:

  R1  a non-empty ``name`` — the key every consumer looks the block up
      by, and the identifier the A-track names its artefacts after.
  R2  a non-empty ``type``/``topology`` — ``_pick_block_type``'s deck
      selector. Checked against the CONSUMER'S OWN deck/TARGETS tables,
      which are imported at runtime, so this gate stays correct when a
      new block type is added to the sweep. A type the consumer has no
      deck for is reported distinctly from a missing type.
  R3  an ACTIONABLE spec: ``l5_block_specs()`` — the consumer's own
      parser, imported and called, not reimplemented — must return at
      least one numerically-bounded spec for the block. This is the
      exact predicate that decides whether the sweep grades against the
      design or against a generic default.

R3 is skipped for a block whose consumer-side TARGETS row is purely
informational AND which declares no spec content at all: see the
"honest silence" carve-out below.

Fail-safe / no-false-positive design
====================================
* No ``L5`` file, or L5 with ``no_analog: true`` / ``analog_blocks: []``
  → SKIP(2). A digital design is not penalised for an empty interface
  layer; that is what ``analog_content_detected_must_emit_l5_check``
  is for (this gate deliberately does NOT duplicate it — that one asks
  "should L5 exist?", this one asks "is what L5 says usable?").
* ``ic_class`` in the digital-only classes → SKIP.
* HONEST SILENCE carve-out: a block that carries NO spec field at all
  (``spec`` absent/None) and whose own ``low_confidence`` flag is set is
  reported as a WARN line, not a FAIL — L5 is telling us it could not
  extract, which is honest, and fabricating a target would be worse.
  A block that carries spec CONTENT in an unparseable form is always a
  FAIL: the information exists and was simply not typed.

Waiver: ``l5_analog_block_spec_degraded_intentional`` (>=40 chars) in
``<project>/waivers.json``.

Usage:
    python3 l5_analog_block_spec_actionable_check.py <project_dir> \
        [--json <out.json>]

Exit codes:
    0 = PASS / SKIP-by-class / PASS_WITH_WAIVER
    1 = FAIL (blocks)
    2 = input-missing / not-applicable (skip)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _path_layout as _pl  # noqa: E402

WAIVER_KEY = "l5_analog_block_spec_degraded_intentional"
WAIVER_MIN_LEN = 40

# IC classes with no analog-digital interface to describe.
_SKIP_CLASSES = ("bare_fpga",)

_BLOCK_LIST_KEYS = ("analog_blocks", "blocks")
_NAME_KEYS = ("name", "block", "block_name", "id")
_TYPE_KEYS = ("type", "topology", "block_type", "kind")


# ---------------------------------------------------------------------------
# Consumer imports — the requirement is DERIVED from the consuming program,
# not restated here. If the sweep learns a new deck or a new spec alias this
# gate follows automatically.
# ---------------------------------------------------------------------------

def _load_consumer() -> Tuple[Any, Optional[str]]:
    """Import analog_real_corner_sweep (the A4 consumer).

    Returns (module, None) or (None, reason). A missing/unimportable
    consumer means we cannot state the contract, so the gate SKIPs
    rather than guessing — never a fabricated verdict.
    """
    try:
        import analog_real_corner_sweep as ars  # type: ignore
        return ars, None
    except Exception as exc:  # pragma: no cover - defensive
        return None, f"cannot import analog_real_corner_sweep: {exc}"


def _consumer_known_types(ars: Any) -> set:
    """The block types the consumer actually has a deck / target row for.

    R6-FIX-3: also admits a type SPELLING the consumer resolves to one of its
    own decks (`BLOCK_TYPE_ALIASES`, e.g. `dac` -> `trim`, whose TARGETS label
    is literally "DAC out (V)"). The gate's contract is "can the consumer build
    a testbench for this type", and an alias the consumer really resolves is
    really known — reading only the raw table KEYS reported a deck-backed type
    as deckless. Union, never a replacement: a type in neither the tables nor
    the alias map still fails."""
    known: set = set()
    for attr in ("TARGETS", "T", "DECKS", "TEMPLATES"):
        tbl = getattr(ars, attr, None)
        if isinstance(tbl, dict):
            known.update(str(k).lower() for k in tbl.keys())
    aliases = getattr(ars, "BLOCK_TYPE_ALIASES", None)
    if isinstance(aliases, dict) and known:
        # Only admit an alias whose TARGET is a genuinely decked type, so a
        # stale alias entry cannot smuggle in a type with no deck behind it.
        known.update(str(k).lower() for k, v in aliases.items()
                     if str(v).lower() in known)
    return known


def _target_is_informational(ars: Any, btype: str) -> bool:
    """True when the consumer's static TARGETS row for this type carries
    no numeric target — i.e. even a perfect sweep can only ever return
    PASS_INFORMATIONAL unless L5 supplies the number."""
    tbl = getattr(ars, "TARGETS", None)
    if not isinstance(tbl, dict):
        return False
    row = tbl.get(btype)
    if not isinstance(row, dict):
        return False
    return row.get("target") is None


# ---------------------------------------------------------------------------
# L5 loading / normalisation
# ---------------------------------------------------------------------------

def _find_l5(project: Path) -> Optional[Path]:
    cand = _pl.generated_docs_dir(project) / "L5_ADI_SPEC.json"
    if cand.is_file():
        return cand
    for pat in ("phase1/generated_docs/L5_ADI_SPEC.json",
                "phase1/generated_docs/L5*.json",
                "**/L5_ADI_SPEC.json"):
        for hit in project.glob(pat):
            if hit.is_file():
                return hit
    return None


def _first(entry: dict, keys) -> str:
    for k in keys:
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _blocks(l5: dict) -> List[dict]:
    for k in _BLOCK_LIST_KEYS:
        v = l5.get(k)
        if isinstance(v, list):
            return [e for e in v if isinstance(e, dict)]
    return []


def _declares_no_analog(l5: dict) -> bool:
    """L5's own positive assertion that the design has no analog content."""
    if l5.get("no_analog") is True:
        return True
    if l5.get("analog_blocks_detected") is False:
        return True
    return False


def _spec_has_content(entry: dict) -> bool:
    """True when the block carries spec CONTENT of any shape.

    Distinguishes "L5 said nothing" (honest silence) from "L5 said
    something the consumer cannot parse" (the defect)."""
    spec = entry.get("spec")
    if isinstance(spec, str) and spec.strip():
        return True
    if isinstance(spec, dict) and spec:
        return True
    if isinstance(spec, list) and spec:
        return True
    for k in ("specs", "targets", "requirements", "electrical_specs"):
        v = entry.get(k)
        if isinstance(v, (list, dict)) and v:
            return True
    return False


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
    """Return a structured verdict dict. Never raises on bad input."""
    out: Dict[str, Any] = {
        "gate": "l5_analog_block_spec_actionable_check",
        "verdict": "SKIP",
        "reason": "",
        "blocks_total": 0,
        "blocks_actionable": 0,
        "failures": [],
        "warnings": [],
    }

    l5p = _find_l5(project)
    if l5p is None:
        out["reason"] = "no L5_ADI_SPEC.json"
        return out
    try:
        l5 = json.loads(l5p.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        out["verdict"] = "FAIL"
        out["reason"] = f"L5 is not parseable JSON: {exc}"
        out["failures"] = [out["reason"]]
        return out
    if not isinstance(l5, dict):
        out["verdict"] = "FAIL"
        out["reason"] = "L5 top level is not an object"
        out["failures"] = [out["reason"]]
        return out

    blocks = _blocks(l5)
    if not blocks:
        out["reason"] = (
            "L5 declares no analog_blocks[] "
            f"(no_analog={l5.get('no_analog')!r}, "
            f"analog_blocks_detected={l5.get('analog_blocks_detected')!r}) "
            "— the analog-digital interface layer is legitimately empty "
            "for a pure-digital design")
        return out
    if _declares_no_analog(l5) and not blocks:
        out["reason"] = "L5 positively declares no analog content"
        return out

    ars, err = _load_consumer()
    if ars is None:
        out["reason"] = f"consumer unavailable — cannot state contract ({err})"
        return out
    known_types = _consumer_known_types(ars)

    out["blocks_total"] = len(blocks)
    failures: List[str] = []
    warnings: List[str] = []
    actionable = 0

    for idx, entry in enumerate(blocks):
        name = _first(entry, _NAME_KEYS)
        label = name or f"analog_blocks[{idx}]"

        # R1 — name
        if not name:
            failures.append(
                f"{label}: no name — every consumer "
                "(analog_one_shot_runner, _pick_block_type, "
                "l5_block_specs) looks the block up by name; an unnamed "
                "entry is unreachable")
            continue

        # R2 — type / deck selector
        btype = _first(entry, _TYPE_KEYS)
        if not btype:
            failures.append(
                f"{label}: no type/topology — "
                "analog_real_corner_sweep._pick_block_type() falls back "
                f"to name-as-type ('{name}'), and the consumer has no "
                "deck for it, so the block is listed but never simulated")
            continue
        if known_types and btype.lower() not in known_types:
            failures.append(
                f"{label}: type='{btype}' has no deck in the consumer's "
                f"own table (known: {len(known_types)} types) — "
                "_pick_block_type returns it but analog_real_corner_sweep "
                "cannot build a testbench, so A4 silently produces no "
                "graded measurement")
            continue

        # R3 — actionable spec, decided by the CONSUMER'S OWN parser.
        try:
            parsed = ars.l5_block_specs(str(project), name, btype)
        except Exception as exc:  # pragma: no cover - defensive
            failures.append(
                f"{label}: consumer parser l5_block_specs() raised "
                f"{type(exc).__name__}: {exc}")
            continue

        if parsed:
            actionable += 1
            continue

        # Nothing parsed. Honest silence vs unparseable content.
        if not _spec_has_content(entry):
            if entry.get("low_confidence") is True:
                warnings.append(
                    f"{label} (type={btype}): no spec declared and L5 "
                    "marks it low_confidence — honest extraction gap, "
                    "not a typing defect; A4 will grade against the "
                    "generic default for this type")
                continue
            if _target_is_informational(ars, btype.lower()):
                failures.append(
                    f"{label} (type={btype}): no spec declared, and the "
                    "consumer's static TARGETS row for this type has "
                    "target=None — every A4 measurement for this block "
                    "will be stamped PASS_INFORMATIONAL, i.e. the block "
                    "is swept but NEVER graded. L5 must supply "
                    "spec.specs[] with a numeric target/min/max")
                continue
            failures.append(
                f"{label} (type={btype}): no spec declared — A4 will "
                "grade against the generic static default for this "
                "type, not against this design")
            continue

        failures.append(
            f"{label} (type={btype}): spec content IS present but "
            f"l5_block_specs() — the consumer's own parser — returns "
            f"nothing from it (spec is a "
            f"{type(entry.get('spec')).__name__}, not a dict carrying "
            "specs[] with a numeric target/min/max). The requirement is "
            "in the layer but not in the form the layer's consumer "
            "reads, so A4 falls back to a generic default")

    out["blocks_actionable"] = actionable
    out["failures"] = failures
    out["warnings"] = warnings
    if failures:
        out["verdict"] = "FAIL"
        out["reason"] = (
            f"{len(failures)}/{len(blocks)} analog block(s) are not "
            "actionable by their A-track consumers")
    else:
        out["verdict"] = "PASS"
        out["reason"] = (
            f"{actionable}/{len(blocks)} analog block(s) yield a "
            "numerically-bounded spec through the consumer's own parser"
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
        print("[SKIP] l5_analog_block_spec_actionable_check: "
              f"project dir not found: {project}")
        return 2

    # IC-class guard (best effort — a detector failure must not fabricate
    # a verdict, so we simply continue with the structural check).
    try:
        from ic_class_profile import detect_ic_class  # noqa: E402
        ic_class = detect_ic_class(project).get("ic_class", "unknown")
    except Exception:
        ic_class = "unknown"
    if ic_class in _SKIP_CLASSES:
        print("[SKIP] l5_analog_block_spec_actionable_check: "
              f"ic_class={ic_class} (no analog-digital interface layer)")
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
        print(f"[WARN] l5_analog_block_spec_actionable_check: {w}")

    if res["verdict"] == "SKIP":
        print("[SKIP] l5_analog_block_spec_actionable_check: "
              f"{res['reason']}")
        return 2
    if res["verdict"] == "PASS":
        print("[PASS] l5_analog_block_spec_actionable_check: "
              f"{res['reason']}")
        return 0

    waived, rationale = _waived(project)
    if waived:
        print("[PASS] l5_analog_block_spec_actionable_check: waived by "
              f"waivers.{WAIVER_KEY} ({len(res['failures'])} suppressed): "
              f"{rationale[:70]}…")
        for f in res["failures"][:6]:
            print(f"  • {f}")
        return 0

    print("[FAIL] l5_analog_block_spec_actionable_check: " + res["reason"])
    for f in res["failures"][:8]:
        print(f"  • {f}")
    print()
    print("  Fix by typing the block's own declared numbers into "
          "L5.analog_blocks[].spec as:")
    print('    "spec": {"specs": [{"name": "Vout", "target": <num>, '
          '"unit": "V"}, ...]}')
    print("  (Do NOT invent a number the input does not state — if the "
          "input is silent, say so with low_confidence: true.)")
    print(f"  Or document the alternative in waivers.json under "
          f'"{WAIVER_KEY}" (>={WAIVER_MIN_LEN} chars).')
    return 1


if __name__ == "__main__":
    sys.exit(main())
