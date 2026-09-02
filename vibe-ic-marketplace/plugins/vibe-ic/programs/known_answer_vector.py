#!/usr/bin/env python3
"""known_answer_vector.py — the L10 case kind for a DECLARED reference output.

NOT A GATE. This module is a schema / producer imported by the L10 emitter, the
unit-TB producer and `l10_tb_conformance_check`; it declares no `ENFORCEMENT:`
intent because it is not wired into the flow definition as a clause and
`flow_gate_enforcement_audit` would correctly call such a declaration orphaned.
Its siblings `arith_oracle_tb_gen` and `cpu_boot_latency_oracle_tb_gen` declare
none either.

Why this exists. `opentitan_aes` states its functional oracle in its own brief —
"NIST FIPS-197 / SP 800-38A 標準測試向量（ECB/CBC/CFB/OFB/CTR），經自建 TB 由
TL-UL register interface 驅動完整 encrypt/decrypt round-trip" — and the flow had
nowhere to put it. `grep -rl known_answer programs/ skills/` returned 0 files;
the only vector-consuming producers were CRC- and opcode-shaped; and the general
path, `testbench_gen.emit_unit_tbs`, carried a case's `expected` into a COMMENT
with an instruction for a human to write the compare. So a design whose
reference output is published, fixed and machine-checkable reached Step 4 with
connectivity evidence only (`pass=4 fail=0 bytes=0 bits=0`) and the
`cap:cpu_functional_oracle` waiver, whose justifying sentence — "the oracle is
the instrument-set model this pass did not author" — is false for it.

THE SHAPE. One kind, `known_answer_vector`, carrying a TYPED (inputs,
expected_outputs) pair. `expected` as prose is what produced the defect, so
every value here is a hex STRING of even length that a comparator can widen to a
Verilog literal, and a record whose expected side is prose is REFUSED rather
than emitted.

    {
      "name":              str          unique, a legal identifier
      "kind":              "known_answer_vector"
      "algorithm":         str          "aes" / "sha2" / ... (vendor-neutral)
      "inputs":            {str: hex}   e.g. {"key":..,"plaintext":..,"iv":..}
                                        or  {"message": ..}
      "expected_outputs":  {str: hex}   e.g. {"ciphertext":..} / {"digest":..}
      "parameters":        {str: any}   the conditions it is valid under
                                        (key_len, mode, operation, digest_len)
      "transport":         {...}        HOW it is driven — resolved from the
                                        design's OWN L9/L3, never assumed
      "citation":          str          the section it comes from
      "source":            "input_document" | "named_public_standard"
      "evidence":          str          the input path, or the standard the
                                        design's own input NAMED
    }

Both corpus shapes express in it unchanged: AES's (key, plaintext, ciphertext,
mode) and SHA-2's (message, digest).

§4.05. A vector may come from the design's INPUT (a table in `input/docs/**` or
the prompt), or from a public standard the design's own input NAMES, whose
transcription ships under `data/known_answer_vectors/` and was re-computed on
the host before it was committed. It may NEVER come from `input/golden/**` or
any oracle / harness / reference-model directory — `vector_source_is_permitted`
is the one door, and it refuses those paths by construction.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

#: The L10 `kind` token. One literal, imported by the extractor, the producer
#: and the conformance gate, so the #761 two-private-scopes shape cannot recur.
KIND = "known_answer_vector"

#: Where the public-standard transcriptions live, relative to this file.
STANDARD_TABLE_DIR = Path(__file__).resolve().parent.parent / "data" / "known_answer_vectors"

#: Path segments that mark a design's ORACLE rather than its INPUT. §4.05: a
#: vector read from any of these is a leak, and the reader refuses it by
#: construction rather than by convention.
ORACLE_PATH_SEGMENTS = ("golden", "oracle", "harness", "reference_model",
                        "ref_model", "solution", "answers")

_HEX_RE = re.compile(r"\A(?:0x)?[0-9a-fA-F]+\Z")
_ID_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]{0,63}\Z")


def normalise_hex(raw: Any) -> Optional[str]:
    """A typed hex VALUE, or None when the thing is prose.

    Accepts the spacing real specifications use (`ba7816bf 8f01cfea ...`), a
    `0x` prefix and back-ticks; rejects anything that is not an even number of
    hex digits. Returning None is how a prose `expected` is refused instead of
    being carried into a comment."""
    if isinstance(raw, int):
        h = f"{raw:x}"
        return h if len(h) % 2 == 0 else "0" + h
    if not isinstance(raw, str):
        return None
    s = raw.strip().strip("`").replace(" ", "").replace("_", "")
    s = s.replace(" ", "")
    if not s or not _HEX_RE.match(s):
        return None
    s = s[2:] if s[:2].lower() == "0x" else s
    if not s or len(s) % 2:
        return None
    return s.lower()


def vector_source_is_permitted(path: Any) -> Tuple[bool, str]:
    """§4.05 door. `(ok, reason)` for reading vectors out of `path`.

    The refusal is by PATH SEGMENT, so it holds for a directory nobody thought
    of when this was written, and it is checked at the one place vectors enter
    — never left to the caller to remember."""
    p = str(path or "").replace("\\", "/").lower()
    for seg in ORACLE_PATH_SEGMENTS:
        if f"/{seg}/" in f"/{p}/" or f"/{seg}." in p:
            return False, (
                f"§4.05: {path} sits under a design's {seg!r} tree — a vector "
                f"read from the oracle is a leak, not an oracle")
    return True, ""


def validate(case: Dict[str, Any]) -> List[str]:
    """Every reason `case` is not a usable known-answer vector. Empty == usable.

    Fail-closed and typed: a record that cannot be compared against is refused
    here rather than emitted and discovered later by a testbench that prints a
    PASS it never checked."""
    errs: List[str] = []
    if not isinstance(case, dict):
        return ["not a mapping"]
    if case.get("kind") != KIND:
        errs.append(f"kind must be {KIND!r}, got {case.get('kind')!r}")
    if not _ID_RE.match(str(case.get("name") or "")):
        errs.append(f"name {case.get('name')!r} is not a legal identifier")
    for field in ("inputs", "expected_outputs"):
        val = case.get(field)
        if not isinstance(val, dict) or not val:
            errs.append(f"{field} must be a non-empty mapping")
            continue
        for k, v in val.items():
            if normalise_hex(v) is None:
                errs.append(
                    f"{field}.{k} is not a typed hex value ({v!r}) — an "
                    f"expected side that is prose cannot be compared against")
    if not str(case.get("citation") or "").strip():
        errs.append("citation is required: a vector with no source is a claim")
    if case.get("source") not in ("input_document", "named_public_standard"):
        errs.append(f"source {case.get('source')!r} is not one of "
                    f"input_document / named_public_standard")
    ok, why = vector_source_is_permitted(case.get("evidence"))
    if not ok:
        errs.append(why)
    return errs


def is_known_answer_vector(case: Any) -> bool:
    """True when `case` declares this kind AND survives validation."""
    return isinstance(case, dict) and case.get("kind") == KIND and not validate(case)


def load_standard_tables(table_dir: Optional[Path] = None) -> Dict[str, dict]:
    """Every shipped public-standard table, keyed by its designator."""
    root = Path(table_dir) if table_dir else STANDARD_TABLE_DIR
    out: Dict[str, dict] = {}
    if not root.is_dir():
        return out
    for f in sorted(root.glob("*.json")):
        try:
            doc = json.loads(f.read_text(errors="replace"))
        except Exception:
            continue
        std = str(doc.get("standard") or "").strip()
        if std and isinstance(doc.get("vectors"), list):
            doc["_file"] = str(f)
            out[std.upper()] = doc
    return out


def standard_designators(text: str) -> List[str]:
    """The public-standard designators a document NAMES, in first-seen order.

    Matched on the designator's own published shape (`FIPS-197`, `FIPS 180-4`,
    `SP 800-38A`, `NIST 800-38D`), never on a chip, vendor or SKU literal. A
    design that names no standard yields none, which is how "this design has no
    declared vector oracle" stays a real, reachable answer."""
    seen: List[str] = []
    if not isinstance(text, str):
        return seen

    def _add(v: str) -> None:
        if v not in seen:
            seen.append(v)

    for m in re.finditer(r"\bFIPS[\s‑-]*(\d{3})(?:[\s‑-]*(\d))?\b",
                         text, re.I):
        _add(f"FIPS-{m.group(1)}" + (f"-{m.group(2)}" if m.group(2) else ""))
    for m in re.finditer(r"\b(?:NIST\s+)?SP[\s‑-]*(800[\s‑-]*\d{2}[A-Za-z]?)\b",
                         text, re.I):
        _add("SP " + re.sub(r"[\s‑-]+", "-", m.group(1)).upper())
    for m in re.finditer(r"\bNIST[\s‑-]+(800[\s‑-]*\d{2}[A-Za-z]?)\b",
                         text, re.I):
        _add("SP " + re.sub(r"[\s‑-]+", "-", m.group(1)).upper())
    return seen


