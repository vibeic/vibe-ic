"""Extract register-table rows from extracted PDF/text docs.

v1.6.106 — addresses GitHub issue #36 Bug 1 (P0) — dash-separated
prose form ``0x<HEX> (r|r/w|w) <name> - <description>``.

v1.6.108 — addresses GitHub issue #40 Bug 1B (P0) — column-whitespace
aligned tables found in real opencores PDFs (verbatim SHA-1 example)::

       0x00          r       name0
       0x01          r       name1
       0x10          r/w     ctrl
       0x20-0x2F     w       block0..F
       0x40-0x47     r       digest0..7

No dash separator; columns are aligned with 2+ spaces; description
column may be absent; address may be a range (``0x20-0x2F``) which
emits a single row with ``addr_range_hex`` instead of ``addr_hex``.

The extractor tries the dash-separated regex first (backward-compat
with v1.6.106 callers), then the column-whitespace regex. Header rows
(``Address  Type  Name  Description``) are filtered via a small name
stop-list to avoid junk entries.

Pure regex, no project-specific paths. Class-conditional gating
happens at the call site (crypto_*, memory_controller,
storage_controller).
"""

from __future__ import annotations

import re
from typing import Dict, List


# ---------------------------------------------------------------------------
# v1.6.106 — dash-separated form (backward compat)
# ---------------------------------------------------------------------------
_REG_TABLE_ROW_RE = re.compile(
    r"^\s*(0x[0-9A-Fa-f]+)\s+"           # address: 0x00, 0x10, ...
    r"(r/w|rw|r|w)\s+"                    # access: r, r/w, w
    r"([A-Za-z_][A-Za-z0-9_]*)\s+"        # name: core_name, ctrl, ...
    r"[-–—]\s+"                # separator dash (-, en-, em-)
    r"(.+?)\s*$",                          # description (rest of line)
    re.MULTILINE,
)

# ---------------------------------------------------------------------------
# v1.6.108 — column-whitespace aligned form (#40 Bug 1B)
#
# Address column may be a single 0x<HEX> or a range
# `0x<HEX>-0x<HEX>` (en/em-dash also tolerated). Access column is one
# of r/w/rw/r/w. Name column is a normal identifier (allow trailing
# `0..F`/`0..7` style range hints). Description column is optional.
# Columns are separated by 2+ spaces — a single space is too loose
# (would match prose like "see 0x00 r register" which we don't want).
# ---------------------------------------------------------------------------
_REG_TABLE_ROW_COLS_RE = re.compile(
    r"^\s*"
    r"(0x[0-9A-Fa-f]+(?:[-–—]0x[0-9A-Fa-f]+)?)"  # addr or range
    r"\s{2,}"                                              # column gap
    r"(r/w|rw|r|w)"                                        # access
    r"\s{2,}"                                              # column gap
    r"([A-Za-z_][A-Za-z0-9_.]*(?:\.\.[0-9A-Fa-f]+)?)"      # name (+range hint)
    r"(?:\s{2,}(.+?))?"                                    # optional description
    r"\s*$",
)

# Header rows often render as a column-aligned line (`Address  Type
# Name  Description`) that the column regex above will happily
# accept as `addr_hex="Address"` ... no, addr is anchored to 0x. But
# a defensive name stop-list still helps: cells like `Type` / `Name`
# / `Address` are never real register names.
_HEADER_NAME_STOP_LIST = {
    "type", "name", "address", "description", "access", "field",
    "register", "regname",
}

# Address-range separator (real PDFs sometimes use en/em dash).
_ADDR_RANGE_SEP_RE = re.compile(r"[-–—]")


def _is_header_row(name: str) -> bool:
    return name.strip().lower() in _HEADER_NAME_STOP_LIST


def _normalize_addr(addr: str) -> str:
    """Lower-case and replace en/em dashes with ASCII '-'."""
    return _ADDR_RANGE_SEP_RE.sub("-", addr).lower()


def extract_regmap_table(text: str, source_path: str) -> List[Dict]:
    """Return list of register dicts. Empty list if no rows match.

    Each entry shape (single-address row)::

        {
          "addr_hex": "0x10",         # lowercased
          "access":   "r_w",           # "r" / "w" / "r_w"
          "name":     "ctrl",
          "description": "control register",
          "evidence": {
            "source": <source_path>,
            "line":   <1-based line number>,
            "matched_token": <line[:120]>,
            "extraction_strategy":
                "pdf_regmap_table_match" |
                "pdf_regmap_table_columns_match",
          }
        }

    Range rows (e.g. ``0x20-0x2F``) drop ``addr_hex`` and emit
    ``addr_range_hex`` instead — downstream consumers can choose how
    to expand them.
    """
    if not text:
        return []
    rows: List[Dict] = []
    for lineno, line in enumerate(text.split("\n"), start=1):
        # Try v1.6.106 dash-separated form first (backward compat).
        m_dash = _REG_TABLE_ROW_RE.match(line)
        if m_dash:
            addr_hex, access, name, description = m_dash.groups()
            if _is_header_row(name):
                continue
            access_norm = access.lower().replace("/", "_")
            rows.append({
                "addr_hex": addr_hex.lower(),
                "access": access_norm,
                "name": name,
                "description": description.strip(),
                "evidence": {
                    "source": source_path,
                    "line": lineno,
                    "matched_token": line.strip()[:120],
                    "extraction_strategy": "pdf_regmap_table_match",
                },
            })
            continue

        # v1.6.108 — column-whitespace form fallback.
        m_cols = _REG_TABLE_ROW_COLS_RE.match(line)
        if m_cols:
            addr_raw, access, name, description = m_cols.groups()
            if _is_header_row(name):
                continue
            access_norm = access.lower().replace("/", "_")
            entry: Dict = {
                "access": access_norm,
                "name": name,
                "description": (description or "").strip(),
                "evidence": {
                    "source": source_path,
                    "line": lineno,
                    "matched_token": line.strip()[:120],
                    "extraction_strategy": "pdf_regmap_table_columns_match",
                },
            }
            addr_norm = _normalize_addr(addr_raw)
            if "-" in addr_norm:
                entry["addr_range_hex"] = addr_norm
            else:
                entry["addr_hex"] = addr_norm
            rows.append(entry)
            continue
    return rows
