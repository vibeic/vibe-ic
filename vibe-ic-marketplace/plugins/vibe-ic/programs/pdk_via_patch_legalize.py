#!/usr/bin/env python3
"""Derive legal VIA landing patches from one tech LEF.

This is a REMEDIATION, not a verdict.  It changes only routing-layer ``RECT``
records inside fixed ``VIA`` blocks and routing-layer ``ENCLOSURE`` records
inside ``VIARULE ... GENERATE`` blocks.  Both forms are changed only when the
same tech LEF declares that their generated patch is smaller than that layer's
``MINWIDTH``/``WIDTH`` or ``AREA``.  Growth is centered, manufacturing-grid
aligned, and minimal under those constraints.  Healthy input is returned
byte-for-byte.

PIN-ACCESS LAYERS ARE NEVER TOUCHED (owner ruling, 2026-09-02)
==============================================================
A wider via landing on the layer standard-cell PINS are drawn on covers the
access points the detailed router needs, and the router then cannot reach the
pin at all.  MEASURED on a subservient x gf180mcuD run: legalizing every
routing layer produced 81 x ``[ERROR DRT-0073] No access point``, detailed
routing did not complete, and the DEF shipped with NO signal routing — whose
DRC then reported ZERO violations.  A DRC of zero on an unrouted DEF is the
most dangerous number this program can cause, because it reads exactly like a
total fix.

So ``pin_layers`` is a REQUIRED input, and layers in it are skipped entirely.
This is the same exclusion the flow's own min-area patcher already applies —
it prints ``MIN_AREA_PATCH_PIN_LAYERS_NOT_JUDGED`` for precisely this reason —
so the two remediations now agree instead of contradicting each other.

Skipping costs nothing on the violations that matter: cell pins sit on the
LOWEST routing layer, while the min-width/min-area offenders this program
exists for are on the layers ABOVE it (measured: 1 on Metal2, 1 on Metal3, 10
on Metal5, and NONE on the Metal1 pin layer).

An EMPTY ``pin_layers`` is accepted but recorded as ``pin_layers_declared:
false``, so a caller that could not derive the set cannot be mistaken for one
that derived an empty set.  The caller decides whether that is good enough;
this function never guesses.
"""

from __future__ import annotations

import re
from decimal import Decimal, ROUND_CEILING
from typing import Dict, Iterable, List, Optional, Tuple


_NUM = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_GRID_RE = re.compile(rf"(?im)^\s*MANUFACTURINGGRID\s+({_NUM})\s*;")
_LAYER_RE = re.compile(
    r"(?ms)^[ \t]*LAYER[ \t]+(?P<name>\S+)[ \t]*\r?\n"
    r"(?P<body>.*?)^[ \t]*END[ \t]+(?P=name)[ \t]*\r?$"
)
_VIA_START_RE = re.compile(r"^[ \t]*VIA[ \t]+(\S+)(?:[ \t]+[^\r\n]*)?\r?\n?$")
_VIARULE_START_RE = re.compile(
    r"^[ \t]*VIARULE[ \t]+(\S+)[ \t]+GENERATE\b[^\r\n]*\r?\n?$"
)
_LAYER_SELECT_RE = re.compile(r"^[ \t]*LAYER[ \t]+(\S+)[ \t]*;[ \t]*\r?\n?$")
_RECT_RE = re.compile(
    rf"^(?P<head>[ \t]*RECT[ \t]+)(?P<x1>{_NUM})[ \t]+"
    rf"(?P<y1>{_NUM})[ \t]+(?P<x2>{_NUM})[ \t]+(?P<y2>{_NUM})"
    r"(?P<tail>[ \t]*;[^\r\n]*)(?P<nl>\r?\n?)$"
)
_ENCLOSURE_RE = re.compile(
    rf"^(?P<head>[ \t]*ENCLOSURE[ \t]+)(?P<x>{_NUM})[ \t]+"
    rf"(?P<y>{_NUM})(?P<tail>[ \t]*;[^\r\n]*)(?P<nl>\r?\n?)$"
)


