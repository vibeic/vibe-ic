"""Source-declared pin conditions, shared by the L1 and L5 emitters.

No pin vocabulary or electrical defaults. Conflicting live declarations raise
PIN_INTERFACE_CONDITION_CONFLICT, so the normal producer records a refusal.
L5 spec.input_conditions is separate from performance targets: an externally
supplied condition must never become an output acceptance target.
"""
from copy import deepcopy
from decimal import Decimal
import math
import re

from _prose_polarity import is_denied

_NUM = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_UNIT = r"(?:[munpµμkMG]?V|[munpµμkM]?A|[kMG]?Hz|[munpµμ]?s|[munpµμ]?F|Ohm|Ω|°C)"
_PIN = re.compile(
    r"(?<!\w)(?:`?(?P<before>[A-Za-z_]\w*)`?\s+pin\b"
    r"|pin\s+`?(?P<after>[A-Za-z_]\w*)\b`?)"
    r"(?=\s+(?:is\b|(?:interface|input|operating)\s+condition\b))", re.I)
_VALUE = re.compile(rf"(?P<value>{_NUM})\s*(?P<unit>{_UNIT})(?![A-Za-z])")
_UNCERTAIN = re.compile(r"\b(?:if|perhaps|possibly|might|may|could|should|would|hypothetical|histor\w*|legacy|example|previously|formerly|proposed)\b", re.I)
_HISTORY = re.compile(r"\b(?:history|histor\w*|legacy|example|hypothetical|alternatives?|options?)\b", re.I)
_REPLACE = re.compile(r"\b(?:replaces?|supersedes?)\s+(?P<what>[^.!?]+)", re.I)


def _cite(fname, number, line):
    return {"doc": str(fname) if str(fname).startswith("input/") else f"input/docs/{fname}",
            "line": number, "quote": line}


def _signature(row):
    return row["unit"], row["min_typ_max"], row["role"].lower()


def declared_pin_conditions(extracted, is_current=None):
    """Return resolved rows by exact source pin spelling, preserving evidence.

    Only an affirmative 'pin is driven by ...' or labelled 'pin ... interface
    condition' binds a quantity. The first sentence owns the values; subsequent
    replacement/supporting-evidence sentences cannot supply another quantity.
    Explicit replacements retain the replaced record, never erase history.
    """
    candidates = {}
    for fname, text in (extracted or {}).items():
        headings = []
        offset = 0
        for number, line in enumerate((text or "").splitlines(), 1):
            heading = re.match(r"^\s*(#{1,6})\s+(.+)", line)
            if heading:
                level = len(heading[1])
                headings = [(n, t) for n, t in headings if n < level]
                headings.append((level, heading[2]))
            current = not any(_HISTORY.search(t) for _, t in headings)
            if is_current is not None:
                current = current and is_current(text, offset)
            offset += len(line) + 1
            if not current:
                continue
            # Split sentences without splitting decimals or numbered bullets.
            declaration = re.sub(r"^\s*(?:\d+[.)]|[-*])\s+", "", line)
            clause = re.split(r"(?<=[.!?])\s+(?=[A-Z])", declaration, maxsplit=1)[0]
            match = _PIN.search(clause)
            if not match or is_denied(clause) or _UNCERTAIN.search(clause):
                continue
            pin = match["before"] or match["after"]
            tail = clause[match.end():]
            role = re.search(r"\s+is\s+(?:externally\s+)?driven\s+by\s+(?P<role>[^,;]+)[,;]\s*", tail, re.I)
            if role:
                quantity = tail[role.end():]
                role_text = role["role"].strip()
            else:
                role = re.match(r"\s*(?:interface|input|operating)\s+condition\s*:\s*", tail, re.I)
                if not role:
                    continue
                quantity = tail[role.end():]
                role_text = "declared interface condition"
            value = _VALUE.search(quantity)
            if not value:
                continue
            unit = value["unit"]
            minimum = re.search(rf"\bmin(?:imum)?\s*[:=]?\s*({_NUM})\s*{re.escape(unit)}", quantity, re.I)
            maximum = re.search(rf"\bmax(?:imum)?\s*[:=]?\s*({_NUM})\s*{re.escape(unit)}", quantity, re.I)
            interval = re.search(rf"({_NUM})\s*(?:{re.escape(unit)})?\s*(?:to|–|\.\.|-)\s*({_NUM})\s*{re.escape(unit)}", quantity)
            # A min/max-only declaration has no nominal. Do not turn either
            # endpoint into one just because it is the first unit-bearing token.
            endpoint = any(m and m.start() <= value.start() < m.end()
                           for m in (minimum, maximum, interval))
            bounds = {} if endpoint else {"typ": float(value["value"])}
            row = {"pin": pin, "name": pin, "kind": "input_condition", "role": role_text,
                   "unit": unit, "min_typ_max": bounds, "evidence": _cite(fname, number, line)}
            tolerance = re.search(rf"(?:\+/-|±)\s*({_NUM})\s*(%|{re.escape(unit)})", quantity[value.end():])
            if tolerance:
                if "typ" not in bounds:
                    raise ValueError(f"PIN_INTERFACE_CONDITION_INVALID: {pin}: tolerance needs a nominal")
                amount = float(tolerance[1])
                nominal_decimal = Decimal(value["value"])
                amount_decimal = Decimal(tolerance[1])
                delta = abs(nominal_decimal) * amount_decimal / 100 if tolerance[2] == "%" else amount_decimal
                if amount < 0:
                    raise ValueError(f"PIN_INTERFACE_CONDITION_INVALID: {pin}: negative tolerance")
                bounds.update(min=float(nominal_decimal - delta), max=float(nominal_decimal + delta))
                row["tolerance_percent" if tolerance[2] == "%" else "tolerance_absolute"] = amount
            explicit = ({"min": float(minimum[1]), "max": float(maximum[1])} if minimum and maximum else
                        {"min": float(interval[1]), "max": float(interval[2])} if interval else {})
            if explicit and any(k in bounds and bounds[k] != v for k, v in explicit.items()):
                raise ValueError(f"PIN_INTERFACE_CONDITION_CONFLICT: {pin}: tolerance and range disagree")
            bounds.update(explicit)
            if not bounds:
                continue
            if not all(math.isfinite(n) for n in bounds.values()):
                raise ValueError(f"PIN_INTERFACE_CONDITION_INVALID: {pin}: nonfinite value")
            if ("min" in bounds and "max" in bounds and bounds["min"] > bounds["max"]) or (
                "typ" in bounds and (("min" in bounds and bounds["min"] > bounds["typ"])
                                     or ("max" in bounds and bounds["max"] < bounds["typ"]))):
                raise ValueError(f"PIN_INTERFACE_CONDITION_INVALID: {pin}: inconsistent bounds")
            replacement = _REPLACE.search(declaration[len(clause):])
            label = re.search(r"#\w+", clause[:match.start()])
            candidates.setdefault(pin, []).append((row, replacement, label[0] if label else None))
    resolved = {}
    for pin, declarations in candidates.items():
        active = []
        for row, replacement, label in declarations:
            replaced = []
            if replacement:
                what = replacement["what"]
                refs = re.findall(r"#\w+", what)
                earlier = re.search(r"\b(?:earlier|previous|prior)\s+(?:declaration|condition)\b", what, re.I)
                for old, old_label in active[:]:
                    if (refs and old_label in refs) or (earlier and not refs):
                        replaced.append(old)
                        active.remove((old, old_label))
                row["replaced_declarations"] = deepcopy(replaced)
                row["replacement_evidence"] = {**row["evidence"], "quote": replacement[0]}
            active.append((row, label))
        unique = []
        for row, _ in active:
            if not any(_signature(row) == _signature(old) for old in unique):
                unique.append(row)
        if len(unique) > 1:
            locations = [r["evidence"] for r in unique]
            raise ValueError(f"PIN_INTERFACE_CONDITION_CONFLICT: {pin}: {locations}")
        if unique:
            resolved[pin] = unique[0]
    return resolved


