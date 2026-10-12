"""Minimum legal elaboration values stated by the design input.

Only explicit ``parameter NAME >= N`` / ``NAME ≥ N`` requirements are read.
No range is invented for a merely parameterized port. Denied prose is ignored.
"""
from __future__ import annotations

import re
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _prose_polarity import is_denied, sentence_scope
from _specrtl_common import strip_comments, _PARAM_ASSIGN

_MINIMUM = re.compile(
    r"\b(?:parameter\s+)?([A-Za-z_]\w*)\s*(?:>=|≥)\s*(\d+)\b", re.I)


def minimums(text: str, *, declared_parameters=()) -> dict[str, int]:
    answer: dict[str, int] = {}
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        data = None
    lines = [(line, None) for line in text.splitlines()] if data is None else []
    def collect(node, parent="", names=frozenset()):
        if isinstance(node, str):
            lines.extend((line, names) for line in node.splitlines())
        elif isinstance(node, list):
            for child in node:
                collect(child, parent, names)
        elif isinstance(node, dict):
            if parent in ("parameters", "parameter_ranges"):
                name = node.get("name")
                if isinstance(name, str) and re.fullmatch(r"[A-Za-z_]\w*", name):
                    names = frozenset((name.lower(),))
            if parent == "parameter_ranges":
                name, low = node.get("name"), node.get("min")
                if (isinstance(name, str) and re.fullmatch(r"[A-Za-z_]\w*", name)
                        and type(low) is int and low >= 0):
                    answer[name.lower()] = max(low, answer.get(name.lower(), low))
            for key, child in node.items():
                collect(child, key, names)
    if data is not None:
        collect(data, names=frozenset(name.lower() for name in declared_parameters))
    for line, names in lines:
        for match in _MINIMUM.finditer(line):
            # Bare inequalities in integration/signoff prose describe physical
            # acceptance. In JSON they become RTL ranges only inside the named
            # parameter contract, or with an explicit "parameter" declaration.
            if (names is not None and match.group(1).lower() not in names
                    and not re.match(r"parameter\s+", match.group(), re.I)):
                continue
            lo, hi = sentence_scope(line, match.start(), match.end(),
                                    before=len(line), after=len(line))
            if is_denied(line[lo:hi]) is not None:
                continue
            name, value = match.group(1), int(match.group(2))
            answer[name.lower()] = max(value, answer.get(name.lower(), value))
    return answer


def _module_region(rtl: str, top: str | None) -> str:
    """Limit a guard to its module; a neighbor's guard cannot protect `top`."""
    modules = list(re.finditer(r"\bmodule\s+(?:automatic\s+)?([A-Za-z_]\w*)\b", rtl))
    if not modules:
        return rtl if top is None else ""
    for match in modules:
        if top is not None and match.group(1) != top:
            continue
        end = re.search(r"\bendmodule\b", rtl[match.end():])
        return rtl[match.end():match.end() + end.start()] if end else ""
    return ""


def rtl_parameter_names(rtl: str, top: str) -> frozenset[str]:
    """Use the checked module's parameter declarations, never its neighbors."""
    clean = re.sub(r'"(?:\\.|[^"\\])*"', '""', strip_comments(rtl))
    return frozenset(match.group(1).lower() for match in
                     _PARAM_ASSIGN.finditer(_module_region(clean, top)))


def _branch_body(region: str, begin_end: int) -> str | None:
    """Return only the matched generate begin/end body, excluding its else."""
    depth = 1
    for token in re.finditer(r"\bbegin\b|\bend\b", region[begin_end:]):
        depth += 1 if token.group() == "begin" else -1
        if depth == 0:
            return region[begin_end:begin_end + token.start()]
    return None


def _condition_covers_invalid(condition: str, parameter: str,
                              minimum: int) -> bool:
    """Prove a simple nested condition true for every integer below minimum."""
    match = re.fullmatch(
        rf"\s*{re.escape(parameter)}\s*(<|<=|>|>=|==|!=)\s*(-?\d+)\s*",
        condition, re.I)
    if match is None:
        return False
    op, bound = match.group(1), int(match.group(2))
    return ((op == "<" and bound >= minimum) or
            (op == "<=" and bound >= minimum - 1) or
            (op == "!=" and bound >= minimum))


