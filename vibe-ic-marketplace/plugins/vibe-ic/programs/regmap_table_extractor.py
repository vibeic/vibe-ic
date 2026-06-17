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


# ---------------------------------------------------------------------------
# #616 — GitHub-Flavored-Markdown pipe-delimited register summary tables.
#
# Auto-generated register docs (e.g. an `*_registers.md`) commonly render as::
#
#     | Name                         | Offset | Length | Description          |
#     |------------------------------|--------|--------|----------------------|
#     | [`ALERT_TEST`](#alert_test)  | 0x0    | 4      | Alert Test Register  |
#
# The address is NOT the first token (Name-first ordering) and cells are
# `|`-delimited, so neither the dash nor the column-whitespace regex above
# matches — the extractor returned ZERO rows for a 40+ register map. This
# parser is HEADER-DRIVEN: it locates the column roles from a `|`-leading
# header whose cells include a name keyword AND an offset/address keyword,
# then reads each data row by those column indices. Chip-AGNOSTIC: pure GFM
# table grammar, no chip/register-name vocabulary.
# ---------------------------------------------------------------------------
_GFM_NAME_HDR = {"name", "register", "field", "regname", "reg",
                 "register name", "csr name", "field name",
                 # #747-reopen: rst grid maps use these as the NAME column
                 # header (perf-counters / interrupt-cause / parameter tables).
                 "event counter", "event selector", "event", "counter",
                 "selector", "mcause", "parameter"}
_GFM_OFFSET_HDR = {"offset", "address", "addr", "csr address",
                   "base address", "register address", "reg address",
                   # #747-reopen: rst grid maps put the hex constant under a
                   # generic value/default column header. These are weak-role
                   # headers — the cell must contain an actual 0x... token to
                   # emit a row (see _GFM_OFFSET_HEX_RE gate), so a decimal
                   # `Default` value (0/4/40) never fabricates a phantom addr.
                   "default", "reset value", "value"}
_GFM_LEN_HDR = {"length", "size", "width", "bytes"}
_GFM_DESC_HDR = {"description", "desc", "notes", "function"}
_GFM_ACCESS_HDR = {"access", "type", "rw", "mode", "permission", "perm"}
# Weak-role OFFSET headers: a column header that legitimately holds non-address
# data (a parameter `Default` of 0/4/RV32MFast, a `Value`, a `Reset Value`).
# When the offset column was tagged from one of these, ONLY emit a row whose
# offset cell actually holds a real `0x...` hex token — never a bare decimal —
# so the parameter/value tables do not fabricate phantom addresses (§4.05).
_GFM_OFFSET_WEAK_HDR = {"default", "reset value", "value"}
_GFM_SEP_CELL_RE = re.compile(r"^:?-{2,}:?$")
_GFM_OFFSET_RE = re.compile(r"(0x[0-9A-Fa-f]+|\b\d+\b)")
# ORGANIC #800 (gapJ) — a CSR offset cell of the form ``0xLOW (0xHIGH)`` carries
# TWO addresses: the low-word register address + a parenthetical high-word alias
# (the upper-32b companion CSR of a 64b counter pair). The single-offset regexes
# capture only the LEADING 0x token, so the high-word alias is lost — one
# undercounted address token per pair. This captures BOTH. chip-AGNOSTIC: pure
# ``0x.. (0x..)`` grammar. The parenthetical is OPTIONAL (a plain ``0xC00`` cell
# yields group(2)=None → a single-address row exactly as before, no duplication).
_GFM_OFFSET_PAREN_ALIAS_RE = re.compile(
    r"^\s*(0x[0-9A-Fa-f][0-9A-Fa-f_]*)"                  # primary low-word addr
    r"(?:\s*\(\s*(0x[0-9A-Fa-f][0-9A-Fa-f_]*)\s*\))?")  # optional (0xHIGH) alias


