#!/usr/bin/env python3
"""formal_harness_gen.py — Step 5 DETERMINISTIC formal-property authoring.

Wires the formal step so a BARE run (no AI) still authors every property that
can be derived safely and records the denominator it could not author. It reads
the design's OWN L3/L6/L8 declarations plus top-module interface and reset logic
(design INPUT only, §4.05) and emits a `formal_<top>.sv` harness
carrying the always-valuable, construction-safe **reset-safety** invariant:

    one cycle after the design's declared reset is asserted, every registered
    output settles to the exact value the RTL's OWN reset branch assigns it.

`formal_property_run.py` then dispatches that harness to SymbiYosys with the
in-container `abc pdr` engine (`aigsmt none` — no external SMT solver needed),
producing a REAL unbounded proof + evidence that `formal_proof_evidence_check`
consumes. This closes the Step-5 "no formal tool ran" SKIP without any AI in
the loop, for any synchronous design with a clock, a reset and a registered
output whose reset value is a literal constant.

Why this is construction-safe (can never fabricate a proof OR a false FAIL):
  * The asserted value is LIFTED VERBATIM from the design's own reset branch —
    it is definitionally the value the FF holds after reset, so a correct
    design PROVES it and never counter-examples it.
  * When the interface / reset value cannot be determined with confidence the
    generator emits no assertion and returns INCOMPLETE, naming the missing
    declaration/property and the `formal-verify` expert route. It returns
    NOT_APPLICABLE only when the design explicitly declares formal inapplicable.

chip-AGNOSTIC: the mechanism keys off GENERIC hardware conventions (a clock /
reset port, a registered output) and the design's own RTL text. There is no
vendor / SKU / IC / PDK literal anywhere — the per-design names and reset values
come from the RTL, which is design INPUT.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from _hdl_code_text import strip_hdl_comments_and_strings  # noqa: E402
try:
    import _path_layout as _pl  # noqa: E402
except Exception:  # pragma: no cover - _path_layout always present in-tree
    _pl = None


PROPERTY_CONTRACT = "property_contract.json"
AUTHORING_REQUEST = "formal_authoring_request.json"

# ── #2183 — THREE INPUT STATES THAT USED TO PRINT THE SAME SENTENCE ─────────
#
# `declaration_obligations` reported one thing — "<L> declaration is absent;
# applicability and property are unknown" — for three states that are not the
# same statement about the design:
#
#   1. the Phase-1 declaration ROOT does not exist at all, so nothing was read;
#   2. the root exists and holds an `L*.json` that could NOT be parsed or
#      opened (`json.loads` / `read_text` raised, and the exception was
#      swallowed by a bare `continue`);
#   3. the root exists but could not be LISTED — `Path.glob` answers a
#      directory it may not read with an empty iterator and no exception, so
#      every declaration inside it, individually openable by name, was counted
#      as a layer the design never declared. Its sibling, an ancestor that
#      cannot be traversed, was not silent but was not Step 5's answer either:
#      `Path.is_dir()` propagates EACCES, so the exception escaped this
#      function and the runner's blanket handler wrote one opaque
#      `authoring_program_error` row naming no root and no layer;
#   4. the root exists, every file in it was read, and the design genuinely
#      declares nothing for that layer.
#
# Only (4) is "absent". (1), (2) and (3) are "I could not read it", and
# reporting them as (4) is what left vibe-ic#2183 unable to name its own
# mechanism: the run's own `property_contract.json` said the design's L3/L6/L8
# declarations were absent while they were present and yielded four
# obligations, and the artefact carried nothing that could say WHICH root had
# been read. Every contract below now names that root, so the next reader of a
# phantom denominator can see the directory it was measured against.
#
# (3) is the state this file reproduced LAST, and it is the one that still
# printed (4)'s sentence after (1) and (2) were separated out. MEASURED
# (lane cy2183, 8HD-4, 2026-09-09) on `main` 610cae2cc2b9, against a project
# whose L3/L6/L8 are present and whose declaration root is merely not
# listable:
#
#     missing_declarations  ['L3', 'L6', 'L8']      obligations 0
#     declaration_root_present True                 unreadable_declarations []
#     row L3.declaration_missing  DECLARATION_MISSING
#         "L3 declaration is absent; applicability and property are unknown"
#
# — which is #2183's reported artefact, verbatim, produced from a root whose
# declarations are on disk and readable BY NAME. A directory this process may
# not list is not a design that declared nothing.
#
# Never greener: each state is still an UNRESOLVED row on an INCOMPLETE
# verdict, the denominator is unchanged, and an unreadable file or root adds a
# row where it used to add silence.
DECLARATION_MISSING = "DECLARATION_MISSING"
DECLARATION_ROOT_ABSENT = "DECLARATION_ROOT_ABSENT"
DECLARATION_ROOT_UNREADABLE = "DECLARATION_ROOT_UNREADABLE"
DECLARATION_UNREADABLE = "DECLARATION_UNREADABLE"

#: The layers `_read_l_docs` reads. L3/L6/L8 carry the authoring denominator;
#: L22 carries the GLOBAL applicability declaration, so an unreadable L22 is
#: also unresolved work — the design may have declared formal inapplicable and
#: nobody can tell.
DECLARATION_LAYERS = ("L3", "L6", "L8", "L22")
DENOMINATOR_LAYERS = ("L3", "L6", "L8")


def _norm_applicability(value: Any) -> Tuple[str, str]:
    """Return (status, reason) from a small, explicit declaration dialect.

    A bare false is deliberately not enough: inapplicability needs a reason a
    reviewer can inspect. Unknown/malformed values remain UNDECLARED.
    """
    reason = ""
    status = value
    if isinstance(value, dict):
        status = value.get("status", value.get("applicability", ""))
        reason = str(value.get("reason", "")).strip()
    if status is False:
        status = "NOT_APPLICABLE"
    norm = str(status or "").upper().replace("-", "_").replace(" ", "_")
    if norm in {"NOT_APPLICABLE", "INAPPLICABLE", "N_A"} and reason:
        return "NOT_APPLICABLE", reason
    if norm in {"APPLICABLE", "REQUIRED", "YES", "TRUE"}:
        return "APPLICABLE", reason
    return "UNDECLARED", reason


def _read_l_docs(project: Optional[Path]) -> Tuple[
        Dict[str, List[Tuple[Path, dict]]], Optional[Path], bool,
        List[Dict[str, str]], Optional[str]]:
    """Read the canonical Phase-1 L3/L6/L8/L22 declarations, and SAY WHAT HAPPENED.

    Returns ``(docs, root, root_present, unreadable, root_error)``:

    * ``root`` — the directory that was actually listed, or None when there is
      no project to derive one from. It is returned so every caller can put the
      path it read into the artefact it writes (#2183).
    * ``root_present`` — whether that directory was POSITIVELY established to
      be a directory. "There is no such directory" and "the directory holds no
      L3" are different findings.
    * ``unreadable`` — one row per ``L*.json`` that exists but could not be
      opened or parsed, naming the file and the error. This used to be a bare
      ``continue``: an unparseable declaration was indistinguishable from an
      undeclared one, which is the same error as reporting a failed read as an
      empty result anywhere else in this flow.
    * ``root_error`` — set when the root itself could not be READ: the listing
      raised, or ``stat`` raised something other than "no such file". The
      directory is enumerated with ``os.listdir`` rather than ``Path.glob``
      for exactly this reason — ``glob`` answers a directory it may not read
      with an empty iterator and no exception, and every caller below then
      reports declarations that are present, and individually openable by
      name, as declarations the design never made. The selection is otherwise
      byte-identical to the ``L*.json`` glob it replaces.

    A file that parses to something that is not a JSON object is NOT an
    unreadable file — it was read, and it declares nothing this schema can use.
    """
    out: Dict[str, List[Tuple[Path, dict]]] = {
        layer: [] for layer in DECLARATION_LAYERS}
    unreadable: List[Dict[str, str]] = []
    if project is None or _pl is None:
        return out, None, False, unreadable, None
    root = _pl.generated_docs_dir(project)
    try:
        is_dir = stat.S_ISDIR(os.stat(root).st_mode)
    except OSError as exc:
        # ENOENT/ENOTDIR is the honest "it is not there". Anything else is a
        # failed read, and a failed read is never an absent declaration.
        if exc.errno in (errno.ENOENT, errno.ENOTDIR):
            return out, root, False, unreadable, None
        return out, root, False, unreadable, f"{type(exc).__name__}: {exc}"
    if not is_dir:
        return out, root, False, unreadable, None
    try:
        names = sorted(os.listdir(root))
    except OSError as exc:
        return out, root, True, unreadable, f"{type(exc).__name__}: {exc}"
    for layer in out:
        for name in names:
            if not (name.startswith(layer) and name.endswith(".json")):
                continue
            path = root / name
            try:
                data = json.loads(path.read_text(errors="replace"))
            except (OSError, ValueError) as exc:
                unreadable.append({
                    "layer": layer, "path": str(path),
                    "error": f"{type(exc).__name__}: {exc}"})
                continue
            if isinstance(data, dict):
                out[layer].append((path, data))
    return out, root, True, unreadable, None


def _global_formal_applicability(
        docs: Dict[str, List[Tuple[Path, dict]]]) -> Optional[dict]:
    """A global NOT_APPLICABLE must be explicit in L22 and carry a reason."""
    for path, data in docs.get("L22", []):
        fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}
        for value in (data.get("formal_applicability"),
                      fields.get("formal_applicability")):
            status, reason = _norm_applicability(value)
            if status == "NOT_APPLICABLE":
                return {"status": status, "reason": reason,
                        "source": str(path)}
    return None


def _layer_is_not_applicable(path: Path, data: dict) -> Optional[dict]:
    status, reason = _norm_applicability(data.get("formal_applicability"))
    if status == "NOT_APPLICABLE":
        return {"status": status, "reason": reason, "source": str(path)}
    return None


def _obligation(layer: str, key: str, description: str, path: Path) -> dict:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", key).strip("_") or "item"
    return {
        "id": f"{layer}.{safe}",
        "layer": layer,
        "source": str(path),
        "description": description[:500],
        "author": "formal-verify",
        "status": "UNAUTHORED",
    }


# R-0924-2 — AN OBLIGATION WHOSE CONTENT IS A NAME, NOT A BEHAVIOUR.
#
# `resets.N.name = rst` states WHICH PORT is the reset. A name is not a
# property of any trace, so no assertion can discharge it, and demanding one
# kept Step 5 partial forever (MEASURED on spm run23: 4 of 5 obligations proved
# unbounded, the fifth `resets.0.name`). Such an obligation is discharged
# STRUCTURALLY by `formal_proof_evidence_check`: the harness must bind the
# declared port as the reset AND a PROVEN property of the same run must be
# guarded by it. It is recorded DISCHARGED_BY_BINDING with that evidence, never
# counted as a trace proof; absent / mismatched / unproven it stays outstanding.
_BINDING_ID_RE = re.compile(r"L8\.(?:[\w.-]*\.)?(resets)\.\d+\.name")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
BINDING_ROLES = {"resets": "reset"}


def _binding_of(oid: str, value: Any) -> Optional[dict]:
    """{"role", "port"} when `oid` is a name obligation and its declared
    (structured, L8-leaf) value is an identifier."""
    m = _BINDING_ID_RE.fullmatch(str(oid))
    v = value.strip() if isinstance(value, str) else ""
    if m and _IDENT_RE.fullmatch(v):
        return {"role": BINDING_ROLES[m.group(1)], "port": v}
    return None


def _value_at(doc: Any, path: str) -> Any:
    """The leaf at a dotted path (digits index lists) of a parsed document."""
    cur = doc
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def binding_obligation(row: dict, project: Optional[Path] = None) -> Optional[dict]:
    """{"role", "port"} when this obligation's content is a port NAME, else None.

    The declared value is read STRUCTURALLY — the row's own `binding` tag, else
    the L8 document's leaf at the obligation's path (its `source`, else the
    project's L8 files) — never parsed out of the description sentence. So a
    results.json written before the tag existed is judged the same way."""
    if not isinstance(row, dict):
        return None
    oid = str(row.get("id", ""))
    if _binding_of(oid, "x") is None:
        return None
    tag = row.get("binding")
    if isinstance(tag, dict) and _binding_of(oid, tag.get("port")):
        return _binding_of(oid, tag.get("port"))
    path = oid.split(".", 1)[1]
    docs: List[Any] = []
    src = Path(str(row.get("source") or ""))
    if src.name and src.is_file():
        try:
            docs.append(json.loads(src.read_text(errors="replace")))
        except (OSError, ValueError):
            pass
    if project is not None:
        docs += [d for _p, d in _read_l_docs(project)[0].get("L8", [])]
    for doc in docs:
        found = _binding_of(oid, _value_at(doc, path))
        if found:
            return found
    return None


_TIMING_KEY_RE = re.compile(
    r"reset|latency|turnaround|timeout|cycle|holdoff|pulse", re.IGNORECASE)
# A leaf VALUE that itself states sequencing (prose declarations such as
# "synchronous, active-high; internals clear the cycle after assert").
_TIMING_VALUE_RE = re.compile(
    r"cycle|edge|assert|deassert|synchron|active[- ]?(high|low)|latency|"
    r"hold|after|before|同步|非同步|週期|邊緣", re.IGNORECASE)
# L-document PROVENANCE keys: every emitted layer carries them, and none of
# them states behaviour. ROUND-3 (subservient x gf180mcuD, 2026-09-02):
# `clock_and_reset_waveform.derived_from.0`, `.derived_from.1` and
# `.extraction_strategy` were enumerated as "declared temporal behavior"
# because the CONTAINER key contains "reset" — three of seven expert
# obligations that no property can discharge, on every design that ships
# an L8, so Step 5 could never complete honestly.
_PROVENANCE_KEYS = {
    "derived_from", "extraction_strategy", "provenance", "extracted_by",
    "emitter", "generator", "schema", "schema_version", "version",
    "generated_at", "generated_by",
}
_ARTEFACT_PATH_RE = re.compile(r"^[\w./-]+\.(json|md|txt|ya?ml)$")


def _own_and_group(prefix: str) -> Tuple[str, str]:
    """(leaf key, nearest non-index ancestor key) of a dotted path."""
    parts = [s for s in prefix.split(".") if s and not s.isdigit()]
    own = parts[-1] if parts else ""
    group = parts[-2] if len(parts) > 1 else ""
    return own, group


def _timing_semantics(value: Any, prefix: str = "") -> List[Tuple[str, str]]:
    """Find cycle/reset/latency semantics that can imply temporal properties.

    Absolute MHz/ns constraints are STA obligations, not cycle-accurate FPV
    properties. We therefore select only names that state RTL sequencing.

    A leaf qualifies when its OWN key or its nearest GROUP key names
    sequencing, or when its VALUE is a sequencing statement — not merely
    because some ancestor container carries "reset" in its name. Provenance
    keys and values that are artefact paths never qualify (see the ROUND-3
    note above `_PROVENANCE_KEYS`).
    """
    out: List[Tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            k = str(key).lower()
            if k in {
                    "extraction_evidence", "evidence", "source", "source_doc",
                    "note", "description", "matched_substring"}:
                continue
            if k in _PROVENANCE_KEYS:
                continue
            p = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_timing_semantics(child, p))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            out.extend(_timing_semantics(child, f"{prefix}.{idx}"))
    else:
        text = str(value).strip()
        if not text or text.lower() in {"none", "null", "unspecified", "unknown"}:
            return out
        if _ARTEFACT_PATH_RE.match(text):
            return out
        own, group = _own_and_group(prefix)
        if (_TIMING_KEY_RE.search(own) or _TIMING_KEY_RE.search(group)
                or _TIMING_VALUE_RE.search(text)):
            out.append((prefix, text))
    return out


# ── R-0915-144 — PROGRAM RULES FOR L8 CLOCK/RESET DECLARATIONS ──────────────
#
# Program first, AI backup. An L8 clock/reset declaration is one of two kinds:
#
#   STRUCTURAL  a fact about the RTL's structure: the clock EDGE, the reset
#               port NAME, synchronous vs asynchronous. No temporal property can
#               falsify these in the cycle-based model Step 5 proves in (there
#               is no "between edges"), so they are answered by
#               `formal_structural_check` from the flow's own yosys netlist.
#   TEMPORAL    reset BEHAVIOUR: the POLARITY, and "all internal state is zero
#               one cycle after assertion". These become generated properties,
#               proved or refuted by the flow's own engine.
#
# A claim with no rule here goes to the `formal-verify` expert exactly as
# before. Prose is parsed CONSERVATIVELY: every clause must be fully consumed
# by a recognised claim, or the whole declaration stays with the expert. A
# clause the program half-understood is a clause it must not answer.
KIND_STRUCTURAL = "STRUCTURAL"
KIND_TEMPORAL = "TEMPORAL"
KIND_MIXED = "MIXED"
# R-0915-144 round 5: polarity is a STRUCTURAL netlist fact (the SRST/ARST
# polarity of every flop the reset forces), not a property over a textual
# subset of registers (review round 4, H2).
_STRUCTURAL_CLAIMS = {"clock_edge", "reset_port", "reset_sync", "reset_polarity",
                      "state_covered"}
_TEMPORAL_CLAIMS = {"reset_state_zero", "state_sync"}

_CR_PATH_RE = re.compile(
    r"(?:^|\.)(?P<group>clocks|clock_domains|resets)\.(?P<idx>\d+)\.(?P<field>[A-Za-z_]\w*)$")


def _norm_edge(text: str) -> Optional[str]:
    t = text.strip().lower().replace("-", "").replace("_", "")
    if t in {"posedge", "rising", "risingedge", "positive", "pos", "rise"}:
        return "posedge"
    if t in {"negedge", "falling", "fallingedge", "negative", "neg", "fall"}:
        return "negedge"
    return None


def _norm_sync(text: str) -> Optional[str]:
    t = text.strip().lower()
    if t in {"asynchronous", "async", "非同步", "異步"}:
        return "asynchronous"
    if t in {"synchronous", "sync", "同步"}:
        return "synchronous"
    return None


def _norm_polarity(text: str) -> Optional[str]:
    t = text.strip().lower().replace("-", "_").replace(" ", "_")
    if t in {"active_high", "high", "activehigh"}:
        return "active_high"
    if t in {"active_low", "low", "activelow"}:
        return "active_low"
    return None


_P_ASYNC = re.compile(r"非同步|異步|\basynchronous\b|\basync\b", re.I)
_P_SYNC = re.compile(r"同步|\bsynchronous\b|\bsync\b", re.I)
_P_HIGH = re.compile(r"active[\s_-]?high|高電位有效|高態有效", re.I)
_P_LOW = re.compile(r"active[\s_-]?low|低電位有效|低態有效", re.I)
# "all internal state is zero one cycle after assertion", in the two word
# orders a declaration is written in, Chinese and English.
_P_ZERO = [
    re.compile(
        r"(?:(?:reset\s*)?(?:assertion|asserted|assert)\s*)?(?:後|之後)?\s*"
        r"(?:一個|一|1)\s*(?:clock\s*)?(?:cycle|個?週期|個?周期|時脈)\s*(?:內|之內)?\s*"
        r"(?:所有|全部)\s*(?:的)?\s*(?:內部)?\s*(?:的)?\s*"
        r"(?:狀態|暫存器|registers?|state)\s*(?:都|皆|均)?\s*"
        r"(?:歸零|清零|清為\s*0|為\s*0|設為\s*0)", re.I),
    re.compile(
        r"all\s+(?:internal\s+)?(?:state|registers?|flip[\s-]?flops?|flops?)\s+"
        r"(?:is\s+|are\s+)?(?:zeroed|cleared|zero|reset\s+to\s+(?:0|zero)|"
        r"set\s+to\s+(?:0|zero)|cleared\s+to\s+(?:0|zero))\s+"
        r"(?:within\s+)?(?:one|1|a\s+single)\s+(?:clock\s+)?cycle\s+"
        r"after\s+(?:reset\s+)?(?:assertion|(?:it\s+|reset\s+)?is\s+asserted)", re.I),
    re.compile(
        r"(?:within\s+)?(?:one|1|a\s+single)\s+(?:clock\s+)?cycle\s+"
        r"after\s+(?:reset\s+)?(?:assertion|(?:it\s+|reset\s+)?is\s+asserted)"
        r"\s*,?\s*all\s+(?:internal\s+)?(?:state|registers?|flip[\s-]?flops?|flops?)\s+"
        r"(?:is\s+|are\s+)?(?:zeroed|cleared|zero|reset\s+to\s+(?:0|zero)|"
        r"set\s+to\s+(?:0|zero))", re.I),
]
# Words that carry no claim. Anything ELSE left in a clause after the
# recognised claims are removed makes the clause unrecognised. A WORD SET, not
# a regex: this is English/Chinese prose from L8, and a keyword regex over it
# reads like an HDL declaration scan to the hygiene gate.
_FILLER_WORDS = frozenset({"reset", "rst", "signal", "the", "is", "a", "an",
                           "input", "port"})
_FILLER_CJK_RE = re.compile(r"reset\s*信號|信號|的", re.I)
_FILLER_SEP_RE = re.compile(r"[()（）\[\]*`'\"\s:：]+")


def _only_filler(rest: str) -> bool:
    """True when nothing but claim-free filler is left in a clause."""
    words = _FILLER_SEP_RE.split(_FILLER_CJK_RE.sub(" ", rest))
    return all(w.lower() in _FILLER_WORDS for w in words if w)
_CLAUSE_SPLIT_RE = re.compile(r"[;；。,，\n]+")


def parse_reset_prose(text: str, reset: str, declared_polarity: Optional[str]
                      ) -> Optional[List[dict]]:
    """Every claim a reset prose declaration makes, or None when ANY clause is
    not fully understood. Pure. A None keeps the declaration with the expert."""
    claims: List[dict] = []
    polarity = declared_polarity
    zero = False
    clauses = [c for c in _CLAUSE_SPLIT_RE.split(text) if c.strip()]
    if not clauses:
        return None
    for clause in clauses:
        rest = clause
        found = False
        if _P_ASYNC.search(rest):
            claims.append({"rule": "reset_sync", "signal": reset,
                           "value": "asynchronous"})
            rest = _P_ASYNC.sub(" ", rest)
            found = True
        elif _P_SYNC.search(rest):
            claims.append({"rule": "reset_sync", "signal": reset,
                           "value": "synchronous"})
            rest = _P_SYNC.sub(" ", rest)
            found = True
        if _P_HIGH.search(rest) and not _P_LOW.search(rest):
            polarity = "active_high"
            claims.append({"rule": "reset_polarity", "signal": reset,
                           "value": "active_high"})
            rest = _P_HIGH.sub(" ", rest)
            found = True
        elif _P_LOW.search(rest) and not _P_HIGH.search(rest):
            polarity = "active_low"
            claims.append({"rule": "reset_polarity", "signal": reset,
                           "value": "active_low"})
            rest = _P_LOW.sub(" ", rest)
            found = True
        for pat in _P_ZERO:
            if pat.search(rest):
                zero = True
                rest = pat.sub(" ", rest)
                found = True
                break
        if not found or not _only_filler(rest):
            return None
    if zero:
        if polarity is None:
            # "zero after assertion" with no stated polarity names no guard.
            return None
        claims.append({"rule": "reset_state_zero", "signal": reset,
                       "value": polarity})
    # the same claim stated twice is one claim
    uniq: List[dict] = []
    for c in claims:
        if c not in uniq:
            uniq.append(c)
    return uniq


def _record_at(data: Any, key: str) -> Optional[dict]:
    """The dict holding the leaf at dotted `key` (its parent record)."""
    parts = key.split(".")[:-1]
    cur = data
    for p in parts:
        if isinstance(cur, dict):
            cur = cur.get(p)
        elif isinstance(cur, list) and p.isdigit() and int(p) < len(cur):
            cur = cur[int(p)]
        else:
            return None
    return cur if isinstance(cur, dict) else None


def _rule(claims: List[dict]) -> dict:
    kinds = {KIND_STRUCTURAL if c["rule"] in _STRUCTURAL_CLAIMS
             else KIND_TEMPORAL for c in claims}
    kind = kinds.pop() if len(kinds) == 1 else KIND_MIXED
    return {"kind": kind, "claims": claims, "ruling": "R-0915-144"}


def _l8_provenance_rule(data: dict, key: str, text: str,
                        project: Optional[Path]) -> Optional[dict]:
    """Bind an equivalent fact to its canonical claim, never to a new assertion."""
    parent, sep, tail = key.partition(".semantic_provenance.")
    if not sep:
        return None
    field = tail.split(".")[0]
    canonical = parent + "." + field
    rec = _record_at(data, canonical)
    if not rec or _value_at(data, key) != text:
        return None
    metadata = rec.get("semantic_provenance")
    provenance = metadata.get(field) if isinstance(metadata, dict) else None
    if not isinstance(provenance, dict):
        return None
    rule = l8_program_rule(data, canonical, str(rec.get(field, "")))
    if not rule:
        return None
    claim = rule["claims"][0]
    if tail == "edge.rule":
        if (provenance != {"kind": "convention", "rule": "default_positive_clock_edge"}
                or claim["rule"] != "clock_edge" or claim["value"] != "posedge"):
            return None
    elif re.fullmatch(r"(?:sync|polarity)\.basis\.\d+\.quote", tail):
        basis = _record_at(data, key)
        if (project is None or provenance.get("kind") != "explicit"
                or claim["rule"] != "reset_" + field or not basis):
            return None
        # A citation is a claim about these exact source bytes and this line.
        # Neither a matching keyword nor a hash of the quote is a source binding.
        try:
            source = (project / basis["file"]).resolve()
            source.relative_to((project / "input").resolve())
            raw = source.read_bytes()
            line = basis["line"]
            if (type(line) is not int or line < 1
                    or hashlib.sha256(raw).hexdigest() != basis.get("sha256")
                    or raw.decode("utf-8").splitlines()[line - 1] != text):
                return None
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return None
        # Only explicitly named reset declarations qualify. A foreign signal
        # elsewhere in a paragraph cannot lend this reset its semantics.
        plain = text.replace("`", "").replace("**", "").strip()
        signal = re.escape(claim["signal"])
        subject = re.match(r"(?:-\s+" + signal + r"\s+|\|\s*" + signal
                           + r"\s*\|\s*1-bit\s*\|\s*input\s*\|\s*)(.*)", plain)
        if not subject:
            return None
        description = subject.group(1)
        if plain.startswith("|"):
            if not description.endswith("|"):
                return None
            description = description[:-1].strip()
        # Source authentication does not establish what a sentence means.
        # Consume the complete clause using the existing conservative parser;
        # negation, conditions and foreign redirection must stay unresolved.
        claims = parse_reset_prose(description, claim["signal"],
                                   _norm_polarity(str(rec.get("polarity", ""))))
        expected = [{"rule": "reset_sync", "signal": claim["signal"],
                     "value": _norm_sync(str(rec.get("sync", "")))},
                    {"rule": "reset_polarity", "signal": claim["signal"],
                     "value": _norm_polarity(str(rec.get("polarity", "")))}]
        if (not claims or any(c not in claims for c in expected)
                or any(c not in expected for c in claims)):
            return None
    else:
        return None
    return dict(rule, equivalent_to="L8." + canonical,
                semantic_provenance=provenance)


def l8_program_rule(data: dict, key: str, text: str,
                    project: Optional[Path] = None) -> Optional[dict]:
    """The program rule that answers L8 declaration `key`=`text`, or None."""
    if ".semantic_provenance." in key:
        return _l8_provenance_rule(data, key, text, project)
    m = _CR_PATH_RE.search(key)
    if not m:
        return None
    rec = _record_at(data, key)
    if rec is None:
        return None
    group, field_ = m.group("group"), m.group("field")
    name = str(rec.get("name") or "").strip()
    if not re.fullmatch(r"[A-Za-z_]\w*", name):
        return None
    if group in {"clocks", "clock_domains"}:
        if rec.get("source_pin", name) != name:
            return None
        if field_ == "edge":
            edge = _norm_edge(text)
            if edge:
                return _rule([{"rule": "clock_edge", "signal": name,
                               "value": edge}])
        return None
    # resets
    if field_ == "name":
        return _rule([{"rule": "reset_port", "signal": name, "value": ""}])
    if field_ == "sync":
        sync = _norm_sync(text)
        return _rule([{"rule": "reset_sync", "signal": name,
                       "value": sync}]) if sync else None
    if field_ == "polarity":
        pol = _norm_polarity(text)
        return _rule([{"rule": "reset_polarity", "signal": name,
                       "value": pol}]) if pol else None
    declared_pol = _norm_polarity(str(rec.get("polarity") or ""))
    claims = parse_reset_prose(text, name, declared_pol)
    return _rule(claims) if claims else None


def declaration_obligations(project: Optional[Path]) -> dict:
    """Build the exact L3/L6/L8 formal-authoring denominator.

    This function does not translate prose into SVA. It only identifies the
    declarations whose semantic mapping needs an expert when no safe generic
    mapping exists; guessing signal names would be the false-proof path.
    """
    if project is None:
        # Pure/standalone authoring has no L-document denominator to assess.
        # The canonical in-flow caller always supplies a project.
        return {"applicability": "APPLICABLE", "obligations": [],
                "missing_declarations": [], "layer_not_applicable": [],
                "declaration_root": None, "declaration_root_present": False,
                "declaration_root_error": None,
                "unreadable_declarations": []}
    docs, root, root_present, unreadable, root_error = _read_l_docs(project)
    read_state = {
        "declaration_root": str(root) if root is not None else None,
        "declaration_root_present": root_present,
        # #2183 — the state that used to be indistinguishable from "the design
        # declares nothing": the root is there and this process could not read
        # it. Never None-and-silent; a reader can tell the two apart.
        "declaration_root_error": root_error,
        "unreadable_declarations": unreadable,
    }
    explicit_na = _global_formal_applicability(docs)
    if explicit_na:
        return {"applicability": "NOT_APPLICABLE",
                "declaration": explicit_na, "obligations": [],
                "missing_declarations": [], "layer_not_applicable": [],
                **read_state}

    obligations: List[dict] = []
    # #2183: a layer whose file could not be READ is not a layer the design
    # left undeclared. It gets its own row below and must not also be counted
    # here, or one unreadable file would be reported as an absent declaration.
    unreadable_layers = {row["layer"] for row in unreadable}
    missing = [layer for layer in DENOMINATOR_LAYERS
               if not docs[layer] and layer not in unreadable_layers]
    layer_na: List[dict] = []
    for layer in DENOMINATOR_LAYERS:
        for path, data in docs[layer]:
            na = _layer_is_not_applicable(path, data)
            if na:
                layer_na.append(dict(na, layer=layer))
                continue
            if layer == "L3":
                if data.get("no_opcodes_in_input") is False:
                    for idx, item in enumerate(data.get("opcodes") or []):
                        if not isinstance(item, dict):
                            continue
                        name = str(item.get("name") or item.get("hex") or idx)
                        desc = (f"command {name}: "
                                f"{item.get('purpose', 'declared command behavior')}")
                        obligations.append(_obligation(
                            "L3", f"opcode.{name}", desc, path))
                if (data.get("crc_parameters")
                        and data.get("no_crc_parameters_in_input") is False):
                    obligations.append(_obligation(
                        "L3", "crc_parameters",
                        "declared CRC acceptance/rejection behavior", path))
                for idx, rule in enumerate(data.get("reject_rules") or []):
                    obligations.append(_obligation(
                        "L3", f"reject_rule.{idx}", str(rule), path))
            elif layer == "L6":
                if data.get("no_fsm_in_input") is False:
                    for idx, state in enumerate(data.get("fsm_states") or []):
                        if not isinstance(state, dict):
                            continue
                        name = str(state.get("name") or idx)
                        detail = state.get("transitions") or state.get("actions") or []
                        obligations.append(_obligation(
                            "L6", f"fsm_state.{name}",
                            f"state {name}: {detail}", path))
                for idx, rule in enumerate(data.get("reject_rules") or []):
                    obligations.append(_obligation(
                        "L6", f"reject_rule.{idx}", str(rule), path))
            else:
                for key, text in _timing_semantics(data):
                    row = _obligation(
                        "L8", key, f"declared temporal behavior {key}={text}", path)
                    binding = _binding_of(row["id"], text)
                    rule = l8_program_rule(data, key, text, project)
                    if rule is not None:
                        # R-0915-144: a declaration a PROGRAM rule covers
                        # carries that rule, so the program answers it and the
                        # expert is asked only for what no rule covers.
                        row["program_rule"] = rule
                        row["kind"] = rule["kind"]
                    if binding:
                        # R-0924-2: a NAME obligation stays kind `binding`
                        # (the landed contract); its structural rule above
                        # still routes it to the program.
                        row["kind"] = "binding"
                        row["binding"] = binding
                    obligations.append(row)

    # Stable IDs are part of the handoff contract. Multiple L8 files can carry
    # the same declaration; de-duplicate rather than inflate the denominator.
    uniq: Dict[str, dict] = {}
    for row in obligations:
        uniq.setdefault(row["id"], row)
    return {
        "applicability": "APPLICABLE",
        "obligations": list(uniq.values()),
        "missing_declarations": missing,
        "layer_not_applicable": layer_na,
        **read_state,
    }


def _authoring_request_snapshot(formal_dir: Path) -> Optional[dict]:
    """The exact active request, or its preserved bytes after floor completion."""
    active = formal_dir / AUTHORING_REQUEST
    try:
        if active.is_file():
            text = active.read_text()
            snapshot = {"text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}
        else:
            contract = json.loads((formal_dir / PROPERTY_CONTRACT).read_text())
            snapshot = contract.get("authoring_request")
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("text"), str):
            return None
        if hashlib.sha256(snapshot["text"].encode()).hexdigest() != snapshot.get("sha256"):
            return None
        request = json.loads(snapshot["text"])
        if (not isinstance(request, dict) or request.get("fallback_skill") != "formal-verify"
                or not isinstance(request.get("unresolved_obligations"), list)
                or not request["unresolved_obligations"]):
            return None
        return snapshot
    except (OSError, ValueError, AttributeError):
        return None


def _write_property_contract(project: Optional[Path], contract: dict) -> None:
    if project is None or _pl is None:
        return
    formal_dir = _pl.formal_dir(project)
    formal_dir.mkdir(parents=True, exist_ok=True)
    prior_request = _authoring_request_snapshot(formal_dir)
    unresolved = contract.get("unresolved_obligations") or []
    if unresolved:
        request = {
            "program": "formal_harness_gen",
            "verdict": "INCOMPLETE",
            "fallback_skill": "formal-verify",
            "invocation_status": "REQUIRED_NOT_INVOKED",
            "property_denominator": contract.get("property_denominator", 0),
            "authored_property_count": contract.get("authored_property_count", 0),
            "unresolved_obligations": unresolved,
            "missing_declarations": contract.get("missing_declarations", []),
            # #2183 — the hand-off names the root it measured. A request built
            # on a directory that does not exist asks an expert to author
            # properties for declarations that are not missing.
            "declaration_root": contract.get("declaration_root"),
            "declaration_root_present": contract.get(
                "declaration_root_present"),
            "declaration_root_error": contract.get("declaration_root_error"),
            "unreadable_declarations": contract.get(
                "unreadable_declarations", []),
            "reason": (
                "applicable formal obligations remain without a sound property; "
                "invoke formal-verify on these exact IDs and record each authored "
                "property in property_contract.json before rerunning Step 5"),
        }
        text = json.dumps(request, indent=2, ensure_ascii=False) + "\n"
        if prior_request is not None:
            original = json.loads(prior_request["text"])
            original_rows = {str(r.get("id")): r for r in
                             original["unresolved_obligations"] if isinstance(r, dict)}
            if (original.get("property_denominator") == request["property_denominator"]
                    and all(original.get(k) == request.get(k) for k in
                            ("missing_declarations", "declaration_root", "declaration_root_present",
                             "declaration_root_error", "unreadable_declarations"))
                    and all(str(r.get("id")) in original_rows and all(
                        original_rows[str(r.get("id"))].get(k) == r.get(k)
                        for k in ("id", "layer", "source", "description")) for r in unresolved)):
                # Partial authorship changes the open contract, not the exact
                # request the provider already answered. Keep that identity.
                text = prior_request["text"]
        (formal_dir / AUTHORING_REQUEST).write_text(text)
        prior_request = {"text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}
    if prior_request is not None:
        # The active queue may be cleared; its requested role, IDs, denominator
        # and identity remain independently checkable in the existing contract.
        contract["authoring_request"] = prior_request
    (formal_dir / PROPERTY_CONTRACT).write_text(
        json.dumps(contract, indent=2, ensure_ascii=False) + "\n")
    if not unresolved:
        stale = formal_dir / AUTHORING_REQUEST
        if stale.is_file():
            stale.unlink()


# ── comment / text hygiene ──────────────────────────────────────────────────
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def strip_comments(text: str) -> str:
    """Remove // and /* */ comments (pure). Keeps newlines so line structure
    (and the always-block sensitivity scan) stays intact."""
    text = _BLOCK_COMMENT_RE.sub(" ", text)
    text = _LINE_COMMENT_RE.sub("", text)
    return text


# ── generic hardware-convention name matchers (NOT chip literals) ───────────
# A clock / reset port is a universal RTL convention; matching the port name is
# design-independent (the actual spelling comes from the design's RTL).
_CLOCK_NAME_RE = re.compile(r"(^|_)(clk|clock|aclk|hclk|pclk|sclk|mclk)($|_|\d)",
                            re.IGNORECASE)
_RESET_NAME_RE = re.compile(
    r"(^|_)(rst|reset|resetn|rstn|nrst|nreset|arst|aresetn|por)($|_|\d|n)",
    re.IGNORECASE)
# active-low reset spellings: a trailing _n / n suffix or an `nreset`/`resetn`.
_ACTIVE_LOW_NAME_RE = re.compile(
    r"(_n$|_ni$|_n\d+$|n$|_b$)|^n(rst|reset)|reset_?n$|rst_?n$", re.IGNORECASE)


# ── module header parsing (params + ANSI ports) ─────────────────────────────
@dataclass
class Port:
    direction: str          # input / output / inout
    width: str              # e.g. "" (1-bit) or "[size-1:0]"
    name: str
    # v1.15.67 — the declared DATA TYPE, when the port carries a
    # user-defined or package-qualified one (`input alert_rx_t alert_rx_i`,
    # `input pkg::t_e sig`). "" for a plain net/variable port. Held so the
    # name can never be taken from it — see `_parse_ansi_ports`.
    data_type: str = ""


@dataclass
class ModuleIface:
    name: str
    params: List[Tuple[str, str]] = field(default_factory=list)   # (name, default)
    ports: List[Port] = field(default_factory=list)
    body: str = ""
    # v1.15.67 — the packages the module's OWN header imports
    # (`module m import p::*; #(...)`). A harness that mirrors a typed port
    # must mirror the scope the type is visible in; see `emit_harness`.
    imports: List[str] = field(default_factory=list)


def _split_top_level(text: str, sep: str = ",") -> List[str]:
    """Split on `sep` at paren/brace/bracket depth 0 (pure)."""
    out, depth, cur = [], 0, []
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


_MODULE_RE_TMPL = r"\bmodule\s+{name}\b"


def _find_module_span(text: str, name: str) -> Optional[Tuple[int, int, int]]:
    """Return (header_start, body_start, endmodule_start) for `module <name>`.
    body_start is the index just after the header's closing `);`."""
    m = re.search(_MODULE_RE_TMPL.format(name=re.escape(name)), text)
    if not m:
        return None
    start = m.start()
    # find the header's port-list close: the ')' that matches the first '(' after
    # the module name at depth 0, then the following ';'.
    i = m.end()
    # skip an optional parameter port list `#( ... )` and the main port list.
    depth = 0
    seen_paren = False
    header_end = None
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
            seen_paren = True
        elif ch == ")":
            depth -= 1
            if depth == 0 and seen_paren:
                # header ends at the next ';'
                j = text.find(";", i)
                header_end = (j + 1) if j != -1 else (i + 1)
                break
        i += 1
    if header_end is None:
        return None
    em = re.search(r"\bendmodule\b", text[header_end:])
    end = (header_end + em.start()) if em else len(text)
    return (start, header_end, end)


def _parse_params(header: str) -> List[Tuple[str, str]]:
    """Parse `#( parameter A = x, parameter B = y )` → [(A,x),(B,y)]."""
    mp = re.search(r"#\s*\((.*?)\)\s*\(", header, re.DOTALL)
    if not mp:
        return []
    inner = mp.group(1)
    out: List[Tuple[str, str]] = []
    for chunk in _split_top_level(inner):
        c = chunk.strip()
        if not c:
            continue
        # `parameter [type] NAME = VALUE`
        mm = re.search(
            r"(?:parameter|localparam)?\s*(?:\[[^\]]*\]\s*)?"
            r"(?:integer|int|logic|bit|signed|unsigned|\s)*"
            r"([A-Za-z_]\w*)\s*=\s*(.+)$", c)
        if mm:
            out.append((mm.group(1), mm.group(2).strip()))
    return out


def _parse_ansi_ports(header: str) -> List[Port]:
    """Parse the ANSI port list `( input wire [w] a, output b, ... )`."""
    # take the LAST top-level (...) group in the header (the port list).
    depth = 0
    last_open = None
    spans = []
    for idx, ch in enumerate(header):
        if ch == "(":
            if depth == 0:
                last_open = idx
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and last_open is not None:
                spans.append((last_open, idx))
    if not spans:
        return []
    open_i, close_i = spans[-1]
    inner = header[open_i + 1:close_i]
    ports: List[Port] = []
    last_dir = None
    last_width = ""
    for chunk in _split_top_level(inner):
        c = " ".join(chunk.split())
        if not c:
            continue
        md = re.match(r"^(input|output|inout)\b", c)
        if md:
            last_dir = md.group(1)
            rest = c[md.end():].strip()
            # strip net/var type keywords
            rest = re.sub(r"^(wire|reg|logic|bit|var|signed|unsigned|\s)+", "",
                          rest).strip()
            wm = re.match(r"^(\[[^\]]*\])\s*", rest)
            last_width = wm.group(1) if wm else ""
            if wm:
                rest = rest[wm.end():].strip()
            names = rest
        else:
            # continuation: same direction/width, just a name (ANSI list with
            # `input a, b` sharing the decl) — rare; keep width from previous.
            names = c
        if last_dir is None:
            continue
        for nm in _split_top_level(names):
            nm = nm.strip().rstrip(";")
            # a name may still carry its own width when list-shared
            wm2 = re.match(r"^(\[[^\]]*\])\s*(\w+)", nm)
            if wm2:
                ports.append(Port(last_dir, wm2.group(1), wm2.group(2)))
                continue
            # v1.15.67 — a port declared with a USER-DEFINED or PACKAGE-
            # QUALIFIED data type reaches here as TWO identifiers, type first:
            #     input alert_rx_t  alert_rx_i
            #     output alert_tx_t alert_tx_o
            # The net/variable keyword strip above only removes the built-in
            # keywords (wire/reg/logic/bit/var/signed/unsigned), so a
            # user-defined type survives and the old `^([A-Za-z_]\w*)` match
            # took it AS THE NAME. MEASURED on opentitan_aes: the emitted
            # harness instantiated the DUT as
            #     .alert_rx_t(alert_rx_t), .alert_tx_t(alert_tx_t)
            # — two ports the module does not have — and slang refuses it with
            # "port 'alert_rx_t' does not exist in 'prim_alert_sender'".
            #
            # In SystemVerilog a port declaration ends with its name, so when
            # the remainder is a type-then-name sequence the NAME is the LAST
            # identifier and everything before it is the type. One identifier
            # is a bare port and is unchanged.
            idents = re.findall(r"[A-Za-z_]\w*(?:\s*::\s*[A-Za-z_]\w*)*", nm)
            if idents:
                nm_name = idents[-1].strip()
                nm_type = " ".join(t.strip() for t in idents[:-1])
                ports.append(Port(last_dir, last_width, nm_name, nm_type))
    return ports


def _parse_header_imports(header: str) -> List[str]:
    """v1.15.67 — the wildcard package imports in a module HEADER.

    `module prim_alert_sender import prim_alert_pkg::*; #( ... ) ( ... );`

    The harness declares the DUT's typed ports with the DUT's own type names,
    and a type name is only visible in a scope that imports its package. The
    DUT states which packages those are, in its own header; nothing else has
    to be guessed. Deduplicated, declaration order preserved."""
    out: List[str] = []
    for m in re.finditer(r"\bimport\s+([A-Za-z_]\w*)\s*::\s*\*\s*;", header):
        pkg = m.group(1)
        if pkg not in out:
            out.append(pkg)
    return out


def parse_module(text: str, name: str) -> Optional[ModuleIface]:
    """Parse `module <name>` → ModuleIface (params + ANSI ports + body). Pure."""
    text = strip_comments(text)
    span = _find_module_span(text, name)
    if span is None:
        return None
    start, body_start, end = span
    header = text[start:body_start]
    body = text[body_start:end]
    return ModuleIface(name=name, params=_parse_params(header),
                       ports=_parse_ansi_ports(header), body=body,
                       imports=_parse_header_imports(header))


# ── reset polarity + registered-output reset value analysis ─────────────────
def classify_clock(ports: List[Port]) -> Optional[str]:
    """Pick the design's clock: a 1-bit input whose name matches the clock
    convention. Returns the port name or None."""
    for p in ports:
        if p.direction == "input" and _is_scalar(p.width) \
                and _CLOCK_NAME_RE.search(p.name):
            return p.name
    return None


def classify_reset(ports: List[Port], body: str
                   ) -> Optional[Tuple[str, bool]]:
    """Pick the design's reset: a 1-bit input matching the reset convention.
    Returns (name, active_low). Polarity is decided by the name spelling and
    corroborated by how the body uses it (`if(!rst)` → active-low)."""
    for p in ports:
        if p.direction == "input" and _is_scalar(p.width) \
                and _RESET_NAME_RE.search(p.name) \
                and not _CLOCK_NAME_RE.search(p.name):
            active_low = bool(_ACTIVE_LOW_NAME_RE.search(p.name))
            # corroborate with usage: `if (!name` / `if (~name` / `if(name==0`
            if re.search(rf"if\s*\(\s*[!~]\s*{re.escape(p.name)}\b", body):
                active_low = True
            elif re.search(rf"if\s*\(\s*{re.escape(p.name)}\s*==\s*1'b0", body):
                active_low = True
            elif re.search(rf"if\s*\(\s*{re.escape(p.name)}\b\s*\)", body):
                # bare `if (name)` → active-high use (unless name says _n)
                if not _ACTIVE_LOW_NAME_RE.search(p.name):
                    active_low = False
            return (p.name, active_low)
    return None


def _is_scalar(width: str) -> bool:
    """A 1-bit port (no [..] range, or an explicit [0:0])."""
    w = width.strip()
    return w == "" or re.match(r"^\[\s*0\s*:\s*0\s*\]$", w) is not None


# an `always @( ... )` block: capture sensitivity + statement text.
_ALWAYS_RE = re.compile(
    r"always(?:_ff)?\s*@\s*\((?P<sens>[^)]*)\)\s*(?P<stmt>.*?)"
    r"(?=(?:\balways\b)|(?:\bassign\b)|(?:\bendmodule\b)|\Z)",
    re.DOTALL | re.IGNORECASE)

_ZERO_LIT_RE = re.compile(
    r"^(0|1'b0|1'h0|'0|\d+'[bhdo]0+|\{[^}]*1'b0[^}]*\}|\{[^}]*\{\s*1'b0\s*\}[^}]*\})$")
_ONE_BIT_ONE_RE = re.compile(r"^(1|1'b1|1'h1|'1)$")
_SIZED_LIT_RE = re.compile(r"^\d+'[bhdoBHDO][0-9a-fA-F_xXzZ]+$")


def _normalize_reset_const(val: str) -> Optional[str]:
    """Normalize a reset assignment RHS to a comparable Verilog constant, or
    None when it is not a plain literal (→ that output is skipped, fail-safe).
    All-zero forms collapse to `'0` (width-agnostic all-bits-zero)."""
    v = val.strip().rstrip(";").strip()
    v = " ".join(v.split())
    if _ZERO_LIT_RE.match(v.replace(" ", "")):
        return "'0"
    if _ONE_BIT_ONE_RE.match(v):
        return "1'b1"
    if _SIZED_LIT_RE.match(v):
        return v
    return None


@dataclass
class ResetFF:
    signal: str             # the registered signal reset here
    value: str              # normalized reset constant
    is_async: bool          # reset in the always sensitivity list


def _reset_branch_text(stmt: str, reset_name: str, active_low: bool
                       ) -> Optional[str]:
    """From an always block statement, return the text of the RESET branch (the
    body executed when reset is asserted), or None if no reset `if` is found."""
    # match `if ( <reset-cond> )` then capture the following statement/block.
    if active_low:
        cond = rf"[!~]\s*{re.escape(reset_name)}\b|{re.escape(reset_name)}\s*==\s*1'b0"
    else:
        cond = rf"{re.escape(reset_name)}\b(?!\s*==\s*1'b0)"
    m = re.search(rf"if\s*\(\s*(?:{cond})\s*\)", stmt)
    if not m:
        return None
    rest = stmt[m.end():].lstrip()
    if rest.startswith("begin"):
        # balanced begin..end
        depth = 0
        i = 0
        toks = re.finditer(r"\bbegin\b|\bend\b", rest)
        span_end = None
        for t in toks:
            if t.group() == "begin":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    span_end = t.end()
                    break
        return rest[:span_end] if span_end else rest
    # single statement up to the first ';'
    j = rest.find(";")
    return rest[:j + 1] if j != -1 else rest


def find_reset_ffs(body: str, reset_name: str, active_low: bool
                   ) -> List[ResetFF]:
    """Scan clocked always blocks; for each reset-branch `sig <= const;` return
    a ResetFF(sig, normalized-const, async?). Non-literal resets are skipped."""
    out: List[ResetFF] = []
    seen = set()
    for m in _ALWAYS_RE.finditer(body):
        sens = m.group("sens")
        stmt = m.group("stmt")
        if not re.search(r"\bposedge\b|\bnegedge\b", sens):
            continue  # combinational always — no registered reset value
        is_async = bool(re.search(
            rf"(pos|neg)edge\s+{re.escape(reset_name)}\b", sens))
        branch = _reset_branch_text(stmt, reset_name, active_low)
        if branch is None:
            continue
        for am in re.finditer(
                r"([A-Za-z_]\w*)\s*<=\s*([^;]+);", branch):
            sig, rhs = am.group(1), am.group(2)
            val = _normalize_reset_const(rhs)
            if val is None or sig in seen:
                continue
            seen.add(sig)
            out.append(ResetFF(signal=sig, value=val, is_async=is_async))
    return out


def _alias_map(body: str) -> Dict[str, str]:
    """`assign out = reg;` (single identifier RHS) → {out: reg}. Only simple
    one-identifier aliases are resolved (an expression RHS is NOT a plain
    register alias and is left unmapped → that output is skipped)."""
    out: Dict[str, str] = {}
    for m in re.finditer(r"assign\s+([A-Za-z_]\w*)\s*=\s*([^;]+);", body):
        lhs, rhs = m.group(1), m.group(2).strip()
        if re.fullmatch(r"[A-Za-z_]\w*", rhs):
            out[lhs] = rhs
    return out


def _outer_parens(expr: str) -> str:
    """Remove only balanced parentheses enclosing the WHOLE expression."""
    expr = expr.strip()
    while expr.startswith("(") and expr.endswith(")"):
        depth = 0
        whole = True
        for idx, char in enumerate(expr):
            depth += (char == "(") - (char == ")")
            if depth < 0 or (depth == 0 and idx != len(expr) - 1):
                whole = False
                break
        if not whole or depth:
            break
        expr = expr[1:-1].strip()
    return expr


def _procedural_driver_count(body: str, signal: str) -> int:
    body = strip_hdl_comments_and_strings(body)
    return sum(bool(re.search(
        rf"\b{re.escape(signal)}\s*(?:<=|=(?!=))",
        re.split(r"\bassign\b|\bendmodule\b", block, maxsplit=1)[0]))
        for block in re.split(r"\balways(?:_ff|_comb|_latch)?\b", body)[1:])


def _reset_gated_aliases(iface: ModuleIface, reset_name: str,
                         active_low: bool, ffs: Dict[str, ResetFF]
                         ) -> Dict[str, str]:
    """Scalar ``deasserted_reset &/&& zero_reset_register`` output bindings.

    This finite grammar retains a reset-safety output obligation when write
    admission becomes combinational but its transaction qualifier stays
    registered. It does NOT infer arbitrary combinational output reset values.
    Both operands must be atoms; the reset atom must have the declared polarity,
    and the other atom must have one procedural driver with literal-zero reset.
    At the reset edge the gate is zero; afterwards the register is zero, so the
    existing sampled-reset assertion is sound even when reset is released.
    Unknown polarity, expressions, competing drivers and nonzero reset values
    remain outside the deterministic floor and are never claimed as proved.
    """
    assignments: Dict[str, List[str]] = {}
    for m in re.finditer(r"\bassign\s+([A-Za-z_]\w*)\s*=\s*([^;]+);",
                         strip_hdl_comments_and_strings(iface.body)):
        assignments.setdefault(m.group(1), []).append(m.group(2))
    out: Dict[str, str] = {}
    for port in iface.ports:
        if port.direction != "output" or not _is_scalar(port.width):
            continue
        rhss = assignments.get(port.name, [])
        if len(rhss) != 1:
            continue
        expr = _outer_parens(rhss[0])
        depth = 0
        cuts = []
        idx = 0
        while idx < len(expr):
            char = expr[idx]
            depth += (char == "(") - (char == ")")
            if char == "&" and depth == 0:
                width = 2 if expr[idx:idx + 2] == "&&" else 1
                cuts.append((idx, width))
                idx += width
            else:
                idx += 1
        if depth or len(cuts) != 1:
            continue
        at, width = cuts[0]
        atoms = []
        for operand in (expr[:at], expr[at + width:]):
            atom = _outer_parens(operand)
            prefix = atom[:1] if atom[:1] in ("!", "~") else ""
            identifier = _outer_parens(atom[1:] if prefix else atom)
            if not re.fullmatch(r"[A-Za-z_]\w*", identifier):
                break
            atoms.append((prefix, identifier))
        if len(atoms) != 2:
            continue
        for gate, target in (atoms, atoms[::-1]):
            if gate[1] != reset_name or bool(gate[0]) == active_low:
                continue
            if target[0]:
                continue
            signal = target[1]
            ff = ffs.get(signal)
            if ff is None or ff.value != "'0" or signal in assignments:
                continue
            if _procedural_driver_count(iface.body, signal) != 1:
                continue
            out[port.name] = signal
    return out


@dataclass
class ResetProp:
    output: str             # the OUTPUT port asserted
    target: str             # the registered signal that holds the value
    value: str              # normalized reset constant
    is_async: bool
    reset_gate: bool = False  # also inhibit at the FIRST currently reset edge


def derive_reset_props(iface: ModuleIface, reset_name: str, active_low: bool
                       ) -> List[ResetProp]:
    """For each OUTPUT port, find its reset value (directly registered, or via a
    plain alias or scalar reset-gated zero-reset register) → a ResetProp. Outputs
    whose reset value cannot be pinned to a literal are omitted (fail-safe)."""
    ffs = {f.signal: f for f in find_reset_ffs(iface.body, reset_name, active_low)}
    aliases = _alias_map(iface.body)
    gated = _reset_gated_aliases(iface, reset_name, active_low, ffs)
    aliases.update(gated)
    props: List[ResetProp] = []
    driver_body = strip_hdl_comments_and_strings(iface.body)
    for p in iface.ports:
        if p.direction != "output":
            continue
        if (re.search(rf"\bassign\s+{re.escape(p.name)}\s*=", driver_body)
                and _procedural_driver_count(iface.body, p.name)):
            # A procedural write to the continuously assigned OUTPUT is a
            # second driver too, even if that write has a literal reset branch.
            continue
        target = p.name
        if target not in ffs and target in aliases:
            target = aliases[target]
        ff = ffs.get(target)
        if ff is None:
            continue
        props.append(ResetProp(output=p.name, target=target, value=ff.value,
                               is_async=ff.is_async, reset_gate=p.name in gated))
    return props


# ── R-0915-144 — observable DUT state and the generated L8 reset properties ─
#
# WHY OBSERVERS, AND WHY NEVER `dut.<reg>`. MEASURED 2026-09-23 (lane icspm5
# §48, mechanism confirmed by lane icformal1): a property written over a
# hierarchical reference into the DUT does NOT read the DUT's register in this
# flow's formal path. yosys `read_verilog` has no hierarchical references; it
# makes `dut.pr` an IMPLICITLY DECLARED LOCAL WIRE of the harness
#     Warning: Identifier `\dut.pr' is implicitly declared.
#     Warning: Wire formal_spm.\dut.pr is used but has no driver.
# which the engine then treats as a FREE variable. The same claim over the
# harness port `p` (`assign p = pr`) proved while the one over `dut.pr` failed
# at frame 3. (Under the harness's own `default_nettype none` it is a hard
# parse error instead.) Either way the property is not about the design.
#
# The mechanism the engine DOES bind is the flow's own `@connect` one (see
# `formal_property_run.emit_invariant_sby`): the harness declares an explicit,
# undriven `(* keep *)` observer wire, and the .sby script flattens the design
# and `connect -set`s the observer to the flattened DUT net, after asserting
# that net exists. Measured on spm: s/c/yr/pr all prove zero one cycle after
# reset, and a mutant whose reset branch leaves `yr` alone fails. The pragma is
# `@observe`, not `@connect`, so a generated harness stays on the STANDARD proof
# path and keeps writing the canonical results.json.
OBSERVE_PRAGMA = "@observe"
OBSERVER_PREFIX = "vibeic_obs_"


@dataclass
class Observer:
    wire: str        # the harness wire
    net: str         # the DUT net it is bound to (flattened name, may be dotted)
    width: str       # "[N-1:0]" from the NETLIST's bit count, "" for 1 bit


@dataclass
class L8Prop:
    name: str        # property name
    guard: str       # harness expression that is true one cycle after reset
    expr: str        # consequent
    obligation: str  # the obligation id it answers
    reset: str = ""  # the declared reset the guard follows
    active_low: bool = False  # its DECLARED polarity
    global_step: bool = False


def _obs_wire(net: str) -> str:
    """The observer wire for DUT net `net`. INJECTIVE by construction: only a
    plain identifier is accepted (R-0915-155 C6 keeps everything else outside
    the class), so the wire is the prefix plus the name, unchanged. The old
    `$`->`__` mapping made `a$b` and `a__b` one wire (round-6 review)."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", net):
        raise ValueError(f"observer net {net!r} is not a plain identifier")
    return OBSERVER_PREFIX + net


def netlist_state(rtl_files: List[Path], top: str, work_dir: Path,
                  container: Optional[str], resets: List[str] = (),
                  clock: str = "", simdef: str = "", declared_edge: str = ""
                  ) -> Tuple[Optional[dict], str]:
    """The design's state, from the NETLIST of the DUT read exactly as the
    chip's synthesis reads it (R-0915-157) — never from RTL text (review round
    4, M4), never from a FORMAL variant. If the DUT does not elaborate under
    that read, the design is outside the class (`outside_class`, named)."""
    try:
        import formal_structural_check as _fsc
    except Exception as exc:  # noqa: BLE001
        return None, f"netlist reader unavailable: {exc}"
    elabs = _fsc.elaborations(rtl_files, top, work_dir, container, simdef)
    facts = []
    klass: List[str] = []
    clock_edge_klass: List[str] = []
    temporal: List[str] = []
    for e in elabs:
        if e["netlist"] is None:
            why = (f"R-0915-157: the DUT does not elaborate under the chip's own "
                   f"read ({e['defines']}, yosys rc={e['rc']}) — the program "
                   f"proves the chip's design or nothing")
            return {"ok": False, "outside_class": [why]}, (
                "outside the class the program proves soundly (R-0915-155): " + why)
        for f in _fsc.applicability(e["netlist"], top, clock, list(resets), e["raw"]):
            if f not in klass:
                klass.append(f)
        for f in _fsc.clock_edge_applicability(e["netlist"], e["raw"], top, clock):
            if f not in clock_edge_klass:
                clock_edge_klass.append(f)
        for f in _fsc.temporal_applicability(e["netlist"], top):
            if f not in temporal:
                temporal.append(f)
        facts.append(_fsc.netlist_facts(e["netlist"], top))
    if klass:
        # R-0915-155: outside the class the program proves soundly. Nothing
        # is claimed — the caller refuses EVERY ruled obligation with this.
        # Observe before cleanup can discard an unused state element. The
        # default proof binds these same aliases before its own prep/cleanup.
        rc, _log, full_path = _fsc.run_yosys(
            rtl_files, top, work_dir, container, simdef,
            tag="_sync_census", passes="proc; flatten")
        try:
            full_raw = json.loads(full_path.read_text()) if rc == 0 else None
        except (OSError, ValueError):
            full_raw = None
        sync = [_fsc.sync_state_facts(full_raw, top, clock)]
        full_sync = sync[0]
        if any(s != full_sync for s in sync):
            full_sync = {"ok": False, "why": "current full state elaborations disagree"}
        if declared_edge not in ("posedge", "negedge"):
            full_sync = {"ok": False, "why": "no unique declared clock edge"}
        elif full_sync.get("ok"):
            full_sync = dict(full_sync, state_clock_edge=full_sync["clock_edge"],
                             clock_edge=declared_edge)
        return {"ok": False, "outside_class": klass,
                "clock_edge_outside_class": clock_edge_klass,
                "sync_state": full_sync}, (
            "outside the class the program proves soundly (R-0915-155): "
            + "; ".join(klass))
    if any(not f["ok"] for f in facts):
        return None, next(f["why"] for f in facts if not f["ok"])
    if any(f["registers"] != facts[0]["registers"] for f in facts):
        return None, "the proof's elaborations disagree about the design's state"
    # which declared resets force state ASYNCHRONOUSLY (netlist, not text)
    out = dict(facts[0])
    out["temporal_outside"] = temporal
    out["async_resets"] = {}
    for rst in resets:
        hit = False
        for e in elabs:
            tm = _fsc._top_module(e["netlist"], top)
            if tm is None:
                continue
            bit, _w = _fsc._port_bit(tm[1], rst)
            if bit is None:
                continue
            rm = _fsc._reset_map(tm[1], bit)
            hit = hit or bool(rm["async"] or rm["async_x"])
        out["async_resets"][rst] = hit
    return out, ""


def derive_l8_props(facts: Optional[dict], facts_why: str,
                    obligations: List[dict], inputs: set
                    ) -> Tuple[List[L8Prop], List[Observer], Dict[str, dict],
                               Dict[str, str]]:
    """Generated properties for the TEMPORAL claims ("all state zero one
    cycle after assertion"), over EVERY register the netlist says is design
    state. Returns (props, observers, answered, refused).

    The guard uses the DECLARED polarity, and its identity is (reset,
    polarity). Polarity itself is no longer a property: it is a STRUCTURAL
    netlist fact checked on every flop the reset forces (review round 4, H2)."""
    props: List[L8Prop] = []
    observers: Dict[str, Observer] = {}
    answered: Dict[str, dict] = {}
    refused: Dict[str, str] = {}
    for ob in obligations:
        rule = ob.get("program_rule") or {}
        sync_claims = [c for c in rule.get("claims") or []
                       if c.get("rule") == "reset_sync"
                       and c.get("value") == "synchronous"]
        # Extend only the formerly refused class. Existing reset/value
        # constructors and their admission conditions are unchanged.
        if sync_claims and facts and facts.get("outside_class"):
            oid = str(ob["id"])
            full = facts.get("sync_state") or {}
            other_temporal = [c for c in rule.get("claims") or []
                              if c.get("rule") in _TEMPORAL_CLAIMS]
            if not full.get("ok") or other_temporal:
                refused[oid] = full.get("why") or facts_why
                continue
            regs = full["registers"]
            # Encode every alias, including plain ones, injectively. Dots
            # are passed unchanged in @observe, never mangled in the target.
            wires = {r["name"]: OBSERVER_PREFIX + "q_" + r["name"].encode().hex()
                     for r in regs}
            for reg in regs:
                wire = wires[reg["name"]]
                width = f"[{reg['width']-1}:0]" if reg["width"] > 1 else ""
                observers[wire] = Observer(wire, reg["name"], width)
            state = "{" + ", ".join(wires[r["name"]] for r in regs) + "}"
            clk = full["clock"]
            edge = f"(!$past({clk}) && {clk})" if full["clock_edge"] == "posedge" else f"($past({clk}) && !{clk})"
            name = "p_l8_state_sync_" + str(len(props))
            props.append(L8Prop(name, f"f_sync_past_valid && !{edge}",
                                f"({state} == $past({state}))", oid,
                                global_step=True))
            answered[oid] = {"properties": [name], "sync_claims": sync_claims,
                             "full_state_census": full}
            continue
        temporal = [c for c in rule.get("claims") or []
                    if c.get("rule") in _TEMPORAL_CLAIMS]
        if not temporal:
            continue
        oid = str(ob["id"])
        if facts is None or facts.get("outside_class"):
            refused[oid] = (facts_why if facts is not None else
                            f"the design's state could not be read from the netlist: {facts_why}")
            continue
        if facts.get("temporal_outside"):
            refused[oid] = ("the temporal claim is outside the class (R-0915-155): "
                            + "; ".join(facts["temporal_outside"]))
            continue
        names: List[str] = []
        why = ""
        for c in temporal:
            reset = c["signal"]
            if reset not in inputs:
                why = f"declared reset {reset!r} is not a 1-bit input of the declared top"
                break
            decl_low = c.get("value") == "active_low"
            if (facts.get("async_resets") or {}).get(reset):
                why = (f"{reset!r} resets state asynchronously; the one-cycle-"
                       f"after guard does not state that behaviour")
                break
            tag = f"{reset}_{'al' if decl_low else 'ah'}"
            guard = f"f_past_valid && l8_{tag}_active_q"
            try:
                wires = {reg["name"]: _obs_wire(reg["name"]) for reg in facts["registers"]}
            except ValueError as exc:
                why = f"cannot observe the design's state faithfully: {exc}"
                break
            if len(set(wires.values())) != len(wires):
                why = "two registers would share one observer wire"
                break
            for reg in facts["registers"]:
                wire = wires[reg["name"]]
                width = f"[{reg['width'] - 1}:0]" if reg["width"] > 1 else ""
                observers.setdefault(wire, Observer(wire, reg["name"], width))
                name = f"p_l8_reset_state_zero_{tag}_{wire[len(OBSERVER_PREFIX):]}"
                if not any(p.name == name for p in props):
                    props.append(L8Prop(name, guard, f"({wire} == '0)", oid,
                                        reset, decl_low))
                names.append(name)
        if why:
            refused[oid] = why
            continue
        answered[oid] = {"properties": names, "claims": temporal,
                         "state_registers": [r["name"] for r in facts["registers"]]}
    keep = {n for a in answered.values() for n in a["properties"]}
    props = [p for p in props if p.name in keep]
    used = {w for p in props for w in re.findall(rf"\b{OBSERVER_PREFIX}\w+", p.expr)}
    return props, [o for w, o in observers.items() if w in used], answered, refused


# ── harness emission ────────────────────────────────────────────────────────
#: The ONE file in `formal/` this generator never writes. See the comment in
#: `emit_harness` for why it has to exist and why it has to be a fragment.
EXPERT_PROPERTIES_SVH = "formal_expert_properties.svh"


def _expert_closed_obligations(formal_dir: Path, unresolved: List[dict],
                               harness_text: str) -> List[dict]:
    """The obligations the `formal-verify` receipt has genuinely discharged.

    An entry is returned only when ALL of these hold, and each one is a way a
    receipt can be wrong rather than a formality:

      * the receipt exists and says `invocation_status: INVOKED` -- a file
        that records no invocation is not one;
      * it carries a disposition FOR THIS OBLIGATION ID, `status: AUTHORED`,
        naming a property. Closure by omission is what the immutable request
        IDs exist to prevent;
      * the named property is DECLARED in the harness text this run emitted,
        or in the expert fragment that harness includes. A receipt naming a
        property nobody wrote closes nothing.

    Returns rows in `covered_obligations` shape, authored by `formal-verify`.
    """
    receipt_path = formal_dir / "formal_expert_review.json"
    try:
        receipt = json.loads(receipt_path.read_text(errors="replace"))
    except (OSError, ValueError):
        return []
    if not isinstance(receipt, dict):
        return []
    if str(receipt.get("invocation_status", "")).upper() != "INVOKED":
        return []
    request = _authoring_request_snapshot(formal_dir)
    if (request is None or receipt.get("request_sha256") != request["sha256"]
            or receipt.get("fallback_skill", "formal-verify") != "formal-verify"):
        return []
    requested = {str(r.get("id")): r for r in
                 json.loads(request["text"])["unresolved_obligations"] if isinstance(r, dict)}
    dispositions = {
        str(row.get("id")): row
        for row in (receipt.get("dispositions") or [])
        if isinstance(row, dict) and str(row.get("id", "")).strip()
    }
    if not dispositions:
        return []
    text = harness_text
    frag = formal_dir / EXPERT_PROPERTIES_SVH
    if frag.is_file():
        try:
            text += "\n" + frag.read_text(errors="replace")
        except OSError:
            pass
    text = strip_comments(text)
    closed: List[dict] = []
    for row in unresolved:
        oid = str(row.get("id", "")).strip()
        original = requested.get(oid)
        if original is None or any(original.get(k) != row.get(k)
                                   for k in ("id", "layer", "source", "description")):
            continue
        d = dispositions.get(oid)
        if not d or str(d.get("status", "")).upper() != "AUTHORED":
            continue
        prop = str(d.get("property", "")).strip()
        if not prop:
            continue
        # OpenTitan/package RTL uses read_slang, whose supported assertion
        # form is a labelled immediate assert.  Its label is an executable
        # property name too: require the assert itself, never a bare label.
        concurrent = (re.search(r"\bproperty\s+" + re.escape(prop) + r"\b", text)
                      and re.search(r"\bassert\s+property\s*\(\s*"
                                    + re.escape(prop) + r"\s*\)", text))
        immediate = re.search(r"\b" + re.escape(prop)
                              + r"\s*:\s*assert\s*\(", text)
        if not (concurrent or immediate):
            continue
        out = dict(row)
        out.update({"property": prop, "status": "AUTHORED",
                    "author": "formal-verify",
                    "receipt": receipt_path.name})
        if d.get("reason"):
            out["disposition_reason"] = str(d["reason"])
        closed.append(out)
    return closed


def emit_harness(iface: ModuleIface, clock: str, reset_name: str,
                 active_low: bool, props: List[ResetProp],
                 assertion_form: str = "concurrent",
                 expert_properties: str = "",
                 l8_props: Optional[List[L8Prop]] = None,
                 observers: Optional[List["Observer"]] = None) -> str:
    """Emit `formal_<top>.sv`: instantiate the DUT with all ports, drive every
    non-clock input as free `(* anyseq *)`, and assert each output's reset-safety
    invariant under the guard appropriate to its FF's reset style. Pure."""
    top = iface.name
    hmod = f"formal_{top}"
    # v1.15.67 — mirror the DUT's header imports. Without them a harness that
    # declares `alert_rx_t alert_rx_i` (the DUT's own port type) is refused
    # with "use of undeclared identifier 'alert_rx_t'": the type lives in
    # `prim_alert_pkg`, which the DUT header imports and the harness did not.
    # Empty for a design whose module header imports nothing, so every such
    # harness is byte-identical.
    import_decl = "".join(f" import {pkg}::*;" for pkg in
                          (getattr(iface, "imports", None) or []))
    param_decl = ""
    param_conn = ""
    if iface.params:
        param_decl = " #(\n" + ",\n".join(
            f"    parameter {n} = {v}" for n, v in iface.params) + "\n)"
        param_conn = " #(" + ", ".join(
            f".{n}({n})" for n, _ in iface.params) + ")"

    in_decls, out_decls, conns = [], [], []
    for p in iface.ports:
        if p.name == clock:
            conns.append(f".{p.name}({p.name})")
            continue
        w = f"{p.width} " if p.width else ""
        # v1.15.67 — a port declared with a user-defined / package-qualified
        # type must be MIRRORED with that type, not with a bare `wire`. The
        # DUT's own declaration is the only statement of the signal's shape
        # the harness has; declaring `wire alert_rx_i` against
        # `input alert_rx_t alert_rx_i` connects a 1-bit net to a struct.
        # `wire` is kept for a plain net port so every design that has no
        # typed port emits a byte-identical harness.
        decl = f"{p.data_type} " if getattr(p, "data_type", "") else f"wire {w}"
        if p.direction == "output":
            out_decls.append(f"    {decl}{p.name};")
        else:
            in_decls.append(f"    (* anyseq *) {decl}{p.name};")
        conns.append(f".{p.name}({p.name})")

    # reset-active expression (design's own polarity)
    rst_active = f"!{reset_name}" if active_low else reset_name

    # sync FFs assert one cycle after reset (rst_active_q); async FFs assert
    # while reset is currently asserted (rst_active). Both are construction-safe.
    sync_props = [p for p in props if not p.is_async]
    async_props = [p for p in props if p.is_async]

    # CONCURRENT form, and the equivalence is exact rather than approximate.
    #
    #     always @(posedge clk) if (G) assert (X);      the immediate form
    #     property p; @(posedge clk) G |-> X; endproperty
    #     assert property (p);                          the concurrent form
    #
    # Both sample G and X at the same edge and both are vacuously true when G is
    # false, so this is a change of spelling and not of meaning.  `|->` is the
    # OVERLAPPING implication on purpose: `|=>` would move the consequent one
    # cycle later and prove something the design does not claim.
    #
    # WHY THE SPELLING MATTERS.  Step 5's gate requires `property <name>` and
    # `assert property`, so the immediate form left it permanently red — and
    # until v0.2.31 of the EDA image there was no honest way out: our yosys fork
    # could not parse a named property at all (measured: 42/42 spellings
    # rejected, and a harness written to satisfy the gate returned rc=16 from
    # SymbiYosys).  Emitting it then would have traded a proof that ran for a
    # green light that did not.  The fork now parses it AND proves it — a false
    # property FAILs with a counterexample, a true one passes — so the gate can
    # be satisfied by real work rather than by relaxing it.
    prop_lines, assert_lines = [], []
    idx = 0
    for p, guard in ([(p, "rst_active_q") for p in sync_props]
                     + [(p, "rst_active") for p in async_props]):
        idx += 1
        name = f"p_reset_safety_{idx}"
        full_guard = f"f_past_valid && {guard}"
        if p.reset_gate:
            # The admission gate must inhibit a PREVIOUSLY launched transaction
            # at the very first reset-sampling edge. An after-reset-only guard
            # misses that edge. Retain its registered-zero check on release too.
            full_guard = f"rst_active || ({full_guard})"
        if assertion_form == "immediate":
            # v1.15.67 — the IMMEDIATE form, for the `read_slang` frontend.
            # The equivalence is the one this function's own comment states
            # below and is exact, not approximate: both sample the guard and
            # the property at the same edge, and both are vacuously true when
            # the guard is false. The two frontends are COMPLEMENTARY, and
            # that is why the form has to follow the frontend:
            #   * `read_verilog -sv` accepts SVA and rejects a package import
            #     in a module header (the OpenTitan sources);
            #   * `read_slang` elaborates those sources and refuses SVA —
            #     "SVA unsupported (ignore all assertions with
            #     '--ignore-assertions')", measured in the pinned image.
            # Ignoring the assertions is not an option: a harness whose
            # properties are dropped proves nothing while reporting PASS.
            assert_lines.append(
                f"    always @(posedge {clock}) if ({full_guard})\n"
                f"        a_reset_safety_{idx}: assert "
                f"({p.output} == {p.value});")
        else:
            prop_lines.append(
                f"    property {name};\n"
                f"        @(posedge {clock})\n"
                f"            ({full_guard}) |-> ({p.output} == {p.value});\n"
                f"    endproperty")
            assert_lines.append(
                f"    a_reset_safety_{idx}: assert property ({name});")

    body_parts = [
        "\n".join(in_decls),
        "\n".join(out_decls),
        f"    {top}{param_conn} dut ({', '.join(conns)});",
        "",
        "    reg f_past_valid = 1'b0;",
        f"    always @(posedge {clock}) f_past_valid <= 1'b1;",
        f"    wire rst_active = {rst_active};",
    ]
    if sync_props:
        body_parts += [
            "    reg rst_active_q = 1'b0;",
            f"    always @(posedge {clock}) rst_active_q <= rst_active;",
        ]
    body_parts.append("")
    body_parts += prop_lines
    if prop_lines:
        body_parts.append("")
    body_parts += assert_lines
    # R-0915-144 — THE GENERATED L8 RESET PROPERTIES, over observers the
    # engine binds (see OBSERVE_PRAGMA). Absent → byte-identical harness.
    if l8_props:
        body_parts.append("")
        body_parts.append("    // R-0915-144: L8 reset declarations, authored by this program.")
        for ob in observers or []:
            w = f"{ob.width} " if ob.width else ""
            body_parts.append(
                f"    // {OBSERVE_PRAGMA} {ob.wire} = dut.{ob.net}")
            body_parts.append(f"    (* keep *) wire {w}{ob.wire};")
        seen_rst: List[str] = []
        for p in l8_props:
            if p.global_step:
                continue
            tag = f"{p.reset}_{'al' if p.active_low else 'ah'}"
            if tag in seen_rst:
                continue
            seen_rst.append(tag)
            act = f"!{p.reset}" if p.active_low else p.reset
            body_parts += [
                f"    wire l8_{tag}_active = {act};",
                f"    reg l8_{tag}_active_q = 1'b0;",
                f"    always @(posedge {clock}) "
                f"l8_{tag}_active_q <= l8_{tag}_active;",
            ]
        if any(p.global_step for p in l8_props):
            body_parts += ["    reg f_sync_past_valid = 1'b0;",
                           "    always @($global_clock) f_sync_past_valid <= 1'b1;"]
        for p in l8_props:
            if p.global_step:
                body_parts += [
                    f"    always @($global_clock) if ({p.guard})",
                    f"        a_{p.name[2:]}: assert ({p.expr});",
                ]
                continue
            if assertion_form == "immediate":
                body_parts.append(
                    f"    always @(posedge {clock}) if ({p.guard})\n"
                    f"        a_{p.name[2:]}: assert ({p.expr});")
            else:
                body_parts += [
                    f"    property {p.name};",
                    f"        @(posedge {clock})",
                    f"            ({p.guard}) |-> ({p.expr});",
                    f"    endproperty",
                    f"    a_{p.name[2:]}: assert property ({p.name});",
                ]
    # THE EXPERT ROLE'S PROPERTIES, IF THIS RUN HAS ANY.
    #
    # WHY: measured 2026-09-15 on `subservient` x gf180mcuD. This program
    # emits `formal_authoring_request.json` asking the `formal-verify` role to
    # author properties for obligations it cannot discharge itself --
    #   "invoke formal-verify on these exact IDs and record each authored
    #    property in property_contract.json before rerunning Step 5"
    # -- and `formal_property_run` reads a receipt at
    # `formal_expert_review.json` naming each authored property. So the flow
    # REQUESTS expert properties and RECORDS them.
    #
    # It had nowhere for them to LIVE. The only file carrying properties is
    # this harness, and the write below is an unconditional
    # `out_path.write_text(harness)` -- so a property the expert authored was
    # destroyed by the next run of the producer that asked for it, and the
    # receipt then named a property no file contained. A request with no
    # channel to answer on is a request that can only ever be reported
    # unanswered, which is exactly what step 5 reported:
    #   EXPERT_FALLBACK_NOT_INVOKED (#1974)
    #
    # The channel is a file this program never writes and always includes. It
    # is a `.svh` FRAGMENT, included INSIDE the harness module, so the
    # expert's properties see the same nets the generated ones do -- the DUT's
    # ports, `f_past_valid`, and the reset-activity registers above -- without
    # a second instantiation of the DUT or a hierarchical reference.
    if expert_properties:
        body_parts.append("")
        body_parts.append(
            f"    // Expert-authored properties, included and never rewritten")
        body_parts.append(
            f"    // by this generator. See {EXPERT_PROPERTIES_SVH}.")
        body_parts.append(f'    `include "{expert_properties}"')
    body = "\n".join(bp for bp in body_parts if bp is not None)

    return (
        f"// {hmod}.sv — AUTO-EMITTED deterministic reset-safety harness.\n"
        f"// Generated by formal_harness_gen.py from the design's OWN L-layer\n"
        f"// interface + reset branch (design INPUT, §4.05). No chip literal.\n"
        f"// Property: one cycle after reset, each registered output holds the\n"
        f"// exact value the RTL's reset branch assigns it (construction-safe).\n"
        f"`default_nettype none\n"
        f"module {hmod}{import_decl}{param_decl} (input wire {clock});\n"
        f"{body}\n"
        f"endmodule\n"
        f"`default_nettype wire\n"
    )


# ── driver ──────────────────────────────────────────────────────────────────
def _discover_rtl(rtl_dir: Path) -> List[Path]:
    if not rtl_dir.is_dir():
        return []
    files = [p for p in sorted(rtl_dir.rglob("*"))
             if p.suffix in (".v", ".sv") and p.is_file()]
    # exclude obvious testbench files (never synthesis inputs)
    return [f for f in files
            if not re.search(r"(^|_)(tb|testbench)(_|$)", f.stem, re.IGNORECASE)]


def _module_texts(rtl_files: List[Path]) -> Dict[str, Tuple[str, Path]]:
    """Map module name → (source text, file). First definition wins."""
    out: Dict[str, Tuple[str, Path]] = {}
    for f in rtl_files:
        txt = f.read_text(errors="replace")
        for name in re.findall(r"\bmodule\s+([A-Za-z_]\w*)", strip_comments(txt)):
            out.setdefault(name, (txt, f))
    return out


def _child_modules(body: str, known: List[str], self_name: str) -> List[str]:
    """Known module names INSTANTIATED in `body` (`M [#(..)] inst (`). Used to
    descend a thin rename wrapper to the leaf module that holds the logic."""
    found: List[str] = []
    for name in known:
        if name == self_name:
            continue
        if re.search(rf"\b{re.escape(name)}\b\s*(?:#\s*\([^;]*?\)\s*)?"
                     rf"[A-Za-z_]\w*\s*\(", body):
            found.append(name)
    return found


def _resolve_top(rtl_files: List[Path], top: Optional[str],
                 project: Optional[Path]) -> Optional[str]:
    if top:
        return top
    # L9 top_module
    if project is not None:
        base = project / "phase1"
        if base.is_dir():
            for cand in sorted(base.rglob("L9_INTEGRATION_SPEC.json")):
                try:
                    d = json.loads(cand.read_text(errors="replace"))
                    if d.get("top_module"):
                        return d["top_module"]
                except Exception:
                    pass
    # sole module across the RTL
    names: List[str] = []
    for f in rtl_files:
        names += re.findall(r"\bmodule\s+([A-Za-z_]\w*)",
                            strip_comments(f.read_text(errors="replace")))
    uniq = list(dict.fromkeys(names))
    return uniq[0] if len(uniq) == 1 else None


def _analyze(iface: ModuleIface) -> Optional[dict]:
    """Return the construction-safe reset-safety analysis of a parsed module, or
    None when no such property is derivable (no clock / no reset / inout / no
    registered output with a literal reset value)."""
    if any(p.direction == "inout" for p in iface.ports):
        return None
    clock = classify_clock(iface.ports)
    if not clock:
        return None
    rst = classify_reset(iface.ports, iface.body)
    if not rst:
        return None
    reset_name, active_low = rst
    props = derive_reset_props(iface, reset_name, active_low)
    if not props:
        return None
    return {"clock": clock, "reset": reset_name, "active_low": active_low,
            "props": props}


def _hierarchy_below(mtexts: Dict[str, Tuple[str, Path]], known: List[str],
                     start: str) -> List[str]:
    """Every module transitively instantiated under `start`, BFS, deterministic.

    The DESIGN, not the file set. A module that sits in the same directory but
    is instantiated nowhere under the declared top is not part of this design,
    and a property proven there describes something the flow was not asked
    about — the adjacent-measurement failure this whole line of work exists to
    remove. Children are sorted at each level so the pick is reproducible.
    """
    order: List[str] = []
    seen = {start}
    queue = [start]
    while queue:
        cur = queue.pop(0)
        entry = mtexts.get(cur)
        if entry is None:
            continue
        iface = parse_module(entry[0], cur)
        if iface is None:
            continue
        for child in sorted(_child_modules(iface.body, known, cur)):
            if child not in seen:
                seen.add(child)
                order.append(child)
                queue.append(child)
    return order


def _pick_provable(rtl_files: List[Path], top_name: Optional[str],
                   project: Optional[Path]
                   ) -> Optional[Tuple[ModuleIface, Path, dict, bool, str]]:
    """Pick a module with a construction-safe reset-safety property, PREFERRING
    the declared top and DESCENDING through thin single-child rename wrappers
    (e.g. an auto-emitted `chip_top` whose only job is to instantiate the leaf).
    Returns (iface, dut_file, analysis, descended?, basis) or None.

    THE SEARCH USED TO BE ONE PATH WHILE ITS ANSWER CLAIMED THE WHOLE DESIGN.
    ============================================================================
    The descent gives up the moment a module instantiates anything other than
    exactly one child, and `generate` then reports "no module with a
    construction-safe reset-safety property" — a statement about every module
    there is, derived from having examined a single chain of them.

    MEASURED (subservient x sky130A). `subservient` instantiates TWO children,
    `subservient_core` and `subservient_gpio`, so the walk broke at the top and
    the step reported NOT_APPLICABLE. Pointing the SAME program at
    `subservient_gpio` — same project, same RTL — emitted a complete harness
    with two construction-safe properties (`o_rdata == '0` and `o_gpio == '0`
    one cycle after reset, sync reset). The capability was there the whole time;
    only the walk could not reach it. Step 5 then failed, and steps 7, 8, 10 and
    11 went MISSING as blocked-by-upstream — one unreachable branch costing five
    canonical steps, on every hierarchical design whose top-level outputs are
    driven from more than one sub-module, which is essentially every SoC.

    So when the single-child descent ends empty, the hierarchy BELOW the
    declared top is scanned. Not the file set: a module nobody instantiates is
    not part of this design. The basis is returned and recorded, because a
    property proven on a sub-module is a WEAKER statement than one proven on the
    top, and a reader who cannot tell the two apart has been handed the same
    kind of answer this fix removes."""
    mtexts = _module_texts(rtl_files)
    if not mtexts:
        return None
    start = _resolve_top(rtl_files, top_name, project)
    if not start or start not in mtexts:
        # fall back to any single module we can prove
        start = next(iter(mtexts))
    known = list(mtexts.keys())
    visited = set()
    current = start
    descended = False
    for _ in range(len(mtexts) + 1):
        if current in visited or current not in mtexts:
            break
        visited.add(current)
        txt, f = mtexts[current]
        iface = parse_module(txt, current)
        if iface is None or not iface.ports:
            break
        analysis = _analyze(iface)
        if analysis is not None:
            return (iface, f, analysis, descended,
                    "descended_wrapper" if descended else "declared_top")
        # no property here — descend if this is a thin single-child wrapper
        children = [c for c in _child_modules(iface.body, known, current)
                    if c not in visited]
        if len(children) != 1:
            break
        current = children[0]
        descended = True

    # The descent covered ONE PATH. Before claiming the design has no provable
    # module, look at the rest of the hierarchy under the declared top — in
    # deterministic order, skipping what the walk already rejected.
    for name in _hierarchy_below(mtexts, known, start):
        if name in visited:
            continue
        visited.add(name)
        txt, f = mtexts[name]
        iface = parse_module(txt, name)
        if iface is None or not iface.ports:
            continue
        analysis = _analyze(iface)
        if analysis is not None:
            return (iface, f, analysis, True, "hierarchy_scan")
    return None


def _declaration_read_state(decl: dict) -> dict:
    """The three keys every contract carries so it names the root it read."""
    return {
        "declaration_root": decl.get("declaration_root"),
        "declaration_root_present": bool(decl.get("declaration_root_present")),
        "declaration_root_error": decl.get("declaration_root_error"),
        "unreadable_declarations": list(decl.get("unreadable_declarations") or []),
    }


def _unresolved_declaration_rows(decl: dict) -> List[dict]:
    """One row per declaration this run could not turn into an obligation.

    #2183 — the row SAYS WHICH of the three states it is in, and an absent
    root names the directory that was globbed. Before this, a run measuring a
    directory that does not exist and a design that declares nothing wrote the
    same three rows and the same sentence, so a phantom denominator was
    indistinguishable from an honest one.
    """
    rows: List[dict] = []
    root = decl.get("declaration_root")
    root_present = bool(decl.get("declaration_root_present"))
    root_error = decl.get("declaration_root_error")
    for layer in decl.get("missing_declarations") or []:
        if root_error:
            # The root is not absent and the layer is not undeclared: the
            # listing itself failed, so NOTHING was read and nothing here is a
            # statement about the design. Checked FIRST — an unreadable root
            # can be `root_present` either way (a failed listdir vs a failed
            # stat), and neither of the other two rows would be true.
            rows.append({
                "id": f"{layer}.declaration_root_unreadable", "layer": layer,
                "source": root,
                "description": (
                    f"the Phase-1 declaration root {root!r} could not be "
                    f"read: {root_error}; {layer} was never read, and this is "
                    f"NOT a statement that the design declares no {layer}"),
                "author": "formal-verify",
                "status": DECLARATION_ROOT_UNREADABLE,
            })
        elif root_present:
            rows.append({
                "id": f"{layer}.declaration_missing", "layer": layer,
                "source": None,
                "description": (f"{layer} declaration is absent; applicability "
                                f"and property are unknown"),
                "author": "formal-verify", "status": DECLARATION_MISSING,
            })
        else:
            rows.append({
                "id": f"{layer}.declaration_root_absent", "layer": layer,
                "source": root,
                "description": (
                    f"the Phase-1 declaration root {root!r} does not exist, so "
                    f"{layer} was never read; this is NOT a statement that the "
                    f"design declares no {layer}"),
                "author": "formal-verify", "status": DECLARATION_ROOT_ABSENT,
            })
    for row in decl.get("unreadable_declarations") or []:
        layer = row.get("layer", "L?")
        name = Path(str(row.get("path", ""))).name or "?"
        rows.append({
            "id": f"{layer}.declaration_unreadable.{name}", "layer": layer,
            "source": row.get("path"),
            "description": (
                f"{layer} declaration {row.get('path')!r} exists but could not "
                f"be read: {row.get('error')}; it was NOT read as declaring "
                f"nothing"),
            "author": "formal-verify", "status": DECLARATION_UNREADABLE,
        })
    return rows


def _flow_generated_core_binding(project: Optional[Path], declared_top: Optional[str],
                                 core: ModuleIface, rtl_modules: set) -> Tuple[dict, str]:
    """L9's recorded core interface for a DIE whose chip_top is flow generated.

    Step 5 precedes pad-ring generation.  L9 is the input used by that producer
    to connect the core; a later pad-ring record may corroborate it.  A missing
    or ambiguous entry is never inferred from a similar RTL signal name.
    """
    if project is None or declared_top != "chip_top" or declared_top in rtl_modules:
        return {}, "the declared top is not an absent flow-generated chip_top"
    try:
        import _tapeout_declaration as _td
        route = project / _td.DECLARATION_REL
        decision = json.loads(route.read_text(errors="replace"))
        if decision.get("schema") != _td.SCHEMA or _td.answer(
                decision, "deliverable") != _td.DELIVERABLE_DIE:
            return {}, "the owner declaration does not select a DIE"
        l9_path = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
        l9 = json.loads(l9_path.read_text(errors="replace"))
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        return {}, f"DIE/L9 binding evidence could not be read: {exc}"
    if not isinstance(l9, dict) or l9.get("top_module") != core.name:
        return {}, "L9 top_module does not identify the harness core"
    entries = l9.get("top_ports")
    if not isinstance(entries, list) or not entries:
        return {}, "L9 top_ports has no recorded interface"
    by_external: Dict[str, List[str]] = {}
    by_core: Dict[str, List[str]] = {}
    rtl_inputs = {p.name for p in core.ports
                  if p.direction == "input" and _is_scalar(p.width)}
    for row in entries:
        if not isinstance(row, dict):
            continue
        external = row.get("name")
        # The pad-ring producer's u_core binding is .name(core_name).  L9
        # describes that exact port; it does not authorize an arbitrary rename.
        internal = external
        if not (isinstance(external, str) and isinstance(internal, str)
                and _IDENT_RE.fullmatch(external) and _IDENT_RE.fullmatch(internal)):
            continue
        if row.get("core_port", external) != external:
            continue
        if row.get("direction", row.get("mode")) != "input":
            continue
        if row.get("width") != 1:
            continue
        by_external.setdefault(external, []).append(internal)
        by_core.setdefault(internal, []).append(external)
    mapping = {external: targets[0] for external, targets in by_external.items()
               if len(targets) == 1 and len(by_core.get(targets[0], [])) == 1
               and targets[0] in rtl_inputs}
    pad_path = project / "reports/phase3/io_pad_chip_top.json"
    if pad_path.is_file():
        try:
            pad = json.loads(pad_path.read_text(errors="replace"))
        except (OSError, ValueError) as exc:
            return {}, f"pad-ring binding record could not be read: {exc}"
        if (not isinstance(pad, dict) or pad.get("verdict") != "WROTE"
                or pad.get("chip_top_module") != declared_top
                or pad.get("core_module") != core.name
                or not isinstance(pad.get("pad_instances"), dict)):
            return {}, "pad-ring record does not identify this generated wrapper and core"
        counts: Dict[str, int] = {}
        for inst in pad["pad_instances"].values():
            if isinstance(inst, dict) and inst.get("direction") == "input":
                port = inst.get("port")
                if isinstance(port, str):
                    counts[port] = counts.get(port, 0) + 1
        mapping = {outer: inner for outer, inner in mapping.items()
                   if counts.get(outer) == 1}
    return mapping, f"{l9_path}:top_module,top_ports"


def generate(project: Optional[Path] = None, top: Optional[str] = None,
             rtl: Optional[List[Path]] = None,
             out: Optional[Path] = None,
             assertion_form: str = "concurrent",
             container: Optional[str] = None) -> dict:
    """Author the deterministic floor and its declaration denominator.

    NOT_APPLICABLE is reserved for an explicit design declaration. An
    applicable design for which no safe property can be authored is
    INCOMPLETE and carries the exact expert-authoring request.
    """
    decl = declaration_obligations(project)
    if decl["applicability"] == "NOT_APPLICABLE":
        contract = {
            "program": "formal_harness_gen", "version": "2.0.0",
            "verdict": "NOT_APPLICABLE", "applicability": "NOT_APPLICABLE",
            "declaration": decl["declaration"], "property_denominator": 0,
            "authored_property_count": 0, "unresolved_obligations": [],
            "missing_declarations": [],
            **_declaration_read_state(decl),
        }
        _write_property_contract(project, contract)
        return {"verdict": "NOT_APPLICABLE", "rc": 2,
                "reason": decl["declaration"]["reason"],
                "declaration": decl["declaration"],
                "property_denominator": 0}

    declared = list(decl["obligations"]) + _unresolved_declaration_rows(decl)
    # R-0915-157: the DUT is the CHIP's source set — the ONE selection phase-3
    # synthesis reads (`_chip_synth_read.chip_rtl_files`).
    if rtl:
        rtl_files = list(rtl)
    elif project and _pl:
        import _chip_synth_read as _csr
        rtl_files = _csr.chip_rtl_files(_pl.rtl_dir(project))
    else:
        rtl_files = []
    if not rtl_files:
        if project is None:
            return {"verdict": "NOT_APPLICABLE", "rc": 2,
                    "reason": "no RTL sources found to derive a formal property from"}
        unresolved = declared or [{
            "id": "RTL.sources_missing", "layer": "RTL", "source": None,
            "description": "no RTL sources found to derive or bind a formal property",
            "author": "formal-verify", "status": "DECLARATION_MISSING"}]
        contract = {
            "program": "formal_harness_gen", "version": "2.0.0",
            "verdict": "INCOMPLETE", "applicability": "APPLICABLE",
            "property_denominator": len(unresolved),
            "authored_property_count": 0,
            "unresolved_obligations": unresolved,
            "missing_declarations": decl["missing_declarations"],
            "layer_not_applicable": decl["layer_not_applicable"],
            **_declaration_read_state(decl),
        }
        _write_property_contract(project, contract)
        return {"verdict": "INCOMPLETE", "rc": 2,
                "reason": "no RTL sources found to derive or bind a formal property",
                "fallback_skill": "formal-verify",
                "property_denominator": len(unresolved),
                "unresolved_obligations": unresolved}

    picked = _pick_provable(rtl_files, top, project)
    if picked is None:
        # The claim names the scope it actually covered: the declared top and
        # every module instantiated under it. It used to say "no module" after
        # examining one chain of them.
        if project is None:
            reason = ("no module in the declared top's hierarchy has a "
                      "construction-safe reset-safety property (needs a clock, "
                      "a reset and a registered output with a literal reset "
                      "value; no inout)")
            return {"verdict": "NOT_APPLICABLE", "rc": 2, "reason": reason}
        unresolved = declared or [{
            "id": "RTL.sound_property_missing", "layer": "RTL", "source": None,
            "description": ("no construction-safe property could be bound in the "
                            "declared top hierarchy; needs a declared clock/reset "
                            "and a registered literal-reset output, or expert SVA"),
            "author": "formal-verify", "status": "UNAUTHORED"}]
        reason = ("no module in the declared top's hierarchy has a "
                  "construction-safe reset-safety property (needs a clock, a "
                  "reset and a registered output with a literal reset value; "
                  "no inout)")
        # With no construction-safe floor, formal-verify owns the whole
        # harness. Read its answer without rewriting that harness, just as
        # the generated-floor path reads the expert fragment below.
        subject_top = _resolve_top(rtl_files, top, project)
        harness_path = out or (_pl.formal_dir(project) / f"formal_{subject_top}.sv")
        closed = (_expert_closed_obligations(
            harness_path.parent, unresolved, harness_path.read_text(errors="replace"))
            if harness_path.is_file() else [])
        closed_ids = {row["id"] for row in closed}
        unresolved = [row for row in unresolved if row["id"] not in closed_ids]
        contract = {
            "program": "formal_harness_gen", "version": "2.0.0",
            "verdict": "INCOMPLETE" if unresolved else "AUTHORED",
            "applicability": "APPLICABLE",
            "property_denominator": len(closed) + len(unresolved),
            "authored_property_count": len(closed),
            "covered_obligations": closed,
            "unresolved_obligations": unresolved,
            "missing_declarations": decl["missing_declarations"],
            "layer_not_applicable": decl["layer_not_applicable"],
            **_declaration_read_state(decl),
        }
        # A structural declaration is about the declared RTL top even when
        # none of its outputs admits the reset-property construction rule.
        # Keep routing those claims to the existing native structural owner.
        modules = _module_texts(rtl_files)
        if subject_top in modules and any(
                (row.get("program_rule") or {}).get("kind") in (KIND_STRUCTURAL, KIND_MIXED)
                for row in unresolved):
            subject = parse_module(modules[subject_top][0], subject_top)
            if subject is not None:
                import _chip_synth_read as _csr
                unstaged = _csr.unstaged_analog_blocks(project)
                if unstaged:
                    for row in unresolved:
                        if row.get("program_rule"):
                            row["program_refused"] = (
                                f"unstaged analog blocks {unstaged}; the chip's "
                                "define decision is not known at Step 5")
                else:
                    inputs = {p.name for p in subject.ports
                              if p.direction == "input" and _is_scalar(p.width)}
                    simdef, _ = _csr.chip_sim_define(rtl_files, _csr.staged_macro_files(project))
                    contract["structural_subject"] = {
                        "top": subject_top, "clock": classify_clock(subject.ports),
                        "simdef": simdef,
                        "resets": sorted({c["signal"] for row in declared
                                          for c in (row.get("program_rule") or {}).get("claims") or []
                                          if c.get("rule", "").startswith("reset_")
                                          and c.get("signal") in inputs}),
                        "rtl_files": [str(f) for f in rtl_files],
                    }
                    contract["chip_read_top"] = subject_top
        _write_property_contract(project, contract)
        return {"verdict": contract["verdict"], "rc": 2 if unresolved else 0,
                "reason": reason if unresolved else "expert-authored whole harness read back",
                "fallback_skill": "formal-verify" if unresolved else None,
                "property_denominator": contract["property_denominator"],
                "authored_property_count": len(closed),
                "unresolved_obligations": unresolved}
    iface, dut_file, analysis, descended, selection = picked
    dut_top = iface.name
    clock = analysis["clock"]
    reset_name = analysis["reset"]
    active_low = analysis["active_low"]
    props = analysis["props"]

    out_path = out or (
        (_pl.formal_dir(project) / f"formal_{dut_top}.sv")
        if (project and _pl) else Path(f"formal_{dut_top}.sv"))
    # PRESENT, not assumed: the include is emitted only when the fragment is
    # actually on disk, so a design with no expert properties gets a
    # byte-identical harness to the one it got before this existed, and a
    # harness can never `` `include `` a file sby would fail to stage.
    _expert = out_path.parent / EXPERT_PROPERTIES_SVH
    # R-0915-144 — the program answers the TEMPORAL claims it has a rule for.
    _mtexts = _module_texts(rtl_files)
    _known = list(_mtexts.keys())
    # R-0915-144 / review H5 — a rule is about a 1-bit INPUT of the design. A
    # declared reset or clock that is an OUTPUT (the flow's own L8 emitter
    # lists `o_rst_n` among the resets), or not a port at all, is not this
    # rule's subject: the rule is refused with the reason and the obligation
    # goes to the expert. It is never "the RTL contradicts its declaration".
    _decl_top = _resolve_top(rtl_files, top, project)
    _subj_name = _decl_top if _decl_top in _known else dut_top
    _subj = parse_module(_mtexts[_subj_name][0], _subj_name) if _subj_name in _mtexts else None
    _inputs = {p.name for p in (_subj.ports if _subj else iface.ports)
               if p.direction == "input" and _is_scalar(p.width)}
    _pre_refused: Dict[str, str] = {}
    _core_map, _map_source = _flow_generated_core_binding(
        project, _decl_top, iface, set(_known))
    _mapped_core = bool(_core_map) and _decl_top not in _known
    if _decl_top not in _known and _decl_top == "chip_top":
        mapped = []
        for original in declared:
            row = dict(original)
            rule = row.get("program_rule")
            if rule:
                signals = {c.get("signal") for c in rule.get("claims") or []
                           if c.get("signal")}
                if not signals or any(s not in _core_map for s in signals):
                    _pre_refused[str(row["id"])] = (
                        f"no unambiguous flow-recorded core port for {sorted(signals)}; "
                        + _map_source)
                else:
                    row["program_rule"] = dict(rule, claims=[
                        dict(c, signal=_core_map.get(c.get("signal"), c.get("signal")))
                        for c in rule.get("claims") or []])
                    row["core_binding"] = {
                        "declared_top": _decl_top, "core_top": dut_top,
                        "ports": {s: _core_map[s] for s in sorted(signals)},
                        "source": _map_source}
                    if row.get("binding"):
                        row["binding"] = dict(row["binding"],
                                              declared_port=row["binding"]["port"],
                                              port=_core_map[row["binding"]["port"]])
            mapped.append(row)
        declared = mapped
    for o in declared:
        for c in (o.get("program_rule") or {}).get("claims") or []:
            if c.get("signal") and c["signal"] not in _inputs:
                _pre_refused[str(o["id"])] = (
                    f"declared {c['signal']!r} is not a 1-bit input of "
                    f"{_subj_name}; not the subject of rule {c['rule']}")
                break
    # Review round 2, M2 — one reset, two DECLARED polarities (the flow's L8
    # emitter takes `polarity` and `port_description` from independent
    # sources). Both cannot be true; the program answers neither and names
    # the contradiction for the expert.
    _pols: Dict[str, Dict[str, List[str]]] = {}
    for o in declared:
        for c in (o.get("program_rule") or {}).get("claims") or []:
            if c.get("rule") in ("reset_polarity", "reset_state_zero"):
                _pols.setdefault(c["signal"], {}).setdefault(
                    c.get("value", ""), []).append(str(o["id"]))
    for rst, by_pol in _pols.items():
        if len(by_pol) > 1:
            for pol, ids in by_pol.items():
                for oid in ids:
                    _pre_refused.setdefault(oid, (
                        f"L8 declares reset {rst!r} with contradictory "
                        f"polarities {sorted(by_pol)} "
                        f"({'; '.join(f'{k}: {v}' for k, v in sorted(by_pol.items()))}); "
                        f"the program answers neither"))
    # PROGRAM-FIRST OWNS THE DECLARED TOP, AND ONLY THE DECLARED TOP.
    #
    # When the harness proves a module BELOW the declared top, whether the
    # wrappers are transparent to the reset, the clock and the state is a
    # judgement, not a regex. Round 2 closed the top's declarations on the
    # core's proof (a wrapper's `~rst_n` / `rst_n | scan_mode` was invisible);
    # the round-3 allowance for "a plain wire through every wrapper" was
    # itself bypassed three ways (a second instance of the same module, a
    # `#(...)` override of the reset value, the wrapper's own flops) and made
    # `state_covered` compare the core's register names with the top's
    # netlist. So the allowance is REMOVED: off the declared top the program
    # closes NOTHING — temporal or structural — and every ruled obligation
    # goes to the `formal-verify` expert with this reason (review round 3).
    #
    # AND "THE DECLARED TOP" MEANS RESOLVED AND FOUND BY NAME. `_pick_provable`
    # labels its FIRST-MODULE FALLBACK `declared_top` too (no --top and no L9
    # top_module with several modules, a case mismatch, a `macromodule`, the
    # runner's default `chip_top` with no chip_top.v) — so the label alone
    # proves nothing. The program closes only when the resolved declared top
    # exists by that exact name AND is the module the harness proves
    # (review round 4, H1).
    _top_found = (_decl_top is not None and _decl_top in _known
                  and dut_top == _decl_top and selection == "declared_top")
    if not (_top_found or _mapped_core):
        for o in declared:
            if o.get("program_rule"):
                _pre_refused.setdefault(str(o["id"]), (
                    f"the harness proves {dut_top!r} ({selection}), and the "
                    f"declared top {_decl_top!r} is "
                    + ("not a module in the RTL" if _decl_top not in _known
                       else "a different module")
                    + "; whether that module stands for the design is a "
                      "judgement the program does not make, so it closes "
                      "nothing here"))
    _facts, _facts_why = (None, "not computed")
    _simdef = ""
    if (_top_found or _mapped_core) and project is not None and _pl is not None and any(
            str(o["id"]) not in _pre_refused and o.get("program_rule")
            for o in declared):
        _resets = sorted({c["signal"] for o in declared
                          for c in (o.get("program_rule") or {}).get("claims") or []
                          if c.get("rule", "").startswith("reset_")
                          and c.get("signal") in _inputs})
        import _chip_synth_read as _csr
        _simdef, _simdec = _csr.chip_sim_define(
            rtl_files, _csr.staged_macro_files(project))
        # R-0915-157 round 9: the define decision reads the macro views A8
        # stages in phase 3. While a declared analog block has none staged,
        # the chip's decision cannot be known here: outside the class, named.
        _unstaged = _csr.unstaged_analog_blocks(project)
        if _unstaged:
            for o in declared:
                if o.get("program_rule"):
                    _pre_refused.setdefault(str(o["id"]), (
                        f"outside the class: the design declares analog "
                        f"block(s) {_unstaged} whose hard macros A8 has not "
                        f"staged yet, so the chip's -DSIMULATION decision "
                        f"cannot be known at Step 5; the program closes "
                        f"nothing on a read that may not be the chip's"))
        _decl_edges = {c.get("value") for o in declared
                       for c in (o.get("program_rule") or {}).get("claims") or []
                       if c.get("rule") == "clock_edge" and c.get("signal") == clock}
        _facts, _facts_why = netlist_state(
            rtl_files, _subj_name, _pl.formal_dir(project) / "l8_netlist",
            container, _resets, clock, _simdef,
            next(iter(_decl_edges)) if len(_decl_edges) == 1 else "")
        if _facts is not None and _facts.get("outside_class"):
            # Reset/value and temporal obligations retain R-0915-155.  A
            # clock-only obligation may instead use the structural check's
            # complete-state direct-clock route; it never borrows the reset
            # exception and is still refused if that route cannot census every
            # state identity in both reads.
            for o in declared:
                claims = (o.get("program_rule") or {}).get("claims") or []
                has_sync = any(c.get("rule") == "reset_sync" and
                               c.get("value") == "synchronous" for c in claims)
                clock_edge_only = (claims and all(c.get("rule") == "clock_edge"
                                                  for c in claims))
                reset_mapping_only = (claims and all(c.get("rule") in {
                    "reset_port", "reset_polarity", "reset_sync"} for c in claims)
                    and all(f.startswith(("C2 ", "C3 ", "C6 "))
                            for f in _facts["outside_class"]))
                if (o.get("program_rule") and not has_sync and not reset_mapping_only
                        and not (clock_edge_only and not _facts.get(
                            "clock_edge_outside_class"))):
                    _pre_refused.setdefault(str(o["id"]), _facts_why)
    l8_props, l8_obs, l8_answered, l8_refused = derive_l8_props(
        _facts, _facts_why, [o for o in declared if o.get("program_rule")
                             and str(o["id"]) not in _pre_refused], _inputs)
    l8_refused.update(_pre_refused)
    harness = emit_harness(iface, clock, reset_name, active_low, props,
                           assertion_form=assertion_form,
                           expert_properties=(EXPERT_PROPERTIES_SVH
                                              if _expert.is_file() else ""),
                           l8_props=l8_props, observers=l8_obs)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(harness)
    generated = [{
        "id": f"RTL.reset_safety.{dut_top}.{p.output}",
        "layer": "RTL", "source": str(dut_file),
        "description": (f"after declared reset, {p.output} equals "
                        f"the RTL reset value {p.value}"),
        "property": f"p_reset_safety_{idx}", "status": "AUTHORED",
        "author": "formal_harness_gen",
    } for idx, p in enumerate(props, 1)]
    # R-0915-144 — sort each program-ruled obligation by what is left of it:
    #   * every claim TEMPORAL and every one now has a property → covered here,
    #     exactly like the reset-safety floor above (proved or refuted by the
    #     engine);
    #   * any STRUCTURAL claim → stays in the request, annotated, and
    #     `formal_property_run` answers it with `formal_structural_check`
    #     (receipt INVOKED_BY_PROGRAM), citing the properties its temporal
    #     claims rely on;
    #   * a rule the program could not apply → the rule is marked refused, the
    #     reason is written on the row, and the expert gets it as before.
    unresolved = []
    for ob in declared:
        rule = ob.get("program_rule")
        if not rule:
            unresolved.append(ob)
            continue
        oid = str(ob["id"])
        row = dict(ob)
        if oid in l8_refused:
            row["program_refused"] = l8_refused[oid]
            unresolved.append(row)
            continue
        ans = l8_answered.get(oid)
        if ans:
            row["properties"] = ans["properties"]
            if ans.get("sync_claims"):
                # The same declared obligation is now proved temporally;
                # other structural claims in a mixed declaration stay open.
                claims = [dict(c, rule="state_sync", source_rule="reset_sync")
                          if c in ans["sync_claims"] else c for c in rule["claims"]]
                rule = _rule(claims)
                row["program_rule"] = rule
                row["kind"] = rule["kind"]
                row["full_state_census"] = ans["full_state_census"]
            if ans.get("state_registers"):
                # "ALL internal state" is only as true as the register list:
                # the netlist check confirms no flop lies outside it. That is
                # a structural claim, so the obligation becomes MIXED.
                claims = list(rule["claims"]) + [{
                    "rule": "state_covered",
                    "signal": next(c["signal"] for c in rule["claims"]
                                   if c["rule"] == "reset_state_zero"),
                    "value": ",".join(ans["state_registers"])}]
                rule = _rule(claims)
                row["program_rule"] = rule
                row["kind"] = rule["kind"]
        if rule.get("kind") == KIND_TEMPORAL and ans:
            row.update({"property": ans["properties"][0], "status": "AUTHORED",
                        "author": "formal_harness_gen", "source": row.get("source")})
            generated.append(row)
            continue
        unresolved.append(row)
    # THE EXPERT'S ANSWER, READ BACK AND RE-VERIFIED.
    #
    # This program writes `formal_authoring_request.json` telling the
    # `formal-verify` role to author properties for the obligations it cannot
    # discharge, and `formal_property_run` reads a receipt at
    # `formal_expert_review.json` naming each authored property. But the list
    # `formal_property_run` measures completion against is THIS program's
    # `property_contract.json`, and nothing moved an obligation out of it --
    # so an expert could author the properties, prove them, and file a
    # correct receipt, and the contract would still read 3 UNAUTHORED and the
    # run still report `EXPERT_FALLBACK_NOT_INVOKED`. MEASURED on
    # `subservient` x gf180mcuD, with all four assertions proved unbounded.
    #
    # A RECEIPT CANNOT CLOSE AN OBLIGATION BY ASSERTION. The disposition must
    # name a property, and THAT PROPERTY MUST BE IN THE HARNESS THIS RUN JUST
    # EMITTED -- which, for an expert property, means it is in the fragment
    # that harness includes. A name nobody wrote closes nothing, and that
    # clause is what keeps this a read-back rather than a rubber stamp.
    _closed = _expert_closed_obligations(out_path.parent, unresolved, harness)
    if _closed:
        _closed_ids = {c["id"] for c in _closed}
        unresolved = [o for o in unresolved
                      if str(o.get("id")) not in _closed_ids]
        generated = list(generated) + _closed
    contract = {
        "program": "formal_harness_gen", "version": "2.0.0",
        "verdict": "INCOMPLETE" if unresolved else "AUTHORED",
        "applicability": "APPLICABLE",
        "property_denominator": len(generated) + len(unresolved),
        "authored_property_count": len(generated),
        "covered_obligations": generated,
        "unresolved_obligations": unresolved,
        "missing_declarations": decl["missing_declarations"],
        "layer_not_applicable": decl["layer_not_applicable"],
        "fallback_skill": "formal-verify" if unresolved else None,
        **_declaration_read_state(decl),
    }
    if any((o.get("program_rule") or {}).get("kind") in (KIND_STRUCTURAL, KIND_MIXED)
           and not o.get("program_refused") for o in unresolved):
        # WHAT the structural check reads: the declared top (the declaration
        # is about the chip), falling back to the module the harness proves.
        contract["structural_subject"] = {
            "top": _subj_name,
            # the R-0915-155 gate is re-applied by the check that answers
            "clock": clock,
            # R-0915-157: the chip's define decision, the same read the proof uses
            "simdef": _simdef if (_top_found or _mapped_core) else "",
            "resets": sorted({c["signal"] for o in declared
                              for c in (o.get("program_rule") or {}).get("claims") or []
                              if c.get("rule", "").startswith("reset_")
                              and c.get("signal") in _inputs}),
            "rtl_files": [str(f) for f in rtl_files],
        }
    if (_top_found or _mapped_core) and project is not None and _pl is not None:
        # R-0915-157 round 9: the module the program-closed proof is ABOUT;
        # `formal_property_run` records the exact chip read under it.
        contract["chip_read_top"] = _subj_name
    if _mapped_core:
        contract["flow_generated_core_binding"] = {
            "declared_top": _decl_top, "core_top": dut_top,
            "source": _map_source, "ports": _core_map}
    if l8_obs:
        contract["observers"] = [
            {"wire": o.wire, "net": f"dut.{o.net}", "width": o.width}
            for o in l8_obs]
    _write_property_contract(project, contract)
    return {
        "verdict": "EMITTED", "rc": 0,
        "top": dut_top,
        "declared_top": _resolve_top(rtl_files, top, project),
        "descended_to_leaf": descended,
        # HOW this module was reached. A property proven on a sub-module is a
        # weaker statement than one proven on the declared top, and a consumer
        # that cannot tell them apart is reading an adjacent measurement.
        "selection": "flow_generated_core" if _mapped_core else selection,
        "proves_declared_top": _top_found,
        "flow_generated_core_binding": _mapped_core,
        "harness_module": f"formal_{dut_top}",
        "harness_path": str(out_path),
        "dut_file": str(dut_file),
        "rtl_files": [str(f) for f in rtl_files],
        "clock": clock,
        "reset": reset_name,
        "reset_active_low": active_low,
        "properties": [
            {"output": p.output, "target": p.target, "reset_value": p.value,
             "reset_style": "async" if p.is_async else "sync"} for p in props],
        "property_denominator": contract["property_denominator"],
        "authored_property_count": contract["authored_property_count"],
        "unresolved_obligations": unresolved,
        "fallback_skill": "formal-verify" if unresolved else None,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir", type=Path, nargs="?", default=None)
    ap.add_argument("--top", default=None)
    ap.add_argument("--rtl", type=Path, nargs="*", default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--container", default=None,
                    help="EDA container for the netlist read (default: this "
                         "filesystem, the in-image route)")
    args = ap.parse_args(argv)
    project = args.project_dir.resolve() if args.project_dir else None
    res = generate(project=project, top=args.top, rtl=args.rtl, out=args.out,
                   container=args.container)
    rc = res.pop("rc", 0)
    out = json.dumps(res, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
