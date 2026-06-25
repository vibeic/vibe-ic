"""Ingest — any input format → facts.yaml.

Supported inputs
----------------
  existing_docs : a directory of L1..L9 JSON (the v0.51 benchmark output).
                  Walks each layer tree and emits one Fact per leaf.
  structured    : a single YAML file with top-level keys L1/L2/.../L9.
                  Convenient for expert users who can paste a full spec.
  user_yaml     : a YAML file with top-level free-form categories
                  (overview, pinout, electrical_characteristics, protocol,
                  otp, timing, …) — gets mapped into the appropriate layer
                  view via a lookup table.
  text          : (stub) natural-language prompt. MVP delegates to the IC Expert Agent.

The MVP expects either `existing_docs` or `structured` input; `user_yaml`
and `text` land in later iterations.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schema import (
    ALL_LAYER_CODES,
    Fact,
    FactGraph,
    LAYER_CODES,
    LAYER_FILE_NAMES,
    Provenance,
)


# ---------------------------------------------------------------------------
# Lenient JSON reader (benchmark uses 0x70 hex literals)
# ---------------------------------------------------------------------------
_HEX_RE = re.compile(r'(?P<pfx>[:\[\,\s])0x([0-9a-fA-F]+)')


def _lenient_json(path: Path) -> Any:
    text = path.read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(
            _HEX_RE.sub(lambda m: m.group("pfx") + str(int(m.group(2), 16)), text)
        )


# ---------------------------------------------------------------------------
# Tree walk — emit one leaf per fact
# ---------------------------------------------------------------------------
def _walk_leaves(obj: Any, prefix: str = ""):
    """Yield (path, value) for every scalar leaf or dict-of-primitives.

    The "all-scalar record" heuristic only fires when prefix is non-empty
    — i.e. on nested dicts like `{min,typ,max,unit}` or `{opcode,name}`.
    At the top level (prefix == "") we always recurse, otherwise an
    entire layer dict whose values happen to all be scalars (e.g. an L8R
    block of pure clock/polarity constants) would be yielded as a single
    facts-less record and dropped by `if not leaf_path: continue`.
    See v0.61 Bug #1 (L8R silent drop) for the regression that motivated
    this guard.
    """
    if isinstance(obj, dict):
        if (
            prefix
            and obj
            and all(_is_scalar(v) for v in obj.values())
            and len(obj) > 1
        ):
            yield prefix, obj
            return
        for k, v in obj.items():
            # Sanitize key for path: keep as-is except escape dots.
            child_key = str(k).replace(".", "_")
            child_path = f"{prefix}.{child_key}" if prefix else child_key
            yield from _walk_leaves(v, child_path)
    elif isinstance(obj, list):
        # If every element is a scalar (or short), emit whole list as fact.
        # Like the dict heuristic, only fires when prefix is non-empty so
        # a top-level all-scalar list isn't dropped.
        if prefix and (not obj or all(_is_scalar(v) for v in obj)):
            yield prefix, obj
            return
        for i, v in enumerate(obj):
            child_path = f"{prefix}[{i}]" if prefix else f"[{i}]"
            yield from _walk_leaves(v, child_path)
    else:
        yield prefix, obj


def _is_scalar(v: Any) -> bool:
    return v is None or isinstance(v, (bool, int, float, str))


# ---------------------------------------------------------------------------
# Entry — existing docs directory
# ---------------------------------------------------------------------------
def from_existing_docs(
    docs_dir: Path,
    ic_name: Optional[str] = None,
    class_path: Optional[str] = None,
) -> FactGraph:
    """Reverse-extract a fact graph from an existing L1..L9 JSON directory.

    Every leaf in L<N>.json becomes a Fact with path = "L<N>.<leaf_path>",
    views = ["L<N>"], provenance.source = "user_stated" (we treat the
    existing file as authoritative input, not defaulted).
    """
    docs_dir = Path(docs_dir)
    if not docs_dir.is_dir():
        raise FileNotFoundError(f"not a directory: {docs_dir}")

    inferred_name = ic_name
    inferred_class = class_path
    fg = FactGraph(ic_name="__unknown__", class_path="__unknown__")

    for code in ALL_LAYER_CODES:
        fname = LAYER_FILE_NAMES.get(code)
        if not fname:
            continue
        fpath = docs_dir / fname
        if not fpath.exists():
            continue
        tree = _lenient_json(fpath)
        if not isinstance(tree, dict):
            continue

        # Pluck ic_name / class_path if present.
        if inferred_name is None and isinstance(tree.get("ic_name"), str):
            inferred_name = tree["ic_name"]
        if inferred_class is None and isinstance(tree.get("class_path"), str):
            inferred_class = tree["class_path"]

        for leaf_path, leaf_value in _walk_leaves(tree):
            if not leaf_path:
                continue
            fg.add_fact(
                path=f"{code}.{leaf_path}",
                value=leaf_value,
                views=[code],
                source="user_stated",
                origin=str(fpath.relative_to(docs_dir)),
                confidence=1.0,
                reasoning="reverse-extracted from existing layer document",
            )

    if inferred_name:
        fg.ic_name = inferred_name
    if inferred_class:
        fg.class_path = inferred_class

    fg.metadata["ingested_from"] = "existing_docs"
    fg.metadata["source_dir"] = str(docs_dir)
    return fg


# ---------------------------------------------------------------------------
# Entry — structured YAML with layer-keyed sections
# ---------------------------------------------------------------------------
def from_structured_yaml(yaml_path: Path) -> FactGraph:
    """Parse a YAML like:

        ic_name: BENCH-A
        class_path: cable-side-id-ic
        L1: { ic_name: BENCH-A, pinout: {...}, ... }
        L3: { protocol_name: ..., commands: [...] }
        ...

    Each L<N> subtree is walked the same way as from_existing_docs.
    """
    import yaml
    doc = yaml.safe_load(Path(yaml_path).read_text())
    if not isinstance(doc, dict):
        raise ValueError("structured YAML must be a mapping")

    fg = FactGraph(
        ic_name=doc.get("ic_name", "__unknown__"),
        class_path=doc.get("class_path", "__unknown__"),
    )

    for code in ALL_LAYER_CODES:
        tree = doc.get(code)
        if not isinstance(tree, dict):
            continue
        for leaf_path, leaf_value in _walk_leaves(tree):
            if not leaf_path:
                continue
            fg.add_fact(
                path=f"{code}.{leaf_path}",
                value=leaf_value,
                views=[code],
                source="user_stated",
                origin=str(yaml_path),
                confidence=1.0,
                reasoning="parsed from structured yaml",
            )

    fg.metadata["ingested_from"] = "structured_yaml"
    fg.metadata["source_file"] = str(yaml_path)
    return fg


# ---------------------------------------------------------------------------
# Entry — pin table CSV
# ---------------------------------------------------------------------------
def _open_csv_rows(csv_path: Path) -> List[Dict[str, str]]:
    import csv
    with Path(csv_path).open(newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError(f"{csv_path}: CSV has no header row")
        return [
            {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            for row in reader
        ]


def _lower_key_map(row: Dict[str, str]) -> Dict[str, str]:
    return {k.lower(): v for k, v in row.items()}


def from_pin_csv(csv_path: Path) -> FactGraph:
    """Parse a pin-table CSV into L1.pinout facts.

    Required columns (case-insensitive): one of {pin, pin_number, number, #}
    plus one of {name, pin_name, signal}. Optional columns: type, direction,
    description, package_location — stored as sub-facts of pinout.<NAME>.
    Also emits L1.pin_count = row count.
    """
    rows = _open_csv_rows(csv_path)
    if not rows:
        raise ValueError(f"{csv_path}: no data rows")

    PIN_COLS = {"pin", "pin_number", "number", "#", "pin_no"}
    NAME_COLS = {"name", "pin_name", "signal", "signal_name"}

    def pick(row: Dict[str, str], cols: set) -> Optional[str]:
        lk = _lower_key_map(row)
        for c in cols:
            if c in lk and lk[c]:
                return lk[c]
        return None

    fg = FactGraph(ic_name="__unknown__", class_path="__unknown__")
    for idx, row in enumerate(rows):
        pin_num = pick(row, PIN_COLS)
        name = pick(row, NAME_COLS)
        if not name:
            raise ValueError(
                f"{csv_path}: row {idx+1} has no pin name column "
                f"(expected one of {sorted(NAME_COLS)})"
            )
        base = f"L1.pinout.{name}"
        if pin_num:
            fg.add_fact(
                path=f"{base}.pin_number", value=pin_num,
                views=["L1"], source="user_stated",
                origin=str(csv_path),
                confidence=1.0, reasoning="pin csv",
            )
        for k, v in row.items():
            kl = k.lower()
            if kl in PIN_COLS or kl in NAME_COLS:
                continue
            if not v:
                continue
            fg.add_fact(
                path=f"{base}.{kl}", value=v,
                views=["L1"], source="user_stated",
                origin=str(csv_path),
                confidence=1.0, reasoning="pin csv",
            )
    fg.add_fact(
        path="L1.pin_count", value=len(rows),
        views=["L1"], source="derived",
        origin=str(csv_path),
        confidence=1.0, reasoning="derived from pin csv row count",
    )
    fg.metadata["ingested_from"] = "pin_csv"
    fg.metadata["source_file"] = str(csv_path)
    return fg


# ---------------------------------------------------------------------------
# Entry — register map CSV
# ---------------------------------------------------------------------------
def from_regmap_csv(csv_path: Path) -> FactGraph:
    """Parse a register-map CSV into L4.registers.<NAME> facts.

    Required columns: one of {name, register, reg_name} and one of
    {address, addr, offset}. Optional: width, access, reset, description,
    plus any bit-field columns (emit verbatim as sub-facts).
    Also emits L4.register_count.
    """
    rows = _open_csv_rows(csv_path)
    if not rows:
        raise ValueError(f"{csv_path}: no data rows")

    NAME_COLS = {"name", "register", "reg_name", "reg"}
    ADDR_COLS = {"address", "addr", "offset"}

    def pick(row: Dict[str, str], cols: set) -> Optional[str]:
        lk = _lower_key_map(row)
        for c in cols:
            if c in lk and lk[c]:
                return lk[c]
        return None

    fg = FactGraph(ic_name="__unknown__", class_path="__unknown__")
    for idx, row in enumerate(rows):
        name = pick(row, NAME_COLS)
        if not name:
            raise ValueError(
                f"{csv_path}: row {idx+1} has no register name column "
                f"(expected one of {sorted(NAME_COLS)})"
            )
        addr = pick(row, ADDR_COLS)
        base = f"L4.registers.{name}"
        if addr:
            fg.add_fact(
                path=f"{base}.address", value=addr,
                views=["L4"], source="user_stated",
                origin=str(csv_path), confidence=1.0, reasoning="regmap csv",
            )
        for k, v in row.items():
            kl = k.lower()
            if kl in NAME_COLS or kl in ADDR_COLS:
                continue
            if not v:
                continue
            fg.add_fact(
                path=f"{base}.{kl}", value=v,
                views=["L4"], source="user_stated",
                origin=str(csv_path), confidence=1.0, reasoning="regmap csv",
            )
    fg.add_fact(
        path="L4.register_count", value=len(rows),
        views=["L4"], source="derived",
        origin=str(csv_path), confidence=1.0,
        reasoning="derived from regmap csv row count",
    )
    fg.metadata["ingested_from"] = "regmap_csv"
    fg.metadata["source_file"] = str(csv_path)
    return fg


# ---------------------------------------------------------------------------
# Entry — OTP hex image
# ---------------------------------------------------------------------------
def _parse_intel_hex(text: str) -> List[int]:
    """Return byte array from Intel-HEX text, or raise ValueError.

    Supports record types 00 (data) and 01 (EOF). Sparse records are
    flattened into a contiguous array with zero fill in gaps.
    """
    bytes_out: Dict[int, int] = {}
    saw_data = False
    saw_eof = False
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if not line.startswith(":"):
            raise ValueError(f"line {lineno}: Intel HEX must start with ':'")
        body = line[1:]
        if len(body) < 10 or len(body) % 2 != 0:
            raise ValueError(f"line {lineno}: malformed Intel HEX record")
        try:
            raw_bytes = bytes.fromhex(body)
        except ValueError as e:
            raise ValueError(f"line {lineno}: non-hex data ({e})") from e
        byte_count = raw_bytes[0]
        addr = (raw_bytes[1] << 8) | raw_bytes[2]
        rtype = raw_bytes[3]
        data = raw_bytes[4:4 + byte_count]
        cksum = raw_bytes[4 + byte_count]
        computed = (-sum(raw_bytes[:4 + byte_count])) & 0xFF
        if computed != cksum:
            raise ValueError(
                f"line {lineno}: Intel HEX checksum fail "
                f"(got 0x{cksum:02X}, want 0x{computed:02X})"
            )
        if rtype == 0x00:
            for i, b in enumerate(data):
                bytes_out[addr + i] = b
            saw_data = True
        elif rtype == 0x01:
            saw_eof = True
            break
    if not saw_data:
        raise ValueError("Intel HEX had no data records")
    if not saw_eof:
        raise ValueError("Intel HEX missing EOF record (:00000001FF)")
    if not bytes_out:
        return []
    hi = max(bytes_out)
    return [bytes_out.get(i, 0) for i in range(hi + 1)]


def _parse_raw_hex(text: str) -> List[int]:
    """Parse whitespace/comma-separated hex bytes. Ignores '#' comments and
    '0x' prefixes. Returns byte list starting at address 0."""
    out: List[int] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        # strip comments
        line = re.sub(r"#.*$", "", raw).strip()
        if not line:
            continue
        for tok in re.split(r"[\s,]+", line):
            if not tok:
                continue
            t = tok[2:] if tok.lower().startswith("0x") else tok
            try:
                v = int(t, 16)
            except ValueError as e:
                raise ValueError(
                    f"line {lineno}: bad hex token {tok!r}"
                ) from e
            if not 0 <= v <= 0xFF:
                raise ValueError(
                    f"line {lineno}: byte out of range: 0x{v:X}"
                )
            out.append(v)
    return out


def from_otp_hex(hex_path: Path) -> FactGraph:
    """Parse an OTP image (Intel HEX preferred, falls back to raw hex
    bytes) into L4.otp facts. Emits:
      L4.otp_present = True
      L4.otp_size_bytes = N
      L4.otp.bytes[<idx>] = int (one fact per byte)
      L4.otp.format = "intel_hex" | "raw_hex"
    """
    text = Path(hex_path).read_text()
    # Detect format from first non-empty line. If it starts with ':',
    # the file declares Intel HEX: any parse error inside (checksum,
    # record length, EOF) MUST surface to the caller — silently falling
    # back to raw hex would swallow real data corruption.
    first = next(
        (ln for ln in text.splitlines() if ln.strip()), ""
    )
    if first.strip().startswith(":"):
        bytes_list = _parse_intel_hex(text)
        fmt = "intel_hex"
    else:
        bytes_list = _parse_raw_hex(text)
        fmt = "raw_hex"

    if not bytes_list:
        raise ValueError(f"{hex_path}: no bytes parsed")

    fg = FactGraph(ic_name="__unknown__", class_path="__unknown__")
    fg.add_fact(
        path="L4.otp_present", value=True,
        views=["L4"], source="user_stated",
        origin=str(hex_path), confidence=1.0, reasoning="otp hex",
    )
    fg.add_fact(
        path="L4.otp_size_bytes", value=len(bytes_list),
        views=["L4"], source="derived",
        origin=str(hex_path), confidence=1.0,
        reasoning="otp size from byte count",
    )
    fg.add_fact(
        path="L4.otp.format", value=fmt,
        views=["L4"], source="derived",
        origin=str(hex_path), confidence=1.0, reasoning="otp format detected",
    )
    for i, b in enumerate(bytes_list):
        fg.add_fact(
            path=f"L4.otp.bytes[{i}]", value=b,
            views=["L4"], source="user_stated",
            origin=str(hex_path), confidence=1.0, reasoning="otp byte",
        )
    fg.metadata["ingested_from"] = "otp_hex"
    fg.metadata["source_file"] = str(hex_path)
    return fg


# ---------------------------------------------------------------------------
# Merge multiple graphs (e.g. base structured + pin-table paste)
# ---------------------------------------------------------------------------
def merge(base: FactGraph, *others: FactGraph) -> FactGraph:
    """Merge several graphs into one. Later graphs override earlier ones on
    (path, views) collisions."""
    for other in others:
        if other.ic_name != "__unknown__" and base.ic_name == "__unknown__":
            base.ic_name = other.ic_name
        if other.class_path != "__unknown__" and base.class_path == "__unknown__":
            base.class_path = other.class_path
        for fact in other.facts:
            base.add(fact)
    return base