def _offset_addrs(cell: str) -> "List[str]":
    """ORGANIC #800 — the list of lowercased ``0x..`` addresses an offset cell
    carries: ``[low]`` for a plain ``0xC00`` cell, ``[low, high]`` for a
    ``0xC00 (0xC80)`` low/high CSR pair. ``[]`` when the cell does not LEAD with
    a 0x token (a Description cell that merely mentions a hex in prose
    contributes nothing — §4.05 no-leak). De-dups so ``0xC00 (0xC00)`` yields a
    single ``0xc00``."""
    m = _GFM_OFFSET_PAREN_ALIAS_RE.match(cell)
    if not m:
        return []
    out = [m.group(1).lower()]
    if m.group(2):
        hi = m.group(2).lower()
        if hi != out[0]:
            out.append(hi)
    return out
# Strict `0x...` token (underscored hex like `0x0000_0010` tolerated). Used for
# the weak-role OFFSET headers and the structural fallback so a bare decimal can
# never be promoted to an address (§4.05 no-leak).
_GFM_OFFSET_HEX_RE = re.compile(r"(0x[0-9A-Fa-f][0-9A-Fa-f_]*)")
# An ADDRESS cell LEADS with a `0x...` token (a parenthetical high-word alias
# like `0xB04 (0xB84)` is fine). This is stricter than a buried search: it
# separates a real address cell from a Description cell that merely MENTIONS a
# hex in prose (e.g. ``= ``boot_addr_i`` + 0x80,``) — the structural fallback
# must not mistake such a prose mention for the table's address column (§4.05).
_GFM_ADDR_CELL_RE = re.compile(r"^\s*(0x[0-9A-Fa-f][0-9A-Fa-f_]*)\b")
# Register NAME inside a cell: a markdown link [`X`](#a) / [X](#a), or a bare
# backticked `X`, or a lone identifier cell. The leading link/backtick form
# wins so a "Foo.[`BAR`](#bar)" cell yields BAR (not the prose prefix).
_GFM_LINK_NAME_RE = re.compile(r"\[\s*`?([A-Za-z_]\w*)`?\s*\]")
_GFM_TICK_NAME_RE = re.compile(r"`([A-Za-z_]\w*)`")
_GFM_BARE_NAME_RE = re.compile(r"^[A-Za-z_]\w*$")
# #747-reopen: rst inline literals use DOUBLE backticks and may carry a
# non-identifier suffix, e.g. ``mhpmcounter4(h)`` — the existing single-tick
# regex needs a closing backtick right after the identifier, so it misses these.
# Grab the leading identifier immediately after one-or-more opening backticks.
_GFM_RST_LITERAL_NAME_RE = re.compile(r"`+\s*([A-Za-z_]\w*)")


