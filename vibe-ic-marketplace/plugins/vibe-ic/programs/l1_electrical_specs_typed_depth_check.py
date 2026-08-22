#!/usr/bin/env python3
"""
l1_electrical_specs_typed_depth_check.py — Wave 38 / B1

Audit-driven typed sub-field depth gate. Closes the residual ~70
missed items category surfaced in
``docs/design/PHASE2A_FULL_AUDIT_v0119.67.md`` (line 75–77):
electrical limits (V/I/T) are usually captured as free-form strings
inside L1.description, never as typed min/typ/max/unit/conditions
records that spec-to-rtl, lab-calibration and analog-spec-extract
can lookup.

Trigger: when extracted vendor docs contain an electrical mention
(see ``_electrical_mention``) or the L1 doc has an
``electrical_specs``-shaped field of any depth.

Required typed shape (any of these aliases): ``electrical_specs``,
``electrical_limits``, ``electrical_characteristics``,
``operating_conditions``, ``dc_specs``, ``absolute_max_ratings``.
Each entry MUST have at least ``name`` + ``unit`` + one of
{``min``, ``typ``, ``max``, ``min_typ_max``} + ``evidence``
(``<file>:<line>``).

v1.7.80 — for #514. The gate ALSO falsifies L1's positive claim
``no_electrical_specs_in_input``. That field asserts something about
the INPUT; nothing checked it, so it read identically whether the
input was empty or the extractor was. Empty entries now split three
ways:

  * mentions found, L1 declares none      -> FAIL (the claim is false)
  * mentions found, L1 makes no claim     -> FAIL (unextracted)
  * no mentions, L1 declares none         -> PASS (corroborated: two
                                             independent scans agree)

The gate is chip-AGNOSTIC: only the schema depth and the input/claim
agreement are enforced, never specific voltage/current values.

Usage:
    python3 l1_electrical_specs_typed_depth_check.py <project_dir>

Exit codes:
    0 = PASS (typed sub-field depth OK, OR a corroborated "the input
        has no electrical specs")
    1 = FAIL (electrical mentions present but no/shallow typed
        entries, or L1 falsely claims the input has none)
    2 = input-missing / nothing to validate and nothing to falsify

Honors waiver ``l1_electrical_specs_depth_intentional`` (>=40 chars).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ic_class_profile import detect_ic_class  # noqa: E402
from _electrical_mention import (  # noqa: E402
    search_line as _elec_search_line,
)


# Wave 43 (v0.119.75) — explicit ic_class_profile guard.
# L1 electrical_specs are MANDATORY for digital / mixed-signal /
# AID-class digital ICs. Pure-analog blocks have their own A1-A8
# analog-spec deck (different shape, different units), so this gate
# becomes noise on a pure-analog project.
_SKIP_CLASSES = ("pure_analog",)


_DOC_GLOBS = (
    "**/input_doc/*.txt",
    "**/input/docs/*.txt",
    "**/input/input_doc/*.txt",
)

_L1_GLOBS = (
    "phase1/generated_docs/L1_DATASHEET.json",
    "phase1/generated_docs/L1*.json",
    "**/L1_DATASHEET.json",
)

# v1.7.80 — for #514. `_RE_ELEC` used to be defined here. Every
# mention it reported on `benchmark-data/ic/ibex` was a false
# positive: `VOL` matched inside "Volume" (the alternation had a
# leading \b and no trailing one) and `2v` inside the tool name
# "sv2v" (the quantity branch had no left boundary). The gate was
# therefore FAILing a CPU core whose documents contain no electrical
# quantity at all, while a design with four invented amperes passed.
# The definition now lives in `_electrical_mention`, shared with the
# L1 emitter whose claim this gate exists to falsify.

_SPEC_KEYS = (
    "electrical_specs", "electrical_limits",
    "electrical_characteristics", "operating_conditions",
    "dc_specs", "absolute_max_ratings", "ac_specs",
)

_REQUIRED_VALUE_KEYS = ("min", "typ", "max", "min_typ_max",
                         "value", "nominal", "limit")
_REQUIRED_NAME_KEYS = ("name", "param", "parameter", "symbol")
_REQUIRED_UNIT_KEYS = ("unit", "units")
_REQUIRED_EVIDENCE_KEYS = ("evidence", "evidence_path", "source")


def _find_l1(project: Path) -> Optional[Path]:
    for pat in _L1_GLOBS:
        for hit in project.glob(pat):
            if hit.is_file():
                return hit
    return None


def _scan_docs(project: Path) -> List[Tuple[Path, int, str]]:
    """Return ``[(doc, line_number, matched_literal), ...]``.

    v1.7.80 — for #514. The matched literal is carried so a FAIL can
    QUOTE its evidence. The old message said "16 electrical
    mention(s) (e.g. ibex_compliance.txt:7)" and every one of them was
    the word "Volume" or the tool name "sv2v"; had the literal been
    printed, the false positive would have been visible from the
    gate's own output instead of requiring an investigation.
    """
    hits: List[Tuple[Path, int, str]] = []
    seen = set()
    for pat in _DOC_GLOBS:
        for doc in project.glob(pat):
            if not doc.is_file() or doc in seen:
                continue
            seen.add(doc)
            try:
                text = doc.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                m = _elec_search_line(line)
                if m:
                    hits.append((doc, i, m.group(0)))
                    if len(hits) >= 50:
                        return hits
    return hits


def _collect_spec_entries(node, out: List[dict]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _SPEC_KEYS and isinstance(v, list):
                for it in v:
                    if isinstance(it, dict):
                        out.append(it)
            else:
                _collect_spec_entries(v, out)
    elif isinstance(node, list):
        for it in node:
            _collect_spec_entries(it, out)


def _entry_typed_ok(entry: dict) -> Tuple[bool, str]:
    has_name = any(k in entry for k in _REQUIRED_NAME_KEYS)
    has_value = any(k in entry for k in _REQUIRED_VALUE_KEYS)
    has_unit = any(k in entry for k in _REQUIRED_UNIT_KEYS)
    has_evidence = any(k in entry for k in _REQUIRED_EVIDENCE_KEYS)
    missing: List[str] = []
    if not has_name:
        missing.append("name")
    if not has_value:
        missing.append("min/typ/max/value")
    if not has_unit:
        missing.append("unit")
    if not has_evidence:
        missing.append("evidence")
    return (not missing, ",".join(missing))


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: l1_electrical_specs_typed_depth_check <project_dir>",
              file=sys.stderr)
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        return 2

    profile = detect_ic_class(project)
    ic_class = profile.get("ic_class", "unknown")
    if ic_class in _SKIP_CLASSES:
        print(f"[SKIP] l1_electrical_specs_typed_depth_check: "
              f"ic_class={ic_class} (analog blocks carry their own "
              f"A1-A8 spec deck, not L1.electrical_specs[])")
        return 2

    hits = _scan_docs(project)
    l1 = _find_l1(project)
    if not hits and l1 is None:
        print("[SKIP] l1_electrical_specs_typed_depth_check: "
              "no electrical mention in docs and no L1 to inspect")
        return 2

    if l1 is None:
        print(f"[FAIL] l1_electrical_specs_typed_depth_check: "
              f"{len(hits)} electrical mention(s) in extracted docs "
              f"but L1_DATASHEET.json missing")
        return 1

    try:
        data = json.loads(l1.read_text())
    except Exception as exc:
        print(f"[FAIL] l1_electrical_specs_typed_depth_check: "
              f"cannot parse {l1.relative_to(project)}: {exc}")
        return 1

    entries: List[dict] = []
    _collect_spec_entries(data, entries)

    if not entries:
        # v1.7.80 — for #514. L1 publishes a POSITIVE claim about the
        # input, `no_electrical_specs_in_input`. This gate is the only
        # thing that can falsify it, so check it rather than ignoring
        # it: an unchecked claim about the input is indistinguishable
        # from "the extractor returned nothing", which is what the
        # field meant before it was corroborated.
        declares_none = data.get("no_electrical_specs_in_input") is True
        if hits:
            if declares_none:
                print(f"[FAIL] l1_electrical_specs_typed_depth_check: "
                      f"L1 declares no_electrical_specs_in_input=true but "
                      f"the input carries {len(hits)} electrical "
                      f"mention(s) (e.g. {hits[0][0].name}:{hits[0][1]} "
                      f"{hits[0][2]!r}). That is a false claim about the "
                      f"input, not a missing value: either extract typed "
                      f"entries or set the flag false and list the "
                      f"mentions under "
                      f"electrical_specs_unextracted_mentions[].")
                return 1
            print(f"[FAIL] l1_electrical_specs_typed_depth_check: "
                  f"{len(hits)} electrical mention(s) (e.g. "
                  f"{hits[0][0].name}:{hits[0][1]} {hits[0][2]!r}) but L1 "
                  f"has no typed electrical_specs[] / electrical_limits[] "
                  f"/ electrical_characteristics[] array. Add typed "
                  f"entries with name/min_typ_max/unit/conditions/evidence.")
            return 1
        if declares_none:
            # No entries, no mentions, and L1 says so. Two independent
            # scans agree the input carries nothing electrical: that is
            # a verified negative, not an absence of information.
            print("[PASS] l1_electrical_specs_typed_depth_check: L1 "
                  "declares no_electrical_specs_in_input=true and an "
                  "independent scan of the input agrees (0 electrical "
                  "mentions) — corroborated, not merely unextracted")
            return 0
        # No mentions, no entries, and no claim either way => nothing
        # to validate and nothing to falsify.
        print("[SKIP] l1_electrical_specs_typed_depth_check: "
              "no electrical entries to validate")
        return 2

    bad: List[str] = []
    for i, e in enumerate(entries):
        ok, miss = _entry_typed_ok(e)
        if not ok:
            label = (e.get("name") or e.get("param")
                     or e.get("symbol") or f"entry[{i}]")
            bad.append(f"{label}: missing {miss}")
    if bad:
        print(f"[FAIL] l1_electrical_specs_typed_depth_check: "
              f"{len(bad)}/{len(entries)} entries are too shallow. "
              f"Examples: {'; '.join(bad[:5])}")
        return 1

    print(f"[PASS] l1_electrical_specs_typed_depth_check: "
          f"{len(entries)} typed electrical entries with "
          f"name/min_typ_max/unit/evidence")
    return 0


if __name__ == "__main__":
    sys.exit(main())
