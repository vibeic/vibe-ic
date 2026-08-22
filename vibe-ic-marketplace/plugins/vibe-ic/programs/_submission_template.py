#!/usr/bin/env python3
"""Shared record shape for step 0.5ic — the shuttle operator's slot contract.

Both halves of step 0.5ic read this module: `submission_template_ingest` builds
the record, `submission_template_check` judges it. One module so the two cannot
drift into disagreeing about what a slot record is.

WHY THE GEOMETRY IS INGESTED AND NOT COMPUTED
=============================================
A shuttle operator publishes a project template that PINS the die rectangle for
each purchasable slot -- absolutely, alongside the core rectangle, the sizing
mode and the slot's pad list -- and ships the die-identification fixtures the
operator's own submission gate requires as pre-built layout, not as something a
script generates. So the numbers are not a calculation this flow failed to do.
They are data it never went and got, and only a step can be said to have not run.

THREE STATES, NOT TWO
=====================
    INGESTED       a path was given, it is on disk, and its slots were read.
    ABSENT         a path was given and nothing is there.
    NOT_ATTEMPTED  no path was given. NOBODY LOOKED.

The last two are the distinction this step exists for, and collapsing them is
the defect: "I could not look" must never reach a reader as "I looked and it was
clean". `ABSENT` can be bought with a stated reason, exactly as the flow buys an
unmet `condition_files_exist` with an `absent_condition_reason`, and it then
reads NOT_APPLICABLE -- never PASS. `NOT_ATTEMPTED` cannot be bought at all: a
reason offered for a template nobody searched for describes nothing.

NO NETWORK, EVER
================
Nothing here fetches. The template is a path already on disk, because a step
that silently downloads its own input produces a result that cannot be
reproduced, and this flow's provenance rules exist for exactly that.

NOTHING IS VENDORED
===================
A slot record carries the operator's file PATH and its sha256, never a copy of
the operator's fixtures. The checker re-stats and re-hashes what the record
names, which is what makes "a report claiming a template that is not on disk"
a refusable claim rather than an unfalsifiable one.

CHIP-AGNOSTIC
=============
No vendor, SKU or process-node literal appears here. Slot names, geometry, pad
lists and fixture cell names are all read out of whatever template the caller
points at.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))  # so the sibling import below resolves however this is invoked

# The floor on a stated not-applicable reason is READ, not copied. Two
# hand-kept numbers are two numbers that drift -- the same argument
# `flow_condition_reachability_check` makes for keeping its own copy equal to
# the runtime's, and `test_w4_absent_condition_is_not_a_pass.py::A8` asserts it.
from flow_condition_reachability_check import (  # noqa: E402
    MIN_ABSENT_CONDITION_REASON as MIN_REASON_CHARS,
)

SCHEMA = "submission_template/1"

# Paths this step owns, exactly as `flow/phase1_phase2_phase3.yaml` declares
# them for step 0.5ic. Relative to the design's project root.
REPORT_REL = "reports/phase1/submission_template.json"
INGEST_DIR_REL = "input/submission_template"
SLOTS_DIR_REL = "input/submission_template/slots"
NO_TEMPLATE_REL = "input/submission_template/NO_TEMPLATE.txt"

#: Written when the step ran and NO decision came out of it. Deliberately NOT
#: one of the two names any flow condition tests, because it must select
#: nothing -- see `declares_no_template` below.
NO_DECLARATION_REL = "input/submission_template/NO_DECLARATION.txt"

# Written as the first line of every NO_TEMPLATE.txt this step emits, so a
# re-ingest can retire its OWN stale marker and will not touch a file some
# other hand put there.
NO_TEMPLATE_MARKER = "# submission_template_ingest: no template record"

#: THE TWO FILES ABOVE ARE ROUTERS, NOT NOTES. Measured on the flow that
#: consumes them: `slots/*.yaml` makes the chip-path steps applicable and
#: `NO_TEMPLATE.txt` makes the IP-path step applicable, by `files_exist`
#: condition and nothing else. No step blocks on 0.5ic and no step takes a
#: required_input from it, so a FAILED ingest does not stop either path from
#: being selected -- the file existing is the whole decision.
#:
#: That is why an absence has to be BOUGHT before it is written. A run where
#: nobody looked and a run that searched, found nothing and said so produce the
#: same empty directory; if both wrote `NO_TEMPLATE.txt`, both would select the
#: IP path and the three states this module exists to keep apart would be
#: collapsed back to two by the router, whatever the report said.
STATUS_INGESTED = "INGESTED"
STATUS_ABSENT = "ABSENT"
STATUS_NOT_ATTEMPTED = "NOT_ATTEMPTED"

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_NOT_APPLICABLE = "NOT_APPLICABLE"

def declares_no_template(status: str, reason) -> bool:
    """True iff this record is a DECLARATION that there is no template.

    Both halves of the step call this, so the producer cannot write a router
    file the judge would not have accepted. A stated reason shorter than the
    floor buys nothing here for the same reason it buys nothing at the gate.
    """
    if status != STATUS_ABSENT:
        return False
    why = reason.strip() if isinstance(reason, str) else ""
    return len(why) >= MIN_REASON_CHARS


# A slot file is discovered by the key that PINS THE DIE, and by nothing else --
# not by a filename pattern and not by a directory the operator happens to use
# today. CORE_AREA is deliberately NOT part of the discriminator: a file that
# pins a die and omits the core must be FOUND and refused, because skipping it
# is the silent hole this step exists to close.
DIE_AREA_KEY = "DIE_AREA"
CORE_AREA_KEY = "CORE_AREA"
FP_SIZING_KEY = "FP_SIZING"

#: Candidate keys for the slot's own name, in preference order. Falls back to
#: the file stem, which is what a template that names its slots by filename
#: gives us.
SLOT_NAME_KEYS = ("SLOT", "SLOT_NAME", "slot", "slot_name", "name")

#: A per-slot pad list key. MEASURED, and the measurement corrected this: a real
#: operator template does not carry ONE pad list -- it carries one PER DIE SIDE
#: (`PAD_SOUTH`, `PAD_EAST`, `PAD_NORTH`, `PAD_WEST`), and a candidate list of
#: singular names matched none of them and recorded `pads: null`. That is the
#: exact defect this module is built to refuse: an unmeasured thing reading as a
#: measured zero. So the key is matched by PATTERN, every match is recorded, and
#: the list-valued keys that did NOT match are recorded beside them -- which is
#: what would have made the miss visible on the first run instead of the second.
PAD_LIST_KEY_RE = re.compile(
    r"^PAD(?:S|_LIST|_ORDER|_(?:NORTH|SOUTH|EAST|WEST))?$", re.IGNORECASE)

#: Candidate keys for a DECLARED ring width between the core and the die. When
#: the template states one, `DIE_AREA` must equal `CORE_AREA` grown by it on all
#: four sides -- that is the arithmetic a slot file can fail against itself.
RING_WIDTH_KEY_RE = re.compile(
    r"^(?:(?:SEAL|GUARD)_?RING(?:_?(?:WIDTH|MARGIN|SIZE))?|RING_WIDTH|CORE_MARGIN)$",
    re.IGNORECASE)

SLOT_FILE_SUFFIXES = (".yaml", ".yml", ".json")

#: Layout fixtures a template can ship. The die-identification cells the
#: operator's submission gate requires are among these; which ones they are is
#: the OPERATOR's classification, so this program records every fixture it finds
#: with its path and its cell names and does not pretend to make that call.
FIXTURE_SUFFIXES = (".gds", ".gds.gz", ".gdsii", ".oas", ".oasis", ".lef", ".mag")

#: Scan bounds. Any truncation is REPORTED -- a capped listing and a clean one
#: are otherwise the same answer.
MAX_SCAN_DEPTH = 12
MAX_SCAN_FILES = 20000
MAX_FIXTURE_READ_BYTES = 256 * 1024 * 1024


# --------------------------------------------------------------------------- #
# numbers -- parsed exactly, never rounded
# --------------------------------------------------------------------------- #
def _dec(tok: Any) -> Optional[Decimal]:
    """Exact Decimal for a rect component, or None if it is not a number.

    Built from the token's STRING form so a value the template wrote as
    `3932.5` stays `3932.5` and never acquires a binary-float tail. Nothing
    here rounds.
    """
    if isinstance(tok, bool):
        return None
    try:
        return Decimal(str(tok).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None


def parse_rect(value: Any) -> Optional[List[Decimal]]:
    """`[llx, lly, urx, ury]` from a template's rect value, or None.

    Accepts the list form a YAML/JSON config uses and the whitespace- or
    comma-separated string form a TCL-flavoured config uses. Returns exact
    Decimals; a rect that is not four numbers is not a rect.
    """
    toks: List[Any]
    if isinstance(value, (list, tuple)):
        toks = list(value)
    elif isinstance(value, str):
        toks = [t for t in re.split(r"[\s,]+", value.strip()) if t]
    else:
        return None
    if len(toks) != 4:
        return None
    out: List[Decimal] = []
    for t in toks:
        d = _dec(t)
        if d is None:
            return None
        out.append(d)
    return out


def rect_wh(rect: List[Decimal]) -> Tuple[Decimal, Decimal]:
    """(width, height) of an [llx, lly, urx, ury] rect."""
    return rect[2] - rect[0], rect[3] - rect[1]


def dec_str(d: Optional[Decimal]) -> Optional[str]:
    """A Decimal rendered for JSON as a STRING.

    Derived numbers are emitted as strings on purpose: a die dimension that
    round-trips through a JSON float is a die dimension that has been rounded,
    and the whole point of this record is that it was not.
    """
    return None if d is None else format(d, "f")


# --------------------------------------------------------------------------- #
# hashing
# --------------------------------------------------------------------------- #
def sha256_file(path: Path) -> Optional[str]:
    """sha256 of a file's bytes, or None if it cannot be read."""
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# scanning
# --------------------------------------------------------------------------- #
def _walk(root: Path) -> Tuple[List[Path], Dict[str, Any]]:
    """Every file under `root` within the scan bounds, plus what was cut.

    The bounds are reported rather than applied silently: a listing that hit a
    cap and a listing that saw everything are otherwise the same answer.
    """
    files: List[Path] = []
    bounds = {"max_depth": MAX_SCAN_DEPTH, "max_files": MAX_SCAN_FILES,
              "truncated": False, "truncated_reason": None}
    stack = [(root, 0)]
    while stack:
        d, depth = stack.pop()
        if depth > MAX_SCAN_DEPTH:
            bounds["truncated"] = True
            bounds["truncated_reason"] = (
                f"directory depth exceeded {MAX_SCAN_DEPTH} under {d}")
            continue
        try:
            entries = sorted(d.iterdir())
        except OSError as exc:
            bounds["truncated"] = True
            bounds["truncated_reason"] = f"cannot read {d}: {exc}"
            continue
        for e in entries:
            if e.is_symlink():
                continue
            if e.is_dir():
                stack.append((e, depth + 1))
            elif e.is_file():
                files.append(e)
                if len(files) >= MAX_SCAN_FILES:
                    bounds["truncated"] = True
                    bounds["truncated_reason"] = (
                        f"file count reached {MAX_SCAN_FILES}")
                    return sorted(files), bounds
    return sorted(files), bounds


