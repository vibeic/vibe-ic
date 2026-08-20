#!/usr/bin/env python3
"""Yosys `stat` -> canonical area records. Parsing only, no policy.

WHAT THIS FILE IS ALLOWED TO DO
-------------------------------
Turn the text yosys prints into `vibeic.ppa.metric.v1` records. It holds no
threshold, decides no verdict, and — structurally, not by convention — cannot
emit a PHYSICAL metric: every record leaves through `area.proxy_record`, which
raises on a physical metric name. Adding a tool must never change a rule
(PPA_INTERFACES.md §4), and the cheapest way to guarantee that is to make the
rule unreachable from here.

WHAT YOSYS ACTUALLY PRINTS, taken from a real run
-------------------------------------------------
`/home/reyerchu/_c_cv_spm_run/phase2/stage2/synth/synth.log`, gf180mcuD, spm.
The GENERIC (pre-techmap) block, line 562:

    6.28. Printing statistics.

    === spm ===

            +----------Local Count, excluding submodules.
            |
          174 wires
          232 cells
           58   $_AND_

and the technology-MAPPED block after `abc`, line 699, which gains an area
column:

    === spm ===

            +----------Local Count, excluding submodules.
            |        +-Local Area, excluding submodules.
            |        |
          226        - wires
          252  4703.53 cells
           33 1.65E+03   DFFHQD1

       Chip area for module '\\spm': 4703.529600
         of which used for sequential elements: 1646.568000 (35.01%)

Three traps that are visible in those eleven lines:

1. THE TABLE'S AREA COLUMN IS ROUNDED. The cells row says `4703.53`; the
   `Chip area for module` line says `4703.529600`. They are the same quantity
   printed to different precision, and the digest of a record depends on which
   one was read. This parser takes the full-precision line and never the column.
   Per-cell-type areas are printed in the same lossy form (`1.65E+03` for what
   the summary shows as 1646.568) — so they are not summed to recover a total.

2. TWO SPELLINGS. Older yosys prints `Number of cells: N`; current yosys prints
   `N cells`. Both appear in the wild in this repository's own logs.

3. MORE THAN ONE MODULE. A hierarchical design prints one block per module and
   a `=== design hierarchy ===` roll-up. Which one is "the" area is a question
   this parser refuses to answer by guessing: without an explicit `top` it emits
   INVALID with a reason naming the candidates. A parser that picks the last
   block would silently report a leaf cell's area as the design's.

THE UNIT IS NOT um^2. `Chip area for module` is in whatever area unit the
liberty the synthesis script loaded declares. It is registered as
`lib_area_unit` for that reason, and `area.compare` refuses a cross-unit
comparison, so it can never be silently weighed against a DEF-derived um^2.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

if __package__ in (None, ""):  # pragma: no cover - executed as a script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from _ppa import area as _area  # type: ignore
    from _ppa import canonical_json as _cj  # type: ignore
else:
    from .. import area as _area
    from .. import canonical_json as _cj

__all__ = [
    "TOOL", "StatBlock", "HIERARCHY_BLOCK",
    "parse_stat_blocks", "select_block", "records_from_stat",
    "sha256_of_text",
]

TOOL = "yosys"

#: yosys prints this pseudo-module for the whole-design roll-up.
HIERARCHY_BLOCK = "design hierarchy"

_BLOCK_RE = re.compile(r"^===\s+(?P<name>.+?)\s+===\s*$", re.M)

# "      232 cells" / "      252  4703.53 cells"  (count first, current yosys)
_COUNT_NEW = r"^\s*(?P<n>[\d,]+)\s+(?:[\d.eE+-]+\s+)?{kw}\s*$"
# "   Number of cells:              232"          (older yosys)
_COUNT_OLD = r"^\s*Number of {kw}:\s*(?P<n>[\d,]+)\s*$"

_CHIP_AREA_RE = re.compile(
    r"^\s*Chip area for (?:module|top module)\s+'\\?(?P<mod>[^']*)':\s*"
    r"(?P<v>[-+0-9.eE]+)\s*$", re.M)
_SEQ_AREA_RE = re.compile(
    r"^\s*of which used for sequential elements:\s*(?P<v>[-+0-9.eE]+)", re.M)

_COUNT_KEYWORDS = {
    "wires": "wires",
    "wire_bits": "wire bits",
    "public_wires": "public wires",
    "public_wire_bits": "public wire bits",
    "ports": "ports",
    "port_bits": "port bits",
    "cells": "cells",
    "memories": "memories",
    "processes": "processes",
}


class StatBlock:
    """One `=== module ===` statistics block, parsed. Pure data."""

    __slots__ = ("module", "counts", "chip_area", "sequential_area", "text")

    def __init__(self, module: str, counts: Dict[str, Optional[int]],
                 chip_area: Optional[float], sequential_area: Optional[float],
                 text: str):
        self.module = module
        self.counts = counts
        self.chip_area = chip_area
        self.sequential_area = sequential_area
        self.text = text

    @property
    def is_hierarchy_rollup(self) -> bool:
        return self.module.strip().lower() == HIERARCHY_BLOCK

    @property
    def is_statistics(self) -> bool:
        """Whether this `=== ... ===` really is a statistics block.

        `===` banners are not exclusive to yosys `stat`: the real synthesis log
        this parser was written against contains

            === STAGED-MACRO vs BEHAVIOURAL PATH [INFO] ===

        printed by the flow, not by yosys. Treating that as a module would make
        every single-module design look ambiguous and force a refusal. A
        statistics block always prints at least one count row or a chip-area
        line; a block with neither is not one, and that test needs no guessing.
        """
        return (self.chip_area is not None
                or any(v is not None for v in self.counts.values()))

    @property
    def is_mapped(self) -> bool:
        """True when the block carries an area, i.e. it is post-techmap."""
        return self.chip_area is not None

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (f"StatBlock({self.module!r}, cells={self.counts.get('cells')}, "
                f"chip_area={self.chip_area})")


def _find_count(text: str, keyword: str) -> Optional[int]:
    """The LAST match of either spelling, or None. Never a fabricated 0."""
    kw = re.escape(keyword)
    for pat in (_COUNT_NEW.format(kw=kw), _COUNT_OLD.format(kw=kw)):
        found = re.findall(pat, text, re.M)
        if found:
            return int(str(found[-1]).replace(",", ""))
    return None


def parse_stat_blocks(text: str) -> List[StatBlock]:
    """Every `=== module ===` block in a yosys transcript, in printed order.

    PURE — no I/O. A transcript with no block at all yields `[]`, which the
    caller must distinguish from "a block with no numbers": those are different
    facts and this function keeps them different.
    """
    src = text or ""
    marks = list(_BLOCK_RE.finditer(src))
    blocks: List[StatBlock] = []
    for i, m in enumerate(marks):
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(src)
        body = src[start:end]
        counts = {k: _find_count(body, kw) for k, kw in _COUNT_KEYWORDS.items()}
        # The full-precision area line belongs to the block it is printed in.
        area = None
        am = None
        for am in _CHIP_AREA_RE.finditer(body):
            pass
        if am is not None:
            try:
                area = float(am.group("v"))
            except ValueError:
                area = None
        seq = None
        sm = None
        for sm in _SEQ_AREA_RE.finditer(body):
            pass
        if sm is not None:
            try:
                seq = float(sm.group("v"))
            except ValueError:
                seq = None
        blocks.append(StatBlock(m.group("name").strip(), counts, area, seq, body))
    return blocks


def select_block(blocks: Sequence[StatBlock], top: Optional[str] = None,
                 *, kind: Optional[str] = None
                 ) -> Tuple[Optional[StatBlock], str]:
    """Pick the block a record should describe. Returns (block, reason).

    The reason is returned even on success, because "which block did this number
    come from" is part of the number's provenance and a caller that has to
    reconstruct it later will reconstruct it differently.

    `kind` selects between the two blocks one synthesis run prints:
    ``"mapped"`` requires a technology-mapped block (one that carries a chip
    area), ``"generic"`` requires a pre-techmap one, and ``None`` prefers mapped
    and falls back to the last block. Asking for a kind the transcript does not
    contain returns `(None, reason)` — it does not fall back, because falling
    back would answer a question about the mapped netlist with a generic number.

    Ambiguity is never resolved by position. With several candidate modules and
    no `top`, this returns `(None, reason)` and the caller emits INVALID.
    """
    if kind not in (None, "mapped", "generic"):
        raise ValueError(f"kind must be None, 'mapped' or 'generic', not {kind!r}")
    stats = [b for b in blocks if b.is_statistics]
    if not stats:
        if blocks:
            return None, (f"the transcript has {len(blocks)} `=== ... ===` "
                          f"banner(s) but none of them is a statistics block "
                          f"(no count rows, no chip area)")
        return None, "no `=== module ===` statistics block in the transcript"
    named = [b for b in stats if not b.is_hierarchy_rollup]
    pool = named or list(stats)
    if top:
        want = top.lstrip("\\").strip()
        pool = [b for b in pool if b.module.lstrip("\\").strip() == want]
        if not pool:
            avail = ", ".join(sorted({b.module for b in stats})) or "(none)"
            return None, (f"no statistics block for top {top!r}; "
                          f"blocks present: {avail}")
        where = f"module {want!r}"
    else:
        modules = sorted({b.module for b in pool})
        if len(modules) > 1:
            return None, ("the transcript holds statistics for more than one "
                          f"module ({', '.join(modules)}) and no top was named; "
                          "refusing to guess which one is the design")
        where = f"the only module {modules[0]!r}"

    mapped = [b for b in pool if b.is_mapped]
    generic = [b for b in pool if not b.is_mapped]
    if kind == "mapped":
        if not mapped:
            return None, (f"no technology-mapped statistics block for {where} "
                          f"({len(pool)} block(s), none carrying a chip area); "
                          f"a generic block is a different stage, not a "
                          f"substitute")
        return mapped[-1], f"last technology-mapped block for {where}"
    if kind == "generic":
        if not generic:
            return None, (f"no pre-techmap (generic) statistics block for "
                          f"{where} ({len(pool)} block(s), all carrying a chip "
                          f"area)")
        return generic[-1], f"last pre-techmap (generic) block for {where}"
    if mapped:
        return mapped[-1], (f"last technology-mapped block for {where} "
                            f"({len(pool)} block(s) for it)")
    return pool[-1], f"last block for {where} ({len(pool)} block(s) for it)"


def sha256_of_text(text: str) -> str:
    """`sha256:<hex>` of a transcript, so a record can name what it parsed."""
    return "sha256:" + __import__("hashlib").sha256(
        (text or "").encode("utf-8")).hexdigest()


def _source(path: Optional[str], text: str, block_reason: str,
            tool_version: Optional[str]) -> Dict[str, Any]:
    src: Dict[str, Any] = {
        "path": path or "<in-memory transcript>",
        "sha256": sha256_of_text(text),
        "tool": TOOL,
        "parser": "_ppa/backends/yosys.py",
        "selection": block_reason,
    }
    if tool_version:
        src["tool_version"] = tool_version
    return src


def records_from_stat(
    text: str,
    *,
    stage: str,
    top: Optional[str] = None,
    path: Optional[str] = None,
    tool_version: Optional[str] = None,
    scope_extra: Optional[Mapping[str, Any]] = None,
    kind: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Canonical PROXY area records for one yosys transcript.

    `stage` is the scope's stage and it is REQUIRED — a count with no stage
    cannot be compared to anything, and the two blocks yosys prints (generic and
    technology-mapped) are different stages of the same run. Callers pass
    e.g. `"synth_generic"` or `"synth_mapped"`, and pass the matching `kind`
    (`"generic"` / `"mapped"`) so the stage label and the block that was read
    can never drift apart.

    Every emitted record is RTL_PROXY or SYNTH_PROXY. Emitting a PHYSICAL metric
    from here raises: see the module docstring.

    A transcript this parser cannot read produces INVALID records WITH A REASON,
    never an omission and never a zero. "I could not read it" and "I read it and
    it was empty" must not produce the same verdict.
    """
    if not stage:
        raise ValueError("stage is required; an unscoped count is not comparable")
    blocks = parse_stat_blocks(text)
    block, reason = select_block(blocks, top, kind=kind)
    scope: Dict[str, Any] = {"stage": stage, "tool": TOOL}
    if top:
        scope["module"] = top.lstrip("\\").strip()
    elif block is not None:
        scope["module"] = block.module
    if scope_extra:
        scope.update(dict(scope_extra))
    source = _source(path, text, reason, tool_version)

    emit: List[Dict[str, Any]] = []

    def _bad(metric: str, why: str) -> None:
        emit.append(_area.proxy_record(
            metric, _area.INVALID, reason=why, scope=scope, source=source))

    if block is None:
        for metric in ("area.proxy.cell_count", "area.proxy.wire_count",
                       "area.proxy.wire_bit_count", "area.synth.cell_area",
                       "area.synth.sequential_area"):
            _bad(metric, f"cannot select a statistics block: {reason}")
        return emit

    for metric, key in (("area.proxy.cell_count", "cells"),
                        ("area.proxy.wire_count", "wires"),
                        ("area.proxy.wire_bit_count", "wire_bits")):
        n = block.counts.get(key)
        if n is None:
            _bad(metric, (f"the statistics block for {block.module!r} prints no "
                          f"{_COUNT_KEYWORDS[key]!r} row"))
        else:
            emit.append(_area.proxy_record(
                metric, _area.MEASURED, value=n, scope=scope, source=source))

    if block.chip_area is None:
        _bad("area.synth.cell_area",
             (f"the statistics block for {block.module!r} carries no "
              f"`Chip area for module` line — it is a pre-techmap (generic) "
              f"block, which has no area at all"))
        _bad("area.synth.sequential_area",
             f"no chip area in the block for {block.module!r}, so no share of it")
    else:
        emit.append(_area.proxy_record(
            "area.synth.cell_area", _area.MEASURED, value=block.chip_area,
            scope=scope, source=source))
        if block.sequential_area is None:
            _bad("area.synth.sequential_area",
                 (f"the block for {block.module!r} reports a chip area but no "
                  f"`of which used for sequential elements` line"))
        else:
            emit.append(_area.proxy_record(
                "area.synth.sequential_area", _area.MEASURED,
                value=block.sequential_area, scope=scope, source=source))
    return emit


