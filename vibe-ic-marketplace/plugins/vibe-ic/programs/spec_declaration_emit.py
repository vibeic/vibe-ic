#!/usr/bin/env python3
"""spec_declaration_emit.py — the designer's FREE choices, declared not inferred.

THE PRINCIPLE THIS PROGRAM ENFORCES
-----------------------------------
A FREE CHOICE is a decision the designer makes that NO downstream tool can
recover from the artifacts by inference: bit order on a serial port, the
latency from reset-release to the first valid beat, integer encoding, reset
polarity, the parameter value a build actually ran at.  Two correct designs can
disagree on every one of them.

Such a choice must be recorded as a MACHINE-READABLE DECLARATION AT THE MOMENT
IT IS MADE — before the RTL that embodies it is written — never reconstructed
afterwards from prose.  A comment block in an RTL header is prose: it is not
schema-checked, it is not diffable against a consumer's expectation, and a
consumer that scrapes it is one reformat away from silently guessing.

WHAT THIS PROGRAM IS, AND IS NOT
--------------------------------
IS      a contract-DRIVEN emitter.  The field list, the required/informational
        tier of each field, and the target path all come from the PROJECT'S OWN
        Phase-1 documents — never from a table baked into this file.  Three
        real designs in this repo declare three DIFFERENT field sets under the
        same clause shape; a hard-coded field list is a per-design patch, not a
        capability.

IS NOT  an inference engine.  It will not read an ``always`` block and conclude
        a reset polarity, nor scan a whole RTL file for an ``LSB-first`` token.
        That is exactly the recovery-from-prose this program exists to retire.
        The ONLY prose source it will touch is an explicit, opt-in, key=value
        DECLARATION block (``--from-rtl-declaration``) — the designer's own
        words in the wrong file format — and every field taken that way is
        stamped ``recovered_from_prose`` in the provenance sidecar so the debt
        is visible rather than laundered.

MODES
-----
``--contract``  (advisory, ALWAYS rc=0)
    Extract the declaration contract and write it to
    ``phase2/stage1/declaration_contract.json``.  This is the RTL-AUTHORING
    HANDOFF seam: it tells the author, BEFORE a line of RTL exists, exactly
    which free choices this design's spec requires them to record.  It is
    deliberately written OUTSIDE the spec-declared path so it can never be
    mistaken for the declaration itself and can never flip
    ``spec_required_artifact_check`` green.

``(default)``   emit
    Resolve every contract field and write the declaration to the
    SPEC-DECLARED path, merging into any declaration already there (a prior
    step may have merged catalog/IP keys into it — clobbering those would be a
    regression).

FAIL-CLOSED CONTRACT
--------------------
If ANY field the spec marks REQUIRED is still undetermined, this program prints
``spec_declaration_emit: UNDETERMINED`` on stderr, names every such field, and
exits rc EXACTLY 1 having written NO declaration.  A default-filled JSON would
be strictly worse than an absent one: it would turn the downstream
required-artifact gate green while the comparison procedure pairs against a
value nobody chose.  Where required-ness itself cannot be read out of the spec
table, the field is treated as REQUIRED and the ambiguity is disclosed in
``required_marker_recognized`` — an unreadable marker is not a licence to skip.

An INFORMATIONAL field that is undetermined is simply OMITTED from the
declaration and recorded as ``status="undetermined"`` in the provenance
sidecar.  Omission — not a placeholder — is what makes a consumer defer: every
consumer in this repo resolves a missing key to "cannot pair" already.

Exit codes
  0  emitted (or --contract, always)
  1  one or more REQUIRED fields undetermined — nothing written
  2  usage / I/O error
  3  NO_CONTRACT / NO_FIELDS — this project's spec declares no machine-readable
     declaration contract, so there was nothing to emit.  Distinct from 0 so a
     caller expecting a file never reads silence as success.

Chip-agnostic: no design name, no PDK SKU, no field name, no artifact path is
hard-coded anywhere in this file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Reuse the required-artifact gate's clause primitives rather than restating
# them.  That gate already owns the EN/ZH imperative regexes, the path-shape
# filter and the "which directories are Phase-1 input docs" answer; a second
# copy here would be a near-duplicate that drifts.  This module adds what the
# gate does not have: the POSITION of each clause, and the field table that
# follows it.
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import spec_required_artifact_check as _srac  # noqa: E402

STDERR_BANNER = "spec_declaration_emit: UNDETERMINED"

# --------------------------------------------------------------------------- #
# Required-ness vocabulary
# --------------------------------------------------------------------------- #
# Markers a spec table uses to say "this field is mandatory" / "this field is
# informational".  Vocabulary, not design content — extend freely.
_REQUIRED_MARKERS = (
    "✅",           # white heavy check mark
    "☑", "✔", "√",
    "必填",     # "mandatory field"
    "必須",     # "must"
    "required", "mandatory", "must", "yes",
)
_OPTIONAL_MARKERS = (
    "⚠",                       # warning sign (used as "informational")
    "資訊性",           # "informational"
    "選填",                 # "optional field"
    "informational", "info", "optional", "no", "n/a", "nice-to-have",
)
# Header cells that identify WHICH column carries the required-ness marker.
_REQUIRED_HEADERS = (
    "必填", "必要", "是否必填",
    "required", "mandatory", "req", "must",
)
# Header cells that identify the example / allowed-value column.
_EXAMPLE_HEADERS = (
    "範例", "範例值", "例",
    "example", "example value", "examples", "value", "allowed",
)
# Header cells that identify the field-name column.
_FIELD_HEADERS = (
    "欄位", "字段", "鍵", "名稱",
    "field", "key", "name", "attribute",
)

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")
_SEP_CELL_RE = re.compile(r"^:?-{2,}:?$")
# How far past the MUST-declare clause the field table may start.  A table that
# begins many paragraphs later belongs to something else.
_MAX_LINES_TO_TABLE = 6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Markdown table parsing
# --------------------------------------------------------------------------- #

def _split_row(line: str) -> List[str]:
    """Split one pipe-table line into stripped cells."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_separator_row(cells: List[str]) -> bool:
    return bool(cells) and all(_SEP_CELL_RE.match(c or "") for c in cells)


