#!/usr/bin/env python3
"""Source-bound contracts for bounded RTL repair.

The contracts in this module are deliberately narrow.  The preservation
contract proves that a declared executable fragment from the supplied source is
still present, or that its complete source span is inside an AI-authorized edit
region.  The elaboration contract runs each *declared* public configuration
through the native standalone compiler and records the exact invocation.  The
structural contract replays a declared, source-bound Yosys RTLIL observation;
it never treats functional equivalence or an author's assertion as structure.

None of these contracts infers an author's intent, treats a filename as evidence, or
claims semantic equivalence.  A malformed/incomplete declaration is a refusal;
an executable candidate that the native compiler rejects is a measured FAIL.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
import os
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCHEMA_PRESERVATION = "vibeic.rtl_preservation_declaration.v1"
SCHEMA_MATRIX = "vibeic.public_elaboration_matrix.v1"
SCHEMA_STRUCTURAL = "vibeic.native_structural_contract.v1"
STRUCTURAL_ABSTRACTION = "RTLIL_AFTER_PROC_OPT"

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.$'()+*/%\-\s]+$")
_LINE_COMMENT = re.compile(r"//[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_STRING = re.compile(r'"(?:[^"\\\n]|\\.)*"')


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _safe_path(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value or value.startswith("/"):
        return None
    p = Path(value)
    if ".." in p.parts or "\\" in value or p.as_posix() != value:
        return None
    return value


def _strip_comments(text: str) -> str:
    return _BLOCK_COMMENT.sub(" ", _LINE_COMMENT.sub(" ", text or ""))


def _normalise_fragment(text: str) -> str:
    """Whitespace/comment-insensitive executable text; strings stay atomic."""
    clean = _strip_comments(text)
    return re.sub(r"\s+", " ", clean).strip()


def _normalised_tokens(text: str) -> List[str]:
    # Match Verilog based literals before the single-quote fallback.  Without
    # that ordering, ``1'b0`` followed by a formatted newline can consume the
    # next literal's quote and make a pure whitespace edit look like removal.
    return re.findall(
        r"\d+'[sS]?[bBoOdDhH][0-9a-fA-F_xzXZ]+|"
        r"[A-Za-z_][A-Za-z0-9_$]*|\d+(?:\.\d+)?|'[^']*'|[^\s]",
        _strip_comments(text or ""))


def _looks_incomplete(text: str) -> bool:
    clean = _strip_comments(text)
    modules = len(re.findall(r"\bmodule\b", clean))
    endmodules = len(re.findall(r"\bendmodule\b", clean))
    return modules > 0 and modules != endmodules


def _source_rows(declaration: Mapping[str, Any]) -> List[Dict[str, Any]]:
    raw = declaration.get("sources")
    if raw is None:
        raw = declaration.get("source_files")
    rows: List[Dict[str, Any]] = []
    if isinstance(raw, Mapping):
        for path, row in raw.items():
            if isinstance(row, Mapping):
                rows.append({"path": path, **dict(row)})
            elif isinstance(row, str):
                rows.append({"path": path, "source_sha256": row})
    elif isinstance(raw, list):
        rows = [dict(row) for row in raw if isinstance(row, Mapping)]
    return rows


def _hash_field(row: Mapping[str, Any]) -> Optional[str]:
    for key in ("source_sha256", "sha256", "original_sha256"):
        value = row.get(key)
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
            return value
    return None


def _regions(row: Mapping[str, Any], text: str) -> Tuple[List[Tuple[int, int]], List[str]]:
    raw = row.get("authorized_edit_regions")
    if raw is None:
        raw = row.get("authorized_regions")
    errors: List[str] = []
    if raw is None:
        return [], ["authorized_edit_regions is missing"]
    if not isinstance(raw, list):
        return [], ["authorized_edit_regions must be a list"]
    lines = text.splitlines(keepends=True)
    starts = []
    cursor = 0
    for line in lines:
        starts.append(cursor)
        cursor += len(line)
    starts.append(cursor)
    out: List[Tuple[int, int]] = []
    for index, region in enumerate(raw):
        if not isinstance(region, Mapping):
            errors.append(f"authorized region {index} is not an object")
            continue
        if isinstance(region.get("start"), int) and isinstance(region.get("end"), int):
            start, end = int(region["start"]), int(region["end"])
        elif isinstance(region.get("start_line"), int) and isinstance(region.get("end_line"), int):
            start_line, end_line = int(region["start_line"]), int(region["end_line"])
            if start_line < 1 or end_line < start_line or end_line >= len(starts):
                errors.append(f"authorized region {index} has invalid line bounds")
                continue
            start, end = starts[start_line - 1], starts[end_line]
        else:
            errors.append(f"authorized region {index} needs start/end or start_line/end_line")
            continue
        if start < 0 or end < start or end > len(text):
            errors.append(f"authorized region {index} is outside the original source")
            continue
        out.append((start, end))
    return out, errors


def _raw_fragment_span(text: str, quote: str, hint: Optional[Mapping[str, Any]] = None) -> Optional[Tuple[int, int]]:
    exact = [m.span() for m in re.finditer(re.escape(quote), text)]
    if len(exact) == 1:
        return exact[0]
    return None


def _fragment_match(candidate: str, quote: str, renames: Mapping[str, Any]) -> bool:
    wanted = _normalised_tokens(quote)
    if not wanted:
        return False
    mapping = {str(k): str(v) for k, v in renames.items()}
    wanted = [mapping.get(token, token) for token in wanted]
    got = _normalised_tokens(candidate)
    if len(wanted) > len(got):
        return False
    for i in range(len(got) - len(wanted) + 1):
        if got[i:i + len(wanted)] == wanted:
            return True
    return False


def _inside_any(span: Tuple[int, int], regions: Iterable[Tuple[int, int]]) -> bool:
    return any(start <= span[0] and span[1] <= end for start, end in regions)


def validate_preservation_declaration(
    original: Mapping[str, str],
    emitted: Mapping[str, str],
    declaration: Any,
    *,
    require: bool = True,
) -> Dict[str, Any]:
    """Validate a source-bound preserved-fragment declaration.

    ``original`` and ``emitted`` are the fresh bytes used by the consumer.  The
    old ``check_sets`` presence detector remains independent and is not widened
    by this function.
    """
    report: Dict[str, Any] = {"schema": SCHEMA_PRESERVATION, "verdict": "PASS",
                              "findings": [], "sources": []}
    def refuse(message: str, code: str = "DECLARATION_REFUSED") -> None:
        report["verdict"] = "REFUSED"
        report["findings"].append({"code": code, "message": message})

    if declaration is None:
        if require:
            refuse("validate_preservation_declaration.declaration argument is missing while require=True; no declaration fields read", "DECLARATION_MISSING")
        else:
            report["verdict"] = "NOT_MEASURED"
        return report
    if not isinstance(declaration, Mapping):
        refuse("preservation declaration must be a JSON object")
        return report
    if declaration.get("schema") != SCHEMA_PRESERVATION:
        refuse("unsupported or missing preservation declaration schema", "SCHEMA_UNSUPPORTED")
        return report
    rows = _source_rows(declaration)
    if not rows:
        refuse("preservation declaration has no source rows", "DECLARATION_INCOMPLETE")
        return report
    for index, row in enumerate(rows):
        path = _safe_path(row.get("path"))
        if path is None:
            refuse(f"source row {index} has an unsafe or missing path", "SOURCE_PATH_INVALID")
            continue
        source = original.get(path)
        if source is None:
            # A basename match is useful for a normal one-file repair while
            # still refusing an ambiguous source set.
            source = None
        if source is None:
            refuse(f"declared original source {path!r} is absent", "SOURCE_MISSING")
            continue
        expected = _hash_field(row)
        if expected is None:
            refuse(f"source {path!r} has no valid original source hash", "SOURCE_HASH_MISSING")
            continue
        actual = sha256_text(source)
        source_report: Dict[str, Any] = {"path": path, "source_sha256": actual,
                                         "fragments": []}
        report["sources"].append(source_report)
        if actual != expected:
            refuse(f"source {path!r} hash mismatch: declaration={expected}, fresh={actual}",
                   "SOURCE_HASH_MISMATCH")
            continue
        if _looks_incomplete(source):
            refuse(f"source {path!r} is incomplete; executable preservation is unsupported",
                   "SOURCE_INCOMPLETE")
            continue
        regions, region_errors = _regions(row, source)
        for error in region_errors:
            refuse(f"source {path!r}: {error}", "DECLARATION_INCOMPLETE")
        candidate = emitted.get(path)
        if candidate is None:
            candidate = None
        if candidate is None:
            refuse(f"candidate source {path!r} is absent", "CANDIDATE_MISSING")
            continue
        candidate_expected = row.get("candidate_sha256", declaration.get("candidate_sha256"))
        if not isinstance(candidate_expected, str) or not re.fullmatch(r"[0-9a-f]{64}", candidate_expected):
            refuse(f"source {path!r} lacks an immutable candidate hash", "CANDIDATE_HASH_MISSING")
        elif sha256_text(candidate) != candidate_expected:
            refuse(f"candidate source {path!r} is stale", "CANDIDATE_HASH_MISMATCH")
        fragments = row.get("preserved_executable_fragments")
        if fragments is None:
            fragments = row.get("preserved_fragments")
        if not isinstance(fragments, list) or not fragments:
            refuse(f"source {path!r} has no preserved executable fragments",
                   "DECLARATION_INCOMPLETE")
            continue
        spans_seen = set()
        for fidx, fragment in enumerate(fragments):
            if not isinstance(fragment, Mapping):
                refuse(f"source {path!r} fragment {fidx} is not an object", "FRAGMENT_UNSUPPORTED")
                continue
            kind = fragment.get("kind", "text")
            if kind not in ("text", "executable"):
                refuse(f"source {path!r} fragment {fidx} uses unsupported kind {kind!r}",
                       "FRAGMENT_UNSUPPORTED")
                continue
            quote = fragment.get("quote", fragment.get("text"))
            if not isinstance(quote, str) or not _normalise_fragment(quote):
                refuse(f"source {path!r} fragment {fidx} has no executable quote",
                       "FRAGMENT_UNSUPPORTED")
                continue
            if fragment.get("sha256") is not None and fragment.get("sha256") != sha256_text(quote):
                refuse(f"source {path!r} fragment {fidx} quote hash mismatch", "FRAGMENT_HASH_MISMATCH")
                continue
            span = _raw_fragment_span(source, quote, fragment)
            if span is None:
                refuse(f"source {path!r} fragment {fidx} is ambiguous or not present in the original",
                       "FRAGMENT_UNSUPPORTED")
                continue
            # An explicit line/character span must actually contain the quote;
            # this prevents a declaration from authorizing an unrelated region.
            bounded = source[span[0]:span[1]]
            if _normalise_fragment(quote) not in _normalise_fragment(bounded):
                refuse(f"source {path!r} fragment {fidx} span does not contain its quote",
                       "FRAGMENT_UNSUPPORTED")
                continue
            renames = fragment.get("rename_bindings", fragment.get("renames", {}))
            if renames is None:
                renames = {}
            if not isinstance(renames, Mapping):
                refuse(f"source {path!r} fragment {fidx} renames are not an object",
                       "FRAGMENT_UNSUPPORTED")
                continue
            if any(not _IDENT.fullmatch(str(k)) or not _IDENT.fullmatch(str(v))
                   for k, v in renames.items()):
                refuse(f"source {path!r} fragment {fidx} has non-identifier rename bindings", "RENAME_UNSAFE")
                continue
            if span in spans_seen:
                refuse(f"source {path!r} reuses a preserved source span", "FRAGMENT_DUPLICATE")
                continue
            spans_seen.add(span)
            # A preserved executable fragment must remain at its bound source
            # span.  Searching the whole candidate would accept moved or
            # duplicated logic and is not source-preservation evidence.
            candidate_span = candidate[span[0]:span[1]] if span[1] <= len(candidate) else ""
            found = _fragment_match(candidate_span, quote, renames)
            if not found:
                # Permit whitespace-only formatting and identifier renames,
                # while retaining the source token position.  This rejects a
                # moved fragment even when its text still occurs once.
                source_tokens = _normalised_tokens(source)
                candidate_tokens = _normalised_tokens(candidate)
                q_tokens = _normalised_tokens(quote)
                mapped = [str(renames.get(t, t)) for t in q_tokens]
                try:
                    source_at = next(i for i in range(len(source_tokens) - len(q_tokens) + 1)
                                     if source_tokens[i:i + len(q_tokens)] == q_tokens)
                    candidate_at = next(i for i in range(len(candidate_tokens) - len(mapped) + 1)
                                       if candidate_tokens[i:i + len(mapped)] == mapped)
                    found = source_at == candidate_at
                except StopIteration:
                    found = False
            if found and candidate_span.count(quote) > 1:
                refuse(f"source {path!r} fragment {fidx} is duplicated", "FRAGMENT_DUPLICATE")
            if renames:
                vals = [str(v) for v in renames.values()]
                if len(vals) != len(set(vals)):
                    refuse(f"source {path!r} fragment {fidx} rename map is non-injective", "RENAME_NONINJECTIVE")
            status = "PRESERVED" if found else "REMOVED"
            row_out = {"id": fragment.get("id", fragment.get("name", str(fidx))),
                       "status": status, "source_span": [span[0], span[1]]}
            source_report["fragments"].append(row_out)
            if not found and not _inside_any(span, regions):
                report["verdict"] = "FAIL"
                report["findings"].append({
                    "code": "UNAUTHORIZED_FRAGMENT_REMOVAL",
                    "message": (f"candidate removed executable fragment {row_out['id']!r} "
                                f"from {path!r} outside an authorized edit region"),
                    "path": path,
                })
    if report["verdict"] == "PASS" and any(
            item.get("code", "").startswith("DECLARATION") or
            item.get("code", "").endswith("MISSING") or
            item.get("code", "").endswith("INVALID") or
            item.get("code", "").endswith("UNSUPPORTED") or
            item.get("code", "").endswith("MISMATCH")
            for item in report["findings"]):
        report["verdict"] = "REFUSED"
    return report


def _matrix_rows(declaration: Mapping[str, Any]) -> List[Dict[str, Any]]:
    raw = declaration.get("configurations", declaration.get("matrix"))
    if isinstance(raw, Mapping):
        return [{"name": key, **(dict(value) if isinstance(value, Mapping) else {})}
                for key, value in raw.items()]
    return [dict(row) for row in raw] if isinstance(raw, list) and all(isinstance(row, Mapping) for row in raw) else []


def _names(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out: List[str] = []
        for item in value:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, Mapping) and isinstance(item.get("name"), str):
                out.append(item["name"])
        return out
    if isinstance(value, Mapping):
        return [str(k) for k in value]
    return []


def _macro_names(config: Mapping[str, Any]) -> List[str]:
    value = config.get("defines", config.get("macros", []))
    if isinstance(value, Mapping):
        return [str(k) for k in value]
    return _names(value)


def _macro_flags(config: Mapping[str, Any], bindings: Mapping[str, Any]) -> List[str]:
    value = config.get("defines", config.get("macros", []))
    if not isinstance(value, Mapping):
        return [f"-D{bindings.get(name, name)}" for name in _names(value)]
    flags = []
    for name, setting in value.items():
        bound = bindings.get(str(name), name)
        flags.append(f"-D{bound}" if setting in (None, True, "") else f"-D{bound}={setting}")
    return flags


def _parameter_values(config: Mapping[str, Any]) -> Dict[str, Any]:
    value = config.get("parameters", config.get("params", {}))
    if not isinstance(value, Mapping):
        return {}
    return {str(k): v for k, v in value.items()}


def _quote_rows(declaration: Mapping[str, Any]) -> List[Tuple[str, Mapping[str, Any]]]:
    raw = declaration.get("source_quotes", declaration.get("quotes", []))
    if isinstance(raw, str):
        return [(raw, {})]
    if not isinstance(raw, list):
        return []
    out: List[Tuple[str, Mapping[str, Any]]] = []
    for item in raw:
        if isinstance(item, str):
            out.append((item, {}))
        elif isinstance(item, Mapping) and isinstance(item.get("quote", item.get("text")), str):
            out.append((item.get("quote", item.get("text")), item))
    return out


def _quote_texts(declaration: Mapping[str, Any]) -> List[str]:
    return [text for text, _metadata in _quote_rows(declaration)]


def validate_matrix_declaration(
    declaration: Any,
    *,
    original_source: Optional[Any],
    candidate_source: str,
    candidate_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {"schema": SCHEMA_MATRIX, "verdict": "PASS",
                              "configurations": [], "findings": []}
    def refuse(message: str, code: str = "MATRIX_REFUSED") -> None:
        report["verdict"] = "REFUSED"
        report["findings"].append({"code": code, "message": message})

    if not isinstance(declaration, Mapping) or declaration.get("schema") != SCHEMA_MATRIX:
        refuse("unsupported or missing public elaboration matrix schema", "SCHEMA_UNSUPPORTED")
        return report
    if original_source is None:
        refuse("source-bound matrix has no fresh original source bytes", "SOURCE_NOT_MEASURED")
        return report
    source_text = ("\n".join(original_source[key] for key in sorted(original_source))
                   if isinstance(original_source, Mapping) else original_source)
    if isinstance(declaration.get("source_path"), str) and isinstance(original_source, Mapping):
        if declaration["source_path"] not in original_source:
            refuse("declared source_path is absent from the bound source map", "SOURCE_PATH_INVALID")
    if isinstance(declaration.get("source_path"), str) and not _safe_path(declaration["source_path"]):
        refuse("declared source_path is unsafe", "SOURCE_PATH_INVALID")
    expected_source = declaration.get("source_sha256", declaration.get("original_sha256"))
    expected_hashes = ([expected_source] if isinstance(expected_source, str)
                       else expected_source if isinstance(expected_source, list) else [])
    if not expected_hashes or any(not isinstance(item, str) or
                                  not re.fullmatch(r"[0-9a-f]{64}", item)
                                  for item in expected_hashes):
        refuse("matrix lacks a valid original source hash", "SOURCE_HASH_MISSING")
    elif isinstance(original_source, Mapping):
        actual_hashes = sorted(sha256_text(original_source[key]) for key in sorted(original_source))
        if sorted(expected_hashes) != actual_hashes:
            refuse("matrix original source hashes do not match fresh source bytes", "SOURCE_HASH_MISMATCH")
    elif source_text is None or len(expected_hashes) != 1 or sha256_text(source_text) != expected_hashes[0]:
        refuse("matrix original source hash does not match fresh source bytes", "SOURCE_HASH_MISMATCH")
    actual_candidate = candidate_sha256 or sha256_text(candidate_source)
    expected_candidate = declaration.get("candidate_sha256")
    if not isinstance(expected_candidate, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_candidate):
        refuse("matrix declaration.candidate_sha256 must be a 64-character lowercase hex SHA256", "CANDIDATE_HASH_MISSING")
    elif actual_candidate != expected_candidate:
        refuse("matrix candidate hash is stale", "CANDIDATE_HASH_MISMATCH")
    top = declaration.get("top", declaration.get("top_module"))
    if not isinstance(top, str) or not _IDENT.fullmatch(top):
        refuse("matrix declaration.top or declaration.top_module must name a legal top module", "TOP_MISSING")
    supported_macros = set(_names(declaration.get("supported_macros", declaration.get("macros", []))))
    supported_params = set(_names(declaration.get("supported_parameters", declaration.get("parameters", []))))
    macro_bindings = declaration.get("macro_bindings", {})
    parameter_bindings = declaration.get("parameter_bindings", {})
    if not isinstance(macro_bindings, Mapping):
        refuse("macro_bindings must be an object", "MAPPING_UNSUPPORTED")
        macro_bindings = {}
    if not isinstance(parameter_bindings, Mapping):
        refuse("parameter_bindings must be an object", "MAPPING_UNSUPPORTED")
        parameter_bindings = {}
    if len({str(v) for v in macro_bindings.values()}) != len(macro_bindings):
        refuse("macro bindings must be injective", "MAPPING_NONINJECTIVE")
    for source_name, candidate_name in list(macro_bindings.items()) + list(parameter_bindings.items()):
        if not _IDENT.fullmatch(str(source_name)) or not _IDENT.fullmatch(str(candidate_name)):
            refuse("a source-to-candidate public binding is not a legal identifier",
                   "MAPPING_UNSUPPORTED")
    if any(not _IDENT.fullmatch(name) for name in supported_macros | supported_params):
        refuse("matrix contains an unsupported macro or parameter name", "MAPPING_UNSUPPORTED")
    for quote, quote_meta in _quote_rows(declaration):
        if not _normalise_fragment(quote):
            refuse("matrix contains an empty source quote", "QUOTE_UNSUPPORTED")
            continue
        quote_hash = quote_meta.get("source_sha256")
        if quote_hash is not None and quote_hash not in expected_hashes:
            refuse("a source quote is bound to a different source hash", "QUOTE_HASH_MISMATCH")
        if _normalise_fragment(quote) not in _normalise_fragment(source_text or ""):
            refuse("a declared source quote is absent from the original source", "QUOTE_UNSUPPORTED")
        rename_map = {str(k): str(v) for k, v in macro_bindings.items()}
        rename_map.update({str(k): str(v) for k, v in parameter_bindings.items()})
        if not _fragment_match(candidate_source, quote, rename_map):
            report["verdict"] = "FAIL"
            report["findings"].append({"code": "SUPPORTED_BRANCH_REMOVED",
                                       "message": "candidate removed a source-declared public branch or parameter quote"})
    for source_name in supported_macros:
        candidate_name = str(macro_bindings.get(source_name, source_name))
        if not re.search(rf"`(?:ifdef|ifndef|if\s+defined)\s*\(?\s*{re.escape(source_name)}\b",
                         source_text or ""):
            refuse(f"public macro {source_name!r} is not declared by the original source",
                   "MAPPING_UNSUPPORTED")
        if not re.search(rf"`(?:ifdef|ifndef|if\s+defined)\s*\(?\s*{re.escape(candidate_name)}\b",
                         candidate_source):
            report["verdict"] = "FAIL"
            report["findings"].append({"code": "SUPPORTED_BRANCH_REMOVED",
                                       "message": f"candidate has no public macro branch for {candidate_name!r}"})
    for source_name in supported_params:
        candidate_name = str(parameter_bindings.get(source_name, source_name))
        if not re.search(rf"\b{re.escape(source_name)}\b", source_text or ""):
            refuse(f"public parameter {source_name!r} is not declared by the original source",
                   "MAPPING_UNSUPPORTED")
        if not re.search(rf"\b{re.escape(candidate_name)}\b", candidate_source):
            report["verdict"] = "FAIL"
            report["findings"].append({"code": "SUPPORTED_PARAMETER_REMOVED",
                                       "message": f"candidate has no public parameter {candidate_name!r}"})
    rows = _matrix_rows(declaration)
    if not rows:
        refuse("public elaboration matrix has no configurations", "MATRIX_INCOMPLETE")
        return report
    if not any(not _macro_names(row) and not _parameter_values(row) for row in rows):
        refuse("public elaboration matrix must include a default configuration", "MATRIX_INCOMPLETE")
    seen_names: set[str] = set()
    macro_presence: Dict[str, set[bool]] = {name: set() for name in supported_macros}
    param_seen: set[str] = set()
    for index, row in enumerate(rows):
        name = row.get("name", row.get("id"))
        if not isinstance(name, str) or not name or name in seen_names:
            refuse(f"configuration {index} has a missing or duplicate name", "MATRIX_INCOMPLETE")
            continue
        seen_names.add(name)
        macros = _macro_names(row)
        if any(not _IDENT.fullmatch(m) for m in macros) or any(m not in supported_macros for m in macros):
            refuse(f"configuration {name!r} uses an unsupported macro mapping", "MAPPING_UNSUPPORTED")
        raw_macros = row.get("defines", row.get("macros", []))
        if isinstance(raw_macros, Mapping):
            for value in raw_macros.values():
                if value not in (None, True, "") and (isinstance(value, bool) or
                        not isinstance(value, (str, int, float)) or
                        (isinstance(value, float) and not math.isfinite(value)) or
                        not _SAFE_VALUE.fullmatch(str(value))):
                    refuse(f"configuration {name!r} has an unsupported macro value", "MAPPING_UNSUPPORTED")
        for macro in supported_macros:
            macro_presence[macro].add(macro in macros)
        params = _parameter_values(row)
        if any(not _IDENT.fullmatch(p) or p not in supported_params for p in params):
            refuse(f"configuration {name!r} uses an unsupported parameter mapping", "MAPPING_UNSUPPORTED")
        for param, value in params.items():
            param_seen.add(param)
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                refuse(f"configuration {name!r} has an invalid value for {param!r}", "MAPPING_UNSUPPORTED")
            elif isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
                refuse(f"configuration {name!r} has a non-finite value for {param!r}", "MAPPING_UNSUPPORTED")
            elif isinstance(value, str) and (not value.strip() or not _SAFE_VALUE.fullmatch(value.strip())):
                refuse(f"configuration {name!r} has an unsafe parameter expression", "MAPPING_UNSUPPORTED")
    for macro, modes in macro_presence.items():
        if modes != {False, True}:
            refuse(f"public macro {macro!r} lacks an explicit defined and undefined configuration",
                   "MATRIX_INCOMPLETE")
    required_params = set()
    for item in declaration.get("supported_parameters", []) if isinstance(declaration.get("supported_parameters"), list) else []:
        if isinstance(item, Mapping) and item.get("required") is True and isinstance(item.get("name"), str):
            required_params.add(item["name"])
    for param in supported_params - param_seen:
        refuse(f"required public parameter {param!r} has no configuration mapping", "MATRIX_INCOMPLETE")
    if report["verdict"] == "REFUSED":
        return report
    return report


def run_elaboration_matrix(
    candidate_path: Path,
    top: str,
    declaration: Any,
    *,
    original_source: Optional[Any],
    timeout: int = 30,
) -> Dict[str, Any]:
    candidate_path = Path(candidate_path).resolve()
    candidate_source = candidate_path.read_text(errors="replace")
    report = validate_matrix_declaration(
        declaration, original_source=original_source,
        candidate_source=candidate_source, candidate_sha256=sha256_text(candidate_source))
    declared_top = declaration.get("top", declaration.get("top_module")) \
        if isinstance(declaration, Mapping) else None
    if (report["verdict"] == "PASS" and isinstance(declared_top, str)
            and declared_top != top):
        report["verdict"] = "REFUSED"
        report["findings"].append({
            "code": "TOP_MISMATCH",
            "message": f"matrix top {declared_top!r} does not match consumer top {top!r}",
        })
    if report["verdict"] == "REFUSED":
        return report
    if report["verdict"] == "FAIL":
        # A deleted supported branch is a candidate finding. Keep the declared
        # matrix rows visible, but do not pretend to have run invalid evidence.
        return report
    compiler = shutil.which("iverilog")
    if compiler is None:
        report["verdict"] = "NOT_MEASURED"
        report["findings"].append({"code": "TOOL_UNAVAILABLE", "message": "iverilog is unavailable"})
        return report
    rows = _matrix_rows(declaration)
    compiler = str(Path(compiler).resolve())
    if not (compiler.startswith("/usr/bin/") or compiler.startswith("/usr/local/bin/") or compiler.startswith("/foss/")):
        report["verdict"] = "REFUSED"
        report["findings"].append({"code": "COMPILER_IDENTITY_UNTRUSTED", "message": compiler})
        return report
    compiler_sha256 = hashlib.sha256(Path(compiler).read_bytes()).hexdigest()
    macro_bindings = declaration.get("macro_bindings", {})
    parameter_bindings = declaration.get("parameter_bindings", {})
    aggregate = "PASS"
    with tempfile.TemporaryDirectory(prefix="rtl_matrix_") as td:
        for row in rows:
            name = str(row.get("name", row.get("id")))
            params = _parameter_values(row)
            command = [compiler, "-g2012"]
            command.extend(_macro_flags(row, macro_bindings))
            for param, value in params.items():
                command.extend([f"-P{top}.{parameter_bindings.get(param, param)}={value}"])
            output = Path(td) / f"{len(report['configurations'])}.vvp"
            command.extend(["-s", top, "-o", str(output), str(candidate_path)])
            try:
                completed = subprocess.run(command, capture_output=True, text=True,
                                           timeout=timeout)
                rc = completed.returncode
                stdout, stderr = completed.stdout, completed.stderr
            except subprocess.TimeoutExpired as exc:
                if aggregate == "PASS":
                    aggregate = "NOT_MEASURED"
                report["findings"].append({"code": "TIMEOUT", "message": f"configuration {name!r} timed out"})
                report["configurations"].append({"name": name, "command": command,
                                                 "returncode": 124, "stdout": (exc.stdout or ""),
                                                 "stderr": (exc.stderr or ""), "verdict": "NOT_MEASURED",
                                                 "candidate_sha256": sha256_text(candidate_source)})
                continue
            if hashlib.sha256(candidate_path.read_bytes()).hexdigest() != sha256_text(candidate_source):
                report["verdict"] = "REFUSED"
                report["findings"].append({"code": "CANDIDATE_CHANGED_DURING_EXECUTION", "configuration": name})
                continue
            row_report = {"name": name, "command": command, "compiler": compiler,
                          "compiler_sha256": compiler_sha256, "name": name, "returncode": rc,
                          "stdout": stdout, "stderr": stderr,
                          "candidate_sha256": sha256_text(candidate_source),
                          "verdict": "PASS" if rc == 0 else "FAIL"}
            report["configurations"].append(row_report)
            if rc != 0:
                aggregate = "FAIL"
                report["findings"].append({"code": "CANDIDATE_ELABORATION_FAILED",
                                           "configuration": name,
                                           "message": (stderr or stdout or "iverilog failed").strip()[-800:]})
    if aggregate == "FAIL" or (aggregate == "NOT_MEASURED" and report["verdict"] != "FAIL"):
        report["verdict"] = aggregate
    return report


def _docker_image_id(image: str, timeout: int) -> Tuple[Optional[str], Optional[str]]:
    docker = shutil.which("docker")
    if docker is None:
        return None, "docker is unavailable"
    try:
        completed = subprocess.run(
            [docker, "image", "inspect", image, "--format", "{{.Id}}"],
            capture_output=True, text=True, timeout=min(timeout, 30))
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    image_id = completed.stdout.strip()
    if completed.returncode != 0 or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        return None, (completed.stderr or completed.stdout or
                      "docker image identity is unavailable").strip()
    return image_id, None


def run_structural_contract(
    candidate_path: Path,
    declaration: Any,
    *,
    original_source: Optional[str],
    requirement_sources: Optional[Mapping[str, str]] = None,
    timeout: int = 300,
) -> Dict[str, Any]:
    """Replay a source-bound structural observation with a fixed Yosys recipe.

    The author declares cell-type expectations, but cannot provide a Yosys
    script or synthesis mapping.  Absent structure is handled as not applicable
    by the outer consumer; ambiguous declared scope is blocking NOT_MEASURED.
    """
    report: Dict[str, Any] = {
        "schema": SCHEMA_STRUCTURAL, "verdict": "PASS",
        "abstraction": STRUCTURAL_ABSTRACTION, "findings": [],
    }

    def finish(verdict: str, code: str, message: str) -> Dict[str, Any]:
        report["verdict"] = verdict
        report["findings"].append({"code": code, "message": message})
        return report

    if not isinstance(declaration, Mapping) or declaration.get("schema") != SCHEMA_STRUCTURAL:
        return finish("REFUSED", "STRUCTURAL_SCHEMA_UNSUPPORTED",
                      "unsupported or missing native structural contract schema")
    if any(key in declaration for key in ("script", "command", "passes")):
        return finish("REFUSED", "STRUCTURAL_COMMAND_INJECTION_REFUSED",
                      "structural authors cannot provide a Yosys script, command, or pass list")
    if declaration.get("abstraction") != STRUCTURAL_ABSTRACTION:
        return finish("NOT_MEASURED", "STRUCTURAL_SCOPE_AMBIGUOUS",
                      "structural abstraction must be RTLIL_AFTER_PROC_OPT")
    if declaration.get("scope") != "top_module_cells":
        return finish("NOT_MEASURED", "STRUCTURAL_SCOPE_AMBIGUOUS",
                      "structural scope must explicitly be top_module_cells")

    source_path = _safe_path(declaration.get("source_path"))
    if source_path is None or original_source is None:
        return finish("REFUSED", "STRUCTURAL_SOURCE_MISSING",
                      "structural proof lacks its exact original source")
    if declaration.get("source_sha256") != sha256_text(original_source):
        return finish("REFUSED", "STRUCTURAL_SOURCE_HASH_MISMATCH",
                      "structural contract original source hash is stale or wrong")

    candidate_path = Path(candidate_path).resolve()
    try:
        candidate_source = candidate_path.read_text(errors="replace")
    except OSError as exc:
        return finish("REFUSED", "STRUCTURAL_CANDIDATE_MISSING", str(exc))
    candidate_hash = sha256_text(candidate_source)
    if declaration.get("candidate_sha256") != candidate_hash:
        return finish("REFUSED", "STRUCTURAL_CANDIDATE_HASH_MISMATCH",
                      "structural contract candidate hash is stale or wrong")

    requirement = declaration.get("requirement_source")
    if not isinstance(requirement, Mapping):
        return finish("NOT_MEASURED", "STRUCTURAL_REQUIREMENT_AMBIGUOUS",
                      "structural scope lacks a source-bound requirement")
    requirement_path = _safe_path(requirement.get("path"))
    requirement_text = (requirement_sources or {}).get(requirement_path or "")
    quote = requirement.get("quote")
    if (requirement_path is None or requirement_text is None
            or not isinstance(quote, str) or not quote.strip()):
        return finish("NOT_MEASURED", "STRUCTURAL_REQUIREMENT_AMBIGUOUS",
                      "structural requirement path and exact nonempty quote are required")
    if requirement.get("sha256") != sha256_text(requirement_text):
        return finish("REFUSED", "STRUCTURAL_REQUIREMENT_HASH_MISMATCH",
                      "structural requirement source hash is stale or wrong")
    if requirement.get("quote_sha256") != sha256_text(quote) or requirement_text.count(quote) != 1:
        return finish("NOT_MEASURED", "STRUCTURAL_REQUIREMENT_AMBIGUOUS",
                      "structural requirement quote is stale, absent, or ambiguous")

    top = declaration.get("top")
    if not isinstance(top, str) or not _IDENT.fullmatch(top):
        return finish("NOT_MEASURED", "STRUCTURAL_SCOPE_AMBIGUOUS",
                      "structural contract lacks one legal top module")
    expectations = declaration.get("expectations")
    if not isinstance(expectations, Mapping):
        return finish("NOT_MEASURED", "STRUCTURAL_EXPECTATION_AMBIGUOUS",
                      "structural contract lacks typed expectations")
    required = expectations.get("required_cell_types")
    forbidden = expectations.get("forbidden_cell_types")
    allow_other = expectations.get("allow_other_cell_types")
    if (not isinstance(required, Mapping) or not required
            or any(not isinstance(name, str) or not name.startswith("$")
                   or not isinstance(count, int) or isinstance(count, bool) or count < 1
                   for name, count in required.items())
            or not isinstance(forbidden, list)
            or any(not isinstance(name, str) or not name.startswith("$") for name in forbidden)
            or not isinstance(allow_other, bool)):
        return finish("NOT_MEASURED", "STRUCTURAL_EXPECTATION_AMBIGUOUS",
                      "cell expectations require positive minima, a forbidden list, and allow_other_cell_types")
    if set(required) & set(forbidden):
        return finish("REFUSED", "STRUCTURAL_EXPECTATION_CONTRADICTORY",
                      "a cell type cannot be both required and forbidden")

    backend = declaration.get("backend")
    if not isinstance(backend, Mapping) or backend.get("kind") != "docker":
        return finish("NOT_MEASURED", "STRUCTURAL_BACKEND_AMBIGUOUS",
                      "native structural proof requires a declared docker backend")
    image = backend.get("image")
    image_id = backend.get("image_id")
    if (not isinstance(image, str)
            or not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", image)
            or not isinstance(image_id, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id)):
        return finish("REFUSED", "STRUCTURAL_TOOL_IDENTITY_INVALID",
                      "backend must pin an immutable image digest and image id")
    actual_image_id, identity_error = _docker_image_id(image, timeout)
    if identity_error:
        return finish("NOT_MEASURED", "STRUCTURAL_TOOL_UNAVAILABLE", identity_error)
    if actual_image_id != image_id:
        return finish("REFUSED", "STRUCTURAL_TOOL_IDENTITY_MISMATCH",
                      f"declared image id {image_id} differs from local {actual_image_id}")

    docker = str(Path(shutil.which("docker") or "docker").resolve())
    script = (f"read_verilog -sv /work/candidate.sv; "
              f"hierarchy -check -top {top}; proc; opt; "
              "write_json /out/rtlil.json")
    with tempfile.TemporaryDirectory(prefix="rtl_structural_") as temp_dir:
        root = Path(temp_dir)
        frozen = root / "candidate.sv"
        output = root / "out"
        output.mkdir()
        frozen.write_text(candidate_source)
        command = [
            docker, "run", "--rm", "--cpus=2", "--memory=4g",
            "--pids-limit=128", "--network=none", "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "-v", f"{frozen}:/work/candidate.sv:ro",
            "-v", f"{output}:/out:rw", image,
            "--skip", "yosys", "-Q", "-p", script,
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True,
                timeout=min(max(timeout, 1), 300))
        except subprocess.TimeoutExpired as exc:
            report["execution"] = {"command": command, "returncode": 124,
                                   "stdout": exc.stdout or "", "stderr": exc.stderr or ""}
            return finish("NOT_MEASURED", "STRUCTURAL_PROOF_TIMEOUT",
                          "native Yosys structural proof timed out")
        except (OSError, subprocess.SubprocessError) as exc:
            return finish("NOT_MEASURED", "STRUCTURAL_TOOL_UNAVAILABLE", str(exc))
        report["execution"] = {
            "command": command, "returncode": completed.returncode,
            "stdout": completed.stdout, "stderr": completed.stderr,
            "script": script, "script_sha256": sha256_text(script),
            "candidate_sha256": candidate_hash, "image": image,
            "image_id": actual_image_id,
            "limits": {"cpus": 2, "memory": "4g",
                       "timeout_seconds": min(max(timeout, 1), 300),
                       "network": "none"},
        }
        if completed.returncode != 0:
            return finish(
                "NOT_MEASURED", "STRUCTURAL_PROOF_EXECUTION_UNMEASURED",
                (completed.stderr or completed.stdout or "yosys failed").strip()[-1200:])
        if sha256_text(frozen.read_text(errors="replace")) != candidate_hash:
            return finish("REFUSED", "STRUCTURAL_CANDIDATE_CHANGED_DURING_EXECUTION",
                          "frozen structural input changed during native proof")
        try:
            netlist = json.loads((output / "rtlil.json").read_text())
            cells = netlist["modules"][top].get("cells", {})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return finish("NOT_MEASURED", "STRUCTURAL_OUTPUT_INVALID", str(exc))

    counts: Dict[str, int] = {}
    for cell in cells.values():
        cell_type = cell.get("type") if isinstance(cell, Mapping) else None
        if isinstance(cell_type, str):
            counts[cell_type] = counts.get(cell_type, 0) + 1
    report["observation"] = {"top": top, "cell_type_counts": dict(sorted(counts.items()))}
    violations = []
    for cell_type, minimum in required.items():
        if counts.get(cell_type, 0) < minimum:
            violations.append(f"{cell_type} count {counts.get(cell_type, 0)} is below {minimum}")
    for cell_type in forbidden:
        if counts.get(cell_type, 0):
            violations.append(f"forbidden {cell_type} count is {counts[cell_type]}")
    if not allow_other:
        extras = sorted(set(counts) - set(required))
        if extras:
            violations.append("undeclared cell types present: " + ", ".join(extras))
    if violations:
        report["verdict"] = "FAIL"
        report["findings"].extend(
            {"code": "STRUCTURAL_CONTRACT_VIOLATION", "message": item}
            for item in violations)
    return report


def load_json(value: Any) -> Any:
    if isinstance(value, (str, Path)):
        def reject_duplicates(pairs):
            out = {}
            for key, item in pairs:
                if key in out:
                    raise ValueError(f"duplicate JSON key: {key}")
                out[key] = item
            return out
        return json.loads(
            Path(value).read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {token}")))
    return value


def validate_normal_repair_contract(
    original: Mapping[str, str],
    emitted: Mapping[str, str],
    contract: Any,
    *,
    candidate_path: Optional[Path] = None,
    original_source: Optional[str] = None,
    top: Optional[str] = None,
    requirement_sources: Optional[Mapping[str, str]] = None,
    require: bool = True,
) -> Dict[str, Any]:
    """Single blocking consumer binding declared proofs before an emit is accepted.

    Any REFUSED, FAIL, or NOT_MEASURED result is returned to the caller as a
    non-accepted completion; legacy projects may omit the contract only when
    ``require`` is false.
    """
    if contract is None:
        return {"verdict": "REFUSED" if require else "NOT_MEASURED",
                "findings": [{"code": "DECLARATION_MISSING",
                              "message": "normal repair consumer has no contract"}]}
    if not isinstance(contract, Mapping):
        return {"verdict": "REFUSED", "findings": [{"code": "DECLARATION_REFUSED",
                                                      "message": "normal repair contract is not an object"}]}
    preservation = contract.get("preservation", contract.get("preservation_declaration"))
    matrix = contract.get("elaboration_matrix", contract.get("public_elaboration_matrix"))
    structural = contract.get("structural", contract.get("native_structural_contract"))
    if preservation is None and matrix is None and structural is None:
        return {"verdict": "REFUSED", "findings": [{"code": "DECLARATION_INCOMPLETE",
                                                      "message": "normal repair contract declares no preservation, elaboration, or structural proof"}]}
    result: Dict[str, Any] = {"verdict": "PASS", "preservation": None, "elaboration_matrix": None,
                              "structural": None, "findings": []}
    preservation_required = bool(contract.get("require_preservation", preservation is not None))
    if preservation is not None or preservation_required:
        result["preservation"] = validate_preservation_declaration(
            original, emitted, preservation, require=preservation_required)
        if result["preservation"]["verdict"] != "PASS":
            result["verdict"] = result["preservation"]["verdict"]
            result["findings"].extend(result["preservation"].get("findings", []))
    if matrix is not None:
        if candidate_path is None or not top:
            result["elaboration_matrix"] = {"verdict": "REFUSED", "findings": [
                {"code": "MATRIX_INPUT_MISSING", "message": "matrix consumer lacks candidate path or top"}]}
        else:
            result["elaboration_matrix"] = run_elaboration_matrix(
                candidate_path, top, matrix, original_source=original_source)
        if result["elaboration_matrix"]["verdict"] != "PASS" and result["verdict"] == "PASS":
            result["verdict"] = result["elaboration_matrix"]["verdict"]
        result["findings"].extend(result["elaboration_matrix"].get("findings", []))
    elif require and contract.get("require_elaboration_matrix"):
        result["verdict"] = "REFUSED"
        result["findings"].append({"code": "MATRIX_MISSING", "message": "public elaboration matrix is required"})
    if structural is not None:
        if candidate_path is None:
            result["structural"] = {"verdict": "REFUSED", "findings": [{
                "code": "STRUCTURAL_INPUT_MISSING",
                "message": "structural consumer lacks an exact candidate path"}]}
        else:
            result["structural"] = run_structural_contract(
                candidate_path, structural, original_source=original_source,
                requirement_sources=requirement_sources)
        if result["structural"]["verdict"] != "PASS" and result["verdict"] == "PASS":
            result["verdict"] = result["structural"]["verdict"]
        result["findings"].extend(result["structural"].get("findings", []))
    return result
