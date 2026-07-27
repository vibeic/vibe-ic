#!/usr/bin/env python3
"""adder_map_techmap.py — make a DECLARED adder techmap actually bind, and
never claim it bound without evidence from yosys's own log.

WHY THIS EXISTS
===============
Phase-3 ingests a design's staged reference-flow ``ADDER_MAP_FILE`` knob and
emits ``techmap -map <staged>`` so the design's OWN declared adder architecture
replaces the generic default. Two defects in that as-shipped behaviour, both
reproduced against the real flow:

1. **A map that targets ``$lcu`` can never match, and fails SILENTLY.**
   ``techmap`` only rewrites cells that already exist in the design. After
   ``alumacc`` the arithmetic is ``$alu`` / ``$macc`` / ``$add``; ``$lcu`` (the
   carry-lookahead unit that every parallel-prefix map keys on, including
   yosys's own ``+/choices/*.v``) does not exist yet — it is produced by
   ``+/techmap.v``'s own ``$alu`` expansion. So ``techmap -map <lcu-map>``
   alone rewrites nothing, the later generic ``synth`` lowers the arithmetic
   with the DEFAULT map, and the design ships an architecture it did not ask
   for. Measured on a 32-bit multi-operand datapath: the declared Kogge-Stone
   map produced ``_90_lcu_brent_kung`` (the default) and an area within 0.04%
   of applying no map at all, while the correct recipe produced
   ``_80_lcu_kogge_stone``.

   The fix is yosys's documented ordering: the choice map and ``+/techmap.v``
   must be in the SAME ``techmap`` call with the choice map FIRST, so ``$alu``
   lowers to ``$lcu`` and the choice map matches it in the same fixpoint.

2. **The run CLAIMED the map was applied without checking.** The provenance
   note was emitted from "the file was staged", not from "yosys used it", so a
   no-op was reported as an adopted knob. A knob that silently does nothing is
   worse than one that is skipped loudly.

This module is pure text/logic (no I/O, no container calls) so it is unit
testable against real yosys map files and real yosys logs.

chip-AGNOSTIC: every rule keys on yosys's own vocabulary (the
``techmap_celltype`` attribute, the ``Using template ...`` log line). No
vendor / PDK / design / width literal appears anywhere.
"""
from __future__ import annotations

import re
from typing import List, Sequence, Set, Tuple

TOOL = "adder_map_techmap"

# yosys's base techmap library — the map that lowers coarse RTL cells and, in
# doing so, is what CREATES the intermediate cells listed below.
BASE_TECHMAP = "+/techmap.v"

# Cell types that NO front-end pass produces directly: they exist only as an
# intermediate of another cell's techmap expansion. A map keyed on one of these
# cannot match unless the rule that PRODUCES it runs in the SAME techmap call,
# because `techmap` iterates to a fixpoint only over the maps given together.
#
# `$lcu` (carry-lookahead unit) is the one that matters for adder architecture:
# `alumacc` emits `$alu`, and it is the `$alu` rule that emits the `$lcu` every
# parallel-prefix map keys on. `$alu`/`$add`/`$sub`/`$macc` come from the front
# end and need no such help.
#
# Maps intermediate celltype -> the celltype whose expansion produces it. A map
# that declares BOTH is self-sufficient and must NOT have the base map appended
# (yosys's own `+/techmap.v` is exactly that case: it declares `$lcu` and the
# `$alu` rule that creates it).
LOWERED_ONLY_PRODUCERS: dict = {"$lcu": "$alu"}
LOWERED_ONLY_CELLTYPES: Set[str] = set(LOWERED_ONLY_PRODUCERS)

_CELLTYPE_ATTR_RE = re.compile(
    r"""\(\*[^*]*?techmap_celltype\s*=\s*"([^"]*)"[^*]*?\*\)""",
    re.IGNORECASE | re.DOTALL)
_MODULE_RE = re.compile(r"^\s*module\s+\\?([A-Za-z_][A-Za-z0-9_$]*)", re.MULTILINE)
# yosys announces every map module it actually instantiates. The module name is
# either bare or wrapped in a `$paramod\<name>\<PARAM>=<value>` specialisation.
_USING_TEMPLATE_RE = re.compile(
    r"^Using template\s+(\S+)\s+for cells of type\s+(\S+)\.", re.MULTILINE)


def declared_celltypes(map_text: str) -> Set[str]:
    """Every cell type the map file declares it rewrites, via yosys's
    ``(* techmap_celltype = "..." *)`` attribute. One attribute may list several
    space-separated types. Returns an empty set for a map that declares none
    (such a map matches by MODULE NAME instead, e.g. ``_90_alu``)."""
    out: Set[str] = set()
    for raw in _CELLTYPE_ATTR_RE.findall(map_text or ""):
        for tok in raw.split():
            tok = tok.strip()
            if tok:
                out.add(tok)
    return out


def map_module_names(map_text: str) -> List[str]:
    """The module names the map file defines, in declaration order. These are
    what yosys names in its ``Using template ...`` log line, so they are the
    evidence handle for `verify_map_applied`."""
    return _MODULE_RE.findall(map_text or "")