def _clean_cell(cell: str) -> str:
    """Strip markdown emphasis/code fences from a cell."""
    return cell.replace("`", "").replace("**", "").replace("*", "").strip()


def _header_column(header: List[str], vocab: Tuple[str, ...]) -> Optional[int]:
    """Index of the first header cell whose text matches `vocab`."""
    for i, cell in enumerate(header):
        t = _clean_cell(cell).lower()
        if not t:
            continue
        for token in vocab:
            if token in t:
                return i
    return None


def _classify_required(marker: str) -> Tuple[bool, bool]:
    """Return ``(required, marker_recognized)`` for a required-ness cell.

    Fail-closed: an unrecognized marker yields ``(True, False)`` — treated as
    REQUIRED, with the fact that the marker was unreadable carried alongside so
    a reviewer sees the assumption instead of inheriting it silently.
    """
    t = _clean_cell(marker).lower()
    hit_opt = any(tok in t for tok in _OPTIONAL_MARKERS)
    hit_req = any(tok in t for tok in _REQUIRED_MARKERS)
    if hit_opt and hit_req:
        # Contradictory markers ("not required", "optional/mandatory"): resolve
        # REQUIRED (fail-closed) but report the marker as UNRECOGNIZED so the
        # ambiguity is visible.  Claiming recognition here would hide a guess.
        return True, False
    if hit_opt:
        return False, True
    if hit_req:
        return True, True
    return True, False


def _extract_examples(cell: str) -> List[str]:
    """Backticked tokens in an example cell, in order, de-duplicated.

    Advisory only.  Never used to CHOOSE a value — a spec example is what a
    reference implementation happened to pick, not what this designer chose.
    """
    out: List[str] = []
    for m in re.finditer(r"`([^`]+)`", cell):
        tok = m.group(1).strip()
        if tok and tok not in out:
            out.append(tok)
    return out