def declared_block_ports(extracted, block, is_current=None):
    """Read explicit block-scoped Pin tables or .subckt declarations.

    A mention of a pin in ordinary block prose is deliberately insufficient.
    """
    names = {str(block.get(k) or "").lower() for k in ("name", "type")}
    names.discard("")
    ports = set()
    for text in (extracted or {}).values():
        scoped = False
        table = False
        scope_level = 0
        offset = 0
        headings = []
        for line in text.splitlines():
            section = re.match(r"\s*(#{1,6})\s+(.+)", line)
            if section:
                level = len(section[1])
                headings = [(n, t) for n, t in headings if n < level]
                headings.append((level, section[2]))
            current = not any(_HISTORY.search(t) or _UNCERTAIN.search(t) or is_denied(t) for _, t in headings)
            current = current and (is_current is None or is_current(text, offset))
            offset += len(line) + 1
            if not current:
                scoped = False
                table = False
                continue
            subckt = re.match(r"\s*\.subckt\s+(\w+)\s+([^*]+)", line, re.I)
            if subckt and subckt[1].lower() in names:
                ports.update(p for p in subckt[2].split() if "=" not in p)
            heading = re.match(r"\s*(#{1,6})\s+(.+)", line)
            if heading:
                level = len(heading[1])
                if level <= scope_level:
                    scoped = False
                title = heading[2].replace("`", "")
                if any(re.search(rf"\b{re.escape(n)}\b", title, re.I) for n in names):
                    scoped = True
                    scope_level = level
                table = False
            if scoped and line.strip().startswith("|"):
                cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
                if cells[0].lower() in {"pin", "port", "signal"}:
                    table = True
                elif table and re.fullmatch(r"[A-Za-z_]\w*", cells[0]):
                    ports.add(cells[0])
            elif line.strip() and not heading:
                table = False
    return ports


def project_pin_conditions(pins, extracted, is_current=None):
    rows = declared_pin_conditions(extracted, is_current)
    for pin in pins:
        if pin.get("name") in rows:
            pin.setdefault("electrical_specs", []).append(deepcopy(rows[pin["name"]]))


def project_block_conditions(blocks, extracted, is_current=None):
    rows = declared_pin_conditions(extracted, is_current)
    for block in blocks:
        selected = [deepcopy(row) for pin, row in rows.items() if pin in declared_block_ports(extracted, block, is_current)]
        if selected:
            if not isinstance(block.get("spec"), dict):
                block["spec"] = {}
            block["spec"]["input_conditions"] = selected
