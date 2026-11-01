#!/usr/bin/env python3
"""_seal_ring_margin — how far a DIE's core must stay back from the die edge on
a technology that ships its own seal ring.  vibe-ic#2122

THE DEFECT THIS EXISTS FOR (measured, vibeic-eda#189 / vibe-ic#2122)
--------------------------------------------------------------------
On a `deliverable=DIE` run the flow sized the die to the core and then sealed
the ring onto it IN PLACE. The ring is a band at the die edge and the deck
requires a clearance between its marker and every prime-die layer, so a core
that reaches the die edge is inside both. Measured on one gf180mcuD die:

    ring alone, 503 um die                                    16, all density
    the run's own core (filling 0,0;503,503) + that ring    1,359,531
    the same core moved 28.5 um inward, 560 um die                    0

19,826 core shapes sat inside the 16 um ring band. The ring was correct, the
generator was correct and the deck was correct; the DIE was too small by
exactly the band plus the deck's own clearance, on every edge.

WHAT THIS MODULE IS, AND WHAT IT IS NOT
---------------------------------------
It is the ONE derivation of that margin, read out of the TECHNOLOGY, for the
two places that need it — `phase3_one_shot_runner.step_pnr`, which sizes the
die before the ring exists, and `die_finishing_gen`, which must refuse to seal
a core that reaches into the band. It carries NO number of its own:

    band       the seal-ring generator's OWN cell library says how deep its
               edge is (`<something>_width`, discovered by name, never a
               literal here) — or, better where it exists, the MEASURED inner
               extent of the ring the generator actually built
               (`sealring_verify.ring_extent`), which is a measurement of this
               die and not a reading of a parameter.
    clearance  the PDK's own DRC deck, in its own words: the separation every
               prime-die layer owes the guard-ring marker
               (`<layer>.separation(<guard-ring marker>, N.um)`).

EVERY UNREADABLE LINK IS A NAMED `NOT_MEASURED`, never a default. A margin
this module invented would be this flow deciding where the foundry's ring
goes, which is the whole defect one level up.

chip/PDK-AGNOSTIC: no foundry, node, PDK name, layer number or design name
appears here. The layer VARIABLES are discovered from the deck's own text by
what they are (a guard-ring marker), not by what they are called in any one
process.
"""
from __future__ import annotations

import json
import math
import re
import shlex
from typing import Any, Callable, Dict, List, Optional, Tuple

#: `run_sh(cmd) -> (rc, stdout)`. The PDK lives where the tools live, which on
#: this flow is inside a container, so every read goes through the caller's own
#: shell rather than through `open()`.
ShellFn = Callable[[str], Tuple[int, str]]

NOT_MEASURED = "NOT_MEASURED"

#: How `_read_files` frames each file in one shell round trip.
_SEP = "=== VIC_SEAL_FILE "
#: A cap on how much PDK text is pulled back at once. A deck is a few hundred
#: lines; anything past this is not the file we are looking for.
_MAX_BYTES = 400000


# ── pure parsers ────────────────────────────────────────────────────────────

_RE_ASSIGN = re.compile(
    r"^[ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*([0-9]+(?:\.[0-9]+)?)[ \t]*$",
    re.M)


def _is_band_name(name: str) -> bool:
    """A seal-ring generator's own declaration of how deep its edge is.

    BY WHAT IT IS, not by what one PDK calls it: a name that speaks of the SEAL
    and states a WIDTH. `sealring_edge_width` matches; `sealring_corner_radius`
    and `metal1_width` do not.
    """
    low = name.lower()
    return "seal" in low and low.endswith("width")


def band_declarations(text: str) -> List[Tuple[str, float]]:
    """Every `<seal…width> = <number>` this generator library declares."""
    out: List[Tuple[str, float]] = []
    for m in _RE_ASSIGN.finditer(text or ""):
        if _is_band_name(m.group(1)):
            out.append((m.group(1), float(m.group(2))))
    return out