def _gfm_cells(line: str) -> List[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _gfm_clean_name(cell: str) -> str:
    m = _GFM_LINK_NAME_RE.search(cell)
    if m:
        return m.group(1)
    m = _GFM_TICK_NAME_RE.search(cell)
    if m:
        return m.group(1)
    s = cell.strip()
    if _GFM_BARE_NAME_RE.match(s):
        return s
    # #747-reopen: rst double-backtick inline literal like ``mhpmcounter4(h)``
    # (the single-tick regex above needs a closing backtick right after the
    # identifier, so it misses the `(h)`-suffixed form).
    m = _GFM_RST_LITERAL_NAME_RE.match(s)
    if m:
        return m.group(1)
    return ""


def _extract_gfm_pipe_table(text: str, source_path: str) -> List[Dict]:
    """Parse `|`-delimited GFM register summary tables (Name-first). Returns
    [] when no such table (with a name+offset header) is present, so callers
    keep the dash/column regex behaviour for non-pipe docs."""
    rows: List[Dict] = []
    cols = None  # role -> column index, set from the detected header
    for lineno, line in enumerate(text.split("\n"), start=1):
        s = line.strip()
        if not s.startswith("|"):
            cols = None  # any non-pipe line ends the current table region
            continue
        cells = _gfm_cells(line)
        nonempty = [c for c in cells if c]
        # separator row (|---|:--:|---:|) — skip
        if nonempty and all(_GFM_SEP_CELL_RE.match(c.replace(" ", ""))
                            for c in nonempty):
            continue
        low = [c.lower() for c in cells]
        if cols is None:
            # header row iff it names both a register-name and an offset col
            if any(c in _GFM_NAME_HDR for c in low) and \
               any(c in _GFM_OFFSET_HDR for c in low):
                cols = {}
                for i, c in enumerate(low):
                    if c in _GFM_NAME_HDR:
                        cols.setdefault("name", i)
                    elif c in _GFM_OFFSET_HDR:
                        cols.setdefault("offset", i)
                        # #747-r2 weak-offset guard, ported onto the GFM PRIMARY
                        # path: a generic Value/Default/Reset-Value column is a
                        # WEAK offset role — its cell must hold a real 0x... token
                        # before becoming an address, so a `| Field | Value |`
                        # SPEC table (decimals in the Value prose) cannot
                        # fabricate phantom registers (§4.05). First-offset-wins
                        # via setdefault keeps a strong `Offset`/`Address` column
                        # decimal-tolerant.
                        if c in _GFM_OFFSET_WEAK_HDR:
                            cols.setdefault("offset_weak", True)
                    elif c in _GFM_LEN_HDR:
                        cols.setdefault("length", i)
                    elif c in _GFM_DESC_HDR:
                        cols.setdefault("desc", i)
                    elif c in _GFM_ACCESS_HDR:
                        cols.setdefault("access", i)
            continue  # header consumed (or a pre-table pipe line ignored)
        ni, oi = cols.get("name"), cols.get("offset")
        if ni is None or oi is None or ni >= len(cells) or oi >= len(cells):
            continue
        name = _gfm_clean_name(cells[ni])
        if not name or _is_header_row(name):
            continue
        # A WEAK offset column (Value/Default/Reset Value) only yields an address
        # from a genuine 0x... token — never a bare decimal — exactly as the
        # rst-grid path gates it (_flush_rst_grid_table). A strong Offset/Address
        # column keeps the decimal-tolerant match (an `Offset` of `4` is a real
        # byte offset). This is the §4.05 weak-offset guard.
        if cols.get("offset_weak"):
            mo = _GFM_OFFSET_HEX_RE.search(cells[oi])
        else:
            mo = _GFM_OFFSET_RE.search(cells[oi])
        if not mo:
            continue
        # ORGANIC #800 — emit one row per address for a `0xLOW (0xHIGH)` CSR pair.
        addrs = _offset_addrs(cells[oi])
        if not addrs:
            off = mo.group(1).lower()
            addrs = [off if off.startswith("0x") else hex(int(off))]
        desc = ""
        if "desc" in cols and cols["desc"] < len(cells):
            desc = cells[cols["desc"]]
        if "length" in cols and cols["length"] < len(cells) and cells[cols["length"]]:
            length = cells[cols["length"]]
            desc = (f"{desc} (length={length})").strip() if desc else f"length={length}"
        access_norm = ""
        if "access" in cols and cols["access"] < len(cells):
            access_norm = cells[cols["access"]].strip().lower().replace("/", "_")
        for addr_hex in addrs:
            rows.append({
            "addr_hex": addr_hex,
            "access": access_norm,
            "name": name,
            "description": desc.strip(),
            "evidence": {
                "source": source_path,
                "line": lineno,
                "matched_token": line.strip()[:120],
                "extraction_strategy": "gfm_pipe_table_match",
            },
        })
    return rows


# ---------------------------------------------------------------------------
# #747 — reStructuredText GRID-table register/CSR maps.
#
# rst grid tables draw their cell borders with plus/dash/equals runs and put
# the cell contents on `| col | col |` rows, e.g.::
#
#     +-------------+-------------+----------------------+
#     | CSR Address | Name        | Description          |
#     +=============+=============+======================+
#     | 0xB04       | minstret    | Instructions retired |
#     +-------------+-------------+----------------------+
#
# The #616 GFM path RESETS the column map on EVERY non-pipe line, so the
# `+---+` / `+===+` border lines (which separate every rst row) abort the
# table before any data row is read — and multi-word headers like
# `CSR Address` were not in the keyword sets. This parser treats the
# plus-dash / plus-equals border lines as IN-TABLE separators (skip, do NOT
# end the table), keyword-matches the (now multi-word-aware) header, then
# reads each `|`-cell data row by column index — emitting addr_hex/name in
# the same shape as the GFM path. Chip-AGNOSTIC: pure rst grid-table grammar,
# no chip/register-name vocabulary. Enumerated CSR ranges in the name/desc
# cells are expanded exactly as the GFM path would (none here — the address
# cell is a single 0x token; range expansion stays a downstream concern, as
# in the GFM path).
# ---------------------------------------------------------------------------
# A grid border line is ONLY plus/dash/equals/space and contains at least one
# '+' (so it cannot be confused with a data/header `|`-row or a markdown
# `:--:` GFM separator, which has no '+').
_RST_GRID_BORDER_RE = re.compile(r"^\s*\+[+=\-\s]*\+\s*$")


def _rst_is_grid_border(line: str) -> bool:
    s = line.strip()
    return bool(s) and "+" in s and _RST_GRID_BORDER_RE.match(line) is not None


def _rst_header_roles(low: List[str]) -> Dict:
    """Map a lowercased header cell list to {role: column-index}. A column may
    be named (NAME / OFFSET / LEN / DESC / ACCESS) by a generic doc-vocabulary
    keyword. setdefault keeps the FIRST match per role so e.g. a table with both
    `CSR Address` and `Reset Value` picks `CSR Address` as the offset."""
    cols: Dict = {}
    for i, c in enumerate(low):
        if c in _GFM_NAME_HDR:
            cols.setdefault("name", i)
        elif c in _GFM_OFFSET_HDR:
            cols.setdefault("offset", i)
            if c in _GFM_OFFSET_WEAK_HDR:
                cols.setdefault("offset_weak", True)
        elif c in _GFM_LEN_HDR:
            cols.setdefault("length", i)
        elif c in _GFM_DESC_HDR:
            cols.setdefault("desc", i)
        elif c in _GFM_ACCESS_HDR:
            cols.setdefault("access", i)
    return cols


def _rst_structural_roles(header_low: List[str],
                          data_rows: List[List[str]]) -> Dict:
    """STRUCTURAL FALLBACK (#747-reopen): when the header does not name BOTH a
    name and an offset column, infer them from the DATA shape without any
    vocabulary. The column whose cells consistently hold a real `0x...` token is
    the address; an adjacent identifier-bearing text column is the name. Handles
    the 2-column `| 0x... | Description |` case and the `Default`-column case.
    Returns {} (no inference) unless exactly one column is hex-dominant — so a
    Description-ONLY table (no 0x anywhere) yields nothing (§4.05 no-leak)."""
    if not data_rows:
        return {}
    ncols = max(len(r) for r in data_rows)
    # Per-column tallies. addr_hits counts cells that LEAD with a 0x... token (a
    # genuine address cell); nonempty counts all non-blank cells; name_hits the
    # identifier-bearing cells. Leading-token (not buried search) is what lets a
    # Description column that merely MENTIONS a hex in prose stay un-promoted.
    addr_hits = [0] * ncols
    nonempty = [0] * ncols
    name_hits = [0] * ncols
    for r in data_rows:
        for i in range(ncols):
            cell = r[i] if i < len(r) else ""
            if not cell.strip():
                continue
            nonempty[i] += 1
            if _GFM_ADDR_CELL_RE.match(cell):
                addr_hits[i] += 1
            elif _gfm_clean_name(cell):
                name_hits[i] += 1
    # Offset column: the one with the most address-leading cells (>=1) that is
    # also address-DOMINANT (>= half its non-empty cells are addresses) — so a
    # lone prose `0x..` mention inside a Description column cannot win.
    off_i = max(range(ncols), key=lambda i: addr_hits[i])
    if addr_hits[off_i] == 0 or addr_hits[off_i] * 2 < nonempty[off_i]:
        return {}  # no address-dominant column -> nothing (no phantom addr).
    cols: Dict = {"offset": off_i, "offset_struct": True}
    # A column whose HEADER is a known Description keyword is the description,
    # never the name — so a continuation row's prose `` ``mtval`` `` mention does
    # not promote the Description column to a (mis-labelled) name column.
    desc_i = None
    for i, c in enumerate(header_low):
        if c in _GFM_DESC_HDR and i != off_i:
            desc_i = i
            break
    # Name column: prefer a header-named name col; else the identifier-richest
    # OTHER non-description column; else leave unset (a 2-col `| 0x... | prose |`
    # still emits an address row with an empty name — the issue only requires
    # the hex to land).
    name_i = None
    for i, c in enumerate(header_low):
        if c in _GFM_NAME_HDR and i != off_i:
            name_i = i
            break
    if name_i is None:
        cand = [i for i in range(ncols)
                if i != off_i and i != desc_i and name_hits[i] > 0]
        if cand:
            name_i = max(cand, key=lambda i: name_hits[i])
    if name_i is not None:
        cols["name"] = name_i
    if desc_i is not None and desc_i != name_i:
        cols["desc"] = desc_i
    return cols


def _flush_rst_grid_table(header_cells: List[str],
                          data: List["tuple"],
                          source_path: str) -> List[Dict]:
    """Resolve column roles for one completed grid table and emit its rows.
    `data` is a list of (lineno, raw_line, cells). Tries the header-keyword
    roles first; if they don't yield BOTH name and offset, falls back to the
    structural (vocabulary-free) inference. Returns [] when neither resolves to
    an offset column — so non-register grid tables stay silent (§4.05)."""
    if not data:
        return []
    low = [c.lower() for c in header_cells]
    cols = _rst_header_roles(low)
    # The header gives a usable register map only when it names BOTH a name and
    # an offset column (the v1.0.82 behaviour). Otherwise try the structural
    # fallback, which can also recover the 2-column / Default-column shapes.
    if "name" not in cols or "offset" not in cols:
        cols = _rst_structural_roles(low, [c for (_, _, c) in data])
    oi = cols.get("offset")
    if oi is None:
        return []
    weak = cols.get("offset_weak") or cols.get("offset_struct")
    out: List[Dict] = []
    ni = cols.get("name")
    for lineno, raw, cells in data:
        if oi >= len(cells):
            continue
        # Weak / structural offset columns (Default / Value / inferred): only a
        # genuine 0x... token may become an address — never a bare decimal
        # (so a parameter `Default` of 0/4/40 makes NO phantom addr). A header
        # OFFSET column (Offset/Address/CSR Address) keeps the decimal-tolerant
        # match the GFM path uses (an `Offset` of `4` is a real byte offset).
        if weak:
            mo = _GFM_OFFSET_HEX_RE.search(cells[oi])
        else:
            mo = _GFM_OFFSET_RE.search(cells[oi])
        if not mo:
            continue
        # ORGANIC #800 — an address cell that LEADS with a 0x token may carry a
        # `0xLOW (0xHIGH)` low/high CSR-pair alias; emit one row per address. A
        # bare-decimal / non-leading-0x offset keeps the single-row path.
        addrs = _offset_addrs(cells[oi])
        if not addrs:
            off = mo.group(1).lower()
            addrs = [off if off.startswith("0x") else hex(int(off))]
        name = ""
        if ni is not None and ni < len(cells):
            name = _gfm_clean_name(cells[ni])
            if name and _is_header_row(name):
                name = ""
        # A header-role table requires a real name (v1.0.82 behaviour); the
        # structural fallback may emit an address-only row (2-col mcause case).
        if not cols.get("offset_struct") and not name:
            continue
        desc = ""
        if "desc" in cols and cols["desc"] < len(cells):
            desc = cells[cols["desc"]]
        if "length" in cols and cols["length"] < len(cells) and cells[cols["length"]]:
            length = cells[cols["length"]]
            desc = (f"{desc} (length={length})").strip() if desc else f"length={length}"
        access_norm = ""
        if "access" in cols and cols["access"] < len(cells):
            access_norm = cells[cols["access"]].strip().lower().replace("/", "_")
        for addr_hex in addrs:
            out.append({
                "addr_hex": addr_hex,
                "access": access_norm,
                "name": name,
                "description": desc.strip(),
                "evidence": {
                    "source": source_path,
                    "line": lineno,
                    "matched_token": raw.strip()[:120],
                    "extraction_strategy": "rst_grid_table_match",
                },
            })
    return out


def _extract_rst_grid_table(text: str, source_path: str) -> List[Dict]:
    """Parse reStructuredText GRID-table register maps (`+---+` / `+===+`
    borders with `| cell |` rows). Returns [] when no grid table with a
    resolvable offset column is present, so callers keep all other behaviour
    for non-grid docs. Disjoint from the GFM path: the GFM path bails the moment
    it sees a border line (non-pipe → cols=None), so it never emits these rows;
    here we treat borders as in-table separators.

    #747-reopen: the column ROLE is resolved per completed table — first by the
    header keywords (broadened to event/counter/selector/mcause/parameter names
    and default/value/reset-value offsets), and if that fails to name BOTH a
    name and an offset column, by a vocabulary-free STRUCTURAL fallback (the
    consistently-`0x...` column IS the address). This recovers the
    Event-Counter / Event-Selector / Default-parameter / 2-column-mcause shapes
    that the v1.0.82 narrow keyword gate dropped, while a Description-only grid
    (no 0x anywhere) still emits nothing."""
    rows: List[Dict] = []
    header_cells: List[str] = []   # first pipe-row of the current table
    data: List[tuple] = []         # (lineno, raw, cells) data rows of the table
    in_grid = False                # True once we've seen a top border

    def _end_table():
        nonlocal header_cells, data, in_grid
        rows.extend(_flush_rst_grid_table(header_cells, data, source_path))
        header_cells = []
        data = []
        in_grid = False

    for lineno, line in enumerate(text.split("\n"), start=1):
        if _rst_is_grid_border(line):
            in_grid = True          # border = in-table separator, NOT end
            continue
        s = line.strip()
        if not s.startswith("|"):
            # A genuine non-border, non-pipe line ends the current grid table.
            _end_table()
            continue
        if not in_grid:
            # A `|`-row with no preceding grid border is a GFM pipe row, not an
            # rst grid cell — leave it to the GFM path (no double-count).
            continue
        cells = _gfm_cells(line)
        nonempty = [c for c in cells if c]
        # A GFM-style separator row (`|:?--:?|`, no `+`) means this is a GFM pipe
        # table that merely abuts a stray border line. Cede it to the GFM path
        # (end the rst table) so a border directly above a GFM table does not
        # double-count its rows (v1.0.82 adversarial-review MEDIUM — preserved).
        if nonempty and all(_GFM_SEP_CELL_RE.match(c) for c in nonempty):
            _end_table()
            continue
        if not header_cells:
            header_cells = cells     # first pipe row = header
        elif any(c.strip() for c in cells):
            # A data row (skip all-blank wrapped-cell continuation rows, which
            # carry no new address and would otherwise dilute the structural
            # hex-dominance tally).
            data.append((lineno, line, cells))
    _end_table()                     # flush the final table at EOF
    return rows


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
    # #616 — GFM pipe-delimited (Name-first) tables, which the line-by-line
    # 0x-anchored regexes above cannot match. Disjoint from the regex rows
    # (those never match a `|`-leading line), so a plain extend is safe.
    rows.extend(_extract_gfm_pipe_table(text, source_path))
    # #747 — reStructuredText GRID tables (`+---+`/`+===+` borders). Disjoint
    # from the GFM path: the GFM path RESETS its column map on every border
    # line (a non-pipe line), so it emits ZERO rows for a grid table — only
    # this branch reads the cells across the in-table border separators.
    rows.extend(_extract_rst_grid_table(text, source_path))
    return rows