def needs_base_techmap(map_text: str) -> bool:
    """True when the map keys on a cell type that does not exist yet at the
    point the map runs, AND the map does not itself carry the rule that would
    create it — in which case the map MUST be combined with the base techmap in
    one call or it silently matches nothing.

    A map that declares both the intermediate and its producer (yosys's own
    ``+/techmap.v`` declares ``$lcu`` and the ``$alu`` rule that emits it) is
    self-sufficient and gets no base map appended."""
    declared = declared_celltypes(map_text)
    for intermediate, producer in LOWERED_ONLY_PRODUCERS.items():
        if intermediate in declared and producer not in declared:
            return True
    return False


def build_adder_map_step(staged_map_path: str, map_text: str) -> str:
    """The single yosys ``techmap`` command that applies a staged adder map.

    ``staged_map_path`` is used verbatim (the caller has already translated
    host -> container). The staged map always comes FIRST so it wins over the
    base map for any cell both could rewrite.
    """
    if not staged_map_path:
        raise ValueError("staged_map_path is required")
    if needs_base_techmap(map_text):
        return f"techmap -map {staged_map_path} -map {BASE_TECHMAP}"
    return f"techmap -map {staged_map_path}"


def templates_used(log_text: str) -> List[Tuple[str, str]]:
    """Every (template, celltype) pair yosys reported instantiating, read from
    its ``Using template <t> for cells of type <c>.`` lines."""
    return _USING_TEMPLATE_RE.findall(log_text or "")


def _template_base_name(template: str) -> str:
    """Reduce a possibly-parameterised template handle to its module name.
    ``$paramod\\_80_lcu_kogge_stone\\WIDTH=32'0..0`` -> ``_80_lcu_kogge_stone``;
    a bare ``\\_90_alu`` -> ``_90_alu``."""
    t = template
    if t.startswith("$paramod"):
        # $paramod\<module>\<PARAM>=<value>  (module is the first \-segment)
        parts = t.split("\\")
        t = parts[1] if len(parts) > 1 else t
    return t.lstrip("\\$")


def verify_map_applied(log_text: str, map_text: str) -> Tuple[bool, str]:
    """Did yosys actually instantiate a module from the staged map?

    Returns ``(applied, reason)``. ``applied`` is True only on POSITIVE
    evidence — a ``Using template`` line naming one of the map's own modules.
    Absence of evidence is reported as NOT applied, never as success: the whole
    point is that a silent no-op must not be reported as an adopted knob.
    """
    wanted = set(map_module_names(map_text))
    if not wanted:
        return False, "staged map declares no module — nothing could be applied"
    used_pairs = templates_used(log_text)
    used = {_template_base_name(t) for t, _c in used_pairs}
    hit = sorted(wanted & used)
    if hit:
        return True, f"yosys instantiated {', '.join(hit)}"
    # Say WHAT was used instead — that is the actionable half of the report.
    if used:
        others = ", ".join(sorted(used))
        return False, (
            "staged map was NOT used; yosys instantiated "
            f"{others} instead (declared modules: {', '.join(sorted(wanted))})")
    return False, (
        "staged map was NOT used; yosys instantiated no map template at all "
        f"(declared modules: {', '.join(sorted(wanted))})")


def applied_note(map_name: str, applied: bool, reason: str) -> str:
    """The provenance line phase-3 writes for this knob. An unapplied map is
    reported as NOT APPLIED with the tool's own reason attached, so the run
    record can never claim a knob it did not turn."""
    if applied:
        return f"ADDER_MAP_FILE -> techmap -map ({map_name}) [APPLIED: {reason}]"
    return f"ADDER_MAP_FILE NOT APPLIED ({map_name}): {reason}"


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import json
    from pathlib import Path

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--map", required=True, help="the adder techmap .v file")
    ap.add_argument("--staged-path",
                    help="path to use in the emitted techmap command "
                         "(default: the --map path itself)")
    ap.add_argument("--log", help="a yosys log to VERIFY the map was applied")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)

    try:
        map_text = Path(a.map).read_text(errors="replace")
    except OSError as e:
        print(f"[{TOOL}] cannot read map: {e}")
        return 2

    res = {
        "map": a.map,
        "declared_celltypes": sorted(declared_celltypes(map_text)),
        "modules": map_module_names(map_text),
        "needs_base_techmap": needs_base_techmap(map_text),
        "techmap_step": build_adder_map_step(a.staged_path or a.map, map_text),
    }
    if a.log:
        try:
            log_text = Path(a.log).read_text(errors="replace")
        except OSError as e:
            print(f"[{TOOL}] cannot read log: {e}")
            return 2
        applied, reason = verify_map_applied(log_text, map_text)
        res["applied"] = applied
        res["reason"] = reason
        res["note"] = applied_note(Path(a.map).name, applied, reason)

    if a.json:
        print(json.dumps(res, indent=2))
    else:
        for k, v in res.items():
            print(f"{k}: {v}")
    if a.log and not res.get("applied"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
