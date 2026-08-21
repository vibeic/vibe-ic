#!/usr/bin/env python3
"""l8_doc_clock_freq_synth.py — bind a clock frequency the design STATES in a
document table to the L8 clock records the SAME ROW names.

WHY THIS EXISTS (measured, 2026-07-31, agent C4 round 4)
========================================================
`sdc_gen.py` resolves the create_clock period from, in order:

    1. L8.clock_mhz                      (scalar)
    2. L8.clock_domains[].freq_mhz / period_ns / freq_hz
    3. a staged SDC file
    4. a HARD-CODED plugin default

On a real mixed-signal cell whose L5 spec table states

    | fclk | 1.0 | 0.1-10 | MHz | modulator clock (CK4/5/6) (est) |

and whose L1 top-pin list declares `CK4/CK5/CK6`, Phase 1 emitted the number
into `L8.timing_constants[]` and the names into `L8.clocks[]` and joined
NEITHER into the two fields the consumer reads. Resolution fell through to
step 4 and the emitted SDC read

    create_clock -name clk -period 20      (50 MHz)

against a design that states 1.0 MHz / 1000 ns — a 50x wrong period on a clock
name the design does not have. Measured, rc=0, printed with the word `PASS`.

That is the same defect shape `l21_doc_supply_rail_synth` was written for: a
fact the design WROTE DOWN, in a table, never reaching the layer that consumes
it. This program is that producer for the clock contract, and it deliberately
shares the sibling's contract:

  * it reads ONLY the design's own input documents;
  * it NEVER invents a clock — it only fills records L8 ALREADY declares;
  * it NEVER overwrites a frequency some other producer already resolved;
  * every bound value carries file + line + the matched row;
  * it degrades LOUDLY (a distinct verdict + a stdout line), never silently.

THE BINDING RULE, and why it is this strict
===========================================
A table row binds a frequency to a clock only when ALL of the following hold:

  (a) the row yields exactly ONE resolvable frequency — a cell that parses
      whole as a number, plus a frequency unit (Hz/kHz/MHz/GHz) in that same
      row. A cell like `0.1-10` (a Range column) does NOT parse whole and is
      therefore never mistaken for the target;
  (b) the SAME ROW names at least one clock that L8 ALREADY DECLARES. The
      clock vocabulary comes from L8, never from the row — so a row cannot
      introduce a clock, only speak about one;
  (c) if the row resolves two or more DIFFERENT frequencies, nothing is bound
      and the verdict is AMBIGUOUS_NOT_BOUND. Guessing which column the
      design meant is exactly the fabrication this program exists to stop.

(b) is the anti-false-positive guard, and it is the one that matters. The
sibling program shipped a MEASURED false positive (a spec row named `Dropout`
became a 0.6 V power rail because a heading contained the word "supplies"), so
this one refuses to derive anything from row shape alone: the design must
already have declared the clock, in L8, by name.

COMPRESSED ENUMERATIONS
=======================
Designs write `CK4/5/6` far more often than `CK4/CK5/CK6`. A token of the form
`<alpha><digit>(/<digit>)+` expands to `<alpha><digit>` per digit, and each
expansion must STILL match a clock L8 declares, so the expansion cannot invent
a name either. `CK4/5/6` against declared {CK4,CK5,CK6} binds three clocks;
against declared {CK4} it binds one and reports the two it could not place.

WHAT IT WRITES
==============
For each bound clock, into BOTH `clocks[]` and `clock_domains[]` — the runner's
own comment calls these "the `clocks[]` view of the same physical clock", so a
frequency true of one is true of the other — the keys the consumer reads:
`freq_mhz`, `freq_hz`, `period_ns`, plus `freq_evidence` {file,line,row}.
The scalar `clock_mhz` is set ONLY when every bound clock carries the same
frequency; a genuinely multi-rate design leaves the scalar null and lets the
per-record values speak, because a scalar short-circuits the records in the
consumer and would silently pick one rate for all.

DOES IT BLOCK?
==============
No. It is a PRODUCER, not a gate — it exits 0 whenever it ran to completion,
including when it bound nothing. `l8_clock_period_actionability_check` is the
gate that blocks on an unresolvable clock, and it stays the gate: this program
either gives it something real to see or leaves it exactly as red as it was.

Chip-AGNOSTIC: no design name, PDK name, vendor part or pin literal appears in
this file. The clock vocabulary is read from the project's own L8 at run time.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

PROGRAM = "l8_doc_clock_freq_synth"
VERSION = "1.0.0"

#: L docs that carry the clock contract. Both are written, because a frequency
#: true of a clock is true of it wherever the clock is recorded, and the two
#: files are already mirrored by the runner in the other direction.
_L8_DOCS = ("L8_TIMING_WAVEFORM", "L8_RTL_CONSTANTS")

#: The two list keys that hold clock records. `clock_domains` is what
#: `sdc_gen._clock_mhz_from_l8_domains` reads; `clocks` is the sibling view.
_CLOCK_LIST_KEYS = ("clock_domains", "clocks")

#: Frequency units and their multiplier into Hz. Structural, not chip-specific.
_FREQ_UNITS: Dict[str, float] = {
    "hz": 1.0,
    "khz": 1.0e3,
    "mhz": 1.0e6,
    "ghz": 1.0e9,
}

#: A bare unit token occupying a whole cell, or trailing a number in one cell.
_RE_UNIT_ONLY = re.compile(r"^\s*(hz|khz|mhz|ghz)\s*$", re.IGNORECASE)
_RE_NUM_UNIT = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)\s*(hz|khz|mhz|ghz)\b", re.IGNORECASE)

#: A cell that parses WHOLE as a number. `0.1-10` / `0.1–10` (a Range
#: column) deliberately does not match — that is what keeps a range from being
#: read as the target value.
_RE_BARE_NUMBER = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*$")

#: `CK4/5/6` — an alphabetic stem, a digit, then further /-separated digits.
_RE_COMPRESSED_ENUM = re.compile(
    r"\b([A-Za-z][A-Za-z_]*)(\d+)((?:\s*/\s*\d+)+)\b")

#: Identifier-ish token, for scanning a row for declared clock names.
_RE_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_MD_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")


def _split_row(line: str) -> List[str]:
    """Split a markdown table row into trimmed cells."""
    s = line.strip()
    if not s.startswith("|"):
        return []
    s = s.strip("|")
    return [c.strip() for c in s.split("|")]


def _strip_md(cell: str) -> str:
    """Drop markdown emphasis / code ticks so `**1.0**` reads as `1.0`."""
    return cell.replace("*", "").replace("`", "").strip()


def _row_frequencies(cells: Sequence[str]) -> List[Tuple[float, str]]:
    """Every DISTINCT frequency this row resolves, as (hz, matched_text).

    Two shapes are accepted, and only two:
      * a number and a unit in the SAME cell   -> `100 MHz`
      * a cell that is a bare number, plus a cell that is a bare unit token
        -> the `| fclk | 1.0 | ... | MHz | ...` spec-table shape.
    A cell that does not parse WHOLE as a number can never supply the value,
    which is what excludes a Range column such as `0.1-10`.
    """
    found: List[Tuple[float, str]] = []

    def _add(hz: float, text: str) -> None:
        for existing, _ in found:
            if existing == hz:
                return
        found.append((hz, text))

    clean = [_strip_md(c) for c in cells]

    # Shape 1 — number and unit adjacent inside one cell.
    for cell in clean:
        for m in _RE_NUM_UNIT.finditer(cell):
            try:
                val = float(m.group(1))
            except ValueError:
                continue
            mult = _FREQ_UNITS.get(m.group(2).lower())
            if mult and val > 0:
                _add(val * mult, m.group(0))

    # Shape 2 — a standalone unit cell governs the row's bare-number cells.
    unit_mults = [
        _FREQ_UNITS[_RE_UNIT_ONLY.match(c).group(1).lower()]  # type: ignore
        for c in clean if _RE_UNIT_ONLY.match(c)
    ]
    if unit_mults:
        # Exactly one unit column, or the row is not a clean spec row.
        if len(set(unit_mults)) == 1:
            mult = unit_mults[0]
            for cell in clean:
                m = _RE_BARE_NUMBER.match(cell)
                if not m:
                    continue
                try:
                    val = float(m.group(1))
                except ValueError:
                    continue
                if val > 0:
                    _add(val * mult, cell)
        else:
            # Mixed units in one row: refuse, and let the caller report
            # AMBIGUOUS rather than pick.
            for mult in unit_mults:
                _add(-abs(mult), "mixed-unit row")
    return found


def _expand_compressed(text: str) -> List[str]:
    """`CK4/5/6` -> ['CK4','CK5','CK6']. Returns [] when nothing compressed."""
    out: List[str] = []
    for m in _RE_COMPRESSED_ENUM.finditer(text):
        stem, first, rest = m.group(1), m.group(2), m.group(3)
        out.append(f"{stem}{first}")
        for d in re.findall(r"\d+", rest):
            out.append(f"{stem}{d}")
    return out


def _row_clock_names(cells: Sequence[str],
                     declared: Dict[str, str]) -> List[str]:
    """Clocks THIS ROW names, restricted to what L8 already declares.

    `declared` maps lower-case name -> the canonical name as L8 spells it.
    Nothing outside that mapping can ever be returned, so a row cannot
    introduce a clock — only speak about one.
    """
    hits: List[str] = []
    row_text = " ".join(_strip_md(c) for c in cells)
    for cand in _expand_compressed(row_text):
        canon = declared.get(cand.lower())
        if canon and canon not in hits:
            hits.append(canon)
    for tok in _RE_TOKEN.findall(row_text):
        canon = declared.get(tok.lower())
        if canon and canon not in hits:
            hits.append(canon)
    return hits


def _load_l_doc(project: Path, name: str) -> Optional[Dict[str, Any]]:
    p = project / "phase1" / "generated_docs" / f"{name}.json"
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text())
    except Exception:
        return None
    return d if isinstance(d, dict) else None


def _declared_clocks(project: Path) -> Dict[str, str]:
    """Every clock name L8 declares, lower-case -> canonical spelling."""
    out: Dict[str, str] = {}
    for doc in _L8_DOCS:
        d = _load_l_doc(project, doc)
        if not isinstance(d, dict):
            continue
        for key in _CLOCK_LIST_KEYS:
            for rec in (d.get(key) or []):
                if not isinstance(rec, dict):
                    continue
                for field in ("name", "source_pin"):
                    nm = (rec.get(field) or "").strip()
                    if nm:
                        out.setdefault(nm.lower(), nm)
    return out


def _doc_roots(project: Path) -> List[Path]:
    """The design's own input documents, in the two staged locations.

    Both are read because Phase 1 copies `input/docs/*.md` to
    `phase1/input_doc/*.txt`; a project may carry either or both, and the
    line numbers are per-file so the evidence stays exact whichever is used.
    """
    roots = [project / "phase1" / "input_doc",
             project / "input" / "docs",
             project / "input_doc"]
    return [r for r in roots if r.is_dir()]


def _iter_docs(project: Path) -> List[Path]:
    seen: set = set()
    files: List[Path] = []
    for root in _doc_roots(project):
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix.lower() not in (".md", ".txt", ".markdown"):
                continue
            # Dedup by STEM, not by full name: Phase 1 stages
            # `input/docs/X.md` as `phase1/input_doc/X.txt`, and scanning
            # both would double-count the same table and make the evidence
            # path depend on directory-walk order.
            key = p.stem.lower()
            if key in seen:
                continue
            seen.add(key)
            files.append(p)
    return files


def derive(project: Path) -> Dict[str, Any]:
    """Resolve every (clock -> frequency) binding the design STATES.

    Pure: reads the project, writes nothing. `main(--apply)` is the only
    writer, and `phase1_layer_demand_probe`-style consumers can reuse this.
    """
    project = Path(project)
    declared = _declared_clocks(project)
    result: Dict[str, Any] = {
        "program": PROGRAM,
        "version": VERSION,
        "declared_clocks": sorted(set(declared.values())),
        "documents_scanned": 0,
        "tables_seen": 0,
        "rows_with_frequency": 0,
        "bindings": [],
        "ambiguous_rows": [],
        "unplaced_names": [],
        "verdict": "NOT_APPLICABLE",
    }
    if not declared:
        result["reason"] = (
            "L8 declares no clock record at all, so there is no clock to bind "
            "a frequency to. This program never invents a clock.")
        return result

    bindings: Dict[str, Dict[str, Any]] = {}
    for doc in _iter_docs(project):
        result["documents_scanned"] += 1
        try:
            lines = doc.read_text(errors="replace").splitlines()
        except Exception:
            continue
        rel = doc
        try:
            rel = doc.relative_to(project)
        except ValueError:
            pass
        in_table = False
        for idx, line in enumerate(lines, start=1):
            cells = _split_row(line)
            if not cells:
                in_table = False
                continue
            if _MD_TABLE_SEP.match(line):
                # Header separator — the row above was a header.
                if not in_table:
                    in_table = True
                    result["tables_seen"] += 1
                continue
            if not in_table:
                continue
            freqs = _row_frequencies(cells)
            if not freqs:
                continue
            result["rows_with_frequency"] += 1
            names = _row_clock_names(cells, declared)
            if not names:
                continue
            row_text = " | ".join(_strip_md(c) for c in cells)
            if len(freqs) != 1 or freqs[0][0] <= 0:
                result["ambiguous_rows"].append({
                    "file": str(rel), "line": idx, "row": row_text,
                    "frequencies_hz": [f for f, _ in freqs],
                    "clocks_named": names,
                    "reason": ("the row resolves %d different frequencies; "
                               "which column the design meant is not "
                               "derivable, so nothing is bound"
                               % len(freqs)),
                })
                continue
            hz, matched = freqs[0]
            for nm in names:
                prev = bindings.get(nm)
                if prev is not None and prev["freq_hz"] != hz:
                    result["ambiguous_rows"].append({
                        "file": str(rel), "line": idx, "row": row_text,
                        "clocks_named": [nm],
                        "reason": ("two rows state different frequencies for "
                                   "this clock (%g Hz at %s:%d, %g Hz here); "
                                   "nothing is bound"
                                   % (prev["freq_hz"], prev["file"],
                                      prev["line"], hz)),
                    })
                    bindings.pop(nm, None)
                    continue
                if prev is not None:
                    # Same frequency restated elsewhere: keep the FIRST
                    # citation so the evidence path is stable, not
                    # directory-walk dependent.
                    continue
                bindings[nm] = {
                    "clock": nm,
                    "freq_hz": hz,
                    "freq_mhz": hz / 1.0e6,
                    "period_ns": 1.0e9 / hz,
                    "file": str(rel),
                    "line": idx,
                    "row": row_text,
                    "matched_text": matched,
                }

    result["bindings"] = [bindings[k] for k in sorted(bindings)]
    ambiguous_clocks = {
        n for r in result["ambiguous_rows"] for n in r.get("clocks_named", [])}
    result["unplaced_names"] = sorted(
        set(result["declared_clocks"]) - set(bindings) - ambiguous_clocks)
    if result["bindings"]:
        result["verdict"] = "DERIVED"
    elif result["ambiguous_rows"]:
        result["verdict"] = "AMBIGUOUS_NOT_BOUND"
    return result


def _apply(project: Path, derived: Dict[str, Any]) -> Dict[str, Any]:
    """Write the bindings into L8. Never overwrites a resolved frequency."""
    by_name = {b["clock"].lower(): b for b in derived["bindings"]}
    report = {"records_filled": 0, "records_left_alone": 0,
              "files_written": [], "clock_mhz_set": None}
    if not by_name:
        return report

    # The scalar short-circuits the per-record values in the consumer, so it is
    # set ONLY when every bound clock agrees. A multi-rate design keeps the
    # scalar null on purpose and lets its records speak.
    freqs = {b["freq_hz"] for b in derived["bindings"]}
    scalar_mhz = (next(iter(freqs)) / 1.0e6) if len(freqs) == 1 else None

    for doc in _L8_DOCS:
        d = _load_l_doc(project, doc)
        if not isinstance(d, dict):
            continue
        changed = False
        for key in _CLOCK_LIST_KEYS:
            recs = d.get(key)
            if not isinstance(recs, list):
                continue
            for rec in recs:
                if not isinstance(rec, dict):
                    continue
                nm = (rec.get("name") or rec.get("source_pin") or "").strip()
                b = by_name.get(nm.lower())
                if b is None:
                    continue
                # NEVER overwrite a frequency another producer resolved.
                if any(rec.get(k) not in (None, "", 0)
                       for k in ("freq_mhz", "freq_hz", "period_ns")):
                    report["records_left_alone"] += 1
                    continue
                rec["freq_hz"] = int(round(b["freq_hz"]))
                rec["freq_mhz"] = b["freq_mhz"]
                rec["period_ns"] = round(b["period_ns"], 6)
                rec["freq_status"] = (
                    "stated in the design's own documents")
                rec["freq_evidence"] = {
                    "file": b["file"], "line": b["line"],
                    "matched_text": b["matched_text"], "row": b["row"],
                }
                rec["derived_by"] = PROGRAM
                report["records_filled"] += 1
                changed = True
        # The scalar SHORT-CIRCUITS the per-record values in the consumer
        # (`sdc_gen` reads `clock_mhz` first and never looks at the records
        # when it resolves). So it must never be set to a value that
        # contradicts a record this doc already carries. Caught by control
        # PC2: a doc whose record already said 250 MHz, plus a document row
        # saying 100 MHz, had its record correctly left alone and its scalar
        # set to 100 — which would have made the consumer use 100 MHz while
        # the layer said 250. Refuse the scalar whenever ANY record in this
        # doc resolves to something else; the records then speak, and
        # `l8_clock_period_actionability_check` reports the contradiction.
        _conflict = False
        for _key in _CLOCK_LIST_KEYS:
            for _rec in (d.get(_key) or []):
                if not isinstance(_rec, dict):
                    continue
                for _k, _conv in (("freq_mhz", lambda v: float(v)),
                                  ("period_ns", lambda v: 1000.0 / float(v)),
                                  ("freq_hz", lambda v: float(v) / 1.0e6)):
                    _v = _rec.get(_k)
                    if _v in (None, "", 0):
                        continue
                    try:
                        _mhz = _conv(_v)
                    except (TypeError, ValueError, ZeroDivisionError):
                        continue
                    if scalar_mhz is None or abs(_mhz - scalar_mhz) > 1e-9:
                        _conflict = True
                    break
        if _conflict:
            report["clock_mhz_conflict"] = True
        if (scalar_mhz is not None and not _conflict
                and d.get("clock_mhz") in (None, "", 0)):
            d["clock_mhz"] = scalar_mhz
            if "no_clock_mhz_in_input" in d:
                d["no_clock_mhz_in_input"] = False
            report["clock_mhz_set"] = scalar_mhz
            changed = True
        if changed:
            if isinstance(d.get("clock_domains"), list) and d["clock_domains"]:
                d["no_clock_domains_in_input"] = False
            out = (project / "phase1" / "generated_docs" / f"{doc}.json")
            out.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
            report["files_written"].append(str(out.relative_to(project)))
    return report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project")
    ap.add_argument("--apply", action="store_true",
                    help="write the bindings into L8 (default: report only)")
    ap.add_argument("--json", help="also write the full report here")
    args = ap.parse_args(argv)

    project = Path(args.project).resolve()
    res = derive(project)

    print(f"=== {PROGRAM} ({project.name}) ===")
    print(f"  verdict: {res['verdict']}")
    print(f"  scanned: {res['documents_scanned']} document(s), "
          f"{res['tables_seen']} table(s), "
          f"{res['rows_with_frequency']} row(s) stating a frequency")
    print(f"  L8 declares clock(s): {res['declared_clocks'] or 'NONE'}")
    for b in res["bindings"]:
        print(f"    BOUND  {b['clock']}: {b['freq_mhz']:g} MHz "
              f"(period {b['period_ns']:g} ns)  [{b['file']}:{b['line']}]")
    for r in res["ambiguous_rows"]:
        print(f"  [DISCLOSED] {r['file']}:{r['line']} — {r['reason']}")
    if res["unplaced_names"]:
        # Degrade LOUDLY: a clock the design declares but never gives a rate
        # for is a real gap, and staying quiet about it is how a fabricated
        # default got shipped in the first place.
        print("  [DISCLOSED] no document row states a frequency for: "
              + ", ".join(res["unplaced_names"])
              + " — left unresolved, NOT defaulted.")

    if args.apply:
        rep = _apply(project, res)
        res["apply"] = rep
        print(f"  applied: {rep['records_filled']} record(s) filled, "
              f"{rep['records_left_alone']} already resolved and left "
              f"byte-identical")
        if rep["clock_mhz_set"] is not None:
            print(f"           clock_mhz scalar set to "
                  f"{rep['clock_mhz_set']:g} MHz (every bound clock agrees)")
        elif rep.get("clock_mhz_conflict"):
            print("  [DISCLOSED] clock_mhz scalar NOT set — a record already "
                  "in L8 resolves to a different frequency than the document "
                  "row states. The scalar short-circuits the records in the "
                  "consumer, so setting it would silently override the layer. "
                  "The per-record values stand and the contradiction is left "
                  "visible to l8_clock_period_actionability_check.")
        elif res["bindings"]:
            print("           clock_mhz scalar left null — the bound clocks "
                  "do not share one rate; the per-record values speak")

    if args.json:
        p = Path(args.json)
        if not p.is_absolute():
            p = project / p
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