_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_RE_SEPARATION = re.compile(
    rf"\b({_IDENT})\s*\.\s*(?:sep|separation)\s*\(\s*([^,]+)\s*,\s*([^,\n)]*)")
_RE_GUARD_RING_VAR = re.compile(
    r"guard[A-Za-z0-9_]*ring|ring[A-Za-z0-9_]*guard", re.I)
_RE_SEAL_RING_VAR = re.compile(
    _RE_GUARD_RING_VAR.pattern + r"|"
    r"edge[A-Za-z0-9_]*seal|seal[A-Za-z0-9_]*ring", re.I)
_RE_RULE_ID = re.compile(r"\.output\s*\(\s*['\"]([^'\"]+)['\"]")
_RE_CLEAR_ASSIGN = re.compile(rf"^[ \t]*({_IDENT})[ \t]*=[ \t]*([^\n]*)", re.M)
_RE_RULE_VALUE = re.compile(
    rf"({_IDENT})\s*\[\s*['\"]([^'\"]+)['\"]\s*\]\s*\.\s*to_f")
_RE_NUMBER = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_RE_DECK_LITERAL = re.compile(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\#[^\n]*''')


def _clearance_code(text: str) -> Tuple[str, str]:
    body = _RE_DECK_LITERAL.sub(
        lambda m: re.sub(r"[^\n]", " ", m.group()) if m.group().startswith("#") else m.group(), text)
    code = _RE_DECK_LITERAL.sub(lambda m: re.sub(r"[^\n]", " ", m.group()), body)
    return body, code


def _clearance_value(expression: str, files: Dict[str, str]) -> Tuple[Optional[float], str, Optional[Tuple[str, str]]]:
    if _RE_NUMBER.fullmatch(expression):
        value = float(expression)
        return (value, "", None) if math.isfinite(value) else (None, f"nonfinite clearance {expression}", None)
    reference = _RE_RULE_VALUE.fullmatch(expression)
    if not reference:
        return None, f"clearance expression `{expression}` could not be read", None
    table, key = reference.groups()
    values: Dict[float, List[str]] = {}
    errors: List[str] = []

    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError(f"duplicate JSON key {name}")
            result[name] = value
        return result

    for path, text in sorted(files.items()):
        if not re.search(r'"' + re.escape(table) + r'"\s*:', text):
            continue
        try:
            json.loads(text, object_pairs_hook=pairs)
        except (ValueError, TypeError) as exc:
            errors.append(f"{path} is not readable JSON for {table}[{key!r}]: {exc}")
            continue
        decoder = json.JSONDecoder(object_pairs_hook=pairs)
        for table_match in re.finditer(r'"' + re.escape(table) + r'"\s*:', text):
            start = table_match.end()
            while start < len(text) and text[start].isspace():
                start += 1
            try:
                candidate, end = decoder.raw_decode(text, start)
            except ValueError:
                continue
            if not isinstance(candidate, dict):
                errors.append(f"{path} has no readable {table} rule table")
                continue
            if key not in candidate:
                continue
            raw = candidate[key]
            if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
                errors.append(f"{path} has no numeric {table}[{key!r}]")
                continue
            try:
                value = float(raw)
            except (ValueError, TypeError, OverflowError):
                value = math.nan
            if not math.isfinite(value) or value < 0:
                errors.append(f"{path} has no finite nonnegative {table}[{key!r}]")
                continue
            key_match = next((m for m in re.finditer(
                r'("(?:\\.|[^"\\])*")\s*:', text[start:end])
                if json.loads(m.group(1)) == key), None)
            if key_match is None:
                errors.append(f"{path} has no source location for {table}[{key!r}]")
                continue
            line = text.count("\n", 0, start + key_match.start()) + 1
            values.setdefault(value, []).append(
                f"{path}:{line} {table}[{key!r}] = {value} um")
    if errors:
        return None, "; ".join(errors), (table, key)
    if len(values) != 1:
        detail = "; ".join(where for places in values.values() for where in places)
        return None, (f"{table}[{key!r}] is conflicting: {detail}" if values else
                      f"{table}[{key!r}] was not read from a JSON rule table"), (table, key)
    value = next(iter(values))
    return value, "; ".join(values[value]), (table, key)


def clearance_declarations(text: str, *, files: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    body, code = _clearance_code(text or "")
    assignments = list(_RE_CLEAR_ASSIGN.finditer(code))
    out: List[Dict[str, Any]] = []

    def assigned(name, before):
        found = [a for a in assignments if a.start() < before and a.group(1) == name]
        if not found:
            return None
        assignment = found[-1]
        end = assignment.end(2)
        while (code[assignment.start(2):end].count("(")
               > code[assignment.start(2):end].count(")") and end < len(code)):
            next_line = code.find("\n", end + 1)
            end = len(code) if next_line < 0 else next_line
        return body[assignment.start(2):end].strip(), assignment.start()

    def marker(expression, before, seen=(), intersected=False):
        if re.fullmatch(_IDENT, expression):
            if (_RE_GUARD_RING_VAR.search(expression)
                    or intersected and _RE_SEAL_RING_VAR.search(expression)):
                return expression
            if expression in seen:
                return None
            source = assigned(expression, before)
            if source:
                return marker(source[0], source[1], (*seen, expression), intersected)
        qualified = re.fullmatch(
            rf"({_IDENT})\s*\.\s*and\s*\(\s*({_IDENT})\s*\)", expression)
        if qualified and any(marker(v, before, seen, True) for v in qualified.groups()):
            return expression
        return None

    for match in _RE_SEPARATION.finditer(code):
        marker_expression = body[match.start(2):match.end(2)].strip()
        seal = marker(marker_expression, match.start())
        if not seal:
            continue
        expression = body[match.start(3):match.end(3)].strip()
        um = re.fullmatch(r"(.+?)\s*\.\s*um", expression)
        value_expression = um.group(1).strip() if um else expression
        seen = set()
        before = match.start()
        while re.fullmatch(_IDENT, value_expression) and value_expression not in seen:
            seen.add(value_expression)
            source = assigned(value_expression, before)
            if not source:
                break
            value_expression, before = source
        value, basis, reference = _clearance_value(value_expression, files or {}) if um else (
            None, f"clearance `{expression}` has no readable um value", None)
        tail = _RE_RULE_ID.search(body, match.start(3), min(len(body), match.start(3) + 400))
        out.append({"prime_layer": match.group(1), "marker": seal, "um": value,
                    "rule": tail.group(1) if tail else None,
                    "line": body.count("\n", 0, match.start()) + 1,
                    "value_basis": basis, "reference": reference,
                    "error": basis if value is None else ""})
    return out

# ── the technology reads ────────────────────────────────────────────────────

def _read_files(run_sh: ShellFn, find_cmd: str) -> Tuple[Dict[str, str], str]:
    """({path: text}, why-not). `find_cmd` must print one path per line."""
    # `while read` rather than `for f in $(…)`: a path is a path, not a word
    # list. `head -c` caps what a mis-aimed search can drag back.
    cmd = (f"{{ {find_cmd} ; }} | while IFS= read -r f; do "
           f"echo \"{_SEP}$f\"; cat \"$f\"; done | head -c {_MAX_BYTES}")
    try:
        rc, out = run_sh(cmd)
    except Exception as exc:                                   # noqa: BLE001
        return {}, f"the technology could not be read: {exc}"
    if not (out or "").strip():
        return {}, (f"nothing was returned by `{find_cmd}` (rc={rc}), so the "
                    f"technology has not been read")
    files: Dict[str, str] = {}
    cur: Optional[str] = None
    buf: List[str] = []
    for line in (out or "").splitlines():
        if line.startswith(_SEP):
            if cur is not None:
                files[cur] = "\n".join(buf)
            cur, buf = line[len(_SEP):].strip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        files[cur] = "\n".join(buf)
    if not files:
        return {}, (f"`{find_cmd}` returned output that carried no file "
                    f"(rc={rc})")
    if len(out) >= _MAX_BYTES:
        # A CAP THAT FIRES IS A READ THAT DID NOT FINISH. The last file came
        # back cut in half and its declarations are missing from the parse; a
        # partial read that answers is worse than one that says it could not.
        return {}, (f"`{find_cmd}` returned {len(out)} bytes, at or over this "
                    f"module's {_MAX_BYTES}-byte cap, so the last file was cut "
                    f"and the technology has been read only in part")
    return files, ""


def ring_band_um(pdk_dir: str, run_sh: ShellFn) -> Tuple[Optional[float], str]:
    """(the seal ring's edge depth in um, the basis) or (None, why not).

    Read from the generator's OWN cell library — the same tree the PDK's
    `sealring.py` puts on `sys.path` before importing the cells it draws.
    Two different declared widths is NOT_MEASURED naming both: picking one
    would be this program choosing foundry data.
    """
    # `-L` / `-R`: a PDK directory is very often a SYMLINK into a versioned
    # store (measured: `gf180mcuD -> ciel/gf180mcu/versions/<sha>/gf180mcuD` in
    # this image), and a search that does not follow one reports an empty
    # technology with no error at all.
    find = (f"find -L {pdk_dir} -maxdepth 8 -type f -name '*.py' 2>/dev/null "
            f"| grep -i seal")
    files, why = _read_files(run_sh, find)
    if why:
        return None, (f"no seal-ring generator source could be read under "
                      f"{pdk_dir}: {why}")
    found: Dict[float, List[str]] = {}
    for path, text in sorted(files.items()):
        for name, val in band_declarations(text):
            found.setdefault(val, []).append(f"{path}:{name}")
    if not found:
        return None, (f"none of the seal-ring generator sources under "
                      f"{pdk_dir} ({', '.join(sorted(files))}) declares a seal "
                      f"width, so how deep the ring's edge is was not read")
    if len(found) > 1:
        detail = "; ".join(f"{v} um ({', '.join(w)})"
                           for v, w in sorted(found.items()))
        return None, (f"the seal-ring generator sources under {pdk_dir} "
                      f"declare more than one seal width — {detail} — and "
                      f"choosing between them here would be this flow deciding "
                      f"foundry data")
    val = next(iter(found))
    return val, (f"the seal-ring generator's own cell library declares "
                 f"{found[val][0]} = {val} um")


def guard_ring_clearance_um(pdk_dir: str,
                            run_sh: ShellFn) -> Tuple[Optional[float], str]:
    """(the deck's guard-ring-marker clearance in um, the basis) or (None, why).

    The BINDING one, which is the LARGEST the deck states: a core that clears
    the widest separation clears every narrower one. Every distinct value is
    named in the basis so a reader can check the choice against the deck.
    """
    find = (f"grep -RIlEi {shlex.quote(_RE_SEAL_RING_VAR.pattern)} "
            f"--include='*.rb' --include='*.drc' --include='*.lydrc' "
            f"-- {shlex.quote(pdk_dir)} 2>/dev/null")
    files, why = _read_files(run_sh, find)
    if why:
        return None, (f"no DRC deck stating a guard-ring-marker separation "
                      f"could be read under {pdk_dir}: {why}")
    decls: List[Dict[str, Any]] = []
    for path, text in sorted(files.items()):
        for d in clearance_declarations(text):
            d["file"] = path
            decls.append(d)
    if not decls:
        return None, (f"the deck files under {pdk_dir} that mention a "
                      f"seal-ring marker ({', '.join(sorted(files))}) state "
                      f"no readable marker separation in um")
    references = {d["reference"] for d in decls if d["reference"]}
    if references:
        json_files, why = _read_files(
            run_sh, f"find -L {shlex.quote(pdk_dir)} -type f -name '*.json' 2>/dev/null")
        names = ", ".join(f"{table}[{key!r}]" for table, key in sorted(references))
        if why:
            return None, f"the JSON rule table for {names} could not be read: {why}"
        for text in files.values():
            for name in re.findall(r"File\.[^\n]*?['\"]([^'\"\n]+\.json)['\"]", text):
                candidates = [p for p in json_files if p.endswith("/" + name.rsplit("/", 1)[-1])]
                if not candidates:
                    return None, f"the deck's JSON input {name} for {names} could not be read"
                for path in candidates:
                    try:
                        json.loads(json_files[path])
                    except ValueError as exc:
                        return None, f"the deck's JSON input {path} for {names} is malformed: {exc}"
        decls = []
        for path, text in sorted(files.items()):
            for d in clearance_declarations(text, files=json_files):
                d["file"] = path
                decls.append(d)
    unread = [f"{d['file']}:{d['line']} "
              f"{d['rule'] or 'seal clearance'}: {d['error']}"
              for d in decls if d["um"] is None]
    if unread:
        return None, "the seal-ring clearance could not be read: " + "; ".join(unread)
    worst = max(d["um"] for d in decls)
    evidence = sorted({f"{d['file']}:{d['line']}"
                       + (f" rule {d['rule']}" if d["rule"] else "")
                       + (f"; {d['value_basis']}" if d["value_basis"] else "")
                       for d in decls})
    values = sorted({d["um"] for d in decls})
    return worst, (
        f"the PDK's own deck requires {worst} um between the seal-ring "
        f"marker and the prime die; " + "; ".join(evidence)
        + (f", stating {values} um" if len(values) > 1 else ""))


def derive(pdk_dir: str, run_sh: ShellFn,
           band_um: Optional[float] = None,
           band_basis: str = "") -> Dict[str, Any]:
    """The margin a DIE's core owes its own seal ring, and how it was reached.

        {"margin_um": 26.0 | None,
         "band_um": …, "band_basis": …,
         "clearance_um": …, "clearance_basis": …,
         "not_measured": {"band_um": why, …},     # only what is missing
         "chain": [ …, … ]}                       # PDK text -> numbers

    `band_um` may be supplied by a caller that MEASURED it (the inner extent of
    the ring the generator actually built). That measurement outranks reading
    the generator's parameter, and the basis says which was used.
    """
    rec: Dict[str, Any] = {"pdk_dir": pdk_dir, "not_measured": {}, "chain": []}

    if band_um is None:
        band_um, why = ring_band_um(pdk_dir, run_sh)
        band_basis = why
    if band_um is None:
        rec["not_measured"]["band_um"] = band_basis
    rec["band_um"] = band_um
    rec["band_basis"] = band_basis
    rec["chain"].append(f"band: {band_basis}")

    clear_um, clear_basis = guard_ring_clearance_um(pdk_dir, run_sh)
    if clear_um is None:
        rec["not_measured"]["clearance_um"] = clear_basis
    rec["clearance_um"] = clear_um
    rec["clearance_basis"] = clear_basis
    rec["chain"].append(f"clearance: {clear_basis}")

    if band_um is None or clear_um is None:
        rec["margin_um"] = None
        rec["margin_basis"] = (
            f"{NOT_MEASURED}: " + "; ".join(
                f"{k} — {v}" for k, v in sorted(rec["not_measured"].items())))
    else:
        rec["margin_um"] = float(band_um) + float(clear_um)
        rec["margin_basis"] = (
            f"{band_um} um of seal-ring band plus {clear_um} um of deck "
            f"clearance = {rec['margin_um']} um on every edge")
        rec["chain"].append(f"margin: {rec['margin_basis']}")
    return rec


def shell_from_argv(run_argv: Callable[..., Any]) -> ShellFn:
    """Adapt a `runner.run_argv(argv, env, timeout=…) -> (rc, out, err)` to the
    `run_sh` this module wants. Kept here so both callers adapt identically."""
    def _sh(cmd: str) -> Tuple[int, str]:
        rc, out, _err = run_argv(["sh", "-c", cmd], {}, timeout=180)
        return int(rc), (out or "")
    return _sh