def _one(body: str, key: str) -> Optional[Decimal]:
    match = re.search(rf"(?im)^\s*{key}\s+({_NUM})\s*;", body)
    return Decimal(match.group(1)) if match else None


def _routing_rules(text: str) -> Dict[str, Dict[str, Optional[Decimal]]]:
    rules: Dict[str, Dict[str, Optional[Decimal]]] = {}
    for match in _LAYER_RE.finditer(text):
        body = match.group("body")
        if not re.search(r"(?im)^\s*TYPE\s+ROUTING\s*;", body):
            continue
        min_width = _one(body, "MINWIDTH") or _one(body, "WIDTH")
        area = _one(body, "AREA")
        if min_width is not None or area is not None:
            rules[match.group("name")] = {
                "min_width": min_width,
                "area": area,
            }
    return rules


def _places(token: str) -> int:
    mantissa = token.lower().split("e", 1)[0]
    return len(mantissa.split(".", 1)[1]) if "." in mantissa else 0


def _plain(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _grow_dimension(current: Decimal, required: Decimal,
                    grid: Decimal) -> Decimal:
    if current >= required:
        return current
    # Centered growth moves each edge by a whole manufacturing grid, so the
    # dimension changes in quanta of two grids.
    quantum = grid * 2
    steps = ((required - current) / quantum).to_integral_value(
        rounding=ROUND_CEILING)
    return current + steps * quantum


def _legal_dimensions(width: Decimal, height: Decimal,
                      min_width: Optional[Decimal],
                      min_area: Optional[Decimal],
                      grid: Decimal) -> Tuple[Decimal, Decimal]:
    floor = min_width or Decimal(0)
    base_w = _grow_dimension(width, floor, grid)
    base_h = _grow_dimension(height, floor, grid)
    if min_area is None or base_w * base_h >= min_area:
        return base_w, base_h

    need_w = min_area / base_h
    by_width = (_grow_dimension(width, max(floor, need_w), grid), base_h)
    need_h = min_area / base_w
    by_height = (base_w, _grow_dimension(height, max(floor, need_h), grid))

    # Both candidates satisfy the same rules.  Choose the one with the least
    # maximum edge displacement, then least total growth, then width growth for
    # a deterministic tie.  No design/PDK-specific orientation is assumed.
    def score(pair: Tuple[Decimal, Decimal]) -> Tuple[Decimal, Decimal, int]:
        dw, dh = pair[0] - width, pair[1] - height
        return (max(dw, dh), dw + dh, 0 if dw >= dh else 1)

    return min((by_width, by_height), key=score)


def _legalize_generate_rules(lines: List[str],
                             rules: Dict[str, Dict[str, Optional[Decimal]]],
                             grid: Decimal
                             ) -> Tuple[List[str], List[dict], int, List[dict]]:
    """Rewrite routing-layer enclosures in generated-via rules.

    A generated patch is the cut bounding-box plus twice its routing-layer
    enclosure.  The cut layer is structural: it is the layer with RECTs that
    is not one of this file's routing layers.  Ambiguous rules are disclosed
    and left byte-identical so the caller can refuse a partial derived LEF.
    """
    output = list(lines)
    changes: List[dict] = []
    remaining = 0
    unresolved: List[dict] = []
    i = 0
    while i < len(lines):
        start = _VIARULE_START_RE.match(lines[i])
        if not start:
            i += 1
            continue
        name = start.group(1)
        j = i + 1
        while j < len(lines) and not re.match(
                rf"^[ \t]*END[ \t]+{re.escape(name)}[ \t]*\r?\n?$",
                lines[j]):
            j += 1
        if j >= len(lines):
            unresolved.append({"via": name, "reason": "unterminated VIARULE"})
            i += 1
            continue

        layer_name: Optional[str] = None
        rects: Dict[str, List[Tuple[Decimal, Decimal, Decimal, Decimal]]] = {}
        enclosures: List[Tuple[int, str, re.Match]] = []
        for index in range(i + 1, j):
            layer_match = _LAYER_SELECT_RE.match(lines[index])
            if layer_match:
                layer_name = layer_match.group(1)
                continue
            rect_match = _RECT_RE.match(lines[index])
            if rect_match and layer_name:
                rects.setdefault(layer_name, []).append(tuple(
                    Decimal(rect_match.group(k))
                    for k in ("x1", "y1", "x2", "y2")))
                continue
            enclosure_match = _ENCLOSURE_RE.match(lines[index])
            if enclosure_match and layer_name in rules:
                enclosures.append((index, layer_name, enclosure_match))

        cut_layers = [layer for layer, layer_rects in rects.items()
                      if layer not in rules and layer_rects]
        if enclosures and len(cut_layers) != 1:
            unresolved.append({
                "via": name,
                "reason": ("expected exactly one non-routing cut layer with "
                           f"RECT geometry, observed {cut_layers}"),
            })
            i = j + 1
            continue
        if not enclosures:
            i = j + 1
            continue

        cut_rects = rects[cut_layers[0]]
        cut_x1 = min(row[0] for row in cut_rects)
        cut_y1 = min(row[1] for row in cut_rects)
        cut_x2 = max(row[2] for row in cut_rects)
        cut_y2 = max(row[3] for row in cut_rects)
        cut_w, cut_h = cut_x2 - cut_x1, cut_y2 - cut_y1
        for index, layer, enclosure_match in enclosures:
            ex = Decimal(enclosure_match.group("x"))
            ey = Decimal(enclosure_match.group("y"))
            width, height = cut_w + ex * 2, cut_h + ey * 2
            rule = rules[layer]
            target_w, target_h = _legal_dimensions(
                width, height, rule["min_width"], rule["area"], grid)
            if target_w != width or target_h != height:
                target_ex = ex + (target_w - width) / 2
                target_ey = ey + (target_h - height) / 2
                tokens = [enclosure_match.group("x"),
                          enclosure_match.group("y")]
                places = max(*(_places(token) for token in tokens),
                             max(0, -grid.as_tuple().exponent))
                fmt = f".{{}}f".format(places)
                output[index] = (enclosure_match.group("head")
                                 + " ".join(format(v, fmt)
                                            for v in (target_ex, target_ey))
                                 + enclosure_match.group("tail")
                                 + enclosure_match.group("nl"))
                changes.append({
                    "form": "VIARULE",
                    "record": "ENCLOSURE",
                    "via": name,
                    "layer": layer,
                    "before": [_plain(ex), _plain(ey)],
                    "after": [_plain(target_ex), _plain(target_ey)],
                    "before_area": _plain(width * height),
                    "after_area": _plain(target_w * target_h),
                    "min_width": (_plain(rule["min_width"])
                                  if rule["min_width"] is not None else None),
                    "min_area": (_plain(rule["area"])
                                 if rule["area"] is not None else None),
                })
                continue
            violates_width = (rule["min_width"] is not None
                              and min(width, height) < rule["min_width"])
            violates_area = (rule["area"] is not None
                             and width * height < rule["area"])
            if violates_width or violates_area:
                remaining += 1
        i = j + 1
    return output, changes, remaining, unresolved


def legalize_via_patches(text: str,
                        pin_layers: Optional[Iterable[str]] = None
                        ) -> Tuple[str, dict]:
    """Return ``(possibly_changed_text, machine_readable_report)``.

    ``pin_layers`` names the layers standard-cell PINS are drawn on; every one
    of them is left byte-for-byte untouched so the router keeps the access
    points it needs.  See the module docstring for the measurement.

    The function is pure.  Callers decide where to stage the derived LEF and
    must retain the report beside the run that consumed it.
    """
    grid_match = _GRID_RE.search(text)
    grid = Decimal(grid_match.group(1)) if grid_match else Decimal("0.001")
    rules = _routing_rules(text)
    # Case-folded, because LEF layer names are compared case-insensitively
    # everywhere else in this file.
    _pin_declared = pin_layers is not None
    _pin = {str(n).strip().lower() for n in (pin_layers or ()) if str(n).strip()}
    # A layer we must not touch is removed from the rule table outright: every
    # growth decision below is keyed on `rules`, so one deletion covers the
    # fixed-VIA RECT path and the VIARULE GENERATE path together and neither
    # can drift from the other.
    skipped_layers = sorted(n for n in rules if n.strip().lower() in _pin)
    for _n in skipped_layers:
        rules.pop(_n, None)
    lines = text.splitlines(keepends=True)
    lines, changes, remaining, unresolved = _legalize_generate_rules(
        lines, rules, grid)
    output: List[str] = []
    via_name: Optional[str] = None
    layer_name: Optional[str] = None

    for line in lines:
        via_match = _VIA_START_RE.match(line)
        if via_name is None and via_match:
            via_name = via_match.group(1)
            layer_name = None
            output.append(line)
            continue
        if via_name is not None and re.match(
                rf"^[ \t]*END[ \t]+{re.escape(via_name)}[ \t]*\r?\n?$", line):
            via_name = None
            layer_name = None
            output.append(line)
            continue
        if via_name is not None:
            layer_match = _LAYER_SELECT_RE.match(line)
            if layer_match:
                layer_name = layer_match.group(1)
                output.append(line)
                continue
            rect_match = _RECT_RE.match(line)
            rule = rules.get(layer_name or "")
            if rect_match and rule:
                tokens = [rect_match.group(k) for k in ("x1", "y1", "x2", "y2")]
                x1, y1, x2, y2 = map(Decimal, tokens)
                width, height = x2 - x1, y2 - y1
                target_w, target_h = _legal_dimensions(
                    width, height, rule["min_width"], rule["area"], grid)
                if target_w != width or target_h != height:
                    dx, dy = (target_w - width) / 2, (target_h - height) / 2
                    nx1, ny1, nx2, ny2 = x1 - dx, y1 - dy, x2 + dx, y2 + dy
                    places = max(*(_places(token) for token in tokens),
                                 max(0, -grid.as_tuple().exponent))
                    fmt = f".{{}}f".format(places)
                    rewritten = (rect_match.group("head")
                                 + " ".join(format(v, fmt)
                                            for v in (nx1, ny1, nx2, ny2))
                                 + rect_match.group("tail")
                                 + rect_match.group("nl"))
                    output.append(rewritten)
                    changes.append({
                        "form": "VIA",
                        "record": "RECT",
                        "via": via_name,
                        "layer": layer_name,
                        "before": [_plain(v) for v in (x1, y1, x2, y2)],
                        "after": [_plain(v) for v in (nx1, ny1, nx2, ny2)],
                        "before_area": _plain(width * height),
                        "after_area": _plain(target_w * target_h),
                        "min_width": (_plain(rule["min_width"])
                                      if rule["min_width"] is not None else None),
                        "min_area": (_plain(rule["area"])
                                     if rule["area"] is not None else None),
                    })
                    continue
                violates_width = (rule["min_width"] is not None
                                  and min(width, height) < rule["min_width"])
                violates_area = (rule["area"] is not None
                                 and width * height < rule["area"])
                if violates_width or violates_area:
                    remaining += 1
        output.append(line)

    fixed = "".join(output)
    report = {
        "program": "pdk_via_patch_legalize",
        "enforcement": "REMEDIATION",
        "failure_policy": "ADVISORY_KEEP_ORIGINAL_AND_DISCLOSE",
        "manufacturing_grid": _plain(grid),
        "routing_layers_with_rules": len(rules),
        "changed_patch_records": len(changes),
        "changed_rectangles": sum(row["record"] == "RECT" for row in changes),
        "changed_enclosures": sum(row["record"] == "ENCLOSURE"
                                  for row in changes),
        "remaining_via_rule_violations": remaining,
        "unresolved_generate_rules": unresolved,
        "pin_layers_declared": _pin_declared,
        "pin_layers": sorted(_pin),
        "pin_layers_skipped_from_rules": skipped_layers,
        "pin_access_policy": (
            "layers carrying standard-cell PIN geometry are never widened: a "
            "wider landing there covers the router's access points and the "
            "net becomes unroutable (DRT-0073). Same exclusion the min-area "
            "patcher applies."),
        "changes": changes,
    }
    return fixed, report


__all__ = ["legalize_via_patches"]
