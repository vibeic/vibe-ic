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

        "Comment" here means what a Verilog lexer means (see
        ``_scan_declaration_lines``), not "the line starts with a slash".  A
        line-prefix test let ``/* lint_off */ localparam bit_order = 1;`` count
        as a comment and scraped the CODE that followed it — an inference in
        the costume of a declaration, i.e. the precise failure this program
        exists to retire.  A declaration line must therefore carry NO code at
        all, and the ``<field> = <value>`` must begin the comment text, so that
        neither commented-out code (``// localparam bit_order = 1;``) nor prose
        that merely mentions a field can satisfy a contract field.

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

``--verify``    (assertion, rc 0/1, writes NO declaration)
    The SUBSTANCE check that a presence-and-size gate cannot make.
    ``spec_required_artifact_check`` asserts the spec-declared artifact exists
    and is non-empty; ``{}`` is three bytes, so a declaration that declares
    NOTHING satisfies it.  ``--verify`` reads the declaration already on disk
    and asserts it carries a real value for every REQUIRED contract field —
    the required-ness coming from the spec, which this program did not write.
    Wire this next to the required-artifact gate; it is a separate program, so
    the presence gate stays untouched.

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

A supplied value that carries no choice — the empty string, ``TBD``,
``<fill-me>`` — is NOT a declaration; it is UNDETERMINED with extra steps, and
is treated exactly as if the field had not been supplied (see
``_placeholder_reason``).  Otherwise the fail-closed contract would only
distinguish "a key was supplied" from "no key was supplied", never "a choice
was made".

An INFORMATIONAL field that is undetermined is simply OMITTED from the
declaration and recorded as ``status="undetermined"`` in the provenance
sidecar.  Omission — not a placeholder — is what makes a consumer defer: every
consumer in this repo resolves a missing key to "cannot pair" already.

If NO contract field at all is determined, the file is NOT written (rc 4).  A
declaration that declares nothing must not satisfy a requirement to declare:
writing ``{}`` would hand ``spec_required_artifact_check`` three bytes it
scores as "present and non-empty", which is a green gate certifying an
artifact created during the same run to satisfy it.

PROVENANCE IS CARRIED, NOT RECOMPUTED
-------------------------------------
The declaration file is a resolution SOURCE for the next run, and it is a file
this program itself wrote.  Re-deriving each field's provenance from "where did
I read it this time" therefore relabelled every prose-recovered field
``existing_declaration`` on the second, byte-identical run and emptied
``recovered_from_prose`` — one idempotent re-run destroyed the debt marker.  So
a value read back out of the declaration file inherits the provenance the
PREVIOUS sidecar recorded for it, as long as the value is unchanged; the field
is additionally marked ``carried_from_declaration_file``.  The stamp is retired
only by an author actually declaring the field (``--set``), which is the real
remediation.  A value present in the file with no recorded provenance (a
hand-written declaration, or a sidecar that was deleted) is reported with
``provenance_verified: false`` and listed in
``existing_without_recorded_provenance`` — it is not silently promoted to a
clean declaration.

Exit codes
  0  emitted (or --contract, always; or --verify passed)
  1  one or more REQUIRED fields undetermined — nothing written
     (or, under --verify, the declaration on disk fails the contract)
  2  usage / I/O error
  3  NO_CONTRACT / NO_FIELDS — this project's spec declares no machine-readable
     declaration contract, so there was nothing to emit.  Distinct from 0 so a
     caller expecting a file never reads silence as success.
  4  NOTHING_TO_DECLARE — a contract exists, no REQUIRED field is outstanding,
     but not one contract field was determined.  Nothing written; an empty
     declaration is not a declaration.

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


# --------------------------------------------------------------------------- #
# "A value was supplied" is not "a choice was made"
# --------------------------------------------------------------------------- #
# Tokens whose ONLY meaning is "nobody has filled this in yet".  A REQUIRED
# field carrying one of these is UNDETERMINED, not declared — otherwise the
# fail-closed contract degenerates into a key-presence test and `--set
# bit_order=` turns the required-artifact gate green against no choice at all.
#
# Deliberately CONSERVATIVE.  Everything here is meaningless as an interface
# choice in any design.  Tokens that LOOK empty but are legitimate choices
# somewhere are NOT listed: `none` (no parity / no flow control), `n/a`, `null`,
# `unknown`, `0`, `false`, `[]`, and every single punctuation character (a
# delimiter or fill character is a real declaration) — rejecting those would
# trade this false-clean for a false alarm on a correct design.
_PLACEHOLDER_TOKENS = frozenset({
    "tbd", "t.b.d.", "t.b.d", "tba", "todo", "to-do", "to_do", "to do",
    "fixme", "fix-me", "fix_me", "fix me",
    "xxx", "xxxx",
    "placeholder", "place-holder", "place_holder",
    "changeme", "change-me", "change_me", "change me",
    "fillme", "fill-me", "fill_me", "fill me", "fill in", "fill-in",
    "undetermined", "unspecified", "undecided", "not_set", "notset",
    "not-set", "not set", "pending",
})
# Template forms an author leaves behind: `<fill-me>`, `{{value}}`, `${VALUE}`.
_TEMPLATE_VALUE_RE = re.compile(r"^(?:<.*>|\{\{.*\}\}|\$\{.*\})$", re.DOTALL)


def _placeholder_reason(value: Any) -> Optional[str]:
    """Why `value` states no choice, or None when it is a real declaration.

    JSON ``null`` is the ONE non-string that states no choice.  It is the same
    statement ``--set <field>=null`` makes, and that door already resolves to
    UNDETERMINED; a declaration file carrying ``"bit_order": null`` therefore
    has to mean the same thing at this door, or the program certifies through
    one entrance exactly what it refuses at the other.  Leaving it out let an
    all-``null`` declaration pass emit, the presence gate, AND ``--verify``,
    which then printed "declared with a real value" about a file in which no
    value existed.

    Every OTHER non-string is a real choice: ``0``, ``False``, ``[]`` and
    ``{}`` are all values a designer can legitimately have made (no optional
    extensions, no parity, count zero), and refusing them would trade this
    false-clean for a false alarm on a correct design.
    """
    if value is None:
        return ("the value is JSON `null` — the same statement `--set "
                "<field>=null` makes, which this program resolves to "
                "UNDETERMINED rather than to a declaration")
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return ("the value is empty — an empty string records that a key was "
                "supplied, not that a choice was made")
    if _TEMPLATE_VALUE_RE.match(stripped):
        return ("the value %r is an unfilled template placeholder"
                % (value,))
    if stripped.lower() in _PLACEHOLDER_TOKENS:
        return ("the value %r means 'not filled in yet', which is exactly the "
                "undetermined state this program refuses to write" % (value,))
    return None


def _same_declared_value(a: Any, b: Any) -> bool:
    """Is `a` the SAME declared value as `b` — type included, at every depth?

    Python ``==`` is not the right predicate for "the file still carries the
    value the sidecar recorded".  ``1 == True``, ``0 == False`` and
    ``1 == 1.0`` are all true, so editing ``"latency_cycles": 1`` to ``true``
    slipped past the value-match guard in ONE run and was then stamped
    ``provenance_verified``, with the boolean written back into the
    declaration for a consumer that expects an integer.

    Comparing canonical JSON text is exact and type-strict all the way down
    (``1`` -> ``1``, ``True`` -> ``true``, ``1.0`` -> ``1.0``, ``[1]`` vs
    ``[true]``), which ``==`` is not even at the top level.
    """
    try:
        return (json.dumps(a, sort_keys=True, default=repr)
                == json.dumps(b, sort_keys=True, default=repr))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return type(a) is type(b) and a == b


def _contained_artifact_path(project: Path, rel: str) -> Optional[Path]:
    """The absolute path for a spec-declared artifact, or None if it escapes.

    The artifact path comes out of a DOCUMENT, so it is untrusted input: the
    only sanitisation upstream is ``strip('/').rstrip(')')``, which turns an
    absolute path into a relative one but leaves ``../`` intact.  A clause
    naming ``../../escaped/decl.json`` wrote the declaration and its provenance
    sidecar two directories above the run.  Nothing this program emits belongs
    outside the project it was pointed at.
    """
    if not rel:
        return None
    candidate = Path(rel)
    if candidate.is_absolute():
        return None
    try:
        base = project.resolve()
        resolved = (base / candidate).resolve()
    except (OSError, RuntimeError):
        return None
    if resolved == base:
        return None
    try:
        resolved.relative_to(base)
    except ValueError:
        return None
    return resolved


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


def extract_contracts(project: Path,
                      rejected: Optional[List[Dict[str, Any]]] = None,
                      ) -> List[Dict[str, Any]]:
    """Every declaration contract this project's spec declares.

    A contract == a MUST-emit/declare clause naming a path-shaped artifact,
    IMMEDIATELY followed by a field table.  A MUST-emit clause with no field
    table is a required artifact but not a declaration contract, and is left to
    ``spec_required_artifact_check``.

    A clause whose artifact path escapes the project root is DROPPED, not
    honoured, and appended to `rejected` (when supplied) so the narrowing is
    auditable rather than silent.
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
                if _contained_artifact_path(project, path) is None:
                    if rejected is not None:
                        rejected.append({
                            "artifact_path": path,
                            "source": rel,
                            "clause_text": m.group(0).strip(),
                            "reason": ("the declared artifact path resolves "
                                       "outside the project root; this "
                                       "program writes nothing outside the "
                                       "run it was pointed at"),
                        })
                    continue
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


# Leading decoration a comment banner puts in front of its text: box rules,
# bullets, the `*` column of a `/* ... */` block.  `_` and `.` are NOT stripped
# because an identifier may legitimately start with `_`.
_COMMENT_DECORATION_RE = re.compile(r"^[\s*\-=+#|>~]+")
# Keywords that make a comment's content commented-out CODE rather than a
# declaration.  Only used to EXPLAIN a rejection: the anchoring rule below has
# already refused these, because the keyword sits where the field name must be.
_CODE_LEAD_RE = re.compile(
    r"^(?:parameter|localparam|defparam|assign|wire|reg|logic|integer|genvar"
    r"|real|realtime|time|input|output|inout|typedef|`define|`ifdef|`ifndef"
    r"|initial|always|always_ff|always_comb|generate|module|endmodule)\b")


def _scan_declaration_lines(text: str) -> List[Tuple[int, str]]:
    """``(line_no, comment_text)`` for every COMMENT-ONLY line in `text`.

    A Verilog lexer, not a line-prefix test.  The predecessor
    (``^\\s*(?://+|\\*+|/\\*+)``) classified an ENTIRE LINE as a comment when
    the line merely STARTED with a comment token, and then scraped
    ``<field> = <value>`` from anywhere on it.  Three realistic idioms
    therefore fed CODE into the declaration:

        /* verilator lint_off WIDTH */ localparam bit_order = 1;
        /* synthesis keep */ parameter latency_cycles = 8;
        */ parameter crc_seed = 4660;

    Every one of those is code, and every one satisfied a REQUIRED free choice
    stamped ``rtl_header_declaration`` — an inference in the costume of a
    declaration.

    Two rules, both load-bearing:

      * Only text INSIDE a comment is returned.  Block-comment state and
        string literals are tracked across the whole file, so a ``//`` inside
        a string is not a comment and a stray ``*/`` outside a block comment
        opens nothing.
      * A line that carries ANY code — before the comment or after it — is not
        a declaration line at all and contributes nothing.  A DECLARATION
        BLOCK is code-free by construction; a trailing comment on a code line
        is an annotation OF that code, which is the inference this program
        retires.
    """
    out: List[Tuple[int, str]] = []
    in_block = False
    for lineno, line in enumerate(text.split("\n"), start=1):
        i, n = 0, len(line)
        code: List[str] = []
        comment: List[str] = []
        in_string = False
        while i < n:
            if in_block:
                if line.startswith("*/", i):
                    in_block = False
                    i += 2
                else:
                    comment.append(line[i])
                    i += 1
                continue
            if in_string:
                if line[i] == "\\" and i + 1 < n:
                    code.append(line[i:i + 2])
                    i += 2
                    continue
                if line[i] == '"':
                    in_string = False
                code.append(line[i])
                i += 1
                continue
            if line.startswith("//", i):
                comment.append(line[i + 2:])
                i = n
                continue
            if line.startswith("/*", i):
                in_block = True
                i += 2
                continue
            if line[i] == '"':
                in_string = True
            code.append(line[i])
            i += 1
        # A Verilog string literal does not survive a newline, so an
        # unterminated quote must not swallow the rest of the file.
        if "".join(code).strip():
            continue
        joined = "".join(comment)
        if joined.strip():
            out.append((lineno, joined))
    return out


#: A comment body that opens the block this plugin's own RTL generator writes.
_BLOCK_OPEN_RE = re.compile(r"^DECLARED\s+CHOICES\b", re.IGNORECASE)
#: An ALL-CAPS heading closes it.  Without a closing rule the block would run to
#: the end of the contiguous comment run and take the prose sections with it.
_BLOCK_CLOSE_RE = re.compile(r"^[A-Z][A-Z0-9 _/\-]{2,}(?:\s|$)")


def _declaration_block_lines(scanned: List[Tuple[int, str]]) -> set:
    """Line numbers inside a ``DECLARED CHOICES`` block.

    The block is what lets the ALIGNED-COLUMN spelling be read safely.  Outside
    it, ``<field>   <value>`` is indistinguishable from prose; inside it, with
    the column gap required below, it is the spelling the generator emits.

    Bounded at both ends: it opens on the header and closes on the next ALL-CAPS
    heading or when the contiguous comment run ends.  A block that ran to the end
    of the file would put every prose paragraph back in scope, which is the
    over-reach this whole reader exists to avoid.
    """
    inside: set = set()
    open_at: Optional[int] = None
    prev_lineno: Optional[int] = None
    for lineno, comment_text in scanned:
        body = _COMMENT_DECORATION_RE.sub("", comment_text).strip()
        if prev_lineno is not None and lineno - prev_lineno > 1:
            open_at = None          # the comment run ended; so did the block
        prev_lineno = lineno
        if _BLOCK_OPEN_RE.match(body):
            open_at = lineno
            continue
        if open_at is None:
            continue
        if _BLOCK_CLOSE_RE.match(body):
            open_at = None
            continue
        inside.add(lineno)
    return inside


def _rtl_declared(project: Path, names: List[str],
                  rejected: Optional[List[Dict[str, Any]]] = None,
                  ) -> Dict[str, Tuple[Any, str]]:
    """Opt-in legacy recovery: `<field> = <value>` from an RTL DECLARATION block.

    The match is ANCHORED at the start of the comment text (after banner
    decoration such as ``*``/``-``/``|``).  Anchoring is what separates a
    DECLARATION from a mention:

      ``//   bit_order = MSB_first``          -> a declaration
      ``// localparam bit_order = 1;``        -> commented-out CODE, refused
      ``// never set bit_order = MSB_first``  -> prose about the field, refused

    Value is the FIRST bare token so a trailing parenthetical cannot leak in.
    Everything refused is appended to `rejected` (when supplied) so the
    narrowing is auditable instead of silent.
    """
    out: Dict[str, Tuple[Any, str]] = {}
    rtl = _rtl_dir(project)
    if not rtl.is_dir():
        return out
    srcs = sorted(rtl.rglob("*.v")) + sorted(rtl.rglob("*.sv"))
    patterns = {n: re.compile(r"^" + re.escape(n) + r"\s*=\s*([A-Za-z0-9_.+\-]+)")
                for n in names}
    # The SAME generator writes both spellings.  `bit_order = LSB_first` and
    # `bit_order            LSB_first` are one declaration in two hands, and
    # reading only the first reported the second as "never declared" — a check
    # whose failure to parse was published as the design's failure to declare.
    # The column gap is the discriminator: prose separates words with ONE space,
    # a column layout with several.  Block-anchored, so the gap alone is never
    # enough on its own.
    aligned = {n: re.compile(r"^" + re.escape(n) + r"[ \t]{2,}([A-Za-z0-9_.+\-]+)")
               for n in names}
    mention = {n: re.compile(r"(?<![A-Za-z0-9_])" + re.escape(n)
                             + r"\s*=\s*([A-Za-z0-9_.+\-]+)") for n in names}
    # Reported when the field OPENS a comment but yields no declaration: the
    # near miss is the whole point.  "I did not find it" and "I found it and
    # could not read it" send a reader to different places.
    leads = {n: re.compile(r"^" + re.escape(n) + r"(?![A-Za-z0-9_])")
             for n in names}
    for f in srcs:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        try:
            rel = str(f.relative_to(project))
        except ValueError:
            rel = str(f)
        scanned = _scan_declaration_lines(text)
        in_block = _declaration_block_lines(scanned)
        for lineno, comment_text in scanned:
            body = _COMMENT_DECORATION_RE.sub("", comment_text).strip()
            for name, rx in patterns.items():
                if name in out:
                    continue
                m = rx.match(body)
                if not m and lineno in in_block:
                    m = aligned[name].match(body)
                if not m:
                    # Not a declaration.  Say WHY whenever the field is here at
                    # all, so a designer who wrote the block in a form this
                    # program will not read finds out from the report instead of
                    # being told the declaration does not exist.
                    if rejected is not None and (mention[name].search(body)
                                                 or leads[name].match(body)):
                        if _CODE_LEAD_RE.match(body):
                            why = "commented-out code, not a declaration"
                        elif leads[name].match(body):
                            why = (
                                "the comment opens with `%s` but no value "
                                "follows it in a form this reader accepts — "
                                "write `%s = <value>`, or align the value in a "
                                "column (two or more spaces) inside a `DECLARED "
                                "CHOICES` block" % (name, name))
                        else:
                            why = (
                                "`%s = ...` does not begin the comment text, "
                                "so this is prose mentioning the field rather "
                                "than a declaration of it" % name)
                        rejected.append({
                            "field": name,
                            "file": rel,
                            "line": lineno,
                            "text": body[:200],
                            "in_declared_choices_block": lineno in in_block,
                            "reason": why,
                        })
                    continue
                # A Verilog SIZED LITERAL is the natural spelling in an RTL
                # header, and the bare-token value class stops at the
                # apostrophe: `1'b0` was read as 1, `3'd5` as 3, `4'h1_F` as 4
                # — a value that is neither the designer's token nor its
                # numeric meaning, stamped as a full declaration with nothing
                # in the report to say it had been misread.  Refuse it: this
                # program does not produce a value it cannot read faithfully,
                # and the refusal is named so `--set` is the obvious next step.
                if body[m.end():m.end() + 1] == "'":
                    if rejected is not None:
                        rejected.append({
                            "field": name, "file": rel, "line": lineno,
                            "text": body[:200],
                            "reason": ("the value is a Verilog sized literal, "
                                       "which this reader cannot transcribe "
                                       "faithfully — declare it with `--set "
                                       "%s=<value>`" % name),
                        })
                    continue
                value = _coerce(m.group(1))
                if value is UNDETERMINED:
                    # `<field> = null` written in a comment states no choice;
                    # treat it as if the line were absent rather than letting a
                    # sentinel reach the JSON writer.
                    if rejected is not None:
                        rejected.append({
                            "field": name, "file": rel, "line": lineno,
                            "text": body[:200],
                            "reason": "the comment states `null` — no choice",
                        })
                    continue
                out[name] = (value, rel)
    return out


def _load_prior_provenance(sidecar: Path) -> Dict[str, Dict[str, Any]]:
    """Per-field records from the PREVIOUS run's provenance sidecar.

    The declaration file is a resolution source AND a file this program wrote,
    so provenance must be carried forward rather than re-derived from "where
    did I read it this time" — see the module docstring.
    """
    if not sidecar.is_file():
        return {}
    try:
        data = json.loads(sidecar.read_text())
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    fields = data.get("fields")
    if not isinstance(fields, dict):
        return {}
    out = {k: v for k, v in fields.items() if isinstance(v, dict)}
    # Schema 2 writes `provenance_verified` on EVERY determined field.  A
    # schema-2 record missing it has been edited, and dropping one key must not
    # be cheaper than editing the value: treat the omission as the doubt it
    # erases.  Schema 1 predates the distinction and never encoded doubt at
    # all, so its records are carried as-is — reading them as unverified would
    # be a false alarm on every declaration written before this seam existed.
    try:
        version = int(data.get("schema_version", 1))
    except (TypeError, ValueError):
        version = 1
    if version >= 2:
        for rec in out.values():
            rec.setdefault("provenance_verified", False)
    return out


def resolve(contract: Dict[str, Any],
            overrides: Dict[str, Any],
            rtl_declared: Dict[str, Tuple[Any, str]],
            existing: Optional[Dict[str, Any]] = None,
            prior: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Resolve every contract field.  Returns a per-field status map.

    Priority, strongest first:
      1. an explicit author declaration made in THIS invocation
      2. a value already present in the declaration file (someone declared it
         before; re-running the emitter must not silently discard it)
      3. an opt-in `key = value` line from an RTL COMMENT block
      4. UNDETERMINED

    There is no fifth tier.  A value this program cannot trace to something the
    designer wrote is not produced.

    Tier 2 is a file THIS PROGRAM WROTE, so its provenance is CARRIED from
    `prior` (the previous run's sidecar) rather than re-derived — see the
    module docstring.  Re-deriving relabelled every prose-recovered field
    ``existing_declaration`` on the second, byte-identical run.

    At every tier, a value that states no choice (empty string, ``TBD``,
    ``<fill-me>``) resolves to UNDETERMINED, not to a declaration.
    """
    existing = existing or {}
    prior = prior or {}
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
            # Observed THIS run, from an argument this run was given: verified
            # by direct observation rather than by a record.  Stated
            # explicitly so every determined field carries the key and the
            # sidecar is self-describing.
            entry.update(status="determined", value=overrides[name],
                         provenance="author_declared",
                         recovered_from_prose=False,
                         provenance_verified=True)
        elif name in existing:
            record = prior.get(name)
            value_matches = (isinstance(record, dict)
                             and record.get("status") == "determined"
                             and "value" in record
                             and _same_declared_value(record["value"],
                                                      existing[name]))
            # An UNVERIFIED record is not evidence.  The fallback branch below
            # writes `status: determined` for a value nothing accounts for, so
            # a record that merely matches the file is satisfied by the record
            # THIS PROGRAM wrote about its own doubt one run earlier — the
            # auditor accepting evidence it created.  Deleting the sidecar
            # therefore only laundered a field for one extra run: re-run 1
            # printed PROVENANCE UNVERIFIED, re-run 2 carried that record
            # forward and stamped it verified.  The doubt is STICKY: it is
            # retired by DECLARING the field (--set), never by re-running.
            carried = value_matches and record.get(
                "provenance_verified") is not False
            if carried:
                # The value in the file is the one the previous run recorded,
                # so it keeps that run's provenance and its debt stamp.  The
                # stamp is retired by DECLARING the field, not by re-running.
                entry.update(
                    status="determined", value=existing[name],
                    provenance=record.get("provenance",
                                          "existing_declaration"),
                    recovered_from_prose=bool(
                        record.get("recovered_from_prose")),
                    carried_from_declaration_file=True,
                    provenance_verified=True)
                if record.get("provenance_detail"):
                    entry["provenance_detail"] = record["provenance_detail"]
                if record.get("first_recorded_at"):
                    entry["first_recorded_at"] = record["first_recorded_at"]
            else:
                # Present in the file with nothing that accounts for it: a
                # hand-written declaration, a value edited since, a deleted
                # sidecar, or a record this program itself already marked
                # unverified.  Reported as UNVERIFIED rather than promoted to a
                # clean declaration — refusing it outright would be a false
                # alarm on a legitimately hand-authored file.  The mark is
                # written back UNVERIFIED so it survives the next run.
                entry.update(
                    status="determined", value=existing[name],
                    provenance="existing_declaration",
                    recovered_from_prose=False,
                    carried_from_declaration_file=True,
                    provenance_verified=False,
                    provenance_note=(
                        "the declaration file carries this value but no "
                        "verified provenance record matches it; who chose it, "
                        "and whether it was recovered from prose, is unknown. "
                        "Re-running does not clear this — declare the field "
                        "with `--set %s=<value>`." % name))
                if isinstance(record, dict) and record.get("first_recorded_at"):
                    entry["first_recorded_at"] = record["first_recorded_at"]
            # A carried stamp names a SOURCE.  When that source was re-read
            # this run and no longer says what the stamp claims, the stamp is
            # attesting to a file that contradicts it, and the only evidence
            # for it is the sidecar this program wrote.  Demoted to unverified
            # and named — not refused, because the declaration file legitimately
            # outranks the comment block and an author may have edited one
            # without the other.
            if (entry.get("provenance") == "rtl_header_declaration"
                    and name in rtl_declared
                    and not _same_declared_value(rtl_declared[name][0],
                                                 existing[name])):
                entry.update(
                    provenance_verified=False,
                    provenance_diverged=True,
                    provenance_note=(
                        "this value is stamped as recovered from %s, but that "
                        "file now declares %r. Nothing verifies which one the "
                        "designer meant; declare it with `--set %s=<value>`."
                        % (entry.get("provenance_detail", "an RTL comment"),
                           rtl_declared[name][0], name)))
        elif name in rtl_declared:
            value, src = rtl_declared[name]
            entry.update(status="determined", value=value,
                         provenance="rtl_header_declaration",
                         provenance_detail=src,
                         recovered_from_prose=True,
                         provenance_verified=True)
        else:
            entry.update(
                status="undetermined",
                reason=("no author declaration supplied, none already recorded "
                        "in the declaration file, and no `%s = <value>` line in "
                        "an RTL comment block" % name),
                recovered_from_prose=False)

        if entry["status"] == "determined":
            why = _placeholder_reason(entry["value"])
            if why is not None:
                source = entry.get("provenance", "?")
                entry = {
                    k: v for k, v in entry.items()
                    if k in ("required", "required_marker",
                             "required_marker_recognized",
                             "spec_example_values")
                }
                entry.update(
                    status="undetermined",
                    reason="%s (supplied via %s)" % (why, source),
                    rejected_placeholder=True,
                    recovered_from_prose=False)
            elif "first_recorded_at" not in entry:
                entry["first_recorded_at"] = _now()
        status[name] = entry
    return status


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def _print_contract(contracts: List[Dict[str, Any]], out_path: Path,
                    rejected: Optional[List[Dict[str, Any]]] = None) -> None:
    for r in (rejected or []):
        print("  REJECTED CLAUSE %s (from %s): %s"
              % (r["artifact_path"], r["source"], r["reason"]))
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
    rejected: List[Dict[str, Any]] = []
    contracts = extract_contracts(project, rejected)
    out_path = _stage1_dir(project) / "declaration_contract.json"
    _write_json(out_path, {
        "schema_version": 1,
        "program": "spec_declaration_emit",
        "mode": "contract",
        "generated_at": _now(),
        "project": str(project),
        "contract_count": len(contracts),
        "contracts": contracts,
        "rejected_contract_count": len(rejected),
        "rejected_contracts": rejected,
    })
    return out_path, contracts


# --------------------------------------------------------------------------- #
# --verify: the SUBSTANCE assertion the presence gate cannot make
# --------------------------------------------------------------------------- #

def verify_declaration(project: Path, contract: Dict[str, Any],
                       out_path: Path) -> Dict[str, Any]:
    """Assert the declaration ON DISK satisfies `contract`.  Writes nothing.

    ``spec_required_artifact_check`` scores the spec-declared artifact on
    presence and ``st_size > 0``; ``{}`` is three bytes and passes.  The
    quantity that actually matters is whether every field the SPEC marks
    REQUIRED carries a real value — and required-ness comes from the spec,
    an input this program did not write, so this is not a run certifying its
    own output.
    """
    required = [f["name"] for f in contract["fields"] if f["required"]]
    result: Dict[str, Any] = {
        "schema_version": 1,
        "program": "spec_declaration_emit",
        "mode": "verify",
        "run_at": _now(),
        "declaration_path": contract["artifact_path"],
        "contract_source": contract["source"],
        "required_fields": sorted(required),
        "missing_required": [],
        "placeholder_required": [],
        "recovered_from_prose": [],
        "provenance_unverified": [],
        "provenance_sidecar_present": False,
    }
    if not out_path.is_file():
        result["verdict"] = "FAIL_ABSENT"
        result["note"] = ("the spec-declared declaration does not exist; the "
                          "required free choices were never recorded")
        result["missing_required"] = sorted(required)
        return result

    try:
        loaded = json.loads(out_path.read_text())
    except Exception as exc:
        result["verdict"] = "FAIL_UNPARSEABLE"
        result["note"] = "declaration is not readable JSON: %s" % exc
        return result
    if not isinstance(loaded, dict):
        result["verdict"] = "FAIL_UNPARSEABLE"
        result["note"] = "declaration is not a JSON object"
        return result

    for name in sorted(required):
        if name not in loaded:
            result["missing_required"].append(name)
            continue
        why = _placeholder_reason(loaded[name])
        if why is not None:
            result["placeholder_required"].append({"field": name, "reason": why})

    sidecar = out_path.with_name(out_path.stem + ".provenance.json")
    prior = _load_prior_provenance(sidecar)
    result["provenance_sidecar_present"] = bool(prior)
    unverified: set = set()
    for name, rec in sorted(prior.items()):
        if rec.get("recovered_from_prose"):
            result["recovered_from_prose"].append(name)
        if rec.get("status") == "determined" and rec.get(
                "provenance_verified") is False:
            unverified.add(name)
    # A declared field whose provenance record does not MATCH the value on disk
    # is UNVERIFIED, not clean.  Three cases, all of them the same statement
    # "nothing here accounts for this value": no record at all (a deleted
    # sidecar, the laundering route), a record that is not `determined`, and a
    # record whose value has since been edited in the declaration file.
    for name in [f["name"] for f in contract["fields"]]:
        if name not in loaded:
            continue
        rec = prior.get(name)
        if (not isinstance(rec, dict) or rec.get("status") != "determined"
                or "value" not in rec
                or not _same_declared_value(rec["value"], loaded[name])):
            unverified.add(name)
    result["provenance_unverified"] = sorted(unverified)

    declared_contract_fields = sorted(
        f["name"] for f in contract["fields"]
        if f["name"] in loaded and _placeholder_reason(loaded[f["name"]]) is None)
    result["declared_contract_fields"] = declared_contract_fields

    if result["missing_required"] or result["placeholder_required"]:
        result["verdict"] = "FAIL"
        result["note"] = (
            "%d required field(s) missing, %d carrying a placeholder"
            % (len(result["missing_required"]),
               len(result["placeholder_required"])))
    elif not declared_contract_fields:
        # Present, non-empty by byte count, and declaring NOTHING the spec's
        # table asked for.  This is the `{}` case the presence gate scores as
        # PASS; a declaration that declares nothing does not satisfy a
        # requirement to declare.
        result["verdict"] = "FAIL_VACUOUS"
        result["note"] = ("the declaration exists but carries none of the %d "
                          "field(s) the spec's declaration table enumerates"
                          % len(contract["fields"]))
    elif not required:
        result["verdict"] = "PASS_INFORMATIONAL"
        result["note"] = ("the spec's declaration table marks no field "
                          "REQUIRED; %d informational field(s) declared"
                          % len(declared_contract_fields))
    else:
        result["verdict"] = "PASS"
        result["note"] = ("all %d spec-REQUIRED free choice(s) declared with a "
                          "real value" % len(required))
    return result


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
    ap.add_argument("--verify", action="store_true",
                    help="ASSERT the declaration already on disk carries a "
                         "real value for every REQUIRED contract field, and "
                         "exit 1 when it does not. Writes NO declaration. "
                         "This is the SUBSTANCE check the required-artifact "
                         "gate cannot make: it scores presence and byte "
                         "count, and `{}` is 3 bytes.")
    args = ap.parse_args(argv)

    project = Path(args.project).resolve()
    if not project.is_dir():
        print("ERROR: project not found: %s" % project, file=sys.stderr)
        return 2

    if args.contract and args.verify:
        print("ERROR: --contract and --verify are different modes; pick one",
              file=sys.stderr)
        return 2

    rejected_contracts: List[Dict[str, Any]] = []

    if args.contract:
        out_path, contracts = stage_contract(project)
        try:
            rejected_contracts = json.loads(
                out_path.read_text())["rejected_contracts"]
        except Exception:
            rejected_contracts = []
        _print_contract(contracts, out_path, rejected_contracts)
        return 0

    contracts = extract_contracts(project, rejected_contracts)
    for r in rejected_contracts:
        print("spec_declaration_emit: REJECTED CLAUSE %s (from %s) — %s"
              % (r["artifact_path"], r["source"], r["reason"]), file=sys.stderr)

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

    out_path = _contained_artifact_path(project, contract["artifact_path"])
    if out_path is None:
        print("ERROR: the spec-declared declaration path %r resolves outside "
              "the project root; refusing to write there."
              % contract["artifact_path"], file=sys.stderr)
        return 2

    if args.verify:
        report = verify_declaration(project, contract, out_path)
        report_path = (project / "reports" / "phase2" / "gates"
                       / "spec_declaration_verify.json")
        _write_json(report_path, report)
        ok = report["verdict"] in ("PASS", "PASS_INFORMATIONAL")
        stream = sys.stdout if ok else sys.stderr
        print("spec_declaration_verify: %s — %s"
              % (report["verdict"], report["note"]), file=stream)
        for name in report["missing_required"]:
            print("  - %s: REQUIRED by %s, absent from the declaration"
                  % (name, contract["source"]), file=stream)
        for item in report["placeholder_required"]:
            print("  - %s: %s" % (item["field"], item["reason"]), file=stream)
        if report["recovered_from_prose"]:
            print("  RECOVERED FROM PROSE (legacy debt, still outstanding): %s"
                  % ", ".join(report["recovered_from_prose"]), file=stream)
        if report["provenance_unverified"]:
            print("  PROVENANCE UNVERIFIED (declared value with no matching "
                  "provenance record): %s"
                  % ", ".join(report["provenance_unverified"]), file=stream)
        print("  Report: %s" % report_path, file=stream)
        return 0 if ok else 1

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
    rtl_rejected: List[Dict[str, Any]] = []
    rtl_declared = (_rtl_declared(project, names, rtl_rejected)
                    if args.from_rtl_declaration else {})

    existing: Dict[str, Any] = {}
    if out_path.is_file():
        try:
            loaded = json.loads(out_path.read_text())
            if isinstance(loaded, dict):
                existing = loaded
        except Exception:
            existing = {}
    sidecar = out_path.with_name(out_path.stem + ".provenance.json")
    prior = _load_prior_provenance(sidecar)

    status = resolve(contract, overrides, rtl_declared, existing, prior)

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
        for r in rtl_rejected:
            print("  NOT read from %s:%d — %s: %s"
                  % (r["file"], r["line"], r["reason"], r["text"]),
                  file=sys.stderr)
        return 1

    # A declaration that declares NOTHING must not satisfy a requirement to
    # declare.  Writing `{}` here handed `spec_required_artifact_check` three
    # bytes it scores as "present and non-empty" — a green gate certifying an
    # artifact this run created during the same run to satisfy it.  Nothing is
    # written and nothing already on disk is touched; the presence gate then
    # honestly reports the artifact as absent.
    n_determined = sum(1 for e in status.values() if e["status"] == "determined")
    if n_determined == 0:
        print("spec_declaration_emit: NOTHING_TO_DECLARE — the spec's "
              "declaration table enumerates %d field(s), none of them REQUIRED "
              "and not one of them determined. No declaration written: an "
              "empty declaration is not a declaration, and `{}` would turn "
              "the required-artifact gate green while declaring nothing."
              % len(status), file=sys.stderr)
        for n in undetermined_optional:
            print("  - %s: %s" % (n, status[n]["reason"]), file=sys.stderr)
        print("  Declare at least one with --set <field>=<value>, or correct "
              "the spec clause that demands a declaration with no substance.",
              file=sys.stderr)
        return 4

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
            # — or by carrying a placeholder that states no choice, so nothing
            # a designer actually declared is dropped by accident.
            declaration.pop(n, None)
    _write_json(out_path, declaration)

    unverified = sorted(n for n, e in status.items()
                        if e["status"] == "determined"
                        and e.get("provenance_verified") is False)
    _write_json(sidecar, {
        "schema_version": 2,
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
        "existing_without_recorded_provenance": unverified,
        "preserved_foreign_keys": sorted(
            k for k in existing if k not in status),
        "rtl_declaration_scan": {
            "enabled": bool(args.from_rtl_declaration),
            "accepted": sorted(rtl_declared),
            "rejected": rtl_rejected,
        },
    })

    print("spec_declaration_emit: PASS — %d/%d contract field(s) declared -> %s"
          % (n_determined, len(status), out_path))
    if undetermined_optional:
        print("  informational field(s) OMITTED as undetermined (not "
              "defaulted): %s" % ", ".join(undetermined_optional))
    recovered = sorted(n for n, e in status.items()
                       if e.get("recovered_from_prose"))
    if recovered:
        print("  RECOVERED FROM PROSE (legacy path — these should have been "
              "declared before the RTL was written): %s" % ", ".join(recovered))
    if unverified:
        print("  PROVENANCE UNVERIFIED — the declaration file carries these "
              "values but no verified provenance record matches them, so who "
              "chose them is unknown (re-running does not clear this; declare "
              "them with --set): %s" % ", ".join(unverified))
        for n in unverified:
            note = status[n].get("provenance_note")
            if note:
                print("    - %s: %s" % (n, note))
    for r in rtl_rejected:
        print("  NOT read from %s:%d — %s: %s"
              % (r["file"], r["line"], r["reason"], r["text"]))
    print("  Provenance: %s" % sidecar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
