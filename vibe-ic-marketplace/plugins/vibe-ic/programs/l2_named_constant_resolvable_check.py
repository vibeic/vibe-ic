#!/usr/bin/env python3
"""l2_named_constant_resolvable_check.py — L2 consumer-contract gate.

VERDICT SEMANTICS: **BLOCKS** (exit 1 on FAIL).
------------------------------------------------------------------
Why blocking and not advisory: both known dereference paths into L2
FAIL SILENTLY when the constant is absent, which is worse than a hard
stop. `l8_frame_end_gap_derivation_check` reads `l2.get("ibt_us")` and,
when it is missing, records `skipped_reason` and returns PASS — the
derivation it exists to enforce is simply not performed.
`l9_response_delay_schema_check` checks only that the FIELD
`response_delay.spec_constant` exists; it never resolves the name that
field points at, so an L9 that names a constant L2 does not contain
still passes. Downstream, spec-to-RTL has no numeric delay to code and
the RTL is authored against a hole. An advisory verdict here would
reproduce exactly the documented failure where a layer gate said FAIL
and the flow continued anyway. So: FAIL => rc 1.

The principle it embodies
------------------------------------------------------------------
A layer is complete when the requirement is present IN THE LAYER THAT
CONSUMES IT, IN AN ACTIONABLE FORM — not when a token appears
somewhere.

The pre-existing `l2_timing_completeness_check` is the right SHAPE (it
closed the "no keys = silent pass" hole in `frs_timing_range_check` by
cross-checking input/docs evidence against L2) but it verifies key
PRESENCE ONLY: "does L2 contain at least one `*_us` leaf or a
non-empty `timing_parameters` container". It cannot tell that L2 has
ten timing keys and yet is missing THE ONE constant a sibling L-doc
dereferences by name — the direct analogue of the motivating defect,
where a supply pin appeared 7x in L1 and 8x in L2 but 0x in the layer
the backend actually consumed.

Two limbs, both derived, nothing hardcoded
------------------------------------------------------------------
LIMB 1 — cross-layer named references must RESOLVE.
  The set of required constant names is derived from the design's OWN
  sibling L-docs in the same generated_docs/ directory. No name is
  written into this file. Two machine-readable reference shapes are
  recognised, and only structured ones:

    (a) a key named `spec_constant` / `*_spec_constant` / `l2_constant`
        / `l2_ref` whose value is a bare identifier string. This is
        the shape `l9_response_delay_schema_check` mandates:
            response_delay: {spec_constant: <name-from-L2>, ...}
    (b) any string value that is EXACTLY `L2.<ident>` / `L2_FRS.<ident>`
        / `L2:<ident>` (whole-string match, anchored).

  Whole-string anchoring in (b) is load-bearing. Measured on 26 real
  Phase-1 runs, every L3_CMD_PROTOCOL.json contains the PROSE sentence
  "L2.protocol_overview.half_duplex is not True and no explicit
  opcode ... was found", where `L2.protocol_overview` is legitimately
  null under `no_protocol_overview_in_input: true`. An unanchored
  regex treats that sentence as a reference and false-positives on
  100% of runs. It was measured, and narrowed.

  Resolution walks L2 for a key equal to the name, and also matches
  record-list entries by their `name` / `parameter` field — the real
  emitted L2 shape is
      timing_parameters: [{name, parameter, value, unit, evidence}, ...]
  A name that resolves only to null, to prose, or to an empty
  container is NOT resolved: the consumer needs a number.

LIMB 2 — every timing record L2 does carry must be actionable.
  `frs_timing_range_check`, `tx_bit_timing_units_check` and
  design_one_shot_runner all read a record's numeric value. A record
  present with a prose or null value is the same present-but-
  unactionable defect one field over. Only records that L2 itself
  publishes are examined, so this limb is design-agnostic.

Verdicts
------------------------------------------------------------------
  PASS         every derived reference resolves to a concrete number
               and every published timing record carries one
  VACUOUS_PASS no sibling L-doc references L2 by name and L2 publishes
               no timing records
  FAIL         a referenced name is absent / non-numeric in L2, or a
               published timing record has no numeric value
  rc 2         L2 absent / unparseable / project dir absent

Waiver: `waivers.json` key `l2_named_constant_externalized` (>= 40
chars) downgrades FAIL to PASS_WITH_WAIVER — for designs that
genuinely keep the constant in L8/L11 only.

Usage:
    python3 l2_named_constant_resolvable_check.py <project_dir> [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _path_layout as _pl  # noqa: E402

GATE = "l2_named_constant_resolvable_check"
WAIVER_KEY = "l2_named_constant_externalized"
WAIVER_MIN_LEN = 40

# (a) structured reference keys whose VALUE names an L2 constant.
_REF_KEY = re.compile(
    r"^(?:.*_)?(?:spec_constant|l2_constant|l2_ref|l2_key|"
    r"spec_constant_name)$", re.I)
# (b) whole-string dotted reference: `L2.foo`, `L2_FRS:foo`.
_DOTTED_REF = re.compile(r"^\s*L2(?:_FRS)?\s*[.:]\s*([A-Za-z_]\w*)\s*$", re.I)
# A bare identifier — a reference value that is a sentence is prose.
_IDENT = re.compile(r"^[A-Za-z_]\w{0,63}$")

# Fields inside a record-list entry that carry the record's name.
_RECORD_NAME_KEYS = ("name", "parameter", "param", "key", "id", "constant")
# Fields that can carry a record's concrete value.
_RECORD_VALUE_KEYS = ("value", "typ", "typical", "nominal", "nom",
                      "min", "max", "val")
_NUMERIC_STR = re.compile(r"^\s*[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?\s*$")


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _has_concrete_number(v: Any, depth: int = 0) -> bool:
    """True iff `v` yields a number a consumer can compute with."""
    if depth > 6:
        return False
    if _is_number(v):
        return True
    if isinstance(v, str):
        return bool(_NUMERIC_STR.match(v))
    if isinstance(v, list):
        return any(_has_concrete_number(x, depth + 1) for x in v)
    if isinstance(v, dict):
        for k in _RECORD_VALUE_KEYS:
            if k in v and _has_concrete_number(v[k], depth + 1):
                return True
    return False


# ----------------------------------------------------------------- refs
def _walk(node: Any, out: List[Tuple[str, str]], depth: int = 0) -> None:
    """Collect (referenced_name, how_it_was_found) from one L-doc."""
    if depth > 24:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str):
                if _REF_KEY.match(str(k)) and _IDENT.match(v.strip()):
                    out.append((v.strip(), f"key `{k}`"))
                m = _DOTTED_REF.match(v)
                if m:
                    out.append((m.group(1), f"dotted ref in `{k}`"))
            else:
                _walk(v, out, depth + 1)
    elif isinstance(node, list):
        for it in node:
            _walk(it, out, depth + 1)


def derive_required_names(gen_dir: Path) -> Dict[str, List[str]]:
    """Names sibling L-docs dereference in L2 -> list of citing docs."""
    required: Dict[str, List[str]] = {}
    if not gen_dir.is_dir():
        return required
    for path in sorted(gen_dir.glob("L*.json")):
        if path.name.startswith("L2_"):
            continue                     # L2 does not cite itself
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        found: List[Tuple[str, str]] = []
        _walk(doc, found)
        for name, how in found:
            required.setdefault(name, []).append(f"{path.name} ({how})")
    return required


# ------------------------------------------------------------ resolution
def resolve_in_l2(l2: Any, name: str, depth: int = 0) -> Optional[bool]:
    """None if the name is absent; True/False = resolves to a number.

    Matches a dict KEY equal to `name`, or a record-list entry whose
    name/parameter field equals `name` (the emitted L2 record shape).
    """
    if depth > 24:
        return None
    seen_but_unresolved = False
    if isinstance(l2, dict):
        for k, v in l2.items():
            if str(k).lower() == name.lower():
                if _has_concrete_number(v):
                    return True
                seen_but_unresolved = True
            sub = resolve_in_l2(v, name, depth + 1)
            if sub is True:
                return True
            if sub is False:
                seen_but_unresolved = True
    elif isinstance(l2, list):
        for item in l2:
            if isinstance(item, dict):
                labels = {str(item.get(k)).lower()
                          for k in _RECORD_NAME_KEYS if item.get(k) is not None}
                if name.lower() in labels:
                    if any(_has_concrete_number(item.get(k))
                           for k in _RECORD_VALUE_KEYS):
                        return True
                    seen_but_unresolved = True
            sub = resolve_in_l2(item, name, depth + 1)
            if sub is True:
                return True
            if sub is False:
                seen_but_unresolved = True
    return False if seen_but_unresolved else None


def collect_timing_records(l2: Any, depth: int = 0) -> List[Tuple[str, Any]]:
    """Published timing records: (label, entry) for list-of-dict blocks."""
    out: List[Tuple[str, Any]] = []
    if depth > 12:
        return out
    if isinstance(l2, dict):
        for k, v in l2.items():
            kl = str(k).lower()
            if ("timing" in kl or "timeout" in kl) and isinstance(v, list):
                for entry in v:
                    if isinstance(entry, dict) and any(
                            entry.get(nk) for nk in _RECORD_NAME_KEYS):
                        label = next(str(entry[nk]) for nk in _RECORD_NAME_KEYS
                                     if entry.get(nk))
                        out.append((f"{k}.{label}", entry))
            elif isinstance(v, (dict, list)):
                out.extend(collect_timing_records(v, depth + 1))
    elif isinstance(l2, list):
        for item in l2:
            out.extend(collect_timing_records(item, depth + 1))
    return out


def _waived(project: Path) -> bool:
    p = project / "waivers.json"
    if not p.is_file():
        return False
    try:
        v = json.loads(p.read_text()).get(WAIVER_KEY, "")
    except Exception:
        return False
    return isinstance(v, str) and len(v.strip()) >= WAIVER_MIN_LEN


def evaluate(project: Path) -> Dict[str, Any]:
    gen_dir = _pl.generated_docs_dir(project)
    l2_path = gen_dir / "L2_FRS.json"
    if not l2_path.is_file():
        return {"gate": GATE, "verdict": "SILENT_SKIP", "rc": 2,
                "reason": f"{l2_path.name} not found (phase1 hasn't run?)"}
    try:
        l2 = json.loads(l2_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"gate": GATE, "verdict": "ERROR", "rc": 2,
                "reason": f"cannot parse {l2_path.name}: {exc}"}

    required = derive_required_names(gen_dir)
    unresolved: List[Dict[str, Any]] = []
    for name, citers in sorted(required.items()):
        state = resolve_in_l2(l2, name)
        if state is not True:
            unresolved.append({
                "constant": name,
                "kind": ("absent_from_l2" if state is None
                         else "present_but_not_numeric"),
                "referenced_by": citers[:4],
                "detail": (
                    f"`{name}` is dereferenced by name from "
                    f"{citers[0]} but "
                    + ("does not appear in L2_FRS.json at all"
                       if state is None else
                       "resolves only to a null/prose value in L2_FRS.json")
                    + " — the consumer has no number to compute with."),
            })

    records = collect_timing_records(l2)
    unactionable: List[Dict[str, Any]] = []
    for label, entry in records:
        if not any(_has_concrete_number(entry.get(k))
                   for k in _RECORD_VALUE_KEYS):
            unactionable.append({
                "record": label, "kind": "timing_record_no_numeric_value",
                "value": entry.get("value"),
                "detail": (
                    f"L2 publishes timing record `{label}` but its value is "
                    f"{entry.get('value')!r} — not a number the range/unit "
                    f"consumers can dereference."),
            })

    report: Dict[str, Any] = {
        "gate": GATE,
        "required_constants": len(required),
        "timing_records": len(records),
        "unresolved_constants": unresolved,
        "unactionable_records": unactionable,
    }
    violations = len(unresolved) + len(unactionable)
    if violations == 0:
        if not required and not records:
            report.update(verdict="VACUOUS_PASS", rc=0, reason=(
                "no sibling L-doc dereferences an L2 constant by name and "
                "L2 publishes no timing records — nothing to assert."))
        else:
            report.update(verdict="PASS", rc=0, reason=(
                f"{len(required)} cross-layer named reference(s) resolve to "
                f"concrete numbers; {len(records)} published timing "
                f"record(s) carry numeric values."))
        return report
    if _waived(project):
        report.update(verdict="PASS_WITH_WAIVER", rc=0, reason=(
            f"{violations} L2 resolution violation(s) waived via "
            f"waivers.json:{WAIVER_KEY}."))
        return report
    report.update(verdict="FAIL", rc=1, reason=(
        f"{len(unresolved)} named constant(s) dereferenced by a sibling "
        f"L-doc do not resolve to a number in L2, and "
        f"{len(unactionable)} published timing record(s) carry no numeric "
        f"value."))
    return report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog=GATE, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="write JSON verdict here")
    args = ap.parse_args(argv)

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    report = evaluate(project)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")

    rc = int(report.get("rc", 2))
    line = f"{report['verdict']}: {report['reason']}"
    if rc == 1:
        print(f"FAIL: {report['reason']}", file=sys.stderr)
        for v in (report["unresolved_constants"]
                  + report["unactionable_records"])[:8]:
            print(f"  - {v['detail']}", file=sys.stderr)
    elif rc == 2:
        print(line, file=sys.stderr)
    else:
        print(line)
    return rc


if __name__ == "__main__":
    sys.exit(main())