# ---------------------------------------------------------------------------
# PHASE-1 EXTRACTION
# ---------------------------------------------------------------------------
# Two routes, both keyed on what the design's OWN input states, and both
# fail-closed. A design that states neither yields NOTHING, which is how "this
# design has no declared vector oracle" stays a reachable, honest answer and the
# `cap:cpu_functional_oracle` route is not manufactured into a pass.
#
#   (a) a VECTOR TABLE in the design's documents — both sides stated as typed
#       hex, in a GFM table whose header roles name an input and an expected
#       output column;
#   (b) a public standard the design's own input NAMES, resolved against the
#       transcriptions shipped under `data/known_answer_vectors/`.
#
# Route (b) is gated twice: the designator must be named by the design, AND the
# table's algorithm token must occur in the design's own input. A design that
# cites SP 800-38D for a counter definition does not thereby acquire AES-GCM
# vectors, and sha256 naming AES in a comparison paragraph does not acquire the
# AES tables.

#: Header-cell vocabulary. INPUT-side and EXPECTED-side, matched on the role a
#: specification column plays, never on a chip or vendor literal.
_INPUT_HEADERS = ("input", "inputs", "message", "msg", "plaintext", "data",
                  "key", "stimulus", "輸入", "訊息", "明文")
_EXPECT_HEADERS = ("expected", "expect", "digest", "ciphertext", "hash",
                   "result", "output", "預期", "期望", "預期輸出", "摘要")