def _parse_field_table(text: str, start: int) -> Optional[Dict[str, Any]]:
    """Parse the pipe table that follows offset `start`, if one starts soon.

    Returns ``None`` when no table begins within ``_MAX_LINES_TO_TABLE`` lines
    — that is how a plain "MUST emit <file>" requirement is distinguished from
    a DECLARATION CONTRACT that enumerates fields.
    """
    tail = text[start:]
    lines = tail.split("\n")
    # Locate the first table line.
    first = None
    for i, line in enumerate(lines[: _MAX_LINES_TO_TABLE + 1]):
        if line.strip().startswith("|"):
            first = i
            break
    if first is None:
        return None
    block: List[str] = []
    for line in lines[first:]:
        if not line.strip().startswith("|"):
            break
        block.append(line)
    if len(block) < 3:          # header + separator + >=1 data row
        return None
    rows = [_split_row(b) for b in block]
    sep_idx = next((i for i, r in enumerate(rows) if _is_separator_row(r)), None)
    if sep_idx is None or sep_idx == 0 or sep_idx + 1 >= len(rows):
        return None
    header = rows[sep_idx - 1]
    data = rows[sep_idx + 1:]

    field_col = _header_column(header, _FIELD_HEADERS)
    if field_col is None:
        field_col = 0
    req_col = _header_column(header, _REQUIRED_HEADERS)
    ex_col = _header_column(header, _EXAMPLE_HEADERS)

    fields: List[Dict[str, Any]] = []
    ignored: List[Dict[str, Any]] = []
    for r in data:
        if field_col >= len(r):
            continue
        name = _clean_cell(r[field_col])
        if not _IDENT_RE.match(name):
            if name:
                ignored.append({
                    "cell": name,
                    "reason": "field-name cell is not an identifier",
                })
            continue
        if req_col is None:
            # No required-ness column at all: every enumerated field is
            # treated as REQUIRED (fail-closed) and the absence is disclosed.
            required, recognized = True, False
            marker = ""
        else:
            marker = r[req_col] if req_col < len(r) else ""
            required, recognized = _classify_required(marker)
        ex_cell = r[ex_col] if (ex_col is not None and ex_col < len(r)) else ""
        fields.append({
            "name": name,
            "required": required,
            "required_marker": _clean_cell(marker),
            "required_marker_recognized": recognized,
            "example_values": _extract_examples(ex_cell),
            "row": [_clean_cell(c) for c in r],
        })
    if not fields:
        return None
    return {
        "fields": fields,
        "ignored_rows": ignored,
        "header": [_clean_cell(c) for c in header],
        "required_column": req_col,
        "example_column": ex_col,
        "field_column": field_col,
    }


# --------------------------------------------------------------------------- #
# Contract extraction
# --------------------------------------------------------------------------- #