def _single_item_conditions_cover_invalid(prefix: str, parameter: str,
                                           minimum: int) -> bool:
    """An `if (...)` chain may guard a direct initial only if each arm runs."""
    remaining = re.sub(r"^\s*:\s*\w+", "", prefix).strip()
    while remaining:
        match = re.match(r"if\s*\(", remaining, re.I)
        if match is None:
            return False  # else, for, case, or an unknown construct
        start = match.end()
        depth = 1
        end = start
        while end < len(remaining) and depth:
            if remaining[end] == "(":
                depth += 1
            elif remaining[end] == ")":
                depth -= 1
            end += 1
        if depth or not _condition_covers_invalid(
                remaining[start:end - 1], parameter, minimum):
            return False
        remaining = remaining[end:].strip()
    return True


def _direct_initial_fatal(body: str, parameter: str, minimum: int) -> bool:
    """Credit only a fatal reached for every invalid value in this arm."""
    # Each begin/end block inherits whether its preceding single-item `if`
    # chain is guaranteed in the outer invalid range. The first frame is the
    # already-selected invalid arm itself.
    active = [True]
    item_start = [0]
    for token in re.finditer(r"\bbegin\b|\bend\b|\binitial\b|;", body):
        word = token.group()
        if word == "begin":
            active.append(active[-1] and _single_item_conditions_cover_invalid(
                body[item_start[-1]:token.start()], parameter, minimum))
            item_start.append(token.end())
        elif word == "end":
            if len(active) > 1:
                active.pop()
                item_start.pop()
            item_start[-1] = token.end()
        elif word == ";":
            item_start[-1] = token.end()
        elif active[-1] and re.match(
                r"\s+(?:begin(?:\s*:\s*\w+)?\s*)?\$fatal\s*\(",
                body[token.end():]) and _single_item_conditions_cover_invalid(
                    body[item_start[-1]:token.start()], parameter, minimum):
            return True
    return False


def has_elaboration_guard(rtl: str, parameter: str, minimum: int,
                          *, top: str | None = None) -> bool:
    """Find a module-scope explicit or implicit generate arm that fatals below minimum.

    This structural check is advisory. It requires `$fatal` inside the exact
    invalid arm and the checked module; nearby text is not evidence of a guard.
    """
    clean = re.sub(r'"(?:\\.|[^"\\])*"', '""', strip_comments(rtl))
    region = _module_region(clean, top)
    name = re.escape(parameter)
    for match in re.finditer(
            rf"\bif\s*\(\s*{name}\s*(<|<=)\s*(\d+)\s*\)\s*(begin|initial)\b",
            region, re.I):
        op, bound, item = match.group(1), int(match.group(2)), match.group(3).lower()
        if not ((op == "<" and bound == minimum) or
                (op == "<=" and bound == minimum - 1)):
            continue
        # A generate-if is a module item, not a procedural if nested in an
        # always/initial begin/end block or another conditional generate arm.
        prefix = region[:match.start()]
        nesting = sum(1 if t.group() == "begin" else -1 for t in
                      re.finditer(r"\bbegin\b|\bend\b", prefix))
        if nesting != 0:
            continue
        # A single generate item may itself be an `if`. An invalid arm nested
        # under an earlier condition need not execute when the parameter is
        # invalid, even though no begin/end block surrounds it.
        if re.search(r"\bif\s*\([^;]*\)\s*$", prefix.rsplit(";", 1)[-1]):
            continue
        if item == "initial":
            if re.match(r"\s+\$fatal\s*\([^;]*\)\s*;", region[match.end():]):
                return True
        else:
            body = _branch_body(region, match.end())
            if body is not None and _direct_initial_fatal(body, parameter, minimum):
                return True
    return False