def _load_mapping(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    """The top-level mapping in a YAML/JSON file, or (None, why-not)."""
    try:
        text = path.read_text(errors="replace")
    except OSError as exc:
        return None, f"unreadable: {exc}"
    if path.suffix.lower() == ".json":
        try:
            obj = json.loads(text)
        except (ValueError, TypeError) as exc:
            return None, f"not JSON: {exc}"
    else:
        try:
            import yaml  # local import: only slot discovery needs it
        except ImportError:                                   # pragma: no cover
            return None, "PyYAML is not installed"
        try:
            obj = yaml.safe_load(text)
        except Exception as exc:                              # noqa: BLE001
            return None, f"not YAML: {exc}"
    if not isinstance(obj, dict):
        return None, "top level is not a mapping"
    return obj, None


def _get_ci(mapping: dict, key: str) -> Tuple[Optional[str], Any]:
    """(actual key, value) for `key`, exact match first then case-insensitive."""
    if key in mapping:
        return key, mapping[key]
    low = key.lower()
    for k, v in mapping.items():
        if isinstance(k, str) and k.lower() == low:
            return k, v
    return None, None


def _first_key(mapping: dict, candidates) -> Tuple[Optional[str], Any]:
    for c in candidates:
        if c in mapping:
            return c, mapping[c]
    return None, None


def _ring_key(mapping: dict) -> Tuple[Optional[str], Any]:
    for k, v in mapping.items():
        if isinstance(k, str) and RING_WIDTH_KEY_RE.match(k.strip()):
            return k, v
    return None, None


def _rect_field(mapping: dict, key: str) -> Optional[dict]:
    """The verbatim value and its parse, for one rect-valued key."""
    actual, raw = _get_ci(mapping, key)
    if actual is None:
        return None
    rect = parse_rect(raw)
    field: Dict[str, Any] = {"key": actual, "raw": raw,
                             "rect": None, "width": None, "height": None}
    if rect is not None:
        w, h = rect_wh(rect)
        field["rect"] = [dec_str(c) for c in rect]
        field["width"] = dec_str(w)
        field["height"] = dec_str(h)
    return field


def slot_record(path: Path, mapping: dict, root: Path) -> dict:
    """One slot, recorded as DATA: verbatim values and the file they came from.

    Nothing here is re-derived from something else and nothing is rounded. The
    parsed rect sits ALONGSIDE the verbatim value, never instead of it.
    """
    name_key, name_val = _first_key(mapping, SLOT_NAME_KEYS)
    if isinstance(name_val, str) and name_val.strip():
        slot = name_val.strip()
        name_source = f"key {name_key}"
    else:
        slot = path.name
        for suf in SLOT_FILE_SUFFIXES:
            if slot.lower().endswith(suf):
                slot = slot[: -len(suf)]
                break
        name_source = "file stem"

    fp_key, fp_val = _get_ci(mapping, FP_SIZING_KEY)
    ring_k, ring_v = _ring_key(mapping)

    rec_die = _rect_field(mapping, DIE_AREA_KEY)
    rec_core = _rect_field(mapping, CORE_AREA_KEY)

    rec: Dict[str, Any] = {
        "slot": slot,
        "slot_name_source": name_source,
        "source_file": str(path),
        "source_relpath": str(path.relative_to(root)) if _under(path, root) else None,
        "source_sha256": sha256_file(path),
        "die_area": rec_die,
        "core_area": rec_core,
        "fp_sizing": None if fp_key is None else {"key": fp_key, "raw": fp_val},
        "pads": _pad_lists(mapping, {k for k in (
            (rec_die or {}).get("key"), (rec_core or {}).get("key"),
            name_key, fp_key, ring_k) if k}),
        "ring": None,
    }
    if ring_k is not None:
        rec["ring"] = {"key": ring_k, "raw": ring_v,
                       "value": dec_str(_dec(ring_v))}
    return rec


def _pad_lists(mapping: dict, understood: set) -> dict:
    """Every pad list this slot declares, and every list key that was NOT one.

    `unmatched_list_keys` is the honest half: it names the list-valued keys the
    pattern did not claim, so a template that spells its pad lists some third
    way shows up as something a reader can see rather than as a silent zero.
    """
    lists, unmatched = [], []
    for k, v in mapping.items():
        if not isinstance(k, str) or not isinstance(v, (list, tuple)):
            continue
        if PAD_LIST_KEY_RE.match(k.strip()):
            lists.append({"key": k, "raw": list(v), "count": len(v)})
        elif k not in understood:
            # `understood` holds the list-valued keys this program read
            # ELSEWHERE -- the die and core rects above all. Counting those as
            # "keys I did not claim" would make every well-formed slot look
            # like one whose pads had been missed, which is the false alarm
            # that hides the true one.
            unmatched.append(k)
    return {
        "pattern": PAD_LIST_KEY_RE.pattern,
        "lists": lists,
        "keys_matched": [d["key"] for d in lists],
        "count": sum(d["count"] for d in lists),
        "unmatched_list_keys": unmatched,
    }


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def discover_slots(root: Path) -> Tuple[List[dict], Dict[str, Any]]:
    """Every slot file under `root`, plus what the scan could not read.

    A candidate is any YAML/JSON file whose top-level mapping carries the
    die-pinning key. Files that look like configs and could not be PARSED are
    recorded in `unparsable` rather than dropped, because a file silently
    skipped is a slot the report claims does not exist.
    """
    files, bounds = _walk(root)
    slots: List[dict] = []
    unparsable: List[dict] = []
    examined = 0
    for f in files:
        if not any(f.name.lower().endswith(s) for s in SLOT_FILE_SUFFIXES):
            continue
        examined += 1
        mapping, why = _load_mapping(f)
        if mapping is None:
            unparsable.append({"file": str(f), "reason": why})
            continue
        if _get_ci(mapping, DIE_AREA_KEY)[0] is None:
            continue
        slots.append(slot_record(f, mapping, root))
    scan = dict(bounds)
    scan.update({"root": str(root), "config_files_examined": examined,
                 "files_seen": len(files), "unparsable": unparsable})
    slots.sort(key=lambda r: (r["slot"], r["source_file"]))
    return slots, scan


# --------------------------------------------------------------------------- #
# fixtures -- paths and cell names, never a copy
# --------------------------------------------------------------------------- #
_GDS_STRNAME = b"\x06\x06"
_LEF_MACRO_RE = re.compile(r"^\s*MACRO\s+(\S+)", re.MULTILINE | re.IGNORECASE)


def _gds_cell_names(path: Path) -> Tuple[Optional[List[str]], Optional[str]]:
    """Structure names from a GDS stream, or (None, why-not).

    Returns None -- never an empty list -- when the names could not be read.
    An unread file and a file with no cells are different facts and must not
    share an answer.
    """
    try:
        size = path.stat().st_size
    except OSError as exc:
        return None, f"unreadable: {exc}"
    if size > MAX_FIXTURE_READ_BYTES:
        return None, (f"{size} bytes exceeds the {MAX_FIXTURE_READ_BYTES}-byte "
                      f"read ceiling; cell names were NOT read")
    opener = gzip.open if path.name.lower().endswith(".gz") else open
    names: List[str] = []
    try:
        with opener(path, "rb") as fh:                      # type: ignore[operator]
            data = fh.read()
    except OSError as exc:
        return None, f"unreadable: {exc}"
    except Exception as exc:                                 # noqa: BLE001
        return None, f"not a readable GDS stream: {exc}"
    i, n = 0, len(data)
    while i + 4 <= n:
        rec_len = int.from_bytes(data[i:i + 2], "big")
        if rec_len < 4 or i + rec_len > n:
            return (names or None), "record stream ended unexpectedly"
        if data[i + 2:i + 4] == _GDS_STRNAME:
            raw = data[i + 4:i + rec_len].rstrip(b"\x00")
            names.append(raw.decode("ascii", errors="replace"))
        i += rec_len
    return names, None


def _lef_cell_names(path: Path) -> Tuple[Optional[List[str]], Optional[str]]:
    try:
        text = path.read_text(errors="replace")
    except OSError as exc:
        return None, f"unreadable: {exc}"
    return _LEF_MACRO_RE.findall(text), None


def fixture_record(path: Path, root: Path) -> dict:
    """One shipped layout fixture: where it is, what it hashes to, what cells it
    names. The bytes stay where they are -- nothing is copied into this repo."""
    low = path.name.lower()
    if low.endswith((".gds", ".gds.gz", ".gdsii")):
        kind, (cells, why) = "gds", _gds_cell_names(path)
    elif low.endswith(".lef"):
        kind, (cells, why) = "lef", _lef_cell_names(path)
    elif low.endswith(".mag"):
        kind, cells, why = "mag", [path.stem], None
    else:
        kind, cells, why = "oasis", None, (
            "cell names in this container format are not parsed by this "
            "program; the fixture is recorded by path and digest only")
    try:
        nbytes = path.stat().st_size
    except OSError:
        nbytes = None
    return {
        "path": str(path),
        "relpath": str(path.relative_to(root)) if _under(path, root) else None,
        "kind": kind,
        "bytes": nbytes,
        "sha256": sha256_file(path),
        "cells": cells,
        "cells_unread_reason": why,
        "vendored": False,
    }


def discover_fixtures(root: Path) -> List[dict]:
    files, _ = _walk(root)
    out = [fixture_record(f, root) for f in files
           if any(f.name.lower().endswith(s) for s in FIXTURE_SUFFIXES)]
    out.sort(key=lambda r: r["path"])
    return out
