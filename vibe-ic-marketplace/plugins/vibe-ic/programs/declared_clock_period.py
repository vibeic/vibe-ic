#!/usr/bin/env python3
"""
declared_clock_period.py — read the clock period the DESIGN declares for the
library this run is actually building against.

The gap this closes (measured, spm x gf180mcuD, v1.11.3)
--------------------------------------------------------
A constraint L-doc does not always state the period as a literal next to a
`-period` token. The portable way to write a target for a design that will be
built against several PDKs is a PLACEHOLDER plus a table keyed by std-cell
library::

    create_clock [get_ports clk] -name core_clock -period <PERIOD>

    | Std-cell library    | `<PERIOD>` (ns) | frequency |
    |---|---|---|
    | `sky130_fd_sc_hd`   | 10 | 100 MHz   |
    | `sky130_fd_sc_hs`   |  8 | 125 MHz   |
    | `gf180mcu_*`        | 24 | ~41.7 MHz |

`phase3_one_shot_runner._resolve_clock_spec` looked for a NUMBER ADJACENT TO a
`-period` / `period` token. Here the token's neighbour is the literal string
`<PERIOD>` and the real numbers live four lines away in a table, keyed by a
column the resolver never read — it was not even given the library name. So
resolution fell all the way through to the 20.0 ns last-resort default, and the
run signed off at 20 ns (50 MHz) a design that declares 24 ns (41.7 MHz):

    $ grep create_clock phase3/stage3/pnr/constraint.sdc
    create_clock -name clk -period 20.0 [get_ports clk]

That is an OVER-constraint of 20 %, applied silently. It is not conservative in
any useful sense — it makes every setup verdict a verdict about a clock the
design never asked for, and it can turn a design that meets its own target into
a reported setup violation with no line anywhere saying why.

HONESTY BOUNDARY (§4.05) — this reads, it never invents
--------------------------------------------------------
* A period is returned ONLY when a row of a real table in the design's own
  constraint docs matches the library/PDK this run resolved. Nothing is
  defaulted, interpolated, rounded or scaled from a neighbouring row.
* When two rows match with DIFFERENT periods the result is AMBIGUOUS and NO
  period is returned. Picking one by list order is how you silently sign off
  against a period the design never singled out.
* The matched row, the matched key and the source file+line always travel with
  the number, so a downstream reader can check the claim against the doc.
* This program NEVER writes an SDC and NEVER relaxes anything on its own. It
  reports what the design declared; using a declared constraint instead of a
  tool default is not a relaxation, and the caller discloses the swap.

Chip / PDK-AGNOSTIC: no chip, vendor, PDK or library literal appears here. The
candidate names are supplied by the caller from what the run resolved, and the
table keys come from the design's own document.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082/#1470

sys.path.insert(0, str(Path(__file__).resolve().parent))
# The ONE negation vocabulary (vibe-ic#712). `declared_io_delay_fraction` reads
# a DERIVATION out of an English/Chinese design document and publishes it as a
# declared constraint; see its docstring for why the polarity of that sentence
# is load-bearing here and not a formality.
from _prose_polarity import (  # type: ignore  # noqa: E402
    is_denied as _is_denied, sentence_scope as _sentence_scope)

# A markdown table row: starts and ends with '|' after stripping.
_ROW_RE = re.compile(r"^\s*\|(.*)\|\s*$")
# The |---|:---:|---| separator that follows a markdown header row.
_SEP_CELL_RE = re.compile(r"^:?-{2,}:?$")
# A header cell that names the period column. `週期` is "period" in the
# Chinese-language L-docs this plugin already accepts elsewhere in the
# resolver; it is a language token, not a chip/vendor literal.
_PERIOD_HDR_RE = re.compile(r"period|週期|時脈週期", re.IGNORECASE)
# A header cell that names the key column.
_KEY_HDR_RE = re.compile(r"librar|library|pdk|std[\s_-]*cell|cell\s*lib|技術|製程",
                         re.IGNORECASE)
# Units a period column may declare in its header, as a multiplier to ns.
_UNIT_TO_NS = {"s": 1e9, "ms": 1e6, "us": 1e3, "ns": 1.0, "ps": 1e-3}
_UNIT_HDR_RE = re.compile(r"\((?:\s*)(s|ms|us|ns|ps)(?:\s*)\)", re.IGNORECASE)
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _cells(line: str) -> Optional[List[str]]:
    """Split one markdown table line into stripped cells, or None."""
    m = _ROW_RE.match(line)
    if not m:
        return None
    return [c.strip() for c in m.group(1).split("|")]


def _is_separator(cells: Sequence[str]) -> bool:
    return bool(cells) and all(_SEP_CELL_RE.match(c or "") for c in cells)


def _clean_key(cell: str) -> str:
    """Strip markdown code fences and emphasis from a key cell.

    Emphasis is stripped only when it WRAPS the cell symmetrically (``**x**``,
    ``*x*``). A bare `.strip("*")` would eat the trailing glob of a key like
    ``gf180mcu_*`` and turn a family pattern into a literal that matches
    nothing — measured, and the reason this is a function and not a one-liner.
    """
    t = cell.strip().strip("`").strip()
    for mark in ("***", "**", "*", "__", "_"):
        if len(t) > 2 * len(mark) and t.startswith(mark) and t.endswith(mark):
            t = t[len(mark):-len(mark)].strip()
            break
    return t.strip("`").strip()


def parse_period_tables(text: str, source: str = "") -> List[Dict[str, object]]:
    """Every ``{key, period_ns, ...}`` row of every period-keyed table in ``text``.

    A table qualifies when its header row has one cell naming a period and one
    cell naming a library/PDK key. Everything else in the document is ignored —
    including any table that merely contains numbers.
    """
    rows: List[Dict[str, object]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        hdr = _cells(lines[i])
        if hdr is None or i + 1 >= len(lines):
            i += 1
            continue
        sep = _cells(lines[i + 1])
        if sep is None or not _is_separator(sep):
            i += 1
            continue
        # Header + separator found. Does this table key a period by library?
        period_col = next((n for n, c in enumerate(hdr)
                           if _PERIOD_HDR_RE.search(c or "")), None)
        key_col = next((n for n, c in enumerate(hdr)
                        if _KEY_HDR_RE.search(c or "")), None)
        if period_col is None or key_col is None or period_col == key_col:
            i += 1
            continue
        um = _UNIT_HDR_RE.search(hdr[period_col] or "")
        # No unit in the header ⇒ ns, and the row records that it was assumed
        # rather than read, so a caller can refuse an unlabelled table if it
        # wants to. This plugin's SDC layer is ns throughout.
        unit = (um.group(1).lower() if um else "ns")
        scale = _UNIT_TO_NS.get(unit, 1.0)
        j = i + 2
        while j < len(lines):
            row = _cells(lines[j])
            if row is None:
                break
            if _is_separator(row):
                j += 1
                continue
            if max(period_col, key_col) < len(row):
                key = _clean_key(row[key_col])
                nm = _NUM_RE.search(row[period_col] or "")
                if key and nm:
                    # POLARITY, ON THE ROW (vibe-ic#712). A document retires a
                    # row of a table as readily as it states one, and this read
                    #
                    #     | <library> | 10 | this row is no longer used |
                    #
                    # as a declared clock period. This program supplies the
                    # period a design is CONSTRAINED to, so a retired value
                    # published as a declaration is the #712 harm in its literal
                    # form: hard-sized from a document that says otherwise,
                    # citing that document as the authority.
                    #
                    # THE ROW IS THE RECORD, so the row is the scope. A denial in
                    # one row must not retire the row beneath it, and a scope
                    # measured in characters would do exactly that. The same
                    # reason `sentence_scope` is not used here: this table has no
                    # sentences, it has rows.
                    if _is_denied(lines[j]):
                        j += 1
                        continue
                    try:
                        rows.append({
                            "key": key,
                            "period_ns": float(nm.group(0)) * scale,
                            "unit": unit,
                            "unit_declared": bool(um),
                            "source": source,
                            "line": j + 1,
                            "row": lines[j].strip(),
                        })
                    except ValueError:
                        pass
            j += 1
        i = j
    return rows


def match_rows(rows: Sequence[Dict[str, object]],
               candidates: Sequence[str]) -> List[Dict[str, object]]:
    """Rows whose key matches any candidate name, case-insensitively.

    A key may be an exact name (``sky130_fd_sc_hd``) or a glob
    (``gf180mcu_*``). A candidate may also be the more specific of the two —
    a PDK name like ``gf180mcuD`` is matched against a ``gf180mcu_*`` key by
    also trying the key with its trailing separator+glob collapsed, so a table
    written against library families still resolves for a caller that only
    knows the PDK. Both directions are pure pattern matching over strings the
    caller and the document supplied; no name is synthesized here.
    """
    out: List[Dict[str, object]] = []
    cands = [c.strip().lower() for c in candidates if c and c.strip()]
    if not cands:
        return out
    for r in rows:
        key = str(r["key"]).strip().lower()
        if not key:
            continue
        pats = {key}
        if "*" in key:
            # A family key written `<family>_*` must also catch a PDK spelled
            # `<family><variant>` with no separator: allow the separator before
            # the glob to be absent.
            pats.add(re.sub(r"[_\-.]\*$", "*", key))
        hit = any(fnmatch.fnmatchcase(c, p) or c == p.rstrip("*")
                  for c in cands for p in pats)
        if hit:
            out.append(r)
    return out


def declared_period_ns(docs: Sequence[Path],
                       candidates: Sequence[str]) -> Dict[str, object]:
    """Resolve the declared period for ``candidates`` across ``docs``.

    Returns a report dict. ``period_ns`` is None unless exactly one period
    value matched (duplicate rows that AGREE are fine — contradiction is not).
    """
    rep: Dict[str, object] = {
        "period_ns": None,
        "matched_key": None,
        "source": None,
        "line": None,
        "candidates": list(candidates),
        "rows_seen": 0,
        "matches": [],
        "ambiguous": False,
        "note": "",
    }
    all_rows: List[Dict[str, object]] = []
    for d in docs:
        try:
            all_rows.extend(parse_period_tables(d.read_text(errors="ignore"),
                                                source=str(d)))
        except Exception:
            continue
    rep["rows_seen"] = len(all_rows)
    if not all_rows:
        rep["note"] = ("no period-keyed table found in the supplied doc(s) "
                       "(a qualifying table needs a header naming a period "
                       "AND a header naming a library/PDK key)")
        return rep
    hits = match_rows(all_rows, candidates)
    rep["matches"] = hits
    if not hits:
        rep["note"] = (
            f"{len(all_rows)} period-keyed row(s) found but none matches "
            f"{list(candidates)}; keys present: "
            f"{sorted({str(r['key']) for r in all_rows})}")
        return rep
    values = sorted({round(float(r["period_ns"]), 6) for r in hits})
    if len(values) > 1:
        rep["ambiguous"] = True
        rep["note"] = (
            f"AMBIGUOUS — {len(hits)} row(s) match {list(candidates)} but they "
            f"declare DIFFERENT periods {values} ns; refusing to pick one. "
            "Rows: " + "; ".join(f"{r['source']}:{r['line']} {r['row']}"
                                 for r in hits))
        return rep
    # Prefer the most specific matching key (fewest glob chars, then longest)
    # purely for the provenance we report; the value is identical either way.
    best = sorted(hits, key=lambda r: (str(r["key"]).count("*"),
                                       -len(str(r["key"]))))[0]
    rep["period_ns"] = float(best["period_ns"])
    rep["matched_key"] = best["key"]
    rep["source"] = best["source"]
    rep["line"] = best["line"]
    rep["note"] = (
        f"the design declares {rep['period_ns']:g} ns for '{best['key']}' "
        f"(matched {list(candidates)}) at {best['source']}:{best['line']} — "
        f"{best['row']}"
        + ("" if best["unit_declared"]
           else " [column declared no unit; read as ns]"))
    return rep


# ── the I/O delay a design declares as a FRACTION of its own period ──────────
# The same document that keys its period by library states the I/O delay as a
# DERIVATION rather than a number ("I/O delay is 20 % of the clock period",
# with a worked example at one period). A reader written for the literal form
# emits a fixed number that satisfies the derivation at exactly ONE period and
# under- or over-constrains the I/O boundary at every other — a declared
# RELATIONSHIP read as if it were a declared VALUE.
_IO_TOKEN_RE = re.compile(
    r"set_input_delay|set_output_delay|input\s+delay|output\s+delay|"
    r"i/o\s*delay|輸入延遲|輸出延遲|輸入輸出延遲",
    re.IGNORECASE)
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_PERIOD_TOKEN_RE = re.compile(r"clock\s*period|period|時脈週期|週期",
                              re.IGNORECASE)
# How far past the I/O token the derivation may sit. One sentence / bullet.
_IO_WINDOW = 240


#: vibe-ic#712 — the comment form of the documents this module reads.
#:
#: THE HDL STRIPPER IS THE WRONG TOOL HERE and using it would be a REGRESSION.
#: `_design_module_set.strip_comments` removes `//[^\n]*`, and these are design
#: DOCUMENTS: a line carrying `https://spec.example/timing#io-delay` would lose
#: everything after the scheme, so a real I/O-delay statement sharing that line
#: would be silently dropped. Under-reading a declaration is the same class of
#: defect as over-reading one, pointed the other way.
#:
#: `<!-- ... -->` is the comment form these documents actually have, and a
#: commented-out paragraph is exactly the hazard: "<!-- I/O delay is 20 % of the
#: clock period -->" carries an I/O token, a period token and one percentage
#: inside one window, so unstripped it reads as a live mandate.
_DOC_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _strip_doc_comments(text: str) -> str:
    """`text` with markdown/HTML comments blanked, OFFSETS PRESERVED.

    Every character is replaced one-for-one — newlines stay newlines and
    everything else becomes a space — so `text.count("\n", 0, start)` and
    `_sentence_scope` see exactly the positions they saw before. A stripper
    that deleted the span would move every line number and citation after it.
    """
    return _DOC_COMMENT_RE.sub(
        lambda m: "".join("\n" if c == "\n" else " " for c in m.group(0)), text)


def declared_io_delay_fraction(docs: Sequence[Path]) -> Dict[str, object]:
    """The fraction of the clock period the design declares as its I/O delay.

    Returns ``fraction`` (e.g. 0.2) only when a statement naming an I/O delay
    AND the clock period AND one percentage sits inside one window, and every
    such statement across the docs agrees. Two different percentages is a
    REFUSAL, not a vote — the same rule the period table follows.

    A DENIED STATEMENT IS NOT A DECLARATION (vibe-ic#712). "I/O delay is no
    longer derived from the clock period" and "the 20 % I/O delay default does
    not apply to this interface" both carry an I/O token, a period token and
    one percentage inside one window, so without a polarity consult they read
    as a 0.2 mandate — which is #706 and #711 exactly, in a field that lands in
    the emitted SDC. The polarity span is `_prose_polarity.sentence_scope`
    around the I/O token, not this function's own forward-only extraction
    window: a denial that governs the statement can sit BEFORE the token, and
    the repo has one rule for how far a sentence reaches.

    A denial SUPPRESSES the statement and is COUNTED. "no statement was made"
    and "the statement was retracted" are different findings and must not share
    a verdict, so `denied` carries the citations and `note` says so — the
    caller then keeps its historical literal knowing why, rather than because
    the scan silently read less than it found.
    """
    rep: Dict[str, object] = {"fraction": None, "percent": None,
                              "source": None, "line": None,
                              "ambiguous": False, "note": "",
                              "denied": []}
    denied: List[str] = []
    found: List[Tuple[float, str, int, str]] = []
    for d in docs:
        try:
            text = d.read_text(errors="ignore")
        except Exception:
            continue
        # vibe-ic#712 — strip on the value that REACHES the scan. Offsets are
        # preserved, so the line numbers and denial citations below are
        # unchanged; only commented-out prose stops being readable as a
        # declaration.
        text = _strip_doc_comments(text)
        for m in _IO_TOKEN_RE.finditer(text):
            window = text[m.start():m.start() + _IO_WINDOW]
            # The window must not run past a blank line into the next topic.
            window = window.split("\n\n", 1)[0]
            # vibe-ic#712 — a sentence that DENIES the derivation must not have
            # its percentage written out as a mandate; that is the #706/#711
            # defect exactly. TWO LANES FIXED THIS INDEPENDENTLY IN THE SAME
            # BATCH and the merge kept both. The early `continue` that stood
            # here SILENTLY DROPPED the statement, which reaches the same
            # verdict as never having read one — and this function's own test
            # exists to say those are different findings. The denial is
            # consulted and COUNTED below instead, with the citation, using the
            # repo's one sentence-reach rule so a denial sitting BEFORE the
            # token is still seen.
            if not _PERIOD_TOKEN_RE.search(window):
                continue
            pcts = _PCT_RE.findall(window)
            if len(pcts) != 1:
                continue  # 0 = no derivation stated; >1 = not one statement
            try:
                pct = float(pcts[0])
            except ValueError:
                continue
            if not (0.0 < pct < 100.0):
                continue
            line_no = text.count("\n", 0, m.start()) + 1
            # THE POLARITY SPAN IS THE STATEMENT THE VALUE CAME OUT OF, plus
            # the sentence reach BEHIND the token. `window` is exactly what
            # this reader treats as one statement, so it is the forward half;
            # using `sentence_scope` for BOTH halves instead was measured to
            # split them apart — a `### 9.1.3 I/O delay` heading ends its
            # sentence at the `\n- ` that begins the bullet, so the heading hit
            # read its percentage from a bullet whose denial the polarity span
            # no longer contained, and the retracted value was published. The
            # backward half is `sentence_scope`'s, because a denial governing
            # the statement can sit BEFORE the token and the window is
            # forward-only.
            lo, _hi = _sentence_scope(text, m.start(), m.end(),
                                      before=_IO_WINDOW, after=0)
            word = _is_denied(text[lo:m.start()] + window)
            if word:
                denied.append(f"{d}:{line_no} — '{word}' denies "
                              f"{window.splitlines()[0].strip()}")
                continue
            found.append((pct, str(d), line_no,
                          window.splitlines()[0].strip()))
    rep["denied"] = denied
    if not found:
        rep["note"] = (
            "no I/O delay stated as a fraction of the clock period"
            if not denied else
            f"{len(denied)} I/O-delay statement(s) READ AND REFUSED: the "
            f"sentence denies the derivation, so nothing is declared — "
            + "; ".join(denied))
        return rep
    pcts = sorted({round(f[0], 6) for f in found})
    if len(pcts) > 1:
        rep["ambiguous"] = True
        rep["note"] = (f"AMBIGUOUS — the doc(s) state {pcts} % for the I/O "
                       "delay; refusing to pick one")
        return rep
    pct, src, line, snippet = found[0]
    rep.update({"fraction": pct / 100.0, "percent": pct, "source": src,
                "line": line,
                "note": (f"the design declares an I/O delay of {pct:g} % of the "
                         f"clock period at {src}:{line} — {snippet}"
                         + (f" [{len(denied)} further statement(s) refused as "
                            f"denied: {'; '.join(denied)}]" if denied else ""))})
    return rep


def docs_in(docs_dir: Path) -> List[Path]:
    """The constraint docs, most-authoritative first (L9 then L1, as the
    resolver's own priority chain already orders them)."""
    if not docs_dir.is_dir():
        return []
    return sorted(docs_dir.glob("L9_*.md")) + sorted(docs_dir.glob("L1_*.md"))


def library_name_from_liberty(liberty_path: str) -> str:
    """The std-cell library name implied by a liberty PATH, or ''.

    open_pdks lays a PDK out as ``<pdk>/libs.ref/<library>/lib/<file>.lib`` and
    names the file ``<library>__<corner>.lib``. Both are read; neither is a
    literal for any particular PDK.
    """
    if not liberty_path:
        return ""
    p = Path(liberty_path)
    stem = p.stem
    if "__" in stem:
        return stem.split("__", 1)[0]
    parts = p.parts
    if "libs.ref" in parts:
        n = parts.index("libs.ref")
        if n + 1 < len(parts):
            return parts[n + 1]
    return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Read the clock period the design DECLARES for the "
                    "std-cell library / PDK this run resolved.")
    ap.add_argument("--docs-dir", help="the design's input/docs directory")
    ap.add_argument("--doc", action="append", default=[],
                    help="an explicit doc to read (repeatable)")
    ap.add_argument("--library", default="",
                    help="the std-cell library this run builds against")
    ap.add_argument("--liberty", default="",
                    help="a liberty path to derive --library from")
    ap.add_argument("--pdk", default="", help="the PDK this run resolved")
    ap.add_argument("--json", help="write the structured report here")
    args = ap.parse_args(argv)

    docs = [Path(d) for d in args.doc]
    if args.docs_dir:
        docs.extend(docs_in(Path(args.docs_dir)))
    lib = args.library or library_name_from_liberty(args.liberty)
    rep = declared_period_ns(docs, [c for c in (lib, args.pdk) if c])
    rep["library"] = lib
    rep["pdk"] = args.pdk
    if args.json:
        atomic_write_text(Path(args.json), json.dumps(rep, indent=2) + "\n")
    print(json.dumps(rep, indent=2))
    # 0 = a period was resolved; 1 = nothing declared for this library.
    return 0 if rep["period_ns"] is not None else 1


if __name__ == "__main__":
    sys.exit(main())