#: The output field a table row's expected value is bound to, by the algorithm
#: family the design declares. Vendor-neutral vocabulary.
_ALGORITHM_OUTPUT_FIELD = {"aes": "ciphertext", "sha2": "digest"}


def _split_pipe_cells(line: str) -> List[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [c.strip() for c in body.split("|")]


def _is_sep_row(line: str) -> bool:
    body = (line or "").strip()
    if not body or "|" not in body:
        return False
    return all(set(c.strip()) <= set(":- ") and c.strip()
               for c in _split_pipe_cells(body))


def algorithm_tokens(text: str) -> List[str]:
    """The algorithm families the design's own input names. Open vocabulary."""
    out: List[str] = []
    if not isinstance(text, str):
        return out
    if re.search(r"\bAES(?:[\s-]?(?:128|192|256))?\b", text):
        out.append("aes")
    if re.search(r"\bSHA[\s-]?(?:2|224|256|384|512)\b", text, re.I):
        out.append("sha2")
    return out


def vectors_from_document(fname: str, text: str,
                          algorithm: Optional[str] = None) -> Tuple[List[dict], List[dict]]:
    """`(vectors, refusals)` for a GFM vector table stated IN the document.

    A row is admitted only when BOTH sides normalise to a typed hex value. A row
    whose input side is prose ("1,000,000 x 0x61 bytes") is REFUSED and the
    refusal is returned, because a table that states only the answer is not a
    vector — it is the shape that made `expected` a comment in the first place.
    """
    vectors: List[dict] = []
    refusals: List[dict] = []
    ok, why = vector_source_is_permitted(fname)
    if not ok:
        return vectors, [{"document": fname, "reason": why}]
    if not isinstance(text, str) or "|" not in text:
        return vectors, refusals
    field = _ALGORITHM_OUTPUT_FIELD.get(str(algorithm or ""), "expected_value")
    in_field = "message" if algorithm == "sha2" else "plaintext"
    lines = text.split("\n")
    n = len(lines)
    i = 0
    while i < n:
        if ("|" in lines[i] and not _is_sep_row(lines[i])
                and i + 1 < n and _is_sep_row(lines[i + 1])):
            header = [c.strip(" *`").lower() for c in _split_pipe_cells(lines[i])]
            i_col = next((k for k, c in enumerate(header)
                          if any(h in c for h in _INPUT_HEADERS)), None)
            e_col = next((k for k, c in enumerate(header)
                          if any(h in c for h in _EXPECT_HEADERS)), None)
            j = i + 2
            if i_col is not None and e_col is not None and i_col != e_col:
                while j < n and "|" in lines[j] and lines[j].strip():
                    if not _is_sep_row(lines[j]):
                        cells = _split_pipe_cells(lines[j])
                        if max(i_col, e_col) < len(cells):
                            iv = normalise_hex(cells[i_col])
                            ev = normalise_hex(cells[e_col])
                            label = re.sub(r"[^a-z0-9]+", "_",
                                           cells[0].lower()).strip("_")[:40]
                            if iv and ev:
                                vectors.append({
                                    "name": f"doc_vector_{label or len(vectors)}",
                                    "kind": KIND,
                                    "algorithm": algorithm or "unknown",
                                    "inputs": {in_field: iv},
                                    "expected_outputs": {field: ev},
                                    "parameters": {},
                                    "citation": f"{fname} table row {label!r}",
                                    "source": "input_document",
                                    "evidence": fname,
                                })
                            elif ev and not iv:
                                refusals.append({
                                    "document": fname, "row": label,
                                    "reason": ("the expected side is a typed "
                                               "value but the input side is "
                                               "prose — a table that states "
                                               "only the answer is not a "
                                               "vector")})
                    j += 1
            i = max(j, i + 2)
            continue
        i += 1
    return vectors, refusals


def vectors_from_named_standards(text: str,
                                 table_dir: Optional[Path] = None
                                 ) -> Tuple[List[dict], List[str]]:
    """`(vectors, named)` for every public standard the design's input NAMES.

    Gated twice: the designator must be named, AND the table's algorithm token
    must occur in the design's own input."""
    named = standard_designators(text)
    algos = set(algorithm_tokens(text))
    tables = load_standard_tables(table_dir)
    out: List[dict] = []
    for std in named:
        doc = tables.get(std.upper())
        if not doc or doc.get("algorithm") not in algos:
            continue
        for v in doc.get("vectors") or []:
            case = dict(v)
            case.update({"kind": KIND, "algorithm": doc["algorithm"],
                         "source": "named_public_standard", "evidence": std})
            if not validate(case):
                out.append(case)
    return out, named


def resolve_transport(l9: Optional[dict], l3: Optional[dict]) -> dict:
    """HOW a vector is driven, taken from the design's OWN L9/L3 — never
    assumed. A design that states no interface gets `undeclared`, and the
    producer refuses to invent one."""
    l9 = l9 if isinstance(l9, dict) else {}
    l3 = l3 if isinstance(l3, dict) else {}
    iface = str(l9.get("interface_type") or "").strip()
    opcodes = [o for o in (l3.get("opcodes") or []) if isinstance(o, dict)]
    if iface:
        return {"kind": iface,
                "evidence": "L9_INTEGRATION_SPEC.interface_type",
                "opcode_count": len(opcodes)}
    if opcodes:
        return {"kind": "command_protocol",
                "evidence": "L3_CMD_PROTOCOL.opcodes",
                "opcode_count": len(opcodes)}
    return {"kind": "undeclared",
            "evidence": "neither L9.interface_type nor L3.opcodes is stated"}


def extract(extracted: Dict[str, str], l9: Optional[dict] = None,
            l3: Optional[dict] = None,
            table_dir: Optional[Path] = None) -> Dict[str, Any]:
    """The Phase-1 entry point. Returns the census, always — including the
    zero case, so "no declared vector oracle" is a stated answer."""
    corpus = "\n".join(str(t or "") for t in (extracted or {}).values())
    algos = algorithm_tokens(corpus)
    algo = algos[0] if algos else None
    doc_vectors: List[dict] = []
    refusals: List[dict] = []
    for fname, text in sorted((extracted or {}).items()):
        v, r = vectors_from_document(fname, text, algo)
        doc_vectors.extend(v)
        refusals.extend(r)
    std_vectors, named = vectors_from_named_standards(corpus, table_dir)
    transport = resolve_transport(l9, l3)
    seen: set = set()
    vectors: List[dict] = []
    for c in doc_vectors + std_vectors:
        if c["name"] in seen:
            continue
        seen.add(c["name"])
        c["transport"] = transport
        vectors.append(c)
    return {
        "vectors": vectors,
        "standards_named_by_the_input": named,
        "algorithms_named_by_the_input": algos,
        "rows_refused": refusals,
        "transport": transport,
    }
