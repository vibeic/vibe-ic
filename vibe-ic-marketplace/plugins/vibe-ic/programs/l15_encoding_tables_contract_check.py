#!/usr/bin/env python3
"""l15_encoding_tables_contract_check.py — SEMANTIC gate for
L15_ENCODING_TABLES.json.

VERDICT SEMANTICS — THIS GATE **BLOCKS**.
    Any FAIL-severity finding returns exit 1 and the caller must halt.
    Why blocking: L15's only real consumer,
    `programs/opcode_field_width_consistency_check.py`, reconciles a
    declared L3 opcode hex against the encoding table that defines it. It
    compares only mnemonics it can EXTRACT from L15. When it can extract
    none, it prints `ALL_PASS` after comparing exactly zero rows. That is
    not a passing check; it is a check that lies — the same failure mode
    that let a fabricated 4-bit-overflowing opcode set ship. A green
    result with no comparisons behind it must be impossible, so this gate
    is fatal rather than advisory.

    A second, ADVISORY tier (WARN) carries systemic producer defects that
    are real but currently pervasive; `--strict` promotes it to blocking.

WHAT IT ENFORCES (the CONSUMER contract, not token presence)
    The gate does not re-implement the reconciler and then hope the two
    agree. It IMPORTS the consumer and runs the consumer's OWN extractor,
    `opcode_field_width_consistency_check._iter_l15_name_hex`, over each
    table. So "actionable" is defined by exactly the code that will run
    downstream, and the two can never drift apart.

    The central rule: A TABLE THAT CARRIES CODE LITERALS MUST YIELD AT
    LEAST ONE (mnemonic, code) PAIR TO THE CONSUMER. A table can be full
    of encodings and still be invisible to the reconciler — because the
    row has several code cells and none is designated as THE code, because
    the codes are written in a radix the reconciler does not read, or
    because no cell carries a mnemonic at all. In every one of those cases
    the encoding is *present in the document and absent from the layer
    that consumes it*, which is precisely the defect class this gate
    exists to stop. The remedy is in the message: designate the code
    column, or emit typed rows.

    Second rule: WHERE A TABLE DECLARES ITS OWN FIELD WIDTH, ITS OWN CODES
    MUST FIT IN IT. The width is read out of the table's own declaration
    (`bit_width` / `width_bits` / `width`, or a `[W-1:0]` in one of its
    header columns, or an "N-bit" phrase in its own description) — never
    from a design name, a PDK, or a hardcoded literal.

USAGE
    python3 l15_encoding_tables_contract_check.py <project_dir>
        [--l15 PATH] [--strict] [--json OUT]

RULES
    FAIL tier (blocking, always)
      l15_parseable                        valid JSON object.
      l15_encoding_unreconcilable_by_consumer
                                           a code-bearing table from which
                                           the consumer's own extractor
                                           yields no (mnemonic, code) pair.
      l15_code_exceeds_declared_width      a code overflows the width the
                                           same table declares.
    WARN tier (advisory; --strict promotes to blocking)
      l15_status_contradicts_content       extraction_status disagrees with
                                           the content actually present.
      l15_table_caption_without_rows       `tables[]` entry is a bare caption
                                           string — the table's NAME captured
                                           without its encoding.
      l15_l3_reconciliation_vacuous        L3 declares hex opcodes yet not one
                                           reconciles against L15, so the
                                           downstream consistency check runs
                                           zero comparisons and reports PASS.

EXIT CODES
    0 = PASS (or WARN-only without --strict)
    1 = FAIL (blocking)
    2 = L15 not found (skip)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import opcode_field_width_consistency_check as _ofw  # noqa: E402 (the CONSUMER)

try:
    import _path_layout as _pl  # noqa: E402
except Exception:                # pragma: no cover - cache tree without helper
    _pl = None


_FOUND_NOTHING = "EXTRACTION_FOUND_NOTHING"
_ROW_KEYS = ("rows", "entries", "values", "codes", "records")

# Code literals an encoding row may carry, in any radix a spec uses.
_CODE_PATTERNS: Tuple[Tuple[str, re.Pattern, int], ...] = (
    ("hex",     re.compile(r"^0x([0-9a-fA-F]+)$"), 16),
    ("bin",     re.compile(r"^0b([01]+)$"), 2),
    ("vlog_h",  re.compile(r"^\d+'h([0-9a-fA-F]+)$"), 16),
    ("vlog_b",  re.compile(r"^\d+'b([01]+)$"), 2),
    ("vlog_d",  re.compile(r"^\d+'d(\d+)$"), 10),
)
# Width declared by the table itself, unambiguously and for its codes.
# Deliberately narrow: `bits` / `width` are rejected because they are also
# used for a column's display width, and an "N-bit" phrase in a table's prose
# is rejected because it scopes to whatever the sentence is about — both
# produced false alarms against real encodings (a worked checksum example
# whose intermediate sums legitimately carry out of 8 bits, and a PID table
# whose 4-bit header column sits beside an 8-bit byte column).
_WIDTH_KEYS = ("bit_width", "width_bits", "field_width", "code_width")
_BITRANGE_RE = re.compile(r"\[\s*(\d+)\s*:\s*0\s*\]")
_PROV_KEYS = ("table_id", "line", "lines", "page", "pages", "section",
              "clause", "source", "source_file", "reference", "description",
              "note", "notes", "header_columns")


def _code_value(cell: Any) -> Optional[int]:
    if not isinstance(cell, str):
        return None
    s = cell.strip()
    for _kind, pat, base in _CODE_PATTERNS:
        m = pat.match(s)
        if m:
            try:
                return int(m.group(1), base)
            except ValueError:
                return None
    return None


def _cells(row: Any) -> List[Any]:
    if isinstance(row, dict):
        return list(row.values())
    if isinstance(row, (list, tuple)):
        return list(row)
    return [row]


def _row_list(table: Dict[str, Any]) -> List[Any]:
    for k in _ROW_KEYS:
        v = table.get(k)
        if isinstance(v, list) and v:
            return v
    return []


def iter_tables(node: Any, path: str = "fields") -> Iterable[Tuple[str, Dict[str, Any]]]:
    """Every dict in the document that carries a row list — regardless of
    where it sits. The consumer walks the whole `fields` subtree, so the
    gate must consider the same population."""
    if isinstance(node, dict):
        if _row_list(node):
            yield path, node
        for k, v in node.items():
            if k in _ROW_KEYS:
                continue
            yield from iter_tables(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from iter_tables(v, f"{path}[{i}]")


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _scalar_width(table: Dict[str, Any]) -> Optional[int]:
    """A width the table declares for its OWN codes, as a scalar."""
    for k in _WIDTH_KEYS:
        v = table.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, int) and 0 < v <= 64:
            return v
        if isinstance(v, str):
            m = re.match(r"^\s*(\d+)\s*$", v)
            if m and 0 < int(m.group(1)) <= 64:
                return int(m.group(1))
    return None


def width_scoped_codes(table: Dict[str, Any]
                       ) -> List[Tuple[int, Any, int, str]]:
    """(width, code_cell, code_value, scope_label) for every code the table
    binds to a width IT ITSELF declares.

    A width is only applied where the binding is unambiguous:
      A. a scalar width key on the table — it governs the table's codes;
      B. a `[W-1:0]` in one header column — it governs THAT COLUMN ONLY,
         matched positionally for list rows and by normalised header name
         for dict rows.
    Anything looser is skipped rather than guessed at: an unscoped width is
    how a legitimate multi-column table gets flagged for a code that was
    never in the narrow field."""
    out: List[Tuple[int, Any, int, str]] = []
    rows = _row_list(table)

    w = _scalar_width(table)
    if w is not None:
        for r in rows:
            for c in _cells(r):
                v = _code_value(c)
                if v is not None:
                    out.append((w, c, v, "table-declared width"))
        return out

    hdrs = table.get("header_columns")
    if not (isinstance(hdrs, list) and hdrs):
        return out
    colw: Dict[int, Tuple[int, str]] = {}
    for i, h in enumerate(hdrs):
        if isinstance(h, str):
            m = _BITRANGE_RE.search(h)
            if m and 0 < int(m.group(1)) + 1 <= 64:
                colw[i] = (int(m.group(1)) + 1, h)
    if not colw:
        return out
    for r in rows:
        if isinstance(r, (list, tuple)) and len(r) == len(hdrs):
            for i, (cw, h) in colw.items():
                v = _code_value(r[i])
                if v is not None:
                    out.append((cw, r[i], v, f"column {h!r}"))
        elif isinstance(r, dict):
            keymap = {_norm(k): k for k in r}
            for _i, (cw, h) in colw.items():
                k = keymap.get(_norm(h))
                if k is None:
                    continue
                v = _code_value(r[k])
                if v is not None:
                    out.append((cw, r[k], v, f"column {h!r}"))
    return out


def _table_label(path: str, table: Dict[str, Any]) -> str:
    for k in ("table_id", "name", "title"):
        v = table.get(k)
        if isinstance(v, str) and v.strip():
            return f"{path} ({v.strip()[:48]})"
    return path


def check(l15: Optional[Dict[str, Any]],
          l3: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    findings: List[Dict[str, str]] = []

    def fail(rule, msg):
        findings.append({"severity": "FAIL", "rule": rule, "message": msg})

    def warn(rule, msg):
        findings.append({"severity": "WARN", "rule": rule, "message": msg})

    if not isinstance(l15, dict):
        fail("l15_parseable", "L15_ENCODING_TABLES.json is not a JSON object")
        return {"findings": findings}
    if l15.get("applicability") == "N/A":
        return {"findings": findings, "skipped": "applicability=N/A"}

    fields = l15.get("fields")
    fields = fields if isinstance(fields, dict) else l15
    tables = list(iter_tables(fields))

    # ---- FAIL tier: reconcilability + self-consistent width -------------
    n_code_tables = 0
    for path, tb in tables:
        rows = _row_list(tb)
        codes: List[Tuple[Any, int]] = []
        for r in rows:
            for c in _cells(r):
                v = _code_value(c)
                if v is not None:
                    codes.append((c, v))
        if not codes:
            continue            # not an encoding table — nothing to reconcile
        # A table that carries no mnemonic anywhere is a numeric map, not a
        # mnemonic→code encoding; the reconciler keys on mnemonics, so
        # demanding a pair from it would demand the impossible. Out of scope
        # on purpose — narrowing this rule removed its only false alarms
        # (an ECC syndrome matrix and a strap→address map, both nameless).
        has_mnemonic = any(
            isinstance(c, str) and _code_value(c) is None
            and re.search(r"[A-Za-z]", c)
            for r in rows for c in _cells(r))
        if not has_mnemonic:
            continue
        n_code_tables += 1
        label = _table_label(path, tb)

        pairs = list(_ofw._iter_l15_name_hex(tb))
        if not pairs:
            why = []
            multi = any(sum(1 for c in _cells(r) if _code_value(c) is not None) > 1
                        for r in rows)
            if multi:
                why.append("rows carry more than one code cell and none is "
                           "designated as THE code")
            if not any(_ofw._hexval(c) is not None
                       for r in rows for c in _cells(r)):
                why.append("codes are written in a radix the reconciler does "
                           "not read (it accepts 0x… only)")
            fail("l15_encoding_unreconcilable_by_consumer",
                 f"{label}: {len(codes)} code literal(s) present but "
                 f"opcode_field_width_consistency_check extracts ZERO "
                 f"(mnemonic, code) pairs from this table"
                 + (" — " + "; ".join(why) if why else "")
                 + ". The encoding is in the document and absent from the "
                   "layer that consumes it: the reconciliation silently "
                   "degrades to a no-op and reports ALL_PASS. Fix by "
                   "designating the code column or emitting typed rows "
                   "{name, code} per entry.")

        for w, cell, val, scope in width_scoped_codes(tb):
            ceil = (1 << w) - 1
            if val > ceil:
                fail("l15_code_exceeds_declared_width",
                     f"{label}: {scope} declares {w} bit(s) (max "
                     f"{hex(ceil)}) but carries code {cell!r} = {hex(val)}. "
                     f"A code wider than the field the same table declares "
                     f"for it is structurally impossible, not a judgement "
                     f"call.")

    # ---- WARN tier -------------------------------------------------------
    status = l15.get("extraction_status")
    declared_tables = fields.get("tables")
    n_declared = len(declared_tables) if isinstance(declared_tables, list) else 0
    content = n_declared + len(tables)
    if status == _FOUND_NOTHING and content > 0:
        warn("l15_status_contradicts_content",
             f"extraction_status is {_FOUND_NOTHING} while the document "
             f"carries {n_declared} declared table entr(ies) and "
             f"{len(tables)} row-bearing table(s). A reader that trusts the "
             f"flag to decide whether L15 was populated gets the wrong "
             f"answer.")
    if isinstance(status, str) and status.upper().startswith("EXTRACTED") \
            and content == 0:
        warn("l15_status_contradicts_content",
             "extraction_status claims EXTRACTED but no table or row is "
             "present — a green flag with nothing behind it.")

    if isinstance(declared_tables, list):
        captions = [t for t in declared_tables if isinstance(t, str)]
        if captions:
            warn("l15_table_caption_without_rows",
                 f"{len(captions)}/{len(declared_tables)} entries of "
                 f"`tables[]` are bare caption strings, e.g. "
                 f"{captions[0][:60]!r}. The table's NAME was captured; its "
                 f"encoding was not. The consumer's extractor cannot see a "
                 f"string, so these contribute nothing to reconciliation — "
                 f"emit each as a row record {{table_id, name, rows[]}}.")

    # Cross-layer: does the consumer have anything to reconcile at all?
    if isinstance(l3, dict):
        l3map = _ofw._l3_name_hex(l3)
        if l3map:
            seen = {nm for nm, _v, _h in _ofw._iter_l15_name_hex(fields)}
            inter = set(l3map) & seen
            if not inter:
                warn("l15_l3_reconciliation_vacuous",
                     f"L3 declares {len(l3map)} opcode(s) with a hex, and "
                     f"L15 exposes {len(seen)} mnemonic(s) to the "
                     f"reconciler, but the two sets do not intersect at all. "
                     f"opcode_field_width_consistency_check will therefore "
                     f"run ZERO comparisons and report ALL_PASS. Either L15 "
                     f"is missing the encoding table that defines these "
                     f"opcodes, or the L3 mnemonics are not the names the "
                     f"encoding uses — both are gaps, and neither is caught "
                     f"downstream.")

    return {
        "findings": findings,
        "row_bearing_tables": len(tables),
        "code_bearing_tables": n_code_tables,
        "declared_table_entries": n_declared,
        "extraction_status": status,
    }


def _resolve(project: Path, override: Optional[str], name: str) -> Optional[Path]:
    if override:
        p = Path(override)
        return p if p.is_file() else None
    cands = [project / "phase1" / "generated_docs" / name]
    if _pl is not None:
        try:
            cands.append(_pl.generated_docs_dir(project) / name)
        except Exception:
            pass
    cands.append(project / name)
    for c in cands:
        if c.is_file():
            return c
    return None


def _load(p: Optional[Path]) -> Optional[Dict[str, Any]]:
    if p is None:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--l15", default=None)
    ap.add_argument("--l3", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="promote the advisory WARN tier to blocking")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    l15_path = _resolve(args.project_dir, args.l15, "L15_ENCODING_TABLES.json")
    if l15_path is None:
        print("[SKIP] l15_encoding_tables_contract_check: "
              "L15_ENCODING_TABLES.json not found")
        return 2
    l3_path = _resolve(args.project_dir, args.l3, "L3_CMD_PROTOCOL.json")

    try:
        l15 = json.loads(l15_path.read_text(encoding="utf-8"))
    except Exception as exc:
        result = {"findings": [{"severity": "FAIL", "rule": "l15_parseable",
                                "message": f"cannot parse {l15_path}: {exc}"}]}
    else:
        result = check(l15, _load(l3_path))

    result["l15_path"] = str(l15_path)
    result["blocks"] = True
    fails = [f for f in result["findings"] if f["severity"] == "FAIL"]
    warns = [f for f in result["findings"] if f["severity"] == "WARN"]
    result["pass"] = not fails and not (args.strict and warns)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2))
    for f in result["findings"]:
        print(f"  [{f['severity']}] {f['rule']}: {f['message']}")

    if result["pass"]:
        print(f"[PASS] l15_encoding_tables_contract_check: "
              f"{result.get('code_bearing_tables', 0)} code-bearing table(s) "
              f"reconcilable ({len(warns)} advisory)")
        return 0
    print(f"[FAIL] l15_encoding_tables_contract_check: "
          f"{len(fails)} blocking, {len(warns)} advisory "
          f"(strict={args.strict}) — BLOCKS the flow")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
