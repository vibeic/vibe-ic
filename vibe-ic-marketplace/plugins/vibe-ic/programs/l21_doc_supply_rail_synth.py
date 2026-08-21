#!/usr/bin/env python3
"""Derive the power-intent rail set from a supply table the design's OWN docs STATE.

WHY (the measured defect, chip-AGNOSTIC)
----------------------------------------
`l21_macro_supply_rail_declared_check` and `hardmacro_supply_intent` both read
the design's declared rails out of `L21_POWER_INTENT.fields`. When that layer is
empty the consequence chain is deterministic and expensive::

    no rail declared
      -> every hard-macro POWER/GROUND pin classifies as `undeclared`
      -> the l21 pre-route gate FAILs place-and-route
      -> no DEF -> no GDS -> a mixed-signal top with no digital half

v1.8.79/v1.8.95 landed `l21_macro_supply_rail_synth`, which removes the CAUSE by
deriving the rails from the design's own hard-macro **LEFs**. That producer is
correct and it is wired (`phase1_doc_one_shot_runner`, post L19-L23 emit). It
cannot help a design whose rails are stated in a **document table** rather than
carried on a macro pin, and — measured on a real mixed-signal cell — it also
cannot help a design whose macros are its OWN analog blocks, because those LEFs
are generated at A8 in Phase 3 and simply do not exist when the Phase-1 producer
runs::

    $ l21_macro_supply_rail_synth <proj>
    verdict: NOT_APPLICABLE
    count: 0 hard macro(s) with PG pins across 0 LEF file(s), 0 master(s)

while the design's own `L9_CONSTRAINTS.md` states, in a two-row table under a
heading called `## Supplies / levels`, exactly the rails the gate is asking for.

This program is the same contract against the other evidence source: the
document table. Same emit vocabulary, same never-invent rules, same
never-overwrite rule, so the two producers compose instead of fighting.

WHAT IT DERIVES, AND FROM WHAT
------------------------------
Markdown tables in the design's own converted input documents
(`phase1/input_doc/`, `input/docs/`). A table qualifies as a SUPPLY table when
either

* its FIRST column header names a rail (`Rail`, `Supply`, `Supplies`, `Power
  net`, `Net`, `Domain`, `Power domain`) -- the strong signal, heading-
  independent; or
* the markdown heading it sits under names supplies (`Supplies`, `Supply`,
  `Power`, `Rails`, `Power domains`, `Voltage domains`, `Levels`).

and then, ROW BY ROW, a row contributes a rail only when BOTH of

* the first cell yields a leading bare identifier (`IOVDD (IO + analog input
  domain)` -> `IOVDD`), and
* some other cell in the SAME row states a voltage in VOLTS (`1.8 V`, `500 mV`).

A row missing either contributes nothing. That per-row voltage requirement is
what keeps a `| Field | Value |` table under a supply heading from donating its
non-supply rows, and it is why a `## Power` table of milliwatts contributes
nothing at all.

WHAT IT REFUSES TO DO
---------------------
* It never invents a rail name. Names come from the document's own table cell.
* It never invents a voltage. A rail without a stated voltage in its own row is
  not extracted at all -- there is no "assume the core rail" branch.
* It never invents a GROUND. A design whose documents state supplies and no
  ground gets its power rails declared with ``ground_net: null`` and an explicit
  ``ground_status`` naming the gap, plus a loud line on stdout and a verdict of
  ``DERIVED_NO_GROUND_STATED``. Inventing a `VSS` here would be indistinguishable
  from extraction and would be a lie in the layer the PDN is built from.
* It never overwrites an existing declaration. Anything already declared is left
  byte-identical; this only ADDS what is missing, tested against the same
  consumer-visible key set (`name`/`rail`/`supply`) its sibling uses, so the two
  producers are idempotent with respect to each other as well as themselves.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

PROGRAM = "l21_doc_supply_rail_synth"
VERSION = "1.0.0"

# Key spellings the consumer gate accepts -- IDENTICAL to
# `l21_macro_supply_rail_synth`, so a design that gets rails from both sources
# ends up with one vocabulary rather than two.
_POWER_KEY = "power_net"
_GROUND_KEY = "ground_net"
_NAME_KEY = "name"

# ── what counts as a supply table ────────────────────────────────────────────
#
# Two independent qualifiers. Neither alone admits a row: every row still has to
# state a voltage AND yield an identifier (see `_rows_from_table`).

# Strong signal: the first column header names a rail. Heading-independent,
# because a well-formed supply table is recognisable on its own.
_RAIL_COL_RE = re.compile(
    r"^\s*(?:power\s+)?(?:rail|rails|supply|supplies|net|nets|domain|domains|"
    r"power\s*net|supply\s*net|power\s*domain|voltage\s*domain)\s*$", re.I)

# A column that carries the level. Used to PREFER a cell when several in the row
# state volts; a row is never rejected for lacking such a header.
_VOLT_COL_RE = re.compile(
    r"^\s*(?:voltage|voltages|volts?|level|levels|nominal|nom\.?|value|"
    r"v|vdd|supply\s*voltage|typ\.?|typical)\s*$", re.I)

# Heading signal.
_SUPPLY_HEADING_RE = re.compile(
    r"\b(?:supply|supplies|power|rail|rails|voltage|voltages|level|levels|"
    r"domain|domains)\b", re.I)

# A voltage literal, in volts or millivolts. Deliberately NOT matching W / mW /
# A / mA / Hz: a power or current table is not a supply-level table.
_VOLT_RE = re.compile(r"(?<![A-Za-z0-9_.])([0-9]+(?:\.[0-9]+)?)\s*(mV|V)\b")

# The leading bare identifier of a cell. `IOVDD (IO + analog input domain)` ->
# `IOVDD`; `**VDD_CORE**` -> `VDD_CORE`.
_IDENT_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]{0,31})\b")

# Names that are a table's own furniture rather than a rail. Chip-AGNOSTIC:
# these are English/markdown words, not any design's signal names. The header
# row is already excluded structurally by the `---|---` separator; this is a
# cheap second line for documents whose tables repeat a header mid-table.
_NOT_A_RAIL = {
    "field", "fields", "value", "values", "spec", "specs", "target", "targets",
    "range", "ranges", "unit", "units", "note", "notes", "min", "max", "typ",
    "typical", "nominal", "parameter", "parameters", "description", "desc",
    "item", "items", "name", "names", "signal", "signals", "pin", "pins",
    "rail", "rails", "supply", "supplies", "net", "nets", "domain", "domains",
    "voltage", "voltages", "level", "levels", "total", "sum", "n", "a",
}

# A rail whose NAME says it is the return path. Electrical convention, not a
# chip literal. A stated 0 V also classifies as ground.
_GROUND_NAME_RE = re.compile(
    r"^(?:v?ss[a-z0-9_]*|gnd[a-z0-9_]*|[adiv]gnd[a-z0-9_]*|vsub[a-z0-9_]*|"
    r"ground|vgnd[a-z0-9_]*)$", re.I)

# Documents to read. Both roots, both extensions -- `phase1/input_doc/*.txt` is
# the converted copy and `input/docs/*.md` the original; they are usually the
# same bytes, so identical CONTENT is de-duplicated rather than double-counted.
_DOC_GLOBS: Tuple[str, ...] = (
    "phase1/input_doc/**/*.txt",
    "phase1/input_doc/**/*.md",
    "input/docs/**/*.md",
    "input/docs/**/*.txt",
)


def _strip_md(cell: str) -> str:
    """Markdown emphasis / code ticks / links off, whitespace collapsed."""
    s = cell.strip()
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)   # [text](url) -> text
    s = s.replace("**", "").replace("`", "").replace("*", "").replace("_", "_")
    return re.sub(r"\s+", " ", s).strip()


def _split_row(line: str) -> List[str]:
    """`| a | b |` -> ['a', 'b']. Leading/trailing empties from the outer pipes
    are dropped; interior empties are KEPT so column indices stay aligned."""
    s = line.strip()
    if not s.startswith("|"):
        return []
    cells = s.split("|")
    if cells and cells[0].strip() == "":
        cells = cells[1:]
    if cells and cells[-1].strip() == "":
        cells = cells[:-1]
    return [_strip_md(c) for c in cells]


def _is_separator(cells: List[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells)


def _volts(cell: str) -> Optional[Tuple[float, str]]:
    """(volts, matched_text) if the cell states a voltage, else None."""
    m = _VOLT_RE.search(cell or "")
    if not m:
        return None
    v = float(m.group(1))
    if m.group(2).lower() == "mv":
        v /= 1000.0
    return v, m.group(0).strip()


def _rail_name(cell: str) -> Optional[str]:
    m = _IDENT_RE.match(cell or "")
    if not m:
        return None
    name = m.group(1)
    if name.lower() in _NOT_A_RAIL:
        return None
    return name


def _tables(text: str) -> List[Dict[str, Any]]:
    """Every markdown table in `text`, with the heading it sits under and the
    1-based source line of each row."""
    out: List[Dict[str, Any]] = []
    heading = ""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        hm = re.match(r"^\s{0,3}#{1,6}\s+(.*?)\s*$", line)
        if hm:
            heading = hm.group(1)
            i += 1
            continue
        cells = _split_row(line)
        if not cells or len(cells) < 2:
            i += 1
            continue
        # A table is header, separator, then >=1 data row.
        sep = _split_row(lines[i + 1]) if i + 1 < len(lines) else []
        if not _is_separator(sep):
            i += 1
            continue
        header = cells
        rows: List[Tuple[int, List[str]]] = []
        j = i + 2
        while j < len(lines):
            rc = _split_row(lines[j])
            if not rc:
                break
            if not _is_separator(rc):
                rows.append((j + 1, rc))
            j += 1
        out.append({"heading": heading, "header": header, "rows": rows,
                    "header_line": i + 1})
        i = j
    return out


def _table_qualifies(table: Dict[str, Any]) -> Optional[str]:
    """Why this table is a supply table, or None."""
    header = table["header"]
    if header and _RAIL_COL_RE.match(header[0] or ""):
        return f"first column header {header[0]!r} names a rail"
    if _SUPPLY_HEADING_RE.search(table["heading"] or ""):
        return f"markdown heading {table['heading']!r} names supplies"
    return None


def _volt_col(header: List[str]) -> Optional[int]:
    for idx, h in enumerate(header):
        if idx and _VOLT_COL_RE.match(h or ""):
            return idx
    return None


def _rows_from_table(table: Dict[str, Any], rel: str,
                     why: str) -> List[Dict[str, Any]]:
    """The rails this table STATES, or nothing.

    A row contributes only when it yields BOTH a leading identifier and a
    voltage. The TABLE then contributes only when its contributing rows form a
    coherent supply table, by two structural tests that are the load-bearing
    anti-false-positive guards:

    * **Majority.** At least half the data rows must contribute. A supply table
      states a level on (nearly) every row; a SPEC table happens to mention
      volts on one of them.
    * **Same column.** Every contributing row must take its voltage from the
      SAME column index. In a supply table the level lives in a level column;
      in a spec table a stray voltage turns up in a free-text note.

    Both were written from a measured false positive, and the measurement is
    worth keeping because it is the exact shape this program must not have. On a
    real mixed-signal cell the heading qualifier admitted::

        ## Block B — `ldo` : low-dropout regulator (×1, supplies one modulator core)
        | Spec | Target | Range | Unit | Note |
        | Dropout | ≤ 0.5 | — | V | headroom (1.8 IOVDD − 1.2 CORE = 0.6 V available) |

    -- the heading contains the word "supplies", so a *spec* named `Dropout`
    was extracted as a 0.6 V power rail, with the 0.6 V scraped out of a
    parenthetical in a NOTE. That is a fabricated rail in the layer the PDN is
    built from, which is worse than declaring nothing. It is rejected here
    because only 1 of that table's 7 data rows contributes (14 %, below the
    majority floor) -- a structural property, not a blacklist of the word
    `Dropout`, so it generalises to every spec table rather than to that one.
    """
    header = table["header"]
    vcol = _volt_col(header)
    cand: List[Dict[str, Any]] = []
    for line_no, cells in table["rows"]:
        if len(cells) < 2:
            continue
        name = _rail_name(cells[0])
        if not name:
            continue
        got = None
        src_col = None
        if vcol is not None and vcol < len(cells):
            got = _volts(cells[vcol])
            src_col = vcol
        if got is None:
            for idx, c in enumerate(cells):
                if idx == 0:
                    continue
                got = _volts(c)
                if got is not None:
                    src_col = idx
                    break
        if got is None:
            continue
        volts, matched = got
        cand.append({
            "rail": name,
            "voltage_v": volts,
            "evidence": {
                "file": rel,
                "line": line_no,
                "matched_text": " | ".join(cells)[:200],
            },
            "why_table": why,
            "voltage_literal": matched,
            "heading": table["heading"],
            "_col": src_col,
        })

    n_rows = len([1 for _ln, c in table["rows"] if len(c) >= 2])
    if not cand or not n_rows:
        return []
    if len({c["_col"] for c in cand}) != 1:
        return []
    if len(cand) * 2 < n_rows:
        return []
    for c in cand:
        c.pop("_col", None)
    return cand


def _doc_sources(proj: Path, doc_globs: Optional[List[str]] = None
                 ) -> List[Tuple[Path, str, str]]:
    """(path, project-relative path, text) for each distinct document.

    De-duplicated by CONTENT: `phase1/input_doc/X.txt` is normally a verbatim
    copy of `input/docs/X.md`, and counting one table twice would double every
    evidence entry without adding a fact.
    """
    seen_text: Set[int] = set()
    out: List[Tuple[Path, str, str]] = []
    for pat in (doc_globs or list(_DOC_GLOBS)):
        for p in sorted(proj.glob(pat)):
            if not p.is_file():
                continue
            try:
                text = p.read_text(errors="replace")
            except OSError:
                continue
            h = hash(text)
            if h in seen_text:
                continue
            seen_text.add(h)
            try:
                rel = str(p.resolve().relative_to(proj.resolve()))
            except ValueError:
                rel = str(p)
            out.append((p, rel, text))
    return out


def doc_sources(proj: Path, doc_globs: Optional[List[str]] = None
                ) -> List[Tuple[Path, str, str]]:
    """Public name for the document set `derive` reads.

    A second reader that wants to CORROBORATE `derive`'s answer has to read the
    same documents it read. Reading a different set -- a wider glob, a different
    de-duplication -- gives a denominator that is not the one being checked, and
    the corroboration then reports on documents `derive` never saw. Exported so
    `phase1_layer_demand_probe` can hold both readings to one corpus without
    reaching for a private name.
    """
    return _doc_sources(proj, doc_globs)


def derive(proj: Path, doc_globs: Optional[List[str]] = None
           ) -> Dict[str, Any]:
    """Every rail the design's own documents STATE, with evidence.

    Pure: reads documents, writes nothing. This is the function the tests and
    the negative controls drive.
    """
    found: List[Dict[str, Any]] = []
    docs_read = 0
    tables_seen = 0
    tables_qualified = 0
    for _p, rel, text in _doc_sources(proj, doc_globs):
        docs_read += 1
        for table in _tables(text):
            tables_seen += 1
            why = _table_qualifies(table)
            if not why:
                continue
            tables_qualified += 1
            found.extend(_rows_from_table(table, rel, why))

    # One rail may be stated in several documents (a datasheet and a
    # constraints doc). Keep the FIRST statement and record the rest as
    # corroboration rather than emitting a duplicate domain.
    by_name: Dict[str, Dict[str, Any]] = {}
    for f in found:
        key = f["rail"]
        if key in by_name:
            by_name[key].setdefault("also_stated_in", []).append(f["evidence"])
            continue
        by_name[key] = dict(f)
    rails = [by_name[k] for k in sorted(by_name)]
    for r in rails:
        r["use"] = ("GROUND"
                    if (_GROUND_NAME_RE.match(r["rail"])
                        or r["voltage_v"] == 0.0)
                    else "POWER")
    return {
        "rails": rails,
        "docs_read": docs_read,
        "tables_seen": tables_seen,
        "tables_qualified": tables_qualified,
    }


def _declared_nets(entries: List[Any], keys: Tuple[str, ...]) -> Set[str]:
    out: Set[str] = set()
    for e in entries:
        if isinstance(e, str):
            out.add(e)
        elif isinstance(e, dict):
            for k in keys:
                v = e.get(k)
                if isinstance(v, str) and v:
                    out.add(v)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Derive power_domains[] from a supply table the design's "
                    "own documents state.")
    ap.add_argument("project")
    ap.add_argument("--l21", help="power-intent layer JSON (default: "
                                  "phase1/generated_docs/L21_POWER_INTENT.json)")
    ap.add_argument("--doc", nargs="*",
                    help="document glob(s), project-relative "
                         "(default: phase1/input_doc + input/docs, md + txt)")
    ap.add_argument("--apply", action="store_true",
                    help="write the derived rails into the layer (default: dry run)")
    ap.add_argument("--json", help="write the result JSON here")
    args = ap.parse_args(argv)

    proj = Path(args.project).resolve()
    l21 = Path(args.l21) if args.l21 else \
        proj / "phase1" / "generated_docs" / "L21_POWER_INTENT.json"

    if not l21.is_file():
        print(f"[FAIL] {PROGRAM}: power-intent layer not found: {l21}",
              file=sys.stderr)
        return 2

    res = derive(proj, args.doc)
    rails = res["rails"]

    doc = json.loads(l21.read_text())
    container = doc.get("fields") if isinstance(doc.get("fields"), dict) else doc
    existing = container.get("power_domains")
    if not isinstance(existing, list):
        existing = []

    # "Already declared" must mean declared where BOTH readers can see it --
    # the same narrower (consumer) key set `l21_macro_supply_rail_synth` tests
    # against, so the two producers never re-add each other's work and never
    # leave a rail half-declared.
    consumer_visible = _declared_nets(existing, ("name", "rail", "supply"))

    grounds = [r for r in rails if r["use"] == "GROUND"]
    powers = [r for r in rails if r["use"] == "POWER"]
    ref_gnd = grounds[0]["rail"] if grounds else None

    added: List[Dict[str, Any]] = []
    for r in powers:
        if r["rail"] in consumer_visible:
            continue
        entry: Dict[str, Any] = {
            _NAME_KEY: r["rail"],
            _POWER_KEY: r["rail"],
            _GROUND_KEY: ref_gnd,
            "derived_by": PROGRAM,
            "derived_from": {
                "doc_supply_table": r["why_table"],
                "heading": r["heading"],
                "evidence": r["evidence"],
            },
            "voltage_v": r["voltage_v"],
            "voltage_status": "stated in the design's own documents",
            "voltage_evidence": {**r["evidence"],
                                 "matched_text": r["voltage_literal"]},
        }
        if ref_gnd is None:
            entry["ground_status"] = (
                "no ground rail is stated in the design's own documents; "
                "not invented here -- the return path must be declared by the "
                "design or derived from a macro LEF GROUND pin")
        if r.get("also_stated_in"):
            entry["derived_from"]["also_stated_in"] = r["also_stated_in"]
        added.append(entry)

    primary_power = added[0][_POWER_KEY] if added else (
        powers[0]["rail"] if powers else None)
    for r in grounds:
        if r["rail"] in consumer_visible:
            continue
        added.append({
            _NAME_KEY: r["rail"],
            _POWER_KEY: primary_power,
            _GROUND_KEY: r["rail"],
            "derived_by": PROGRAM,
            "derived_from": {
                "doc_supply_table": r["why_table"],
                "heading": r["heading"],
                "evidence": r["evidence"],
            },
            "voltage_v": 0.0,
            "voltage_status": "ground reference",
        })

    if not rails:
        verdict = "NOT_APPLICABLE"
    elif not added:
        verdict = "ALREADY_DECLARED"
    elif ref_gnd is None:
        verdict = "DERIVED_NO_GROUND_STATED"
    else:
        verdict = "DERIVED"

    print(f"=== {PROGRAM} ===")
    print(f"  verdict: {verdict}")
    print(f"  scanned: {res['docs_read']} document(s), {res['tables_seen']} "
          f"table(s), {res['tables_qualified']} qualified as supply table(s)")
    print(f"  stated: {len(rails)} rail(s) "
          f"({len(powers)} POWER, {len(grounds)} GROUND)")
    for r in rails:
        print(f"    {r['use']:6s} {r['rail']}: {r['voltage_v']} V  "
              f"[{r['evidence']['file']}:{r['evidence']['line']}] "
              f"({r['why_table']})")
    if verdict == "DERIVED_NO_GROUND_STATED":
        print("  [DISCLOSED] the design's documents state NO ground rail. "
              "power_domains[].ground_net is null and NOT invented; the return "
              "path must come from the design or from a macro LEF GROUND pin.")
    print(f"  adding: {len(added)} domain(s) "
          f"({len(consumer_visible)} already declared and left byte-identical)")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "program": PROGRAM, "version": VERSION, "verdict": verdict,
            "scanned": {k: res[k] for k in
                        ("docs_read", "tables_seen", "tables_qualified")},
            "stated_rails": rails,
            "added": added,
            "already_declared": sorted(consumer_visible),
        }, indent=2, ensure_ascii=False) + "\n")

    if args.apply and added:
        container["power_domains"] = list(existing) + added
        ev = doc.get("extraction_evidence")
        if not isinstance(ev, dict):
            ev = {}
        for e in added:
            src = e["derived_from"]["evidence"]["file"]
            ev.setdefault(src, []).append({
                "literal": e["derived_from"]["evidence"]["matched_text"],
                "label": (f"power_rail {e[_NAME_KEY]} "
                          f"({e['derived_from']['evidence']['file']}:"
                          f"{e['derived_from']['evidence']['line']})"),
            })
        doc["extraction_evidence"] = ev
        if doc.get("extraction_status") == "NOT_YET_EXTRACTED":
            doc["extraction_status"] = "PARTIALLY_EXTRACTED"
        l21.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        print(f"  [APPLIED] {l21}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