def _iter_doc_texts(project: Path):
    """Yield ``(relative_path, text)`` for every Phase-1 input doc.

    Directory set and extension set both come from
    ``spec_required_artifact_check`` so this program cannot look somewhere the
    required-artifact gate does not — the two must agree about where the spec
    lives or one of them is asserting on a document the other never read.
    """
    for doc_dir in _srac._input_doc_dirs(project):
        for p in sorted(doc_dir.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in _srac._DOC_EXTS:
                continue
            try:
                yield str(p.relative_to(project)), p.read_text(errors="replace")
            except OSError:
                continue
    l_doc_dir = project / "phase1" / "generated_docs"
    if l_doc_dir.is_dir():
        for jf in sorted(l_doc_dir.glob("L*.json")):
            try:
                yield str(jf.relative_to(project)), jf.read_text(errors="replace")
            except OSError:
                continue


def extract_contracts(project: Path) -> List[Dict[str, Any]]:
    """Every declaration contract this project's spec declares.

    A contract == a MUST-emit/declare clause naming a path-shaped artifact,
    IMMEDIATELY followed by a field table.  A MUST-emit clause with no field
    table is a required artifact but not a declaration contract, and is left to
    ``spec_required_artifact_check``.
    """
    contracts: List[Dict[str, Any]] = []
    seen: set = set()
    for rel, text in _iter_doc_texts(project):
        for pattern_name, rx in (("english_imperative", _srac._EN_PATTERN),
                                 ("zh_tw_imperative", _srac._ZH_PATTERN)):
            for m in rx.finditer(text):
                token = ""
                for g in m.groups():
                    if g:
                        token = g
                        break
                path = (token or "").strip("/").rstrip(")")
                if not path or not _srac._is_path_shaped(path):
                    continue
                table = _parse_field_table(text, m.end())
                if table is None:
                    continue
                key = (path, rel)
                if key in seen:
                    continue
                seen.add(key)
                contracts.append({
                    "artifact_path": path,
                    "source": rel,
                    "clause_text": m.group(0).strip(),
                    "pattern": pattern_name,
                    **table,
                })
    return contracts


# --------------------------------------------------------------------------- #
# Value resolution
# --------------------------------------------------------------------------- #

class _Undetermined:
    """Sentinel: the author explicitly declined to determine this field.

    ``--set <field>=null`` is how a schema says "undetermined" out loud.  It is
    NOT the same as omitting the flag (which merely means "not supplied yet"),
    and it is emphatically not a value: a REQUIRED field marked this way still
    refuses, and an informational one is omitted with the author's own
    abstention recorded in the provenance sidecar.
    """

    def __repr__(self) -> str:          # pragma: no cover - debug aid
        return "<undetermined>"


UNDETERMINED = _Undetermined()


def _coerce(raw: str) -> Any:
    """JSON-decode a CLI value when it is valid JSON, else keep the string.

    ``latency_cycles=2`` becomes int 2, ``gpio_pin_count=1`` int 1,
    ``isa_extensions=["I"]`` a list, ``bit_order=LSB_first`` a string.

    Two decodings are deliberately refused rather than accepted:
      * JSON ``null`` -> the UNDETERMINED sentinel, never the value ``None``.
        Recording ``None`` as a choice would put a key in the declaration whose
        value means "no answer" — the exact placeholder this program exists to
        avoid.
      * ``NaN`` / ``Infinity`` — Python's json accepts these bare words, so a
        field legitimately named or valued ``NaN`` would silently become a
        non-finite float that no consumer can compare.  Kept as the string the
        author typed.
    """
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if value is None:
        return UNDETERMINED
    if isinstance(value, float) and (value != value or value in (
            float("inf"), float("-inf"))):
        return raw
    return value


def _rtl_dir(project: Path) -> Path:
    pl = _srac._path_layout()
    if pl is not None:
        try:
            return pl.rtl_dir(project)
        except Exception:
            pass
    return project / "phase2" / "stage1" / "rtl"


def _stage1_dir(project: Path) -> Path:
    pl = _srac._path_layout()
    if pl is not None:
        try:
            return pl.phase2_stage1_dir(project)
        except Exception:
            pass
    return project / "phase2" / "stage1"


# A declaration line inside an RTL COMMENT: `<key> = <value>`, value taken as
# the FIRST bare token so a trailing parenthetical or a comma-separated aside
# cannot leak into it.
#
# COMMENT LINES ONLY, deliberately.  This reads a DECLARATION the designer
# wrote in the wrong file format; it does not interpret the design.  Scanning
# code as well would let a `parameter <name> = N` or a `localparam` satisfy a
# declared field — that is inference from the artifact, which is the failure
# mode this program exists to retire, and it would be indistinguishable in the
# output from a choice the designer actually stated.
_COMMENT_LINE_RE = re.compile(r"^\s*(?://+|\*+|/\*+)")


def _rtl_declared(project: Path, names: List[str]) -> Dict[str, Tuple[Any, str]]:
    out: Dict[str, Tuple[Any, str]] = {}
    rtl = _rtl_dir(project)
    if not rtl.is_dir():
        return out
    srcs = sorted(rtl.rglob("*.v")) + sorted(rtl.rglob("*.sv"))
    patterns = {n: re.compile(r"(?<![A-Za-z0-9_])" + re.escape(n)
                              + r"\s*=\s*([A-Za-z0-9_.+\-]+)") for n in names}
    for f in srcs:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        try:
            rel = str(f.relative_to(project))
        except ValueError:
            rel = str(f)
        for line in text.split("\n"):
            if not _COMMENT_LINE_RE.match(line):
                continue
            for name, rx in patterns.items():
                if name in out:
                    continue
                m = rx.search(line)
                if m:
                    value = _coerce(m.group(1))
                    if value is UNDETERMINED:
                        # `<field> = null` written in a comment states no
                        # choice; treat it as if the line were absent rather
                        # than letting a sentinel reach the JSON writer.
                        continue
                    out[name] = (value, rel)
    return out


def resolve(contract: Dict[str, Any],
            overrides: Dict[str, Any],
            rtl_declared: Dict[str, Tuple[Any, str]],
            existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Resolve every contract field.  Returns a per-field status map.

    Priority, strongest first:
      1. an explicit author declaration made in THIS invocation
      2. a value already present in the declaration file (someone declared it
         before; re-running the emitter must not silently discard it)
      3. an opt-in `key = value` line from an RTL COMMENT block
      4. UNDETERMINED

    There is no fifth tier.  A value this program cannot trace to something the
    designer wrote is not produced.
    """
    existing = existing or {}
    status: Dict[str, Any] = {}
    for f in contract["fields"]:
        name = f["name"]
        entry: Dict[str, Any] = {
            "required": f["required"],
            "required_marker": f["required_marker"],
            "required_marker_recognized": f["required_marker_recognized"],
            "spec_example_values": f["example_values"],
        }
        if name in overrides and overrides[name] is UNDETERMINED:
            entry.update(
                status="undetermined",
                reason=("the author explicitly declared this field "
                        "undetermined (--set %s=null)" % name),
                recovered_from_prose=False)
        elif name in overrides:
            entry.update(status="determined", value=overrides[name],
                         provenance="author_declared",
                         recovered_from_prose=False)
        elif name in existing:
            entry.update(status="determined", value=existing[name],
                         provenance="existing_declaration",
                         recovered_from_prose=False)
        elif name in rtl_declared:
            value, src = rtl_declared[name]
            entry.update(status="determined", value=value,
                         provenance="rtl_header_declaration",
                         provenance_detail=src,
                         recovered_from_prose=True)
        else:
            entry.update(
                status="undetermined",
                reason=("no author declaration supplied, none already recorded "
                        "in the declaration file, and no `%s = <value>` line in "
                        "an RTL comment block" % name),
                recovered_from_prose=False)
        status[name] = entry
    return status


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def _print_contract(contracts: List[Dict[str, Any]], out_path: Path) -> None:
    if not contracts:
        print("spec_declaration_contract: NONE — this project's Phase-1 docs "
              "declare no machine-readable declaration contract (a MUST-declare "
              "clause followed by a field table).")
        return
    total = sum(len(c["fields"]) for c in contracts)
    print("spec_declaration_contract: %d contract(s), %d field(s). These are "
          "FREE CHOICES: decide them NOW and record them, do not leave them to "
          "be re-derived from the RTL later." % (len(contracts), total))
    for c in contracts:
        print("  %s   (required by %s)" % (c["artifact_path"], c["source"]))
        if c["required_column"] is None:
            print("      NOTE: the spec table has no required-ness column — "
                  "every field below is treated as REQUIRED (fail-closed).")
        for f in c["fields"]:
            tier = "REQUIRED" if f["required"] else "informational"
            if not f["required_marker_recognized"]:
                tier += " (marker %r unrecognized -> assumed required)" % (
                    f["required_marker"],)
            ex = (" e.g. " + ", ".join(f["example_values"][:3])
                  if f["example_values"] else "")
            print("      - %-28s %s%s" % (f["name"], tier, ex))
    print("  Contract: %s" % out_path)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def stage_contract(project: Path) -> Tuple[Path, List[Dict[str, Any]]]:
    """Write the declaration contract for `project` and return (path, contracts).

    THE handoff entry point.  ``--contract`` and the runner's authoring-handoff
    staging both go through here so there is exactly one definition of what the
    contract file contains and where it lives — a second copy in the runner
    would drift from this one the first time the schema changes.

    Always writes, even with zero contracts: "we looked and this spec declares
    none" is a different, useful statement from "nobody looked".
    """
    contracts = extract_contracts(project)
    out_path = _stage1_dir(project) / "declaration_contract.json"
    _write_json(out_path, {
        "schema_version": 1,
        "program": "spec_declaration_emit",
        "mode": "contract",
        "generated_at": _now(),
        "project": str(project),
        "contract_count": len(contracts),
        "contracts": contracts,
    })
    return out_path, contracts


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Emit the designer's declared free interface choices as a "
                    "machine-readable artifact, driven by the project's own "
                    "spec.")
    ap.add_argument("project", nargs="?", default=".",
                    help="Project / run directory (default: cwd)")
    ap.add_argument("--contract", action="store_true",
                    help="ADVISORY: extract and print the declaration contract "
                         "(which free choices this spec requires), write it to "
                         "phase2/stage1/declaration_contract.json, exit 0. For "
                         "the RTL-authoring handoff, BEFORE any RTL exists.")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="Declare one field. Value is JSON-decoded when it "
                         "parses as JSON, else kept as a string. Repeatable. "
                         "`--set <field>=null` states UNDETERMINED explicitly: "
                         "a required field so marked still refuses, an "
                         "informational one is omitted and the abstention is "
                         "recorded in the provenance sidecar.")
    ap.add_argument("--from-json", metavar="FILE",
                    help="Declare fields from a JSON object file (a JSON null "
                         "means UNDETERMINED, exactly as with --set).")
    ap.add_argument("--from-rtl-declaration", action="store_true",
                    help="LEGACY RECOVERY (opt-in): also accept `key = value` "
                         "lines from an RTL COMMENT block. Every field taken "
                         "this way is stamped recovered_from_prose in the "
                         "provenance sidecar. Code (parameter/localparam) is "
                         "never read — inferring a free choice from the "
                         "artifact is the failure mode, not the fix.")
    ap.add_argument("--artifact", metavar="PATH",
                    help="Select one contract by its declared artifact path "
                         "when the spec declares more than one.")
    args = ap.parse_args(argv)

    project = Path(args.project).resolve()
    if not project.is_dir():
        print("ERROR: project not found: %s" % project, file=sys.stderr)
        return 2

    if args.contract:
        out_path, contracts = stage_contract(project)
        _print_contract(contracts, out_path)
        return 0

    contracts = extract_contracts(project)

    if not contracts:
        print("spec_declaration_emit: NO_CONTRACT — this project's Phase-1 "
              "docs declare no field table under any MUST-declare clause; "
              "nothing was written.", file=sys.stderr)
        return 3

    if args.artifact:
        contracts = [c for c in contracts if c["artifact_path"] == args.artifact]
        if not contracts:
            print("ERROR: no declaration contract for artifact %r"
                  % args.artifact, file=sys.stderr)
            return 2
    paths = sorted({c["artifact_path"] for c in contracts})
    if len(paths) > 1:
        print("ERROR: spec declares %d declaration artifacts (%s) — select one "
              "with --artifact." % (len(paths), ", ".join(paths)),
              file=sys.stderr)
        return 2

    # Merge every contract that targets the same artifact (the same clause can
    # appear in both the canonical and the legacy doc root).
    merged_fields: Dict[str, Dict[str, Any]] = {}
    for c in contracts:
        for f in c["fields"]:
            prev = merged_fields.get(f["name"])
            if prev is None or (f["required"] and not prev["required"]):
                merged_fields[f["name"]] = f
    contract = {**contracts[0], "fields": list(merged_fields.values())}

    overrides: Dict[str, Any] = {}
    if args.from_json:
        src = Path(args.from_json)
        try:
            data = json.loads(src.read_text())
        except Exception as exc:
            print("ERROR: cannot read --from-json %s: %s" % (src, exc),
                  file=sys.stderr)
            return 2
        if not isinstance(data, dict):
            print("ERROR: --from-json must contain a JSON object",
                  file=sys.stderr)
            return 2
        for k, v in data.items():
            if v is None:
                # Same meaning as `--set k=null`: an explicit abstention, not
                # the value `None`. Letting None through would put a key in the
                # declaration whose value means "no answer".
                overrides[k] = UNDETERMINED
            elif isinstance(v, float) and (v != v or v in (
                    float("inf"), float("-inf"))):
                print("ERROR: --from-json field %r is a non-finite number; no "
                      "consumer can compare it" % k, file=sys.stderr)
                return 2
            else:
                overrides[k] = v
    for item in args.set:
        if "=" not in item:
            print("ERROR: --set expects KEY=VALUE, got %r" % item,
                  file=sys.stderr)
            return 2
        k, _, v = item.partition("=")
        overrides[k.strip()] = _coerce(v)

    names = [f["name"] for f in contract["fields"]]
    rtl_declared = (_rtl_declared(project, names)
                    if args.from_rtl_declaration else {})

    out_path = project / contract["artifact_path"]
    existing: Dict[str, Any] = {}
    if out_path.is_file():
        try:
            loaded = json.loads(out_path.read_text())
            if isinstance(loaded, dict):
                existing = loaded
        except Exception:
            existing = {}

    status = resolve(contract, overrides, rtl_declared, existing)

    undetermined_required = sorted(
        n for n, e in status.items()
        if e["status"] == "undetermined" and e["required"])
    undetermined_optional = sorted(
        n for n, e in status.items()
        if e["status"] == "undetermined" and not e["required"])

    if undetermined_required:
        print("%s — %d REQUIRED free choice(s) not declared:"
              % (STDERR_BANNER, len(undetermined_required)), file=sys.stderr)
        for n in undetermined_required:
            e = status[n]
            print("  - %s: %s" % (n, e["reason"]), file=sys.stderr)
            if e["spec_example_values"]:
                print("      spec example value(s): %s"
                      % ", ".join(e["spec_example_values"][:4]),
                      file=sys.stderr)
            if not e["required_marker_recognized"]:
                print("      (required-ness marker %r was not recognized; "
                      "treated as REQUIRED)" % e["required_marker"],
                      file=sys.stderr)
        print("  Declare each with --set <field>=<value> (or --from-json). "
              "No declaration written — a default-filled declaration would "
              "turn the required-artifact gate green against a value nobody "
              "chose.", file=sys.stderr)
        return 1

    # --- write -------------------------------------------------------------
    # `existing` was already loaded above (it is a resolution SOURCE, not just
    # something to merge into) — start from it so keys a prior step wrote and
    # this contract says nothing about survive untouched.
    declaration = dict(existing)
    for n, e in status.items():
        if e["status"] == "determined":
            declaration[n] = e["value"]
        else:
            # Informational + undetermined: the key is simply not written.
            # Never a placeholder — every consumer in this repo resolves a
            # missing key to "cannot pair", and a placeholder would have to be
            # special-cased by each of them.  A field already present in
            # `existing` reaches this branch ONLY via an explicit
            # `--set <field>=null` — an author deliberately retracting a choice
            # — so nothing recorded earlier is dropped by accident.
            declaration.pop(n, None)
    _write_json(out_path, declaration)

    sidecar = out_path.with_name(out_path.stem + ".provenance.json")
    _write_json(sidecar, {
        "schema_version": 1,
        "program": "spec_declaration_emit",
        "generated_at": _now(),
        "declaration_path": contract["artifact_path"],
        "contract_source": contract["source"],
        "contract_clause": contract["clause_text"],
        "required_column_found": contract["required_column"] is not None,
        "fields": status,
        "undetermined_informational": undetermined_optional,
        "recovered_from_prose": sorted(
            n for n, e in status.items() if e.get("recovered_from_prose")),
        "preserved_foreign_keys": sorted(
            k for k in existing if k not in status),
    })

    n_det = sum(1 for e in status.values() if e["status"] == "determined")
    print("spec_declaration_emit: PASS — %d/%d contract field(s) declared -> %s"
          % (n_det, len(status), out_path))
    if undetermined_optional:
        print("  informational field(s) OMITTED as undetermined (not "
              "defaulted): %s" % ", ".join(undetermined_optional))
    recovered = sorted(n for n, e in status.items()
                       if e.get("recovered_from_prose"))
    if recovered:
        print("  RECOVERED FROM PROSE (legacy path — these should have been "
              "declared before the RTL was written): %s" % ", ".join(recovered))
    print("  Provenance: %s" % sidecar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