def reduction_record(baseline: Mapping[str, Any], candidate: Mapping[str, Any],
                     ) -> Dict[str, Any]:
    """The DERIVED reduction% between two proxy count records.

    `100*(baseline-candidate)/baseline`, carried as DERIVED with its formula
    (PPA_INTERFACES.md §3: a number you computed is DERIVED and states how).
    A negative result means the candidate GREW and is returned verbatim — a
    measured anti-reduction is a fact, not an error.
    """
    metric_map = {
        "area.proxy.cell_count": "area.proxy.cell_count_reduction_pct",
        "area.proxy.wire_count": "area.proxy.wire_count_reduction_pct",
    }
    m = baseline.get("metric")
    out_metric = metric_map.get(str(m))
    if out_metric is None or m != candidate.get("metric"):
        raise ValueError(
            f"no reduction metric is defined for {m!r} vs "
            f"{candidate.get('metric')!r}")
    scope = dict(baseline.get("scope") or {})
    for side, rec in (("baseline", baseline), ("candidate", candidate)):
        if rec.get("status") not in _area.COMPARABLE_STATUSES:
            return _area.proxy_record(
                out_metric, _area.NOT_MEASURED, scope=scope,
                reason=(f"{side} {m} has status {rec.get('status')!r}; a "
                        f"reduction over an unmeasured count is not a number"))
    if not _area.scope_matches(baseline.get("scope"), candidate.get("scope")):
        return _area.proxy_record(
            out_metric, _area.NOT_MEASURED, scope=scope,
            reason=("the two counts were taken at different scopes, so their "
                    "difference is not a reduction"))
    b, c = float(baseline["value"]), float(candidate["value"])
    if b <= 0:
        return _area.proxy_record(
            out_metric, _area.NOT_MEASURED, scope=scope,
            reason=f"baseline count is {b}, which cannot anchor a percentage")
    return _area.proxy_record(
        out_metric, _area.DERIVED, value=round(100.0 * (b - c) / b, 6),
        scope=scope,
        formula="100*(baseline-candidate)/baseline over the proxy counts",
        source={
            "path": "<derived>",
            "tool": TOOL,
            "parser": "_ppa/backends/yosys.py",
            "baseline_record": _cj.digest_of(dict(baseline)),
            "candidate_record": _cj.digest_of(dict(candidate)),
        })
